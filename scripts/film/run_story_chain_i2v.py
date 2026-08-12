#!/usr/bin/env python3
"""RAM-guarded serial/dual MiniMax-H3 I2VA chain with first/last-frame continuity.

Max concurrent H3 workers: 2 (cgroup ~632GiB; each job ~90GiB RSS).
Reads storyboard keyframes from /root/ComfyUI/output/film_coherent/storyboard/
and optional bridge tails.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

COMFY_ROOT = Path("/root/ComfyUI")
PY = Path("/opt/miniconda3/envs/ComfyUI/bin/python")
STORYBOARD = Path("/root/ComfyUI/output/film_coherent/storyboard")
BRIDGE = Path("/root/ComfyUI/output/film_coherent/bridge")
INPUT = Path("/root/ComfyUI/input")
OUT_PREFIX = "video/story_rain_day_v2"
LOG = Path("/workdata/ComfyUI/logs/story_chain_i2v.log")

WIDTH = 1920
HEIGHT = 1088
DURATION_SEC = 5.0
STEPS = 20
MAX_PARALLEL = 2

# GPU assignment for up to 2 concurrent jobs
WORKERS = [
    {"gpu": 0, "port": 8188, "listen": "0.0.0.0"},
    {"gpu": 1, "port": 8191, "listen": "127.0.0.1"},
]

SHOTS = [
    {
        "id": "01_cafe",
        "seed": 20260831,
        "first": "01_cafe.png",
        "last": "02_walk.png",  # bridge toward next
        "dialogue": "你又没带伞啊，还好我在附近，我们一起打伞回去吧",
        "prompt": None,  # filled below
    },
    {
        "id": "02_walk",
        "seed": 20260832,
        "first": "02_walk.png",
        "last": "03_store.png",
        "dialogue": "小心脚底下的积水，拉着我走就好",
    },
    {
        "id": "03_store",
        "seed": 20260833,
        "first": "03_store.png",
        "last": "04_aisle.png",
        "dialogue": "到了，我们进去买点晚上吃的吧",
    },
    {
        "id": "04_aisle",
        "seed": 20260834,
        "first": "04_aisle.png",
        "last": "05_checkout.png",
        "dialogue": "晚上吃这个好不好？再加一块小蛋糕",
    },
    {
        "id": "05_checkout",
        "seed": 20260835,
        "first": "05_checkout.png",
        "last": "06_homewalk.png",
        "dialogue": "这个你提，轻的我来。走吧，回家煮面",
    },
    {
        "id": "06_homewalk",
        "seed": 20260836,
        "first": "06_homewalk.png",
        "last": "07_entry.png",
        "dialogue": "今天雨下得好大，还好我们一起",
    },
    {
        "id": "07_entry",
        "seed": 20260837,
        "first": "07_entry.png",
        "last": "08_kitchen.png",
        "dialogue": "先换鞋，外套给我，我去开灯烧水",
    },
    {
        "id": "08_kitchen",
        "seed": 20260838,
        "first": "08_kitchen.png",
        "last": None,
        "dialogue": "今天好冷，先喝点热的。面马上好",
    },
]


def log(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def frames_for_duration(seconds: float) -> int:
    base = max(5, round(seconds * 24))
    return base + (5 - (base % 17)) % 17


def i2va_prompt(dialogue: str, beat: str) -> str:
    return f"""For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.
{"At the end of the target video, <Picture 2> (from [Shot 1]) is referenced as the last frame." if beat else ""}

integrated_multimodal_description: [Shot 1] Live-action, cinematic, photorealistic continuity from <Picture 1>. Preserve the woman's face, hair, and wardrobe exactly. {beat} Handheld first-person POV with small amplitude at slow speed. The quiet young woman with a soft intimate voice (S1) says: <d>[Chinese] {dialogue}</d> Keep lighting practical and naturalistic with wet speculars where rainy.

overall_soundscape: Natural ambience matching the scene — rain, footsteps, soft room tone as appropriate. Clear dialogue.

