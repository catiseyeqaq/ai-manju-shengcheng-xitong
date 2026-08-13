#!/usr/bin/env python3
"""Start the 4-GPU ComfyUI film studio (preferred launcher).

Role map
--------
  GPU0  port 8188  listen 0.0.0.0   MAIN WEB UI (interactive) + H3 video #1
  GPU1  port 8191  listen 127.0.0.1 H3 video worker #2
  GPU2  port 8192  listen 127.0.0.1 stills worker (majicFlus / FLUX.2)
  GPU3  port 8193  listen 127.0.0.1 stills worker #2

RAM / H3 concurrency
--------------------
Cgroup RAM is ~632 GiB. Each ~1080p MiniMax-H3 job peaks near ~90–100 GiB RSS.
**H3 concurrent MAX = 2** — only GPU0 + GPU1. Do NOT queue 4 parallel H3 jobs.
Stills (大师_01 / 大师_02) can use GPU2 + GPU3, and GPU0 when it is free.

How to use
----------
  python /workdata/ComfyUI/scripts/start_studio_4gpu.py

  Open UI:  http://<host>:8188
  Workflows (UI → Load):
    大师_01_文字生图_麦橘人物_PuLID.json          T2I + PuLID + face + upscale
    大师_02_场景板_FLUX2空镜.json                empty China city plates
    大师_03_图生视频_H3_首尾帧.json              H3 I2VA first/last bridge
    大师_04_文生视频_H3.json                     H3 text-to-video
    大师_05_全链路_中文润色_麦橘_修脸_放大_H3.json  polish → still → H3

Env per worker: COMFY_KITCHEN_DISABLE_CUDA=1, TMPDIR=/tmp/comfyui_gpu{N},
  --temp-directory /tmp/comfyui_temp_gpu{N}, --use-flash-attention,
  --enable-triton-backend, sqlite DB under /root/ComfyUI/run/workers/.

Prefer this over start_h3_workers.py (H3-only, max 2).
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

COMFY_ROOT = Path("/root/ComfyUI")
PY = Path("/opt/miniconda3/envs/ComfyUI/bin/python")
LOG_DIR = COMFY_ROOT / "logs" / "workers"
RUN_DIR = COMFY_ROOT / "run" / "workers"

WORKERS = [
    {
        "gpu": 0,
        "port": 8188,
        "listen": "0.0.0.0",
        "role": "MAIN WEB UI + H3 video #1",
    },
    {
        "gpu": 1,
        "port": 8191,
        "listen": "127.0.0.1",
        "role": "H3 video worker #2",
    },
    {
        "gpu": 2,
        "port": 8192,
        "listen": "127.0.0.1",
        "role": "stills worker (majic / FLUX.2)",
    },
    {
        "gpu": 3,
        "port": 8193,
        "listen": "127.0.0.1",
        "role": "stills worker #2",
    },
]


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def start_one(gpu: int, port: int, listen: str) -> subprocess.Popen | None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    log = LOG_DIR / f"studio_gpu{gpu}_p{port}.log"
    pid_file = RUN_DIR / f"studio_gpu{gpu}.pid"

    if port_open(port):
        print(f"GPU{gpu} port {port} already up — skip start")
        return None

    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(gpu)
    env["COMFY_KITCHEN_DISABLE_CUDA"] = "1"
    env["COMFYUI_ENABLE_TRITON_BACKEND"] = "1"
    tmp = Path(f"/tmp/comfyui_gpu{gpu}")
    temp_dir = Path(f"/tmp/comfyui_temp_gpu{gpu}")
    tmp.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    env["TMPDIR"] = str(tmp)

    db = RUN_DIR / f"comfyui_gpu{gpu}.db"
    cmd = [
        str(PY),
        str(COMFY_ROOT / "main.py"),
        "--listen",
        listen,
        "--port",
        str(port),
        "--temp-directory",
        str(temp_dir),
        "--database-url",
        f"sqlite:///{db}",
        "--use-flash-attention",
        "--enable-triton-backend",
    ]
    lf = open(log, "ab", buffering=0)
    proc = subprocess.Popen(
        cmd,
        cwd=str(COMFY_ROOT),
        env=env,
        stdout=lf,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    pid_file.write_text(f"{proc.pid}\n")
    print(f"started GPU{gpu} pid={proc.pid} port={port} log={log}")
    return proc


def wait_ready(port: int, timeout: float = 300.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if port_open(port):
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/system_stats", timeout=5
                ) as r:
                    if r.status == 200:
                        return True
            except Exception:
                pass
        time.sleep(2)
    return False


def main() -> int:
    stagger = float(os.environ.get("WORKER_STAGGER_SEC", "12"))
    print("=" * 64)
    print("ComfyUI 4-GPU Film Studio")
    print("=" * 64)
    print("H3 concurrent MAX 2 (GPU0+GPU1 only) — cgroup ~632GiB")
    print("Stills: GPU2+GPU3 (+GPU0 if free). Do NOT run 4 parallel H3 jobs.")
    print()

    for i, w in enumerate(WORKERS):
        start_one(w["gpu"], w["port"], w["listen"])
        if i < len(WORKERS) - 1:
            time.sleep(stagger)

    print("\nWaiting until all workers are ready...")
    ok = 0
    for w in WORKERS:
        ready = wait_ready(w["port"], timeout=360)
        status = "READY" if ready else "FAIL"
        print(f"  GPU{w['gpu']}  :{w['port']}  {status:5}  — {w['role']}")
        ok += int(ready)

    print()
    print("URL / role map")
    print("-" * 64)
    print(f"  http://0.0.0.0:8188   GPU0  MAIN WEB UI (open this in browser)")
    print(f"  http://127.0.0.1:8191 GPU1  H3 video #2")
    print(f"  http://127.0.0.1:8192 GPU2  stills (majic / FLUX.2)")
    print(f"  http://127.0.0.1:8193 GPU3  stills #2")
    print("-" * 64)
    print(f"ready {ok}/{len(WORKERS)}")
    return 0 if ok == len(WORKERS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
