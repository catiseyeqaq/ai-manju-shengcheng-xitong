#!/usr/bin/env python3
"""角色写真图生视频：用用户 5 张脸模静帧跑 H3 I2VA（官方提示词）再拼接成片。

Usage:
  python run_portrait_majic_reel.py --stage all --force
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, "/workdata/ComfyUI/scripts")
from run_after_school_road_60s import (  # noqa: E402
    FFMPEG,
    FFPROBE,
    H3_A,
    H3_B,
    TURBO_LORA,
    ensure_h3_workers,
    frames_for_duration,
    log,
    post,
    save_video,
    wait_prompt,
)

OUT = Path("/root/ComfyUI/output/portrait_majic_reel")
JOBS = Path("/workdata/ComfyUI/logs/portrait_majic_reel_jobs.json")
W, H = 1920, 896
DURATION = 6.0
TURBO_STEPS = 8
TURBO_STRENGTH = 1.0
SEED0 = 2026081222


def i2va(body: str, sound: str, music: str) -> str:
    return (
        "For the target video, at 0.00 seconds into the target video, "
        "<Picture 1> (from [Shot 1]) is fully referenced.\n\n"
        f"integrated_multimodal_description: {body}\n\n"
        f"overall_soundscape: {sound}\n\n"
        f"non_diegetic_music: {music}"
    )


# Official I2VA pattern: anchor on <Picture 1> → preserve appearance → visible action → camera (type+amplitude+speed)
# Soundscape: ambient/physical only. Music: instruments + tempo + dynamics (no abstract mood words).
SHOTS = [
    {
        "id": "01_glow_look",
        "file": "portrait_01_glow_look.png",
        "seed": SEED0 + 1,
        "prompt": i2va(
            "[Shot 1] Live-action, cinematic, a medium close-up frames the young East Asian woman "
            "shown in <Picture 1>, preserving her appearance, tan trench coat, warm rim light, "
            "and the night-city bokeh behind her. She draws a soft breath as her gaze drifts slightly "
            "upward and loose strands of wavy hair catch the rim light. "
            "The camera pushes in with small amplitude at slow speed toward her face.",
            "A low night-city traffic bed continues under soft fabric movement from her coat. "
            "A quiet breath is audible near the frame.",
            "Sparse soft-piano notes at a slow tempo, joined by a sustained low string line that stays quiet.",
        ),
    },
    {
        "id": "02_night_coat",
        "file": "portrait_02_night_coat.png",
        "seed": SEED0 + 2,
        "prompt": i2va(
            "[Shot 1] Live-action, cinematic, a medium shot frames the young woman shown in <Picture 1>, "
            "preserving her appearance, dark coat over the light collared shirt, soft side light, "
            "and the out-of-focus city lights. She looks off-camera, blinks once, and a faint breeze "
            "moves her wavy hair across her shoulder. "
            "The camera holds a static shot, then pushes in with small amplitude at slow speed.",
            "Distant night traffic remains low while her coat fabric rustles lightly. "
            "A soft breeze passes through the empty street.",
            "A slow sparse piano figure with quiet sustained strings, held at low volume throughout.",
        ),
    },
    {
        "id": "03_ecu_hand",
        "file": "portrait_03_ecu_hand.png",
        "seed": SEED0 + 3,
        "prompt": i2va(
            "[Shot 1] Live-action, cinematic, an extreme close-up frames the young woman shown in "
            "<Picture 1>, preserving her face, the hand resting near her cheek, golden rim light, "
            "and the dark soft background. Loose hair strands drift across her eyes in a light breeze "
            "while her lips stay slightly parted and her gaze holds on the lens. "
            "The camera pushes in with small amplitude at slow speed toward her eyes.",
            "Near-silence with a soft breath close to the microphone. "
            "A faint far-city hush sits underneath.",
            "Very sparse piano notes at a slow tempo, with a thin low pad that fades at the end.",
        ),
    },
    {
        "id": "04_profile",
        "file": "portrait_04_profile.png",
        "seed": SEED0 + 4,
        "prompt": i2va(
            "[Shot 1] Live-action, cinematic, a medium close-up frames the young woman shown in "
            "<Picture 1> in profile, preserving her appearance, trench coat, and warm city bokeh. "
            "She remains facing left as she breathes softly and a few hair strands shift across her cheek "
            "in the night air. The camera holds a static shot with only a tiny natural sway.",
            "A low night-city bed continues with a soft breeze. "
            "Light cloth movement from her coat is intermittent.",
            "Sustained low strings at a slow tempo, with sparse piano accents kept quiet.",
        ),
    },
    {
        "id": "05_backlit_turn",
        "file": "portrait_05_backlit_turn.png",
        "seed": SEED0 + 5,
        "prompt": i2va(
            "[Shot 1] Live-action, cinematic, a medium close-up frames the young woman shown in "
            "<Picture 1> looking back over her shoulder, preserving her appearance, strong backlight "
            "halo, lens flare, and night bokeh. She turns her face a little farther toward the camera, "
            "her eyes soften, and the backlight continues to rim her hair. "
            "The camera pushes in with small amplitude at slow speed toward her eyes.",
            "Distant night traffic stays low under a soft breeze. "
            "Fabric shifts lightly as she turns her shoulder.",
            "Soft piano at a slow tempo with a quiet sustained string pad that fades out gently.",
        ),
    },
]


def h3_graph(first: str, prompt: str, seed: int, length: int) -> dict:
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
            "filename_prefix": f"video/portrait_majic_reel/{Path(first).stem}",
            "format": "auto", "codec": "auto"}},
    }


def stage_video(force: bool = False) -> None:
    ensure_h3_workers()
    length = frames_for_duration(DURATION)
    log(f"portrait reel H3 {W}x{H} length={length} n={len(SHOTS)}")
    hosts = [H3_A, H3_B]
    jobs: dict = {}

    def one(shot: dict, host: str) -> Path:
        out_clip = OUT / "clips" / f"{shot['id']}.mp4"
        if out_clip.exists() and out_clip.stat().st_size > 100_000 and not force:
            log(f"skip {out_clip}")
            return out_clip
        first = shot["file"]
        if not (Path("/root/ComfyUI/input") / first).exists():
            raise FileNotFoundError(first)
        g = h3_graph(first, shot["prompt"], shot["seed"], length)
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

    i = 0
    while i < len(SHOTS):
        batch = SHOTS[i : i + 2]
        with ThreadPoolExecutor(max_workers=len(batch)) as ex:
            futs = [ex.submit(one, s, hosts[j % 2]) for j, s in enumerate(batch)]
            for fut in futs:
                fut.result()
        i += 2


def stage_merge() -> Path:
    clips = [OUT / "clips" / f"{s['id']}.mp4" for s in SHOTS]
    for p in clips:
        if not p.exists():
            raise FileNotFoundError(p)
    work = OUT / "merge_work"
    work.mkdir(parents=True, exist_ok=True)
    norms = []
    vf = (
        "fps=24,format=yuv420p,"
        "eq=contrast=1.04:saturation=0.96:gamma=0.99,"
        "unsharp=5:5:0.35:5:5:0.0"
    )
    for p in clips:
        dst = work / f"norm_{p.name}"
        subprocess.check_call([
            str(FFMPEG), "-y", "-i", str(p), "-vf", vf,
            "-af", "aresample=48000:async=1,loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:v", "libx264", "-preset", "slow", "-crf", "15",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-t", f"{DURATION:.3f}", "-movflags", "+faststart", str(dst),
        ])
        norms.append(dst)
    fade = 0.25
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
        filters.append(
            f"{cur_v}[{i}:v]xfade=transition=fade:duration={fade}:offset={offset:.6f}{ov}"
        )
        filters.append(f"{cur_a}[{i}:a]acrossfade=d={fade}:c1=tri:c2=tri{oa}")
        cur_v, cur_a = ov, oa
        if i < len(norms) - 1:
            offset += durs[i] - fade
    filters.append(f"{cur_v}format=yuv420p[vout]")
    filters.append(
        f"{cur_a}aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[aout]"
    )
    final = OUT / "portrait_majic_reel.mp4"
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
    ap.add_argument("--stage", choices=["video", "merge", "all"], default="all")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "clips").mkdir(exist_ok=True)
    if args.stage in ("all", "video"):
        stage_video(force=args.force)
    if args.stage in ("all", "merge"):
        stage_merge()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
