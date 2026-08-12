#!/usr/bin/env python3
"""Coherent photoreal film pipeline — bible, plates, keyframes via majicFlus + optional PuLID.

Stages (ComfyUI API on HOST):
  bible   — character identity stills (front/3q/side/full/indoor)
  plates  — empty location plates
  keys    — per-shot continuity keyframes (+ optional FaceDetailer / USDU)

Uses majicFlus (Flux.1) which is proven on this PPU box. PuLID is applied when
the custom node + weights load successfully; otherwise falls back to locked
character prompt + FaceDetailer.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import urllib.request
import uuid
from pathlib import Path

HOST = "http://127.0.0.1:8189"  # dedicated stills worker (GPU1)
INPUT = Path("/root/ComfyUI/input")
OUT_ROOT = Path("/root/ComfyUI/output/film_coherent")
NEG = (
    "blurry, out of focus, low resolution, plastic skin, waxy skin, airbrushed, "
    "deformed face, extra fingers, bad anatomy, anime, illustration, 3d render, "
    "oversaturated, watermark, text, beauty cam, smooth poreless skin"
)
LIGHT = (
    "photorealistic live-action film still, natural skin pores and micro-texture, "
    "35mm lens, T1.5 shallow depth of field, practical lighting, soft bounce fill, "
    "accurate white balance, cinematic color grade, wet specular highlights where rainy, "
    "no beauty filter"
)
CHAR = (
    "a 30-year-old East Asian woman, long dark slightly wavy hair, soft natural features, "
    "subtle freckles, realistic eyes with catchlights, beige trench coat, "
    "same person across all shots, highly detailed face"
)

BIBLE = [
    ("bible_front", f"{LIGHT}, {CHAR}, front portrait, looking at camera, soft window light, head and shoulders"),
    ("bible_3q", f"{LIGHT}, {CHAR}, three-quarter portrait, gentle smile, neon rim light, rain night bokeh"),
    ("bible_side", f"{LIGHT}, {CHAR}, profile side view, wet hair strands, cinematic side lighting"),
    ("bible_full_rain", f"{LIGHT}, {CHAR}, full body standing under transparent umbrella on wet neon street at night, medium-wide shot"),
    ("bible_indoor", f"{LIGHT}, {CHAR}, indoor casual top without trench coat, warm kitchen practical lights, medium shot"),
]

PLATES = [
    ("plate_cafe", f"{LIGHT}, empty rainy neon café entrance at night, awning, wet pavement reflections, no people, establishing wide shot"),
    ("plate_street", f"{LIGHT}, empty rainy neon city street at night, wet asphalt mirror reflections, no people, establishing wide shot"),
    ("plate_market", f"{LIGHT}, empty bright Japanese-style supermarket snack aisle, fluorescent lights, colorful shelves, no people"),
    ("plate_hallway", f"{LIGHT}, empty warm apartment hallway entryway at night, soft ceiling light, door, shoe cabinet, no people"),
    ("plate_kitchen", f"{LIGHT}, empty small warm kitchen at night, practical lights, steam mood, rain on window, no people"),
]

# Continuity keyframes for rain-day v2 (POV with heroine)
KEYS = [
    ("01_cafe", "plate_cafe", True,
     f"{LIGHT}, {CHAR}, first-person POV under café awning rainy neon night, she stands ahead with transparent umbrella, looking toward camera, medium shot, face sharp"),
    ("02_walk", "plate_street", True,
     f"{LIGHT}, {CHAR}, first-person POV walking under shared transparent umbrella rainy neon street, she on the right holding umbrella, medium shot"),
    ("03_store", "plate_market", True,
     f"{LIGHT}, {CHAR}, first-person POV at supermarket glass entrance rainy night, she opens door shaking umbrella, warm interior spill light"),
    ("04_aisle", "plate_market", True,
     f"{LIGHT}, {CHAR}, first-person POV supermarket aisle, trench coat slightly open, she holds instant noodles toward camera, fluorescent light"),
    ("05_checkout", "plate_market", True,
     f"{LIGHT}, {CHAR}, first-person POV supermarket checkout, she hands a grocery bag toward camera, cashier lights"),
    ("06_homewalk", "plate_street", True,
     f"{LIGHT}, {CHAR}, first-person POV quieter rainy residential street, she shares umbrella carrying shopping bags, warm streetlamps"),
    ("07_entry", "plate_hallway", True,
     f"{LIGHT}, {CHAR}, first-person POV apartment hallway, she unlocks door with keys, wet umbrella, warm ceiling light"),
    ("08_kitchen", "plate_kitchen", False,
     f"{LIGHT}, a 30-year-old East Asian woman, long dark hair, same face identity, indoor casual top without trench coat, "
     f"first-person POV warm kitchen, she offers a mug of hot tea toward camera, steam, rain on window"),
]


def post(path: str, payload: dict, host: str = HOST) -> dict:
    req = urllib.request.Request(
        host + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode())


def get(path: str, host: str = HOST) -> dict:
    with urllib.request.urlopen(host + path, timeout=120) as r:
        return json.loads(r.read().decode())


def wait_prompt(pid: str, host: str, timeout: float = 1800) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        hist = get(f"/history/{pid}", host)
        if pid in hist:
            return hist[pid]
        time.sleep(5)
    raise TimeoutError(pid)


def copy_output_to_input(filename: str, dest_name: str) -> str:
    """Copy a Comfy output image into input/ so later LoadImage can see it."""
    # Search recent outputs
    matches = sorted(Path("/root/ComfyUI/output").rglob(filename.replace("%", "*")))
    # Also search by prefix
    prefix = dest_name
    cands = sorted(Path("/root/ComfyUI/output").rglob(f"{prefix}*.png"))
    if not cands:
        cands = sorted(Path("/root/ComfyUI/output/film_coherent").rglob(f"*{prefix}*.png"))
    if not cands:
        raise FileNotFoundError(f"no output for {dest_name}")
    src = cands[-1]
    dst = INPUT / f"{dest_name}.png"
    shutil.copy2(src, dst)
    return dst.name


def collect_saved(entry: dict, dest_name: str) -> str:
    for _nid, o in entry.get("outputs", {}).items():
        for im in o.get("images", []):
            sub = im.get("subfolder", "")
            name = im["filename"]
            src = Path("/root/ComfyUI/output") / sub / name if sub else Path("/root/ComfyUI/output") / name
            if not src.exists():
                # Comfy sometimes nests
                alts = list(Path("/root/ComfyUI/output").rglob(name))
                if alts:
                    src = alts[-1]
            dst_dir = OUT_ROOT / dest_name.split("_")[0]
            if dest_name.startswith("bible"):
                dst_dir = OUT_ROOT / "bible"
            elif dest_name.startswith("plate"):
                dst_dir = OUT_ROOT / "plates"
            elif dest_name[:2].isdigit():
                dst_dir = OUT_ROOT / "storyboard"
            else:
                dst_dir = OUT_ROOT / "misc"
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = dst_dir / f"{dest_name}.png"
            shutil.copy2(src, dst)
            # also into input for chaining
            shutil.copy2(src, INPUT / f"{dest_name}.png")
            return str(dst)
    raise RuntimeError(f"no images in output for {dest_name}: {entry.get('outputs')}")


def flux_graph(
    prompt: str,
    prefix: str,
    width: int,
    height: int,
    steps: int,
    seed: int,
    face: bool,
    upscale: bool,
    pulid_ref: str | None,
    use_pulid: bool,
) -> dict:
    g: dict = {
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
    model_ref: list = ["10", 0]
    if use_pulid and pulid_ref:
        g["50"] = {"class_type": "PulidFluxModelLoader", "inputs": {
            "pulid_file": "pulid_flux_v0.9.1.safetensors"}}
        g["51"] = {"class_type": "PulidFluxInsightFaceLoader", "inputs": {"provider": "CPU"}}
        g["52"] = {"class_type": "PulidFluxEvaClipLoader", "inputs": {}}
        g["53"] = {"class_type": "LoadImage", "inputs": {"image": pulid_ref}}
        g["54"] = {"class_type": "ApplyPulidFlux", "inputs": {
            "model": ["10", 0],
            "pulid_flux": ["50", 0],
            "eva_clip": ["52", 0],
            "face_analysis": ["51", 0],
            "image": ["53", 0],
            "weight": 0.85,
            "start_at": 0.0,
            "end_at": 1.0,
        }}
        model_ref = ["54", 0]
        g["19"]["inputs"]["model"] = model_ref

    g["16"] = {"class_type": "BasicGuider", "inputs": {
        "model": model_ref, "conditioning": ["15", 0]}}
    g["21"] = {"class_type": "SamplerCustomAdvanced", "inputs": {
        "noise": ["20", 0], "guider": ["16", 0], "sampler": ["18", 0],
        "sigmas": ["19", 0], "latent_image": ["17", 0]}}
    g["22"] = {"class_type": "VAEDecode", "inputs": {"samples": ["21", 0], "vae": ["12", 0]}}
    last: list = ["22", 0]

    if face:
        g["30"] = {"class_type": "UltralyticsDetectorProvider",
                   "inputs": {"model_name": "bbox/face_yolov8m.pt"}}
        g["31"] = {"class_type": "FaceDetailer", "inputs": {
            "image": list(last), "model": model_ref, "clip": ["11", 0], "vae": ["12", 0],
            "guide_size": 1024, "guide_size_for": True, "max_size": 1536,
            "seed": seed + 1, "steps": 16, "cfg": 1.0, "sampler_name": "euler", "scheduler": "beta",
            "positive": ["15", 0], "negative": ["14", 0],
            "denoise": 0.4, "feather": 8, "noise_mask": True, "force_inpaint": True,
            "bbox_threshold": 0.4, "bbox_dilation": 10, "bbox_crop_factor": 3.0,
            "sam_detection_hint": "center-1", "sam_dilation": 0, "sam_threshold": 0.93,
            "sam_bbox_expansion": 0, "sam_mask_hint_threshold": 0.7,
            "sam_mask_hint_use_negative": "False", "drop_size": 10,
            "bbox_detector": ["30", 0],
            "wildcard": "sharp detailed face, natural skin pores, catchlight in the eyes, subtle freckles",
            "cycle": 1}}
        last = ["31", 0]

    if upscale:
        g["40"] = {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "RealESRGAN_x4.pth"}}
        g["41"] = {"class_type": "UltimateSDUpscale", "inputs": {
            "image": list(last), "model": model_ref, "positive": ["15", 0], "negative": ["14", 0],
            "vae": ["12", 0], "upscale_by": 1.5, "seed": seed + 2, "steps": 12, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "beta", "denoise": 0.22,
            "upscale_model": ["40", 0], "mode_type": "Linear",
            "tile_width": 1024, "tile_height": 1024, "mask_blur": 8, "tile_padding": 32,
            "seam_fix_mode": "Half Tile", "seam_fix_denoise": 1.0, "seam_fix_width": 64,
            "seam_fix_mask_blur": 8, "seam_fix_padding": 16,
            "force_uniform_tiles": True, "tiled_decode": True, "batch_size": 1}}
        last = ["41", 0]

    g["99"] = {"class_type": "SaveImage", "inputs": {
        "images": list(last), "filename_prefix": f"film_coherent/{prefix}"}}
    return g


def run_one(name: str, prompt: str, host: str, width: int, height: int, steps: int,
            seed: int, face: bool, upscale: bool, pulid_ref: str | None, use_pulid: bool) -> str:
    print(f"\n=== {name} pulid={use_pulid and bool(pulid_ref)} {width}x{height} steps={steps} ===", flush=True)
    g = flux_graph(prompt, name, width, height, steps, seed, face, upscale, pulid_ref, use_pulid)
    try:
        resp = post("/prompt", {"prompt": g, "client_id": str(uuid.uuid4())}, host)
    except Exception as e:
        if use_pulid:
            print(f"  PuLID submit failed ({e}), retry without PuLID", flush=True)
            g = flux_graph(prompt, name, width, height, steps, seed, face, upscale, None, False)
            resp = post("/prompt", {"prompt": g, "client_id": str(uuid.uuid4())}, host)
        else:
            raise
    if "prompt_id" not in resp:
        # node errors — retry without pulid
        err = json.dumps(resp, ensure_ascii=False)[:1500]
        print("  submit error:", err, flush=True)
        if use_pulid:
            g = flux_graph(prompt, name, width, height, steps, seed, face, upscale, None, False)
            resp = post("/prompt", {"prompt": g, "client_id": str(uuid.uuid4())}, host)
        if "prompt_id" not in resp:
            raise RuntimeError(resp)
    pid = resp["prompt_id"]
    print(f"  queued {pid}", flush=True)
    entry = wait_prompt(pid, host)
    status = entry.get("status", {}).get("status_str")
    if status == "error":
        msgs = entry.get("status", {}).get("messages", [])
        err_detail = ""
        for m in msgs:
            if isinstance(m, (list, tuple)) and m and m[0] == "execution_error":
                err_detail = json.dumps(m[1], ensure_ascii=False)[:2000]
                break
        print("  ERROR", err_detail or msgs[:2], flush=True)
        if use_pulid:
            return run_one(name, prompt, host, width, height, steps, seed, face, upscale, None, False)
        raise RuntimeError(status)
    path = collect_saved(entry, name)
    print(f"  -> {path}", flush=True)
    return path


def ensure_host(host: str) -> None:
    get("/system_stats", host)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=HOST)
    ap.add_argument("--stage", choices=["bible", "plates", "keys", "all", "smoke"], default="all")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=768)
    ap.add_argument("--steps", type=int, default=24)
    ap.add_argument("--seed", type=int, default=20260812)
    ap.add_argument("--no-face", action="store_true")
    ap.add_argument("--no-upscale", action="store_true")
    ap.add_argument("--pulid", action="store_true", help="force PuLID on (needs weights)")
    ap.add_argument("--no-pulid", action="store_true")
    args = ap.parse_args()

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    ensure_host(args.host)

    pulid_weight = Path("/root/ComfyUI/models/pulid/pulid_flux_v0.9.1.safetensors")
    use_pulid = args.pulid or (pulid_weight.exists() and pulid_weight.stat().st_size > 1_000_000 and not args.no_pulid)
    if args.no_pulid:
        use_pulid = False
    print(f"host={args.host} use_pulid={use_pulid} weight_ok={pulid_weight.exists()} size={pulid_weight.stat().st_size if pulid_weight.exists() else 0}")

    face = not args.no_face
    up = not args.no_upscale

    if args.stage in ("smoke",):
        run_one("smoke_face", f"{LIGHT}, {CHAR}, front portrait", args.host,
                768, 768, 12, args.seed, True, False,
                "story_heroine.png" if (INPUT / "story_heroine.png").exists() else None,
                use_pulid and (INPUT / "story_heroine.png").exists())
        return 0

    bible_ref = None
    if args.stage in ("bible", "all"):
        for i, (name, prompt) in enumerate(BIBLE):
            # first bible shot: no pulid (establishes identity); later: lock to front
            ref = bible_ref
            up_pulid = use_pulid and ref is not None
            path = run_one(name, prompt, args.host, args.width, args.height, args.steps,
                           args.seed + i, face, False, ref, up_pulid)
            if name == "bible_front":
                bible_ref = f"{name}.png"
                # also set as story heroine master
                shutil.copy2(path, INPUT / "story_heroine_v2.png")
                shutil.copy2(path, INPUT / "story_heroine.png")

    if bible_ref is None and (INPUT / "bible_front.png").exists():
        bible_ref = "bible_front.png"
    elif bible_ref is None and (INPUT / "story_heroine_v2.png").exists():
        bible_ref = "story_heroine_v2.png"
    elif bible_ref is None and (INPUT / "story_heroine.png").exists():
        bible_ref = "story_heroine.png"

    if args.stage in ("plates", "all"):
        for i, (name, prompt) in enumerate(PLATES):
            run_one(name, prompt, args.host, args.width, args.height, max(16, args.steps - 4),
                    args.seed + 100 + i, False, False, None, False)

    if args.stage in ("keys", "all"):
        for i, (name, _plate, coat, prompt) in enumerate(KEYS):
            run_one(name, prompt, args.host, args.width, args.height, args.steps,
                    args.seed + 200 + i, face, up, bible_ref, use_pulid and bible_ref is not None)
            # bridge: copy key as next bridge tail proxy
            src = OUT_ROOT / "storyboard" / f"{name}.png"
            if src.exists():
                br = OUT_ROOT / "bridge"
                br.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, br / f"{name}_tail.png")

    board = {
        "character_ref": bible_ref,
        "bible": [n for n, _ in BIBLE],
        "plates": [n for n, _ in PLATES],
        "keys": [{"id": n, "plate": p, "coat": c} for n, p, c, _ in KEYS],
        "out_root": str(OUT_ROOT),
    }
    board_path = Path("/workdata/ComfyUI/workflows/story_rain_day_v2_board.json")
    board_path.parent.mkdir(parents=True, exist_ok=True)
    board_path.write_text(json.dumps(board, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"board -> {board_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
