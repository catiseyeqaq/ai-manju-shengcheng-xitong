#!/usr/bin/env python3
"""《放学路上》prompt-fix — 按 MiniMax H3 官方 I2VA 公式重写提示词，复用 vmax 关键帧。

官方结构（base-en.txt）:
  1) 首行指令: For the target video, at 0.00 seconds..., <Picture 1> ... fully referenced.
  2) integrated_multimodal_description: [Shot 1] Live-action, cinematic, ...
  3) overall_soundscape / non_diegetic_music

相对 vmax 的坏习惯已去掉:
  - 不再把 twin/pores/NOT plastic 堆进正提示
  - 不再写 micro-motion only / almost locked
  - 一镜到底，具体运镜：motion type + amplitude + speed
  - 对白原句 + <d>[Chinese]...</d>
"""

from __future__ import annotations

import argparse
import json
import shutil
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
    INPUT,
    TURBO_LORA,
    ensure_h3_workers,
    frames_for_duration,
    log,
    post,
    save_video,
    wait_prompt,
)
from run_after_school_road_vmax import (  # noqa: E402
    TURBO_STEPS,
    TURBO_STRENGTH,
    W,
    H,
    grade_filter,
    h3_graph_first_only,
)

OUT = Path("/root/ComfyUI/output/after_school_road_promptfix")
KEY_SRC = Path("/root/ComfyUI/output/after_school_road_vmax/keys")
JOBS = Path("/workdata/ComfyUI/logs/after_school_road_promptfix_jobs.json")
DURATION = 6.0  # slightly longer for natural performance
SEED0 = 2026081221


def i2va(body: str, soundscape: str, music: str) -> str:
    return (
        "For the target video, at 0.00 seconds into the target video, "
        "<Picture 1> (from [Shot 1]) is fully referenced.\n\n"
        f"integrated_multimodal_description: {body}\n\n"
        f"overall_soundscape: {soundscape}\n\n"
        f"non_diegetic_music: {music}"
    )


