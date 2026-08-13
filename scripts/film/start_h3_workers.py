#!/usr/bin/env python3
"""Start ComfyUI H3 workers with a RAM guard (cgroup ~632GiB → max 2 concurrent H3).

PREFERRED: use ``start_studio_4gpu.py`` instead — it brings up the full 4-GPU
film studio (GPU0 UI+H3, GPU1 H3#2, GPU2/GPU3 stills) with the same RAM rules.

This script remains for H3-only boots:
  Default: GPU0 (:8188) + GPU1 (:8191). Each ~1080p MiniMax-H3 job sits near
  ~90–100GiB RSS; launching more than two H3 workers will OOM-kill the box.

Usage:
  python start_studio_4gpu.py             # preferred full studio
  python start_h3_workers.py              # start up to MAX_H3_WORKERS (2)
  python start_h3_workers.py --max 1      # only GPU0
  MAX_H3_WORKERS=2 python start_h3_workers.py
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

COMFY_ROOT = Path("ComfyUI")
PY = Path("/opt/miniconda3/envs/ComfyUI/bin/python")
LOG_DIR = COMFY_ROOT / "logs" / "workers"
RUN_DIR = COMFY_ROOT / "run" / "workers"

# Preferred H3 pair — leave other GPUs free for stills / upscale
H3_WORKERS = [
    {"gpu": 0, "port": 8188, "listen": "0.0.0.0"},
    {"gpu": 1, "port": 8191, "listen": "127.0.0.1"},
]

# Legacy 7-way map (DO NOT use for H3 video — memcg OOM). Kept for reference.
LEGACY_EXTRA = [{"gpu": g, "port": 8190 + g, "listen": "127.0.0.1"} for g in range(2, 8)]

DEFAULT_MAX = int(os.environ.get("MAX_H3_WORKERS", "2"))


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def mem_available_giB() -> float | None:
    """Best-effort free RAM from /proc/meminfo or cgroup."""
    try:
        cg = Path("/sys/fs/cgroup/memory.current")
        maxp = Path("/sys/fs/cgroup/memory.max")
        if cg.exists() and maxp.exists():
            cur = int(cg.read_text().strip())
            mx = maxp.read_text().strip()
            if mx != "max":
                return (int(mx) - cur) / (1024**3)
    except Exception:
        pass
    try:
        info = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, v = line.split(":")
            info[k] = int(v.strip().split()[0])  # kB
        # MemAvailable
        return info.get("MemAvailable", info.get("MemFree", 0)) / (1024**2)
    except Exception:
        return None


def start_one(gpu: int, port: int, listen: str = "127.0.0.1") -> subprocess.Popen | None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    log = LOG_DIR / f"comfy_gpu{gpu}_p{port}.log"
    pid_file = RUN_DIR / f"gpu{gpu}.pid"

    if port_open(port):
        print(f"GPU{gpu} port {port} already up")
        return None

    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(gpu)
    env["COMFY_KITCHEN_DISABLE_CUDA"] = "1"
    env["COMFYUI_ENABLE_TRITON_BACKEND"] = "1"
    # Keep TMPDIR outside ComfyUI/temp — Comfy may wipe that tree mid-job.
    env["TMPDIR"] = f"/tmp/comfyui_h3_gpu{gpu}"
    Path(env["TMPDIR"]).mkdir(parents=True, exist_ok=True)

    db = RUN_DIR / f"comfyui_gpu{gpu}.db"
    cmd = [
        str(PY),
        str(COMFY_ROOT / "main.py"),
        "--listen",
        listen,
        "--port",
        str(port),
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


def wait_ready(port: int, timeout: float = 240.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if port_open(port):
            try:
                import urllib.request

                with urllib.request.urlopen(f"http://127.0.0.1:{port}/system_stats", timeout=5) as r:
                    if r.status == 200:
                        return True
            except Exception:
                pass
        time.sleep(2)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="RAM-guarded H3 worker launcher (max 2)")
    ap.add_argument("--max", type=int, default=DEFAULT_MAX, help="max concurrent H3 workers (cap 2)")
    ap.add_argument("--unsafe-all", action="store_true",
                    help="IGNORE RAM guard and start GPU0-7 (will likely OOM)")
    ap.add_argument("--stagger", type=float, default=float(os.environ.get("WORKER_STAGGER_SEC", "15")))
    args = ap.parse_args()

    max_n = min(max(1, args.max), 2) if not args.unsafe_all else 8
    if args.max > 2 and not args.unsafe_all:
        print(f"WARN: capping --max {args.max} -> 2 (cgroup RAM). Pass --unsafe-all to override.")

    free = mem_available_giB()
    if free is not None:
        print(f"approx free RAM: {free:.1f} GiB")
        # each H3 ~100GiB; keep ~80GiB headroom for OS/stills
        safe = max(1, int((free - 80) // 100)) if free > 100 else 1
        if not args.unsafe_all and max_n > safe:
            print(f"RAM guard: reducing max_workers {max_n} -> {safe}")
            max_n = max(1, safe)

    workers = (H3_WORKERS + LEGACY_EXTRA)[:max_n] if args.unsafe_all else H3_WORKERS[:max_n]
    print(f"starting {len(workers)} H3 worker(s): {[(w['gpu'], w['port']) for w in workers]}")

    for i, w in enumerate(workers):
        start_one(w["gpu"], w["port"], w.get("listen", "127.0.0.1"))
        if i < len(workers) - 1:
            time.sleep(args.stagger)

    print("\nWaiting for workers...")
    ok = 0
    for w in workers:
        ready = wait_ready(w["port"], timeout=300)
        print(f"  GPU{w['gpu']} :{w['port']} ready={ready}")
        ok += int(ready)
    print(f"ready {ok}/{len(workers)}")
    return 0 if ok == len(workers) else 1


if __name__ == "__main__":
    raise SystemExit(main())