non_diegetic_music: Sparse warm piano and low strings, quiet under dialogue."""


BEATS = {
    "01_cafe": "Café awning rainy neon night; she steps closer under the transparent umbrella toward the viewer.",
    "02_walk": "Walking under a shared umbrella on a rainy neon street; puddles and neon reflections.",
    "03_store": "Arriving at supermarket entrance; she opens the door and invites the viewer inside.",
    "04_aisle": "Supermarket aisle; she shows snacks/noodles to the camera playfully.",
    "05_checkout": "Checkout; she bags groceries and hands a bag toward the viewer.",
    "06_homewalk": "Quieter rainy residential walk home with shopping bags under the umbrella.",
    "07_entry": "Apartment hallway; unlock door, set umbrella aside, warm entry light.",
    "08_kitchen": "Warm kitchen; coat off; she offers hot tea with steam toward the camera.",
}


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def http_json(url: str, payload=None, timeout=120):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"} if payload is not None else {},
        method="GET" if payload is None else "POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def ensure_input(name: str) -> str:
    """Ensure storyboard image is in Comfy input/ under a stable name."""
    src = STORYBOARD / name
    if not src.exists():
        # try without path tricks
        alts = list(STORYBOARD.glob(name.replace(".png", "*.png")))
        if not alts:
            raise FileNotFoundError(src)
        src = alts[-1]
    dst = INPUT / name
    if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
        dst.write_bytes(src.read_bytes())
    return name


def start_worker(gpu: int, port: int, listen: str) -> None:
    if port_open(port):
        log(f"port {port} already up")
        return
    run = COMFY_ROOT / "run" / "workers"
    logs = COMFY_ROOT / "logs" / "workers"
    run.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    db = run / f"comfyui_gpu{gpu}.db"
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(gpu)
    env["COMFY_KITCHEN_DISABLE_CUDA"] = "1"
    # Keep TMPDIR outside ComfyUI/temp — Comfy may wipe that tree mid-job.
    env["TMPDIR"] = f"/tmp/comfyui_h3_gpu{gpu}"
    Path(env["TMPDIR"]).mkdir(parents=True, exist_ok=True)
    cmd = [
        str(PY), str(COMFY_ROOT / "main.py"),
        "--listen", listen, "--port", str(port),
        "--database-url", f"sqlite:///{db}",
        "--use-flash-attention", "--enable-triton-backend",
    ]
    lf = open(logs / f"comfy_gpu{gpu}_p{port}.log", "ab", buffering=0)
    proc = subprocess.Popen(cmd, cwd=str(COMFY_ROOT), env=env, stdout=lf, stderr=subprocess.STDOUT, start_new_session=True)
    (run / f"gpu{gpu}.pid").write_text(f"{proc.pid}\n")
    log(f"started GPU{gpu} pid={proc.pid} :{port}")
    t0 = time.time()
    while time.time() - t0 < 300:
        if port_open(port):
            try:
                http_json(f"http://127.0.0.1:{port}/system_stats", timeout=5)
                log(f"GPU{gpu} ready")
                return
            except Exception:
                pass
        time.sleep(2)
    raise RuntimeError(f"GPU{gpu} not ready")


def build_graph(shot: dict, length: int) -> dict:
    first = ensure_input(shot["first"])
    g = {
        "1": {"class_type": "LoadImage", "inputs": {"image": first}},
        "2": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "minimax_h3_fl2va_pruned_bf16.safetensors", "weight_dtype": "default"}},
        "3": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": "qwen3vl_32b_minimax_h3_bf16.safetensors", "type": "minimax", "device": "default"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_video_vae_fp16.safetensors"}},
        "5": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"}},
        "7": {"class_type": "RandomNoise", "inputs": {"noise_seed": shot["seed"]}},
        "9": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
        "10": {"class_type": "BasicScheduler", "inputs": {
            "model": ["2", 0], "scheduler": "simple", "steps": STEPS, "denoise": 1.0}},
    }
    prompt = i2va_prompt(shot["dialogue"], BEATS[shot["id"]])
    mm_inputs = {
        "clip": ["3", 0], "vae": ["4", 0], "first_frame": ["1", 0],
        "prompt": prompt, "width": WIDTH, "height": HEIGHT, "length": length,
    }
    if shot.get("last"):
        last = ensure_input(shot["last"])
        g["1b"] = {"class_type": "LoadImage", "inputs": {"image": last}}
        mm_inputs["last_frame"] = ["1b", 0]
    g["6"] = {"class_type": "MiniMaxH3ImageToVideo", "inputs": mm_inputs}
    g["8"] = {"class_type": "BasicGuider", "inputs": {"model": ["2", 0], "conditioning": ["6", 0]}}
    g["11"] = {"class_type": "SamplerCustomAdvanced", "inputs": {
        "noise": ["7", 0], "guider": ["8", 0], "sampler": ["9", 0],
        "sigmas": ["10", 0], "latent_image": ["6", 1]}}
    g["12"] = {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["4", 0]}}
    g["13"] = {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["11", 0], "vae": ["5", 0]}}
    g["14"] = {"class_type": "CreateVideo", "inputs": {
        "images": ["12", 0], "audio": ["13", 0], "fps": 24.0}}
    g["15"] = {"class_type": "SaveVideo", "inputs": {
        "video": ["14", 0],
        "filename_prefix": f"{OUT_PREFIX}/{shot['id']}",
        "format": "auto", "codec": "auto"}}
    return g


def run_shot(shot: dict, worker: dict, length: int) -> dict:
    host = f"http://127.0.0.1:{worker['port']}"
    log(f"submit {shot['id']} -> GPU{worker['gpu']}:{worker['port']}")
    resp = http_json(f"{host}/prompt", {"prompt": build_graph(shot, length), "client_id": str(uuid.uuid4())})
    if "prompt_id" not in resp:
        raise RuntimeError(f"{shot['id']} submit failed: {resp}")
    pid = resp["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < 7200:
        try:
            hist = http_json(f"{host}/history/{pid}", timeout=60)
        except Exception as e:
            log(f"  {shot['id']} hist err {e}")
            time.sleep(20)
            continue
        if pid in hist:
            st = hist[pid].get("status", {}).get("status_str")
            log(f"  {shot['id']} done status={st} after {time.time()-t0:.0f}s")
            return {"id": shot["id"], "prompt_id": pid, "status": st, "entry": hist[pid]}
        if int(time.time() - t0) % 60 < 15:
            log(f"  {shot['id']} running {int(time.time()-t0)}s")
        time.sleep(15)
    raise TimeoutError(shot["id"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-parallel", type=int, default=MAX_PARALLEL)
    ap.add_argument("--start-workers", action="store_true")
    ap.add_argument("--only", nargs="*", default=None)
    args = ap.parse_args()

    length = frames_for_duration(DURATION_SEC)
    shots = SHOTS
    if args.only:
        shots = [s for s in SHOTS if s["id"] in args.only]

    missing = [s["first"] for s in shots if not (STORYBOARD / s["first"]).exists()]
    if missing:
        log(f"MISSING storyboard frames: {missing}")
        return 1

    if args.start_workers:
        for w in WORKERS[: args.max_parallel]:
            start_worker(w["gpu"], w["port"], w["listen"])
            time.sleep(10)

    for w in WORKERS[: args.max_parallel]:
        if not port_open(w["port"]):
            log(f"worker :{w['port']} not up — pass --start-workers")
            return 1

    # queue in waves of max_parallel
    results = []
    i = 0
    while i < len(shots):
        wave = shots[i : i + args.max_parallel]
        with ThreadPoolExecutor(max_workers=len(wave)) as ex:
            futs = {
                ex.submit(run_shot, shot, WORKERS[j], length): shot
                for j, shot in enumerate(wave)
            }
            for fut in as_completed(futs):
                shot = futs[fut]
                try:
                    results.append(fut.result())
                except Exception as e:
                    log(f"FAIL {shot['id']}: {e}")
                    results.append({"id": shot["id"], "status": "error", "error": str(e)})
        i += args.max_parallel

    out = Path("/workdata/ComfyUI/logs/story_chain_i2v_jobs.json")
    out.write_text(json.dumps([{k: v for k, v in r.items() if k != "entry"} for r in results], indent=2), encoding="utf-8")
    log(f"wrote {out}")
    fails = [r for r in results if r.get("status") != "success"]
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
