#!/usr/bin/env python3
"""Smoke-test the image half of the master workflow through ComfyUI's API.

Runs majicFlus -> FaceDetailer -> UltimateSDUpscale on a short fixed prompt so a
failure shows up here instead of mid-render. Prompt polish is skipped because the
LLM service is optional.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
import uuid

HOST = "http://127.0.0.1:8188"

PROMPT = (
    "photorealistic live-action film still, a 30-year-old East Asian woman in a beige trench coat "
    "holding a transparent umbrella on a neon-lit rainy street at night, medium shot, face clearly "
    "framed and in sharp focus, natural skin texture with visible pores, wet pavement reflections, "
    "35mm lens, shallow depth of field, cinematic color grade, natural lighting"
)
NEGATIVE = (
    "blurry, out of focus, plastic skin, waxy skin, deformed face, bad anatomy, "
    "anime, illustration, 3d render, watermark, text"
)


def build_graph(width: int, height: int, steps: int, do_face: bool, do_upscale: bool) -> dict:
    g = {
        "10": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "majicflus_v134.safetensors", "weight_dtype": "default"}},
        "11": {"class_type": "DualCLIPLoader", "inputs": {
            "clip_name1": "clip_l.safetensors", "clip_name2": "t5xxl_fp16.safetensors", "type": "flux"}},
        "12": {"class_type": "VAELoader", "inputs": {"vae_name": "flux1_ae.safetensors"}},
        "13": {"class_type": "CLIPTextEncode", "inputs": {"text": PROMPT, "clip": ["11", 0]}},
        "14": {"class_type": "CLIPTextEncode", "inputs": {"text": NEGATIVE, "clip": ["11", 0]}},
        "15": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["13", 0], "guidance": 3.5}},
        "16": {"class_type": "BasicGuider", "inputs": {"model": ["10", 0], "conditioning": ["15", 0]}},
        "17": {"class_type": "EmptySD3LatentImage", "inputs": {
            "width": width, "height": height, "batch_size": 1}},
        "18": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "19": {"class_type": "BasicScheduler", "inputs": {
            "model": ["10", 0], "scheduler": "beta", "steps": steps, "denoise": 1.0}},
        "20": {"class_type": "RandomNoise", "inputs": {"noise_seed": 12345}},
        "21": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["20", 0], "guider": ["16", 0], "sampler": ["18", 0],
            "sigmas": ["19", 0], "latent_image": ["17", 0]}},
        "22": {"class_type": "VAEDecode", "inputs": {"samples": ["21", 0], "vae": ["12", 0]}},
    }
    last = ("22", 0)

    if do_face:
        g["30"] = {"class_type": "UltralyticsDetectorProvider",
                   "inputs": {"model_name": "bbox/face_yolov8m.pt"}}
        g["31"] = {"class_type": "FaceDetailer", "inputs": {
            "image": list(last), "model": ["10", 0], "clip": ["11", 0], "vae": ["12", 0],
            "guide_size": 1024, "guide_size_for": True, "max_size": 1536,
            "seed": 42, "steps": 20, "cfg": 1.0, "sampler_name": "euler", "scheduler": "beta",
            "positive": ["15", 0], "negative": ["14", 0],
            "denoise": 0.45, "feather": 8, "noise_mask": True, "force_inpaint": True,
            "bbox_threshold": 0.4, "bbox_dilation": 10, "bbox_crop_factor": 3.0,
            "sam_detection_hint": "center-1", "sam_dilation": 0, "sam_threshold": 0.93,
            "sam_bbox_expansion": 0, "sam_mask_hint_threshold": 0.7,
            "sam_mask_hint_use_negative": "False", "drop_size": 10,
            "bbox_detector": ["30", 0],
            "wildcard": "sharp detailed face, natural skin pores, catchlight in the eyes",
            "cycle": 1}}
        last = ("31", 0)

    if do_upscale:
        g["40"] = {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "RealESRGAN_x4.pth"}}
        g["41"] = {"class_type": "UltimateSDUpscale", "inputs": {
            "image": list(last), "model": ["10", 0], "positive": ["15", 0], "negative": ["14", 0],
            "vae": ["12", 0], "upscale_by": 2.0, "seed": 42, "steps": 14, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "beta", "denoise": 0.22,
            "upscale_model": ["40", 0], "mode_type": "Linear",
            "tile_width": 1024, "tile_height": 1024, "mask_blur": 8, "tile_padding": 32,
            "seam_fix_mode": "Half Tile", "seam_fix_denoise": 1.0, "seam_fix_width": 64,
            "seam_fix_mask_blur": 8, "seam_fix_padding": 16,
            "force_uniform_tiles": True, "tiled_decode": True, "batch_size": 1}}
        last = ("41", 0)

    g["99"] = {"class_type": "SaveImage", "inputs": {
        "images": list(last), "filename_prefix": "smoke/master_chain"}}
    return g


def post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        HOST + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def get(path: str) -> dict:
    with urllib.request.urlopen(HOST + path, timeout=60) as r:
        return json.loads(r.read().decode())


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--width", type=int, default=1344)
    ap.add_argument("--height", type=int, default=768)
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--no-face", action="store_true")
    ap.add_argument("--no-upscale", action="store_true")
    ap.add_argument("--wait", type=int, default=2400)
    args = ap.parse_args()

    client_id = str(uuid.uuid4())
    graph = build_graph(args.width, args.height, args.steps, not args.no_face, not args.no_upscale)
    resp = post("/prompt", {"prompt": graph, "client_id": client_id})
    if "prompt_id" not in resp:
        print("submit failed:", json.dumps(resp, ensure_ascii=False)[:2000])
        return 1
    pid = resp["prompt_id"]
    print(f"queued {pid} ({args.width}x{args.height}, {args.steps} steps, "
          f"face={not args.no_face}, upscale={not args.no_upscale})", flush=True)

    start = time.time()
    while time.time() - start < args.wait:
        hist = get(f"/history/{pid}")
        if pid in hist:
            entry = hist[pid]
            status = entry.get("status", {})
            print(f"\nstatus: {status.get('status_str')} after {time.time() - start:.0f}s")
            if status.get("status_str") == "error":
                for m in status.get("messages", []):
                    print(" ", json.dumps(m, ensure_ascii=False)[:1500])
                return 1
            for node_id, o in entry.get("outputs", {}).items():
                for img in o.get("images", []):
                    print(f"  image: {img.get('subfolder')}/{img.get('filename')}")
            return 0
        time.sleep(10)
        print(".", end="", flush=True)

    print("\ntimed out waiting for result")
    return 1


if __name__ == "__main__":
    sys.exit(main())
