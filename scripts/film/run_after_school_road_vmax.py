#!/usr/bin/env python3
"""《放学路上》vmax — 把 majicFlus + H3 本地链路拉到极致。

相对 v2:
  - 静帧: FaceDetailer(双轮) + UltimateSDUpscale 1.5x → lanczos 回 1920×1088
  - 提示: 纪实/手机抓拍肤质（毛孔/绒毛/微红），禁磨皮塑料感；近景为主
  - 单人强制 + 强负向 twin/clone
  - H3: first-only + 微动（呼吸/眨眼/发丝），禁止大动作与人群
  - 成片: 轻度胶片对比 + 颗粒 + 锐化

Usage:
  python run_after_school_road_vmax.py --stage all
  python run_after_school_road_vmax.py --stage keys --force
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, "/workdata/ComfyUI/scripts")
from run_after_school_road_60s import (  # noqa: E402
    FFMPEG,
    FFPROBE,
    H3_A,
    H3_B,
    INPUT,
    STILLS_A,
    STILLS_B,
    TURBO_LORA,
    ensure_h3_workers,
    frames_for_duration,
    log,
    post,
    save_images,
    save_video,
    wait_prompt,
)

OUT = Path("/root/ComfyUI/output/after_school_road_vmax")
JOBS = Path("/workdata/ComfyUI/logs/after_school_road_vmax_jobs.json")
PULID = "asr_face_ref.png"
W, H = 1920, 1088
DURATION = 5.0
SEED0 = 2026081219
TURBO_STEPS = 8
TURBO_STRENGTH = 1.05  # slightly stronger lock to first frame texture
KEY_STEPS = 32

NEG = (
    "blurry, lowres, plastic skin, waxy skin, airbrushed, beauty filter, doll skin, "
    "cgi, 3d render, overprocessed, porcelain face, smooth plastic, "
    "twin, twins, clone, duplicate person, identical faces, two girls, two women, "
    "doppelganger, split body, ghosting, extra person, crowd, classmates close, "
    "second face, mirrored person, deformed hands, extra fingers, "
    "anime, illustration, japanese sailor fuku, hangul, english billboard, "
    "oversexualized, heavy makeup, fake eyelash clumps"
)

# 纪实真人感：故意压「网红磨皮」，抬毛孔/微瑕/抓拍光
REAL = (
    "photoreal candid documentary photograph, Sony A7IV 85mm f/1.8, natural window light, "
    "real human skin with visible pores and fine peach fuzz, subtle freckles, "
    "natural lip texture, catchlights in eyes, slight under-eye softness, "
    "imperfect stray hair strands, soft film grain, majicFlus photoreal base, "
    "NOT beauty filter, NOT plastic skin, NOT CGI"
)

CHAR = (
    "ONE single 17-18-year-old Chinese mainland high school girl only, "
    "same identity as reference, long black hair with light air bangs, "
    "Chinese school uniform white blouse, navy knit cardigan, navy pleated skirt, "
    "ordinary school backpack, shy gentle everyday look"
)

SOLO = "only one person in the entire frame, empty of other people, no crowd, solo subject"

CORE_H3 = (
    "photoreal live-action documentary, preserve exact face and skin texture from first frame, "
    "Chinese mainland modern high school, strict first-person boy POV (camera=eyes), "
    "ONLY ONE girl visible, majicFlus photoreal, natural pores, "
    "micro-motion only: soft breathing, tiny blink, hair breeze, almost locked camera, "
    "no twins no clones no crowd, Simplified Chinese only if any text"
)

FACE_WILDCARD = (
    "ultra detailed real face, visible skin pores, fine peach fuzz, natural subsurface blush, "
    "realistic iris catchlight, individual eyelashes, soft natural lips, majicFlus photoreal, "
    "no plastic skin, no beauty filter"
)

SHOTS = [
    {
        "id": "01_class",
        "seed": SEED0 + 1,
        "still": (
            f"{REAL}, {CHAR}, {SOLO}, empty Chinese classroom, medium close-up from desk behind, "
            "she sits by window writing, afternoon sun on cheek and hair rim light, "
            "shallow depth of field, blackboard soft bokeh Simplified Chinese, sharp eyes"
        ),
        "action": (
            "[Shot 1] Strict first-person POV. Empty classroom. Only the one girl by the window. "
            "Almost locked camera. She writes slowly, breathes, tiny head turn. "
            "Preserve skin pores from reference. No other students."
        ),
        "audio": "overall_soundscape: quiet classroom, soft page scratch.\nnon_diegetic_music: very low warm piano.",
    },
    {
        "id": "02_smile",
        "seed": SEED0 + 2,
        "still": (
            f"{REAL}, {CHAR}, {SOLO}, empty classroom, close-up looking back over shoulder toward camera, "
            "tiny natural smile, eyes sharp, window backlight hair glow, shallow bokeh, candid"
        ),
        "action": (
            "[Shot 1] Strict first-person POV close-up. Only the one girl. She looks back, "
            "tiny natural smile forms, soft blink, then eyes soften. Camera nearly still. "
            "Keep exact face texture. No classmates."
        ),
        "audio": "overall_soundscape: soft classroom ambience.\nnon_diegetic_music: barely audible.",
    },
    {
        "id": "04_corridor",
        "seed": SEED0 + 4,
        "still": (
            f"{REAL}, {CHAR}, {SOLO}, empty Chinese school corridor, medium close-up she looks back walking, "
            "soft fluorescent + window mix light, Simplified Chinese bulletin soft bokeh, candid tracking feel"
        ),
        "action": (
            "[Shot 1] Strict first-person POV. Empty corridor. Only the one girl ahead. "
            "Very slow gentle tracking, she glances back with light smile. Micro motion only. No students."
        ),
        "audio": "overall_soundscape: soft footsteps, corridor reverb.\nnon_diegetic_music: soft light underscore.",
    },
    {
        "id": "05_play",
        "seed": SEED0 + 5,
        "still": (
            f"{REAL}, {CHAR}, {SOLO}, outside empty plaza by teaching building, medium close-up laughing, "
            "warm late afternoon, hand near chest not extreme gesture, candid joy, sharp eyes"
        ),
        "action": (
            "[Shot 1] Strict first-person POV outside. Only the one girl. Small laugh, tiny half-step, "
            "hair moves in breeze. Keep motion SMALL. Preserve face. No crowd."
        ),
        "audio": "overall_soundscape: light wind, soft campus.\nnon_diegetic_music: soft playful piano.",
    },
    {
        "id": "07_walk",
        "seed": SEED0 + 7,
        "still": (
            f"{REAL}, {CHAR}, {SOLO}, Chinese residential street golden hour, medium close-up walking beside POV, "
            "she glances toward camera, rim light on hair, Simplified Chinese shop signs soft, candid"
        ),
        "action": (
            "[Shot 1] Strict first-person POV walking. Only the one girl visible at side-front. "
            "Slow forward move, she glances once. Hair breeze. No other faces. Micro motion."
        ),
        "audio": "overall_soundscape: footsteps, light breeze, distant city.\nnon_diegetic_music: warm soft underscore.",
    },
    {
        "id": "09_confess",
        "seed": SEED0 + 9,
        "still": (
            f"{REAL}, {CHAR}, {SOLO}, dusk street extreme close-up portrait facing camera, "
            "nervous blush, sincere eyes slightly wet catchlight, sunset side light, "
            "candid confession moment, sharp pores"
        ),
        "action": (
            "[Shot 1] Strict first-person POV extreme close-up. She alone. Looks down, soft breath, "
            "looks up blushing, says in Chinese: <d>[Chinese] 其实……我喜欢你很久了。</d> "
            "Slow tiny push-in. Preserve skin. No other people."
        ),
        "audio": "overall_soundscape: near silence plus far city.\nnon_diegetic_music: soft emotional underscore after the line.",
    },
]


def flux_graph_vmax(prompt: str, prefix: str, seed: int, pulid_ref: str) -> dict:
    """majic + PuLID + FaceDetailer×2-feel + USDU + scale back to HxW."""
    g: dict = {
        "10": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "majicflus_v134.safetensors", "weight_dtype": "default"}},
        "11": {"class_type": "DualCLIPLoader", "inputs": {
            "clip_name1": "clip_l.safetensors", "clip_name2": "t5xxl_fp16.safetensors", "type": "flux"}},
        "12": {"class_type": "VAELoader", "inputs": {"vae_name": "flux1_ae.safetensors"}},
        "13": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["11", 0]}},
        "14": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["11", 0]}},
        "15": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["13", 0], "guidance": 3.2}},
        "17": {"class_type": "EmptySD3LatentImage", "inputs": {
            "width": W, "height": H, "batch_size": 1}},
        "18": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "19": {"class_type": "BasicScheduler", "inputs": {
            "model": ["10", 0], "scheduler": "beta", "steps": KEY_STEPS, "denoise": 1.0}},
        "20": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "50": {"class_type": "PulidFluxModelLoader", "inputs": {
            "pulid_file": "pulid_flux_v0.9.1.safetensors"}},
        "51": {"class_type": "PulidFluxInsightFaceLoader", "inputs": {"provider": "CPU"}},
        "52": {"class_type": "PulidFluxEvaClipLoader", "inputs": {}},
        "53": {"class_type": "LoadImage", "inputs": {"image": pulid_ref}},
        "54": {"class_type": "ApplyPulidFlux", "inputs": {
            "model": ["10", 0], "pulid_flux": ["50", 0], "eva_clip": ["52", 0],
            "face_analysis": ["51", 0], "image": ["53", 0],
            "weight": 0.88, "start_at": 0.0, "end_at": 1.0}},
    }
    g["19"]["inputs"]["model"] = ["54", 0]
    g["16"] = {"class_type": "BasicGuider", "inputs": {"model": ["54", 0], "conditioning": ["15", 0]}}
    g["21"] = {"class_type": "SamplerCustomAdvanced", "inputs": {
        "noise": ["20", 0], "guider": ["16", 0], "sampler": ["18", 0],
        "sigmas": ["19", 0], "latent_image": ["17", 0]}}
    g["22"] = {"class_type": "VAEDecode", "inputs": {"samples": ["21", 0], "vae": ["12", 0]}}

    # FaceDetailer pass 1 — texture recover
    g["30"] = {"class_type": "UltralyticsDetectorProvider",
               "inputs": {"model_name": "bbox/face_yolov8m.pt"}}
    g["31"] = {"class_type": "FaceDetailer", "inputs": {
        "image": ["22", 0], "model": ["54", 0], "clip": ["11", 0], "vae": ["12", 0],
        "guide_size": 1280, "guide_size_for": True, "max_size": 1536,
        "seed": seed + 1, "steps": 24, "cfg": 1.0, "sampler_name": "euler", "scheduler": "beta",
        "positive": ["15", 0], "negative": ["14", 0],
        "denoise": 0.38, "feather": 6, "noise_mask": True, "force_inpaint": True,
        "bbox_threshold": 0.35, "bbox_dilation": 12, "bbox_crop_factor": 3.0,
        "sam_detection_hint": "center-1", "sam_dilation": 0, "sam_threshold": 0.93,
        "sam_bbox_expansion": 0, "sam_mask_hint_threshold": 0.7,
        "sam_mask_hint_use_negative": "False", "drop_size": 10,
        "bbox_detector": ["30", 0],
        "wildcard": FACE_WILDCARD,
        "cycle": 2}}

    # USDU for micro-detail then scale back for H3
    g["40"] = {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "RealESRGAN_x4.pth"}}
    g["41"] = {"class_type": "UltimateSDUpscale", "inputs": {
        "image": ["31", 0], "model": ["54", 0], "positive": ["15", 0], "negative": ["14", 0],
        "vae": ["12", 0], "upscale_by": 1.5, "seed": seed + 2, "steps": 16, "cfg": 1.0,
        "sampler_name": "euler", "scheduler": "beta", "denoise": 0.22,
        "upscale_model": ["40", 0], "mode_type": "Linear",
        "tile_width": 1024, "tile_height": 1024, "mask_blur": 8, "tile_padding": 32,
        "seam_fix_mode": "Half Tile", "seam_fix_denoise": 1.0, "seam_fix_width": 64,
        "seam_fix_mask_blur": 8, "seam_fix_padding": 16,
        "force_uniform_tiles": True, "tiled_decode": True, "batch_size": 1}}
    g["42"] = {"class_type": "ImageScale", "inputs": {
        "image": ["41", 0], "upscale_method": "lanczos",
        "width": W, "height": H, "crop": "disabled"}}
    g["99"] = {"class_type": "SaveImage", "inputs": {
        "images": ["42", 0], "filename_prefix": f"after_school_road_vmax/{prefix}"}}
    return g


def h3_graph_first_only(first: str, prompt: str, seed: int, length: int) -> dict:
    return {
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
            "video": ["14", 0],
            "filename_prefix": f"video/after_school_road_vmax/{Path(first).stem}",
            "format": "auto", "codec": "auto"}},
    }


def build_prompt(shot: dict) -> str:
    return (
        "For the target video, at 0.00 seconds into the target video, "
        "<Picture 1> (from [Shot 1]) is fully referenced. Keep her exact face, hair, uniform, "
        "and photoreal skin texture from the image.\n\n"
        f"integrated_multimodal_description: {CORE_H3}\n\n"
        f"{shot['action']}\n\n"
        f"{shot['audio']}\n"
        "CRITICAL: only one girl; no twin/clone; micro-motion only; do not beautify or smooth skin."
    )


def stage_keys(force: bool = False) -> None:
    if not (INPUT / PULID).exists():
        src = Path("/root/ComfyUI/output/after_school_road/bible/asr_bible_front.png")
        if not src.exists():
            raise SystemExit("missing PuLID ref")
        shutil.copy2(src, INPUT / PULID)
    for i, shot in enumerate(SHOTS):
        stem = f"asr_vmax_key_{shot['id']}"
        out = OUT / "keys" / f"{stem}.png"
        if out.exists() and out.stat().st_size > 10_000 and not force:
            log(f"skip key {stem}")
            shutil.copy2(out, INPUT / f"{stem}.png")
            continue
        host = STILLS_A if i % 2 == 0 else STILLS_B
        g = flux_graph_vmax(shot["still"], stem, shot["seed"], PULID)
        resp = post(host, "/prompt", {"prompt": g, "client_id": str(uuid.uuid4())})
        if "prompt_id" not in resp:
            raise RuntimeError(resp)
        pid = resp["prompt_id"]
        log(f"vmax key {stem} -> {host} {pid}")
        entry = wait_prompt(host, pid, timeout=3600)
        dst = save_images(entry, OUT / "keys", stem)
        shutil.copy2(dst, INPUT / f"{stem}.png")
        log(f"saved {dst}")


def stage_video(force: bool = False) -> None:
    ensure_h3_workers()
    length = frames_for_duration(DURATION)
    log(f"vmax H3 length={length} {W}x{H} turbo={TURBO_STEPS} str={TURBO_STRENGTH} first-only")
    hosts = [H3_A, H3_B]
    jobs: dict = {}

    def one(shot: dict, host: str) -> Path:
        out_clip = OUT / "clips" / f"{shot['id']}.mp4"
        if out_clip.exists() and out_clip.stat().st_size > 100_000 and not force:
            log(f"skip clip {out_clip}")
            return out_clip
        first = f"asr_vmax_key_{shot['id']}.png"
        if not (INPUT / first).exists():
            raise FileNotFoundError(first)
        g = h3_graph_first_only(first, build_prompt(shot), shot["seed"], length)
        resp = post(host, "/prompt", {"prompt": g, "client_id": str(uuid.uuid4())})
        if "prompt_id" not in resp:
            raise RuntimeError(resp)
        pid = resp["prompt_id"]
        log(f"vmax H3 {shot['id']} -> {host} {pid}")
        jobs[shot["id"]] = {"port": int(host.rsplit(":", 1)[1]), "prompt_id": pid}
        JOBS.write_text(json.dumps(jobs, indent=2), encoding="utf-8")
        entry = wait_prompt(host, pid, timeout=5400)
        dst = save_video(entry, OUT / "clips", shot["id"])
        log(f"clip {dst}")
        return dst

    i = 0
    while i < len(SHOTS):
        batch = SHOTS[i:i + 2]
        with ThreadPoolExecutor(max_workers=len(batch)) as ex:
            futs = [ex.submit(one, s, hosts[j % 2]) for j, s in enumerate(batch)]
            for fut in futs:
                fut.result()
        i += 2


def grade_filter() -> str:
    # mild film contrast + unsharp + temporal-ish grain (static noise)
    return (
        "eq=contrast=1.05:brightness=0.01:saturation=0.94:gamma=0.98,"
        "unsharp=5:5:0.45:5:5:0.0,"
        "noise=alls=1.5:allf=t"
    )


def stage_merge() -> Path:
    order = [s["id"] for s in SHOTS]
    clips = []
    for sid in order:
        p = OUT / "clips" / f"{sid}.mp4"
        if not p.exists():
            raise FileNotFoundError(p)
        clips.append(p)
    work = OUT / "merge_work"
    work.mkdir(parents=True, exist_ok=True)
    norms = []
    vf = f"fps=24,format=yuv420p,{grade_filter()}"
    for p in clips:
        dst = work / f"norm_{p.name}"
        subprocess.check_call([
            str(FFMPEG), "-y", "-i", str(p),
            "-vf", vf,
            "-af", "aresample=48000:async=1,loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:v", "libx264", "-preset", "slow", "-crf", "15",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-t", f"{DURATION:.3f}", "-movflags", "+faststart", str(dst),
        ])
        norms.append(dst)
    fade = 0.10
    inputs: list[str] = []
    for f in norms:
        inputs += ["-i", str(f)]
    durs = []
    for f in norms:
        out = subprocess.check_output([
            str(FFPROBE), "-v", "error", "-show_entries", "format=duration",
            "-of", "json", str(f),
        ])
        durs.append(float(json.loads(out)["format"]["duration"]))
    filters = []
    cur_v, cur_a = "[0:v]", "[0:a]"
    offset = durs[0] - fade
    for i in range(1, len(norms)):
        ov, oa = f"[vx{i}]", f"[ax{i}]"
        filters.append(f"{cur_v}[{i}:v]xfade=transition=fade:duration={fade}:offset={offset:.6f}{ov}")
        filters.append(f"{cur_a}[{i}:a]acrossfade=d={fade}:c1=tri:c2=tri{oa}")
        cur_v, cur_a = ov, oa
        if i < len(norms) - 1:
            offset += durs[i] - fade
    filters.append(f"{cur_v}format=yuv420p[vout]")
    filters.append(f"{cur_a}aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[aout]")
    final = OUT / "after_school_road_vmax.mp4"
    subprocess.check_call([
        str(FFMPEG), "-y", *inputs,
        "-filter_complex", ";".join(filters),
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "slow", "-crf", "14",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart", str(final),
    ])
    log(f"FINAL {final} ({final.stat().st_size/1e6:.1f} MB)")
    return final


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["keys", "video", "merge", "all"], default="all")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "keys").mkdir(exist_ok=True)
    (OUT / "clips").mkdir(exist_ok=True)
    if args.stage in ("all", "keys"):
        stage_keys(force=args.force)
    if args.stage in ("all", "video"):
        stage_video(force=args.force)
    if args.stage in ("all", "merge"):
        stage_merge()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