# Official-style: style first, anchor first frame, then visible action + concrete camera.
SHOTS = [
    {
        "id": "01_class",
        "seed": SEED0 + 1,
        "prompt": i2va(
            "[Shot 1] Live-action, cinematic, natural afternoon window light. "
            "The opening matches <Picture 1>: a Chinese mainland high-school classroom, "
            "one girl in white blouse and navy cardigan sitting by the window, medium shot from behind the desks. "
            "She continues writing in her notebook, pauses, then slightly turns her head toward the light; "
            "her hair shifts softly. One continuous take. "
            "The camera holds a Static Shot, then pushes in with small amplitude at slow speed toward her face.",
            "quiet classroom ambience, soft pencil on paper, distant muffled corridor sound",
            "very soft warm piano underscore, low volume",
        ),
    },
    {
        "id": "02_smile",
        "seed": SEED0 + 2,
        "prompt": i2va(
            "[Shot 1] Live-action, cinematic, soft window backlight. "
            "The opening matches <Picture 1>: the same schoolgirl looking back over her shoulder toward camera, "
            "close-up, empty classroom behind her. "
            "Her eyes find the lens; a small natural smile forms; she blinks once, then the smile settles. "
            "One continuous take. The camera pushes in with small amplitude at slow speed toward her eyes.",
            "soft classroom hush, faint cloth rustle",
            "barely audible warm pad",
        ),
    },
    {
        "id": "04_corridor",
        "seed": SEED0 + 4,
        "prompt": i2va(
            "[Shot 1] Live-action, cinematic, Chinese school corridor after class. "
            "The opening matches <Picture 1>: the same schoolgirl walking ahead in the empty corridor, "
            "looking back with a light smile, medium close-up. "
            "She keeps walking while talking casually toward camera, glances back again, hair moving with her steps. "
            "One continuous take. The camera follows with a Tracking Shot at slow speed, small amplitude.",
            "footsteps on corridor floor, soft reverb, distant door close",
            "soft light underscore, low volume",
        ),
    },
    {
        "id": "05_play",
        "seed": SEED0 + 5,
        "prompt": i2va(
            "[Shot 1] Live-action, cinematic, late-afternoon outdoor campus light. "
            "The opening matches <Picture 1>: the same schoolgirl outside an empty plaza by the teaching building, "
            "medium close-up, laughing. "
            "She takes a small half-step back, laughs more openly, then looks toward camera with playful eyes; "
            "a light breeze moves her hair. One continuous take. "
            "The camera holds, then pushes in with small amplitude at slow speed.",
            "light wind, soft outdoor campus ambience, distant birds",
            "soft playful piano, low volume",
        ),
    },
    {
        "id": "07_walk",
        "seed": SEED0 + 7,
        "prompt": i2va(
            "[Shot 1] Live-action, cinematic, golden-hour residential street in a Chinese city. "
            "The opening matches <Picture 1>: the same schoolgirl walking slightly ahead beside the camera, "
            "medium close-up, warm rim light on her hair. "
            "She walks naturally, then glances toward camera once and looks forward again; "
            "shop signs with Simplified Chinese pass softly in the background. One continuous take. "
            "The camera moves forward with a Tracking Shot at slow speed.",
            "footsteps on pavement, light breeze, distant city bed low",
            "warm soft underscore, low volume",
        ),
    },
    {
        "id": "09_confess",
        "seed": SEED0 + 9,
        "prompt": i2va(
            "[Shot 1] Live-action, cinematic, dusk side light. "
            "The opening matches <Picture 1>: extreme close-up of the same schoolgirl facing camera on a quiet street, "
            "nervous sincere expression. "
            "She looks down, takes a soft breath, then looks up into the lens; a faint blush rises. "
            "She says: <d>[Chinese] 其实……我喜欢你很久了。</d> "
            "After the line her eyes stay on camera, lips press together. One continuous take. "
            "The camera pushes in with small amplitude at slow speed toward her face.",
            "near silence, far city bed, soft clothing rustle",
            "soft emotional underscore entering after her line, low volume",
        ),
    },
]


def stage_prep_keys() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "clips").mkdir(exist_ok=True)
    for shot in SHOTS:
        src = KEY_SRC / f"asr_vmax_key_{shot['id']}.png"
        if not src.exists():
            raise FileNotFoundError(src)
        name = f"asr_pf_key_{shot['id']}.png"
        shutil.copy2(src, INPUT / name)
        log(f"input ready {name}")


def stage_video(force: bool = False) -> None:
    ensure_h3_workers()
    length = frames_for_duration(DURATION)
    log(f"promptfix H3 length={length} {W}x{H} official I2VA prompts")
    hosts = [H3_A, H3_B]
    jobs: dict = {}

    def one(shot: dict, host: str) -> Path:
        out_clip = OUT / "clips" / f"{shot['id']}.mp4"
        if out_clip.exists() and out_clip.stat().st_size > 100_000 and not force:
            log(f"skip {out_clip}")
            return out_clip
        first = f"asr_pf_key_{shot['id']}.png"
        g = h3_graph_first_only(first, shot["prompt"], shot["seed"], length)
        # retarget save prefix
        g["15"]["inputs"]["filename_prefix"] = f"video/after_school_road_promptfix/{Path(first).stem}"
        resp = post(host, "/prompt", {"prompt": g, "client_id": str(uuid.uuid4())})
        if "prompt_id" not in resp:
            raise RuntimeError(resp)
        pid = resp["prompt_id"]
        log(f"promptfix H3 {shot['id']} -> {host} {pid}")
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
    order = [s["id"] for s in SHOTS]
    clips = [OUT / "clips" / f"{sid}.mp4" for sid in order]
    for p in clips:
        if not p.exists():
            raise FileNotFoundError(p)
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
    final = OUT / "after_school_road_promptfix.mp4"
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
    stage_prep_keys()
    if args.stage in ("all", "video"):
        stage_video(force=args.force)
    if args.stage in ("all", "merge"):
        stage_merge()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
