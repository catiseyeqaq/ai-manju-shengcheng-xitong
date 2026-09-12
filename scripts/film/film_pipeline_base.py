#!/usr/bin/env python3
"""Film pipeline base — shared helpers for the local ComfyUI + MiniMax-H3 film runners.

Pipeline shape (each stage is driven by a per-title runner script):

  bible   — character bible stills (GPU stills worker)
  plates  — empty scene plates (FLUX.2)
  keys    — POV keyframes with PuLID face lock
  video   — MiniMax-H3 I2VA dual workers
  merge   — ffmpeg concat

This module contains the **reusable** pieces only: worker HTTP helpers, graph
builders, save utilities and worker bootstrap. Title-specific shot tables,
character/style prompts and stage orchestration stay in the individual runners.

Usage from a title runner::

    import sys; sys.path.insert(0, "ComfyUI/scripts")
    from film_pipeline_base import (
        FFMPEG, FFPROBE, H3_A, H3_B, STILLS_A, STILLS_B, TURBO_LORA,
        ensure_h3_workers, flux_graph, frames_for_duration, get, h3_graph,
        log, post, save_images, save_video, wait_prompt,
    )
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path

PY = Path("/opt/miniconda3/envs/ComfyUI/bin/python")
FFMPEG = Path("/opt/miniconda3/envs/ComfyUI/bin/ffmpeg")
FFPROBE = Path("/opt/miniconda3/envs/ComfyUI/bin/ffprobe")
INPUT = Path("ComfyUI/input")

# Default output root / log. Title runners define their own OUT and JOBS.
OUT = Path("ComfyUI/output/film")
LOG = Path("ComfyUI/logs/film_pipeline.log")

STILLS_A = "http://127.0.0.1:8192"
STILLS_B = "http://127.0.0.1:8193"
H3_A = "http://127.0.0.1:8188"
H3_B = "http://127.0.0.1:8191"

# ~2K 16:9 H3 grid (multiple of 32)
W, H = 1920, 1088
STILL_W, STILL_H = 1280, 768
BIBLE_W, BIBLE_H = 1024, 1280
DURATION = 6.0
TURBO_STEPS = 8
TURBO_LORA = "minimax_h3_turbo_v4_step600_ema_pruned_comfyui.safetensors"
TURBO_STRENGTH = 1.0
SEED0 = 2026081214

NEG = (
    "blurry, low resolution, plastic skin, waxy skin, airbrushed, deformed face, "
    "extra fingers, bad anatomy, anime, illustration, 3d render, oversaturated, "
    "japanese school, sailor fuku, tokyo street, torii, sakura avenue, "
    "hangul signage, seoul street, english billboard, latin alphabet storefront, "
    "european campus, western downtown, oversexualized, heavy makeup"
)


def log(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def post(host: str, path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        host + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode())


def get(host: str, path: str) -> dict:
    with urllib.request.urlopen(host + path, timeout=120) as r:
        return json.loads(r.read().decode())


def wait_prompt(host: str, pid: str, timeout: float = 2400) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        hist = get(host, f"/history/{pid}")
        if pid in hist:
            st = hist[pid].get("status", {}).get("status_str")
            if st == "error":
                raise RuntimeError(json.dumps(hist[pid].get("status"), ensure_ascii=False)[:2000])
            return hist[pid]
        time.sleep(4)
    raise TimeoutError(pid)


def save_images(entry: dict, dest_dir: Path, stem: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    for _nid, o in entry.get("outputs", {}).items():
        for im in o.get("images", []):
            name = im["filename"]
            sub = im.get("subfolder", "")
            src = Path("ComfyUI/output") / sub / name if sub else Path("ComfyUI/output") / name
            if not src.exists():
                alts = list(Path("ComfyUI/output").rglob(name))
                if not alts:
                    continue
                src = alts[-1]
            dst = dest_dir / f"{stem}.png"
            shutil.copy2(src, dst)
            shutil.copy2(src, INPUT / f"{stem}.png")
            return dst
    raise RuntimeError(f"no image for {stem}: {list(entry.get('outputs', {}))}")


def save_video(entry: dict, dest_dir: Path, stem: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    for _nid, o in entry.get("outputs", {}).items():
        for key in ("gifs", "videos", "images"):
            for im in o.get(key, []) or []:
                if not isinstance(im, dict):
                    continue
                name = im.get("filename", "")
                if not name.endswith((".mp4", ".webm")):
                    continue
                sub = im.get("subfolder", "")
                src = Path("ComfyUI/output") / sub / name if sub else Path("ComfyUI/output") / name
                if not src.exists():
                    alts = list(Path("ComfyUI/output").rglob(name))
                    if not alts:
                        continue
                    src = alts[-1]
                dst = dest_dir / f"{stem}.mp4"
                shutil.copy2(src, dst)
                return dst
    # fallback glob
    cands = sorted(Path("ComfyUI/output/video").glob(f"*{stem}*"))
    if cands:
        dst = dest_dir / f"{stem}.mp4"
        shutil.copy2(cands[-1], dst)
        return dst
    raise RuntimeError(f"no video for {stem}")


def frames_for_duration(seconds: float) -> int:
    base = max(5, round(seconds * 24))
    return base + (5 - (base % 17)) % 17


def flux_graph(
    prompt: str,
    prefix: str,
    width: int,
    height: int,
    steps: int,
    seed: int,
    *,
    backend: str = "majic",
    pulid_ref: str | None = None,
    face: bool = True,
    upscale: bool = True,
    out_dir: str = "film",
) -> dict:
    if backend == "flux2":
        g: dict = {
            "10": {"class_type": "UNETLoader", "inputs": {
                "unet_name": "flux2_dev_fp8mixed.safetensors", "weight_dtype": "default"}},
            "11": {"class_type": "CLIPLoader", "inputs": {
                "clip_name": "mistral_3_small_flux2_bf16.safetensors",
                "type": "flux2", "device": "default"}},
            "12": {"class_type": "VAELoader", "inputs": {"vae_name": "flux2-vae.safetensors"}},
            "13": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["11", 0]}},
            "14": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["11", 0]}},
            "15": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["13", 0], "guidance": 3.5}},
            "17": {"class_type": "EmptySD3LatentImage", "inputs": {
                "width": width, "height": height, "batch_size": 1}},
            "18": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
            "19": {"class_type": "BasicScheduler", "inputs": {
                "model": ["10", 0], "scheduler": "beta", "steps": steps, "denoise": 1.0}},
            "20": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        }
        model_ref: list = ["10", 0]
        face = False
        upscale = False
        pulid_ref = None
    else:
        g = {
            "10": {"class_type": "UNETLoader", "inputs": {
                "unet_name": "majicflus_v134.safetensors", "weight_dtype": "default"}},
            "11": {"class_type": "DualCLIPLoader", "inputs": {
                "clip_name1": "clip_l.safetensors", "clip_name2": "t5xxl_fp16.safetensors", "type": "flux"}},
            "12": {"class_type": "VAELoader", "inputs": {"vae_name": "flux1_ae.safetensors"}},
            "13": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["11", 0]}},
            "14": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["11", 0]}},
            "15": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["13", 0], "guidance": 3.5}},
            "17": {"class_type": "EmptySD3LatentImage", "inputs": {
                "width": width, "height": height, "batch_size": 1}},
            "18": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
            "19": {"class_type": "BasicScheduler", "inputs": {
                "model": ["10", 0], "scheduler": "beta", "steps": steps, "denoise": 1.0}},
            "20": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        }
        model_ref = ["10", 0]

    if pulid_ref and backend == "majic":
        g["50"] = {"class_type": "PulidFluxModelLoader", "inputs": {
            "pulid_file": "pulid_flux_v0.9.1.safetensors"}}
        g["51"] = {"class_type": "PulidFluxInsightFaceLoader", "inputs": {"provider": "CPU"}}
        g["52"] = {"class_type": "PulidFluxEvaClipLoader", "inputs": {}}
        g["53"] = {"class_type": "LoadImage", "inputs": {"image": pulid_ref}}
        g["54"] = {"class_type": "ApplyPulidFlux", "inputs": {
            "model": ["10", 0], "pulid_flux": ["50", 0], "eva_clip": ["52", 0],
            "face_analysis": ["51", 0], "image": ["53", 0],
            "weight": 0.9, "start_at": 0.0, "end_at": 1.0}}
        model_ref = ["54", 0]
        g["19"]["inputs"]["model"] = model_ref

    g["16"] = {"class_type": "BasicGuider", "inputs": {"model": model_ref, "conditioning": ["15", 0]}}
    g["21"] = {"class_type": "SamplerCustomAdvanced", "inputs": {
        "noise": ["20", 0], "guider": ["16", 0], "sampler": ["18", 0],
        "sigmas": ["19", 0], "latent_image": ["17", 0]}}
    g["22"] = {"class_type": "VAEDecode", "inputs": {"samples": ["21", 0], "vae": ["12", 0]}}
    last: list = ["22", 0]

    if face and backend == "majic":
        g["30"] = {"class_type": "UltralyticsDetectorProvider",
                   "inputs": {"model_name": "bbox/face_yolov8m.pt"}}
        g["31"] = {"class_type": "FaceDetailer", "inputs": {
            "image": list(last), "model": model_ref, "clip": ["11", 0], "vae": ["12", 0],
            "guide_size": 1024, "guide_size_for": True, "max_size": 1536,
            "seed": seed + 1, "steps": 20, "cfg": 1.0, "sampler_name": "euler", "scheduler": "beta",
            "positive": ["15", 0], "negative": ["14", 0],
            "denoise": 0.35, "feather": 8, "noise_mask": True, "force_inpaint": True,
            "bbox_threshold": 0.4, "bbox_dilation": 10, "bbox_crop_factor": 3.0,
            "sam_detection_hint": "center-1", "sam_dilation": 0, "sam_threshold": 0.93,
            "sam_bbox_expansion": 0, "sam_mask_hint_threshold": 0.7,
            "sam_mask_hint_use_negative": "False", "drop_size": 10,
            "bbox_detector": ["30", 0],
            "wildcard": "sharp detailed face, natural skin pores, catchlight, subtle freckles, majicFlus look",
            "cycle": 1}}
        last = ["31", 0]

    if upscale and backend == "majic":
        g["40"] = {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "RealESRGAN_x4.pth"}}
        g["41"] = {"class_type": "UltimateSDUpscale", "inputs": {
            "image": list(last), "model": model_ref, "positive": ["15", 0], "negative": ["14", 0],
            "vae": ["12", 0], "upscale_by": 1.5, "seed": seed + 2, "steps": 14, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "beta", "denoise": 0.2,
            "upscale_model": ["40", 0], "mode_type": "Linear",
            "tile_width": 1024, "tile_height": 1024, "mask_blur": 8, "tile_padding": 32,
            "seam_fix_mode": "Half Tile", "seam_fix_denoise": 1.0, "seam_fix_width": 64,
            "seam_fix_mask_blur": 8, "seam_fix_padding": 16,
            "force_uniform_tiles": True, "tiled_decode": True, "batch_size": 1}}
        last = ["41", 0]

    g["99"] = {"class_type": "SaveImage", "inputs": {
        "images": list(last), "filename_prefix": f"{out_dir}/{prefix}"}}
    return g


def h3_graph(first: str, last: str | None, prompt: str, seed: int, length: int,
             *, out_dir: str = "video/film") -> dict:
    g: dict = {
        "1": {"class_type": "LoadImage", "inputs": {"image": first}},
        "2": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "minimax_h3_fl2va_pruned_bf16.safetensors", "weight_dtype": "default"}},
        "3": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": "qwen3vl_32b_minimax_h3_bf16.safetensors", "type": "minimax", "device": "default"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_video_vae_fp16.safetensors"}},
        "5": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"}},
        "16": {"class_type": "MiniMaxH3TurboLoRA", "inputs": {
            "model": ["2", 0], "lora_name": TURBO_LORA,
            "strength": TURBO_STRENGTH, "low_vram": False}},
        "6": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {
            "clip": ["3", 0], "vae": ["4", 0], "first_frame": ["1", 0],
            "prompt": prompt, "width": W, "height": H, "length": length}},
        "7": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "8": {"class_type": "BasicGuider", "inputs": {"model": ["16", 0], "conditioning": ["6", 0]}},
        "9": {"class_type": "MiniMaxH3TurboSampler", "inputs": {}},
        "10": {"class_type": "BasicScheduler", "inputs": {
            "model": ["16", 0], "scheduler": "simple", "steps": TURBO_STEPS, "denoise": 1.0}},
        "11": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["7", 0], "guider": ["8", 0], "sampler": ["9", 0],
            "sigmas": ["10", 0], "latent_image": ["6", 1]}},
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["4", 0]}},
        "13": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["11", 0], "vae": ["5", 0]}},
        "14": {"class_type": "CreateVideo", "inputs": {"images": ["12", 0], "audio": ["13", 0], "fps": 24.0}},
        "15": {"class_type": "SaveVideo", "inputs": {
            "video": ["14", 0], "filename_prefix": f"{out_dir}/{Path(first).stem}",
            "format": "auto", "codec": "auto"}},
    }
    if last:
        g["1b"] = {"class_type": "LoadImage", "inputs": {"image": last}}
        g["6"]["inputs"]["last_frame"] = ["1b", 0]
    return g


def ensure_h3_workers() -> None:
    """Start GPU0/1 H3 workers if ports are down (stills-only mode may have stopped them)."""
    import os
    import socket

    def up(port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.4):
                return True
        except OSError:
            return False

    need = [p for p in (8188, 8191) if not up(p)]
    if not need:
        log("H3 workers already up")
        return
    log(f"starting H3 workers for ports {need} via start_studio_4gpu.py")
    env = os.environ.copy()
    env["WORKER_STAGGER_SEC"] = "8"
    subprocess.check_call(
        [str(PY), "ComfyUI/scripts/start_studio_4gpu.py"],
        env=env,
    )
    t0 = time.time()
    while time.time() - t0 < 300:
        if up(8188) and up(8191):
            try:
                get(H3_A, "/system_stats")
                get(H3_B, "/system_stats")
                log("H3 workers ready")
                return
            except Exception:
                pass
        time.sleep(3)
    raise RuntimeError("H3 workers failed to start")
