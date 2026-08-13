#!/usr/bin/env python3
"""《放学路上》v2 修复版 — 专治分身 / 同脸路人 / 硬桥不连贯。

关键改动相对 v1:
  1) 关键帧强制「画面里只有女主一人」，禁止第二张脸 / 人群
  2) PuLID 只锁女主；负向加 twin/clone/duplicate/two girls
  3) H3 只用 first_frame（不接下一镜 last），避免跨镜变形分身
  4) 运镜收小；教室/走廊空场，路人只允许极远无脸剪影或干脆没有
  5) 先重做最差 6 镜: 01,02,04,05,07,09

Usage:
  python run_after_school_road_v2_fix.py --stage keys
  python run_after_school_road_v2_fix.py --stage video
  python run_after_school_road_v2_fix.py --stage merge
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

# reuse helpers from v1
sys.path.insert(0, "ComfyUI/scripts")
from run_after_school_road_60s import (  # noqa: E402
    FFMPEG,
    FFPROBE,
    H3_A,
    H3_B,
    INPUT,
    STILLS_A,
    STILLS_B,
    TURBO_LORA,
    TURBO_STEPS,
    TURBO_STRENGTH,
    W,
    H,
    ensure_h3_workers,
    flux_graph,
    frames_for_duration,
    get,
    log,
    post,
    save_images,
    save_video,
    wait_prompt,
)

OUT = Path("ComfyUI/output/after_school_road_v2")
JOBS = Path("ComfyUI/logs/after_school_road_v2_jobs.json")
PULID = "asr_face_ref.png"
DURATION = 5.5
SEED0 = 2026081217

NEG = (
    "blurry, low resolution, plastic skin, anime, illustration, "
    "twin, twins, clone, duplicate person, identical faces, two girls, two women, "
    "doppelganger, split body, ghosting, extra person, crowd close-up, "
    "multiple heroines, second face, mirrored person, "
    "japanese school, sailor fuku, hangul, english billboard, european campus, "
    "oversexualized, heavy makeup, deformed face, extra fingers"
)

LIGHT = (
    "photorealistic live-action cinema, majicFlus look, natural skin pores, "
    "35mm film, soft practical lighting, cinematic color grade, Chinese mainland high school"
)

CHAR = (
    "ONE single 17-18-year-old Chinese mainland high school girl only, "
    "majicFlus photoreal beauty, long black hair with light air bangs, "
    "Chinese school uniform style white blouse, navy pleated skirt, dark knit cardigan, "
    "ordinary school backpack, shy gentle personality, same person"
)

SOLO = (
    "only one person in the entire frame, no other people, no classmates, "
    "no crowd, empty background people, solo subject"
)

CORE_H3 = (
    "photoreal live-action, majicFlus look, Chinese mainland modern high school, "
    "strict first-person POV from a teenage boy (camera is his eyes; do not show a second heroine), "
    "ONLY ONE girl visible: 17-18yo East Asian schoolgirl, majicFlus face, "
    "long black hair with light air bangs, white blouse, navy pleated skirt, dark knit cardigan, "
    "warm afternoon-to-sunset light, Simplified Chinese only if any text, "
    "youth campus romance, small amplitude at slow speed, no twins no clones"
)

# v2 shots: solo keys + no cross-shot last_frame
SHOTS = [
    {
        "id": "01_class",
        "seed": SEED0 + 1,
        "still": f"{LIGHT}, {CHAR}, {SOLO}, empty Chinese classroom, she sits alone by the window from slight rear-side angle as if seen from desk behind, blackboard with Simplified Chinese only, afternoon sun, medium shot, sharp face",
        "action": (
            "[Shot 1] Strict first-person POV from a desk behind. Empty Chinese classroom. "
            "ONLY the one girl sits ahead by the window taking notes, then slightly turns her head; "
            "hair catches light. No other students. Slow tiny push-in."
        ),
        "audio": "overall_soundscape: quiet classroom, page turning, distant muffled teacher.\nnon_diegetic_music: soft warm piano very low.",
    },
    {
        "id": "02_smile",
        "seed": SEED0 + 2,
        "still": f"{LIGHT}, {CHAR}, {SOLO}, empty classroom, she looks back over shoulder toward camera with tiny smile, no other people, warm daylight, sharp face close-medium",
        "action": (
            "[Shot 1] Strict first-person POV. Empty classroom. The single girl looks back toward camera, "
            "tiny smile, then turns forward. No classmates visible. Stable frame."
        ),
        "audio": "overall_soundscape: soft classroom ambience.\nnon_diegetic_music: barely audible.",
    },
    {
        "id": "04_corridor",
        "seed": SEED0 + 4,
        "still": f"{LIGHT}, {CHAR}, {SOLO}, empty Chinese school corridor, she walks ahead looking back smiling, Simplified Chinese bulletin boards, tracking depth, no other people",
        "action": (
            "[Shot 1] Strict first-person POV walking empty corridor. Only the one girl ahead, "
            "looks back with a light smile while walking. No other students. Gentle tracking, slow."
        ),
        "audio": "overall_soundscape: footsteps, corridor reverb.\nnon_diegetic_music: soft light underscore.",
    },
    {
        "id": "05_play",
        "seed": SEED0 + 5,
        "still": f"{LIGHT}, {CHAR}, {SOLO}, outside empty teaching building plaza, she laughs stepping half back, one hand raised playfully toward camera, warm late afternoon, no other people",
        "action": (
            "[Shot 1] Strict first-person POV outside. Only the one girl. She steps half back laughing, "
            "raises one hand toward camera playfully, looks back smiling. Keep motion SMALL. No crowd."
        ),
        "audio": "overall_soundscape: light wind, soft campus ambience.\nnon_diegetic_music: soft playful piano.",
    },
    {
        "id": "07_walk",
        "seed": SEED0 + 7,
        "still": f"{LIGHT}, {CHAR}, {SOLO}, Chinese residential street golden hour, she walks ahead slightly to the right of frame as if companion just out of POV, Simplified Chinese shop signs, no other faces, medium shot",
        "action": (
            "[Shot 1] Strict first-person POV walking home. Only the one girl visible walking slightly ahead to the side; "
            "she occasionally glances back. Shop signs Simplified Chinese only. No other pedestrians with faces. Stable forward move, slow."
        ),
        "audio": "overall_soundscape: footsteps, light breeze, distant city bed.\nnon_diegetic_music: warm soft underscore.",
    },
    {
        "id": "09_confess",
        "seed": SEED0 + 9,
        "still": f"{LIGHT}, {CHAR}, {SOLO}, dusk street close-up facing camera, blushing, nervous sincere, sunset on face, no other people",
        "action": (
            "[Shot 1] Strict first-person POV. She stops facing camera alone. Looks down, breathes, looks up blushing, "
            "says in Chinese: <d>[Chinese] 其实……我喜欢你很久了。</d> Slow push-in. No other people."
        ),
        "audio": "overall_soundscape: near silence plus far city.\nnon_diegetic_music: soft emotional underscore after the line.",
    },
]


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
            "filename_prefix": f"video/after_school_road_v2/{Path(first).stem}",
            "format": "auto", "codec": "auto"}},
    }


def build_prompt(shot: dict) -> str:
    return (
        "For the target video, at 0.00 seconds into the target video, "
        "<Picture 1> (from [Shot 1]) is fully referenced. Keep her exact face, hair, uniform.\n\n"
        f"integrated_multimodal_description: {CORE_H3}\n\n"
        f"{shot['action']}\n\n"
        f"{shot['audio']}\n"
        "CRITICAL: only one girl in frame at all times; no twin, no clone, no second face, no crowd."
    )


def stage_keys(force: bool = False) -> None:
    if not (INPUT / PULID).exists():
        src = Path("ComfyUI/output/after_school_road/bible/asr_bible_front.png")
        if src.exists():
            shutil.copy2(src, INPUT / PULID)
        else:
            raise SystemExit("missing PuLID ref asr_face_ref.png")
    for i, shot in enumerate(SHOTS):
        stem = f"asr_v2_key_{shot['id']}"
        out = OUT / "keys" / f"{stem}.png"
        if out.exists() and out.stat().st_size > 10_000 and not force:
            log(f"skip key {stem}")
            shutil.copy2(out, INPUT / f"{stem}.png")
            continue
        host = STILLS_A if i % 2 == 0 else STILLS_B
        # patch NEG into flux_graph by temporarily monkeypatching module NEG? easier: pass via local graph
        import run_after_school_road_60s as v1
        old = v1.NEG
        v1.NEG = NEG
        try:
            g = flux_graph(
                shot["still"], stem, W, H, 28, shot["seed"],
                backend="majic", pulid_ref=PULID, face=True, upscale=False,
            )
        finally:
            v1.NEG = old
        # also strengthen positive already has SOLO
        resp = post(host, "/prompt", {"prompt": g, "client_id": str(uuid.uuid4())})
        if "prompt_id" not in resp:
            raise RuntimeError(resp)
        pid = resp["prompt_id"]
        log(f"v2 key {stem} -> {host} {pid}")
        entry = wait_prompt(host, pid, timeout=2400)
        dst = save_images(entry, OUT / "keys", stem)
        log(f"saved {dst}")


def stage_video(force: bool = False) -> None:
    ensure_h3_workers()
    length = frames_for_duration(DURATION)
    log(f"v2 H3 length={length} {W}x{H} turbo={TURBO_STEPS} first-only")
    hosts = [H3_A, H3_B]
    jobs: dict = {}

    def one(shot: dict, host: str) -> Path:
        out_clip = OUT / "clips" / f"{shot['id']}.mp4"
        if out_clip.exists() and out_clip.stat().st_size > 100_000 and not force:
            log(f"skip clip {out_clip}")
            return out_clip
        first = f"asr_v2_key_{shot['id']}.png"
        if not (INPUT / first).exists():
            raise FileNotFoundError(first)
        g = h3_graph_first_only(first, build_prompt(shot), shot["seed"], length)
        resp = post(host, "/prompt", {"prompt": g, "client_id": str(uuid.uuid4())})
        if "prompt_id" not in resp:
            raise RuntimeError(resp)
        pid = resp["prompt_id"]
        log(f"v2 H3 {shot['id']} -> {host} {pid}")
        jobs[shot["id"]] = {"port": int(host.rsplit(":", 1)[1]), "prompt_id": pid}
        JOBS.write_text(json.dumps(jobs, indent=2), encoding="utf-8")
        entry = wait_prompt(host, pid, timeout=5400)
        dst = save_video(entry, OUT / "clips", shot["id"])
        log(f"clip {dst}")
        return dst

    # dual batches
    i = 0
    while i < len(SHOTS):
        batch = SHOTS[i:i + 2]
        with ThreadPoolExecutor(max_workers=len(batch)) as ex:
            futs = [ex.submit(one, s, hosts[j % 2]) for j, s in enumerate(batch)]
            for fut in futs:
                fut.result()
        i += 2


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
    for p in clips:
        dst = work / f"norm_{p.name}"
        subprocess.check_call([
            str(FFMPEG), "-y", "-i", str(p),
            "-vf", "fps=24,format=yuv420p",
            "-af", "aresample=48000:async=1,loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:v", "libx264", "-preset", "slow", "-crf", "16",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-t", f"{DURATION:.3f}", "-movflags", "+faststart", str(dst),
        ])
        norms.append(dst)
    # short fades
    fade = 0.12
    inputs = []
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
    final = OUT / "after_school_road_v2_highlight.mp4"
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
    ap.add_argument("--stage", choices=["keys", "video", "merge", "all"], default="all")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.stage in ("all", "keys"):
        stage_keys(force=args.force)
    if args.stage in ("all", "video"):
        stage_video(force=args.force)
    if args.stage in ("all", "merge"):
        stage_merge()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
