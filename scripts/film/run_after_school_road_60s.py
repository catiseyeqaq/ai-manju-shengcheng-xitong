#!/usr/bin/env python3
"""《放学路上》60s campus romance — bible → plates → keys → H3 Turbo → concat.

Quality targets:
  - Identity: majicFlus + PuLID face lock across all character stills
  - Video: MiniMax-H3 I2VA + Turbo LoRA 8-step @ 1920x1088 (~2K 16:9 grid)
  - A/V: native H3 synced audio; final concat 24fps / 48kHz
  - Lighting: cinematic prompts + FaceDetailer + light USDU on stills

Stages:
  bible   — character bible (GPU stills :8192)
  plates  — empty China campus plates (FLUX.2 :8193)
  keys    — 10 POV keyframes with PuLID (:8192)
  video   — H3 I2VA dual workers :8188/:8191 (max 2)
  merge   — ffmpeg beautify concat → 60s cut

Usage:
  python run_after_school_road_60s.py --stage all
  python run_after_school_road_60s.py --stage bible
  python run_after_school_road_60s.py --stage video --shots 02,05,07,09
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

PY = Path("/opt/miniconda3/envs/ComfyUI/bin/python")
FFMPEG = Path("/opt/miniconda3/envs/ComfyUI/bin/ffmpeg")
FFPROBE = Path("/opt/miniconda3/envs/ComfyUI/bin/ffprobe")
INPUT = Path("/root/ComfyUI/input")
OUT = Path("/root/ComfyUI/output/after_school_road")
LOG = Path("/workdata/ComfyUI/logs/after_school_road.log")
JOBS = Path("/workdata/ComfyUI/logs/after_school_road_jobs.json")

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

LIGHT = (
    "photorealistic live-action cinema, majicFlus look, natural skin pores, "
    "35mm film, soft practical lighting, accurate white balance, high dynamic range, "
    "rich volumetric light, cinematic color grade, Chinese mainland high school"
)

CHAR = (
    "a 17-18-year-old Chinese mainland high school girl, majicFlus photoreal beauty, "
    "soft youthful features, long black hair with light air bangs, gentle clean eyes "
    "with catchlights, Chinese school uniform style white blouse, navy pleated skirt, "
    "dark knit cardigan, ordinary school backpack, shy gentle personality, same person"
)

CORE_H3 = (
    "photoreal live-action, majicFlus look, Chinese mainland modern high school, "
    "first-person POV of a teenage boy, a 17-18yo East Asian schoolgirl, "
    "soft youthful majicFlus features, long black hair with light air bangs, "
    "Chinese school uniform style white blouse, navy pleated skirt, dark knit cardigan, "
    "gentle shy personality, warm afternoon-to-sunset natural light, high quality lighting, "
    "Simplified Chinese characters only on any signs or blackboard writing, "
    "youth campus romance short film, restrained cinematic handheld feel, "
    "small amplitude at slow speed camera moves"
)

BIBLE = [
    ("asr_bible_front", f"{LIGHT}, {CHAR}, front portrait looking at camera, soft window light, head and shoulders, sharp face"),
    ("asr_bible_3q", f"{LIGHT}, {CHAR}, three-quarter portrait, gentle smile, corridor window rim light"),
    ("asr_bible_lookback", f"{LIGHT}, {CHAR}, looking back over shoulder toward camera, slight smile"),
    ("asr_bible_shy", f"{LIGHT}, {CHAR}, looking down, fingers on backpack strap, ear tips faintly red"),
    ("asr_bible_blush", f"{LIGHT}, {CHAR}, blushing cheeks, looking up into camera, confession mood, sunset rim"),
    ("asr_bible_full", f"{LIGHT}, {CHAR}, full body standing in Chinese high school corridor, medium-wide"),
]

PLATES = [
    ("asr_plate_classroom", f"{LIGHT}, empty Chinese high school classroom, afternoon sun, blackboard with Simplified Chinese chalk writing only, wooden desks, no people, establishing wide, rich god rays"),
    ("asr_plate_corridor", f"{LIGHT}, empty Chinese high school corridor, Simplified Chinese bulletin boards only, depth for tracking, no people, volumetric window light"),
    ("asr_plate_gate", f"{LIGHT}, Chinese high school front gate at dusk, warm sunset, Simplified Chinese school plaque only, cinematic youth-film atmosphere, no people in foreground"),
    ("asr_plate_street", f"{LIGHT}, Chinese residential street after school, zebra crossing, shops with Simplified Chinese signs only, golden hour, empty foreground"),
]

# (id, first_bible_or_key_hint, last_hint, still_prompt, h3_action, dialogue_zh|None, seed)
SHOTS = [
    {
        "id": "01_class",
        "seed": SEED0 + 1,
        "plate": "asr_plate_classroom",
        "still": f"{LIGHT}, {CHAR}, seated ahead by classroom window from boy POV behind desks, blackboard Simplified Chinese writing, afternoon sun god rays, medium shot face soft side",
        "action": (
            "[Shot 1] First-person POV seated in Chinese classroom. Soft afternoon sun. "
            "The girl sits ahead by the window, quietly taking notes, then slightly turns her head; "
            "hair catches the light. Slow gentle push-in, small amplitude at slow speed."
        ),
        "audio": "overall_soundscape: quiet classroom, page turning, distant teacher voice (no clear words).\nnon_diegetic_music: very soft warm piano, low volume.",
        "dialogue": None,
        "priority": 1,
    },
    {
        "id": "02_smile",
        "seed": SEED0 + 2,
        "plate": "asr_plate_classroom",
        "still": f"{LIGHT}, {CHAR}, looking back toward camera from front desk, tiny smile, classroom bokeh, sharp face",
        "action": (
            "[Shot 1] First-person POV looking forward. The girl senses the gaze, briefly looks back "
            "toward the camera, freezes a beat, gives a tiny smile, then turns forward again. "
            "Stable frame, warm natural light, Simplified Chinese on blackboard."
        ),
        "audio": "overall_soundscape: soft teacher murmur, chalk, quiet classroom.\nnon_diegetic_music: barely audible warm pad.",
        "dialogue": None,
        "priority": 0,
    },
    {
        "id": "03_bell",
        "seed": SEED0 + 3,
        "plate": "asr_plate_classroom",
        "still": f"{LIGHT}, {CHAR}, standing beside desk holding textbook, glancing back to signal leaving, classroom after-class light",
        "action": (
            "[Shot 1] Class-end bell rings. POV hands packing books. The girl passes and gently taps "
            "the desk edge with her book, looks back to signal let's go, light playful motion. Small follow."
        ),
        "audio": "overall_soundscape: school bell, chairs moving, light chatter.\nnon_diegetic_music: N/A",
        "dialogue": None,
        "priority": 1,
    },
    {
        "id": "04_corridor",
        "seed": SEED0 + 4,
        "plate": "asr_plate_corridor",
        "still": f"{LIGHT}, {CHAR}, walking Chinese school corridor looking back smiling, Simplified Chinese bulletin boards, tracking depth",
        "action": (
            "[Shot 1] POV walking Chinese school corridor. Girl walks ahead, looks back while talking "
            "casually with a light smile. Bulletin boards in Simplified Chinese only. Gentle tracking."
        ),
        "audio": "overall_soundscape: footsteps, corridor reverb, distant student voices.\nnon_diegetic_music: soft light underscore.",
        "dialogue": None,
        "priority": 1,
    },
    {
        "id": "05_play",
        "seed": SEED0 + 5,
        "plate": "asr_plate_gate",
        "still": f"{LIGHT}, {CHAR}, outside teaching building, laughing, stepping back, playful hand toward camera, warm late afternoon",
        "action": (
            "[Shot 1] Outside near teaching building. Light playful moment: girl steps back half a step laughing, "
            "raises a hand toward camera as if blocking, then looks back smiling. Keep motion small and soft."
        ),
        "audio": "overall_soundscape: laughter, wind, soft campus ambience.\nnon_diegetic_music: playful soft piano.",
        "dialogue": None,
        "priority": 0,
    },
    {
        "id": "06_invite",
        "seed": SEED0 + 6,
        "plate": "asr_plate_gate",
        "still": f"{LIGHT}, {CHAR}, at Chinese high school gate at sunset, half step ahead, shy side glance, golden hour rim light, sharp face",
        "action": (
            "[Shot 1] At Chinese high school gate at sunset. Girl stands half a step ahead, turns slightly, "
            "shyly asks in Chinese: <d>[Chinese] 要不要一起回家？</d> Soft push-in."
        ),
        "audio": "overall_soundscape: after-school crowd, distant traffic.\nnon_diegetic_music: gentle swell.",
        "dialogue": "要不要一起回家？",
        "priority": 1,
    },
    {
        "id": "07_walk",
        "seed": SEED0 + 7,
        "plate": "asr_plate_street",
        "still": f"{LIGHT}, {CHAR}, walking residential Chinese street side-by-side feel, golden hour, Simplified Chinese shop signs, medium shot",
        "action": (
            "[Shot 1] Walking home side by side on Chinese residential street. Shop signs Simplified Chinese only. "
            "Girl occasionally turns to say small everyday things. Stable forward move, golden hour, hair in wind."
        ),
        "audio": "overall_soundscape: footsteps, city bed, light breeze.\nnon_diegetic_music: warm soft underscore.",
        "dialogue": None,
        "priority": 0,
    },
    {
        "id": "08_tension",
        "seed": SEED0 + 8,
        "plate": "asr_plate_street",
        "still": f"{LIGHT}, {CHAR}, on dusk street gripping backpack strap, eyes avoiding camera, faint blush, anticipatory mood",
        "action": (
            "[Shot 1] Same street, mood shifts. Girl becomes quiet, grips backpack strap, eyes avoid camera, "
            "ear tips and cheeks faintly blush. Slow the pace. Anticipation before confession."
        ),
        "audio": "overall_soundscape: footsteps dominant; city bed lowered.\nnon_diegetic_music: thinning soft strings.",
        "dialogue": None,
        "priority": 1,
    },
    {
        "id": "09_confess",
        "seed": SEED0 + 9,
        "plate": "asr_plate_street",
        "still": f"{LIGHT}, {CHAR}, facing camera at dusk, blushing, nervous sincere expression, sunset on face, confession close-up",
        "action": (
            "[Shot 1] She stops; POV stops. Facing her. She looks down, breathes, then looks up into camera, "
            "blushing, nervous but sincere, says in Chinese: <d>[Chinese] 其实……我喜欢你很久了。</d> "
            "Slow push-in, sunset on her face."
        ),
        "audio": "overall_soundscape: near silence plus far city.\nnon_diegetic_music: soft emotional underscore after the line.",
        "dialogue": "其实……我喜欢你很久了。",
        "priority": 0,
    },
    {
        "id": "10_end",
        "seed": SEED0 + 10,
        "plate": "asr_plate_street",
        "still": f"{LIGHT}, {CHAR}, sunset backlight, shy relieved smile after confession, hair in breeze, ending portrait",
        "action": (
            "[Shot 1] After confession pause. POV steps half a step closer. She presses her lips, then gives a "
            "relieved shy smile, sunset backlight, hair in breeze. Hold on her expectant expression as ending."
        ),
        "audio": "overall_soundscape: wind, distant city.\nnon_diegetic_music: soft resolve.",
        "dialogue": None,
        "priority": 1,
    },
]


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
            src = Path("/root/ComfyUI/output") / sub / name if sub else Path("/root/ComfyUI/output") / name
            if not src.exists():
                alts = list(Path("/root/ComfyUI/output").rglob(name))
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
                src = Path("/root/ComfyUI/output") / sub / name if sub else Path("/root/ComfyUI/output") / name
                if not src.exists():
                    alts = list(Path("/root/ComfyUI/output").rglob(name))
                    if not alts:
                        continue
                    src = alts[-1]
                dst = dest_dir / f"{stem}.mp4"
                shutil.copy2(src, dst)
                return dst
    # fallback glob
    cands = sorted(Path("/root/ComfyUI/output/video").glob(f"*{stem}*"))
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
        "images": list(last), "filename_prefix": f"after_school_road/{prefix}"}}
    return g


def h3_graph(first: str, last: str | None, prompt: str, seed: int, length: int) -> dict:
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
            "video": ["14", 0], "filename_prefix": f"video/after_school_road/{Path(first).stem}",
            "format": "auto", "codec": "auto"}},
    }
    if last:
        g["1b"] = {"class_type": "LoadImage", "inputs": {"image": last}}
        g["6"]["inputs"]["last_frame"] = ["1b", 0]
    return g


def run_still(host: str, prompt: str, stem: str, seed: int, *, backend: str,
              pulid: str | None, w: int, h: int, steps: int, face: bool, upscale: bool) -> Path:
    out_path = OUT / ("bible" if stem.startswith("asr_bible") else "plates" if "plate" in stem else "keys") / f"{stem}.png"
    if out_path.exists() and out_path.stat().st_size > 10_000:
        log(f"skip exists {out_path}")
        shutil.copy2(out_path, INPUT / f"{stem}.png")
        return out_path
    g = flux_graph(prompt, stem, w, h, steps, seed, backend=backend,
                   pulid_ref=pulid, face=face, upscale=upscale)
    resp = post(host, "/prompt", {"prompt": g, "client_id": str(uuid.uuid4())})
    if "prompt_id" not in resp:
        raise RuntimeError(resp)
    pid = resp["prompt_id"]
    log(f"still {stem} -> {host} {pid}")
    entry = wait_prompt(host, pid, timeout=2400)
    dst = save_images(entry, out_path.parent, stem)
    log(f"saved {dst}")
    return dst


def stage_bible() -> str:
    OUT.mkdir(parents=True, exist_ok=True)
    # first front without PuLID
    front = run_still(STILLS_A, BIBLE[0][1], BIBLE[0][0], SEED0, backend="majic",
                      pulid=None, w=BIBLE_W, h=BIBLE_H, steps=28, face=True, upscale=True)
    pulid = f"{BIBLE[0][0]}.png"
    # remaining with PuLID lock
    for i, (stem, prompt) in enumerate(BIBLE[1:], start=1):
        host = STILLS_A if i % 2 else STILLS_B
        run_still(host, prompt, stem, SEED0 + i, backend="majic",
                  pulid=pulid, w=BIBLE_W, h=BIBLE_H, steps=26, face=True, upscale=True)
    # also copy front as canonical face ref
    shutil.copy2(front, INPUT / "asr_face_ref.png")
    log(f"bible done; PuLID ref=asr_face_ref.png")
    return "asr_face_ref.png"


def stage_plates() -> None:
    for i, (stem, prompt) in enumerate(PLATES):
        host = STILLS_B if i % 2 == 0 else STILLS_A
        run_still(host, prompt, stem, SEED0 + 100 + i, backend="flux2",
                  pulid=None, w=STILL_W, h=STILL_H, steps=24, face=False, upscale=False)


def stage_keys(pulid: str) -> None:
    # Generate each shot keyframe at H3 native 1920x1088 for clean I2VA
    for i, shot in enumerate(SHOTS):
        host = STILLS_A if i % 2 == 0 else STILLS_B
        stem = f"asr_key_{shot['id']}"
        run_still(host, shot["still"], stem, shot["seed"], backend="majic",
                  pulid=pulid, w=W, h=H, steps=26, face=True, upscale=False)


def build_h3_prompt(shot: dict) -> str:
    return (
        f"For the target video, at 0.00 seconds into the target video, "
        f"<Picture 1> (from [Shot 1]) is fully referenced.\n\n"
        f"integrated_multimodal_description: {CORE_H3}\n\n"
        f"{shot['action']}\n\n"
        f"{shot['audio']}\n"
        f"No Japanese/Korean/European signage, no English billboards, no anime."
    )


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
        [str(PY), "/workdata/ComfyUI/scripts/start_studio_4gpu.py"],
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


def stage_video(only: set[str] | None = None) -> list[Path]:
    ensure_h3_workers()
    length = frames_for_duration(DURATION)
    log(f"H3 length={length} frames (~{DURATION}s) {W}x{H} turbo={TURBO_STEPS}")
    shots = [s for s in SHOTS if only is None or s["id"] in only]
    # priority order then id
    shots = sorted(shots, key=lambda s: (s["priority"], s["id"]))
    hosts = [H3_A, H3_B]
    results: list[Path] = []
    jobs: dict = {}

    def one(shot: dict, host: str) -> Path:
        out_clip = OUT / "clips" / f"{shot['id']}.mp4"
        if out_clip.exists() and out_clip.stat().st_size > 100_000:
            log(f"skip clip exists {out_clip}")
            return out_clip
        first = f"asr_key_{shot['id']}.png"
        # bridge last = next shot key if exists
        idx = next(i for i, s in enumerate(SHOTS) if s["id"] == shot["id"])
        last = None
        if idx + 1 < len(SHOTS):
            last = f"asr_key_{SHOTS[idx + 1]['id']}.png"
            if not (INPUT / last).exists():
                last = None
        if not (INPUT / first).exists():
            raise FileNotFoundError(first)
        prompt = build_h3_prompt(shot)
        g = h3_graph(first, last, prompt, shot["seed"], length)
        resp = post(host, "/prompt", {"prompt": g, "client_id": str(uuid.uuid4())})
        if "prompt_id" not in resp:
            raise RuntimeError(resp)
        pid = resp["prompt_id"]
        log(f"H3 {shot['id']} -> {host} {pid}")
        jobs[shot["id"]] = {"port": int(host.rsplit(":", 1)[1]), "prompt_id": pid}
        JOBS.write_text(json.dumps(jobs, indent=2), encoding="utf-8")
        entry = wait_prompt(host, pid, timeout=5400)
        dst = save_video(entry, OUT / "clips", shot["id"])
        log(f"clip {dst}")
        return dst

    # dual queue: submit up to 2 at a time
    i = 0
    while i < len(shots):
        batch = shots[i:i + 2]
        with ThreadPoolExecutor(max_workers=len(batch)) as ex:
            futs = {ex.submit(one, s, hosts[j % 2]): s for j, s in enumerate(batch)}
            for fut in as_completed(futs):
                s = futs[fut]
                try:
                    results.append(fut.result())
                except Exception as e:
                    log(f"FAIL {s['id']}: {e}")
                    raise
        i += 2
    return results


def stage_merge() -> Path:
    clips_dir = OUT / "clips"
    ordered = []
    for s in SHOTS:
        p = clips_dir / f"{s['id']}.mp4"
        if not p.exists():
            raise FileNotFoundError(p)
        ordered.append(p)
    work = OUT / "merge_work"
    work.mkdir(parents=True, exist_ok=True)
    norms = []
    for p in ordered:
        dst = work / f"norm_{p.name}"
        # normalize A/V for sync: 24fps, 48kHz, trim to ~6s
        subprocess.check_call([
            str(FFMPEG), "-y", "-i", str(p),
            "-vf", "fps=24,format=yuv420p",
            "-af", "aresample=48000:async=1,loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:v", "libx264", "-preset", "slow", "-crf", "16",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-t", f"{DURATION:.3f}",
            "-movflags", "+faststart", str(dst),
        ])
        norms.append(dst)
    # soft xfade chain
    n = len(norms)
    fade = 0.15
    inputs = []
    for f in norms:
        inputs += ["-i", str(f)]
    filters = []
    # probe durations
    durs = []
    for f in norms:
        out = subprocess.check_output([
            str(FFPROBE), "-v", "error", "-show_entries", "format=duration",
            "-of", "json", str(f),
        ])
        durs.append(float(json.loads(out)["format"]["duration"]))
    cur_v, cur_a = "[0:v]", "[0:a]"
    offset = durs[0] - fade
    for i in range(1, n):
        ov, oa = f"[vx{i}]", f"[ax{i}]"
        filters.append(f"{cur_v}[{i}:v]xfade=transition=fade:duration={fade}:offset={offset:.6f}{ov}")
        filters.append(f"{cur_a}[{i}:a]acrossfade=d={fade}:c1=tri:c2=tri{oa}")
        cur_v, cur_a = ov, oa
        if i < n - 1:
            offset += durs[i] - fade
    filters.append(f"{cur_v}format=yuv420p[vout]")
    filters.append(f"{cur_a}aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[aout]")
    final = OUT / "after_school_road_60s.mp4"
    subprocess.check_call([
        str(FFMPEG), "-y", *inputs,
        "-filter_complex", ";".join(filters),
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "slow", "-crf", "15",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart", str(final),
    ])
    log(f"FINAL {final} ({final.stat().st_size/1e6:.1f} MB)")
    return final


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all",
                    choices=["all", "bible", "plates", "keys", "video", "merge", "priority"])
    ap.add_argument("--shots", default="", help="comma ids for video stage, e.g. 02_smile,09_confess")
    ap.add_argument("--pulid", default="", help="override pulid ref filename in input/")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    only = {x.strip() for x in args.shots.split(",") if x.strip()} or None
    pulid = args.pulid or ("asr_face_ref.png" if (INPUT / "asr_face_ref.png").exists() else "")

    if args.stage in ("all", "bible"):
        pulid = stage_bible()
    if args.stage in ("all", "plates"):
        stage_plates()
    if args.stage in ("all", "keys"):
        if not pulid:
            raise SystemExit("need --pulid or run bible first")
        stage_keys(pulid)
    if args.stage == "priority":
        only = {s["id"] for s in SHOTS if s["priority"] == 0}
        if not pulid:
            raise SystemExit("need bible/pulid first")
        if not list((OUT / "keys").glob("asr_key_*.png")):
            stage_keys(pulid)
        stage_video(only)
        return 0
    if args.stage in ("all", "video"):
        stage_video(only)
    if args.stage in ("all", "merge"):
        stage_merge()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
