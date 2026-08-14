#!/usr/bin/env python3
"""万灵绘卷 · 琴书画 成片：音轨校正 + 暖金调色（贴近 s1-s10）+ 拼接。

近→远 硬切（尾帧续写）；琴|书|画 之间短叠化，远景尾部切掉再转，避免坐住再溶。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

FFMPEG = Path("/opt/miniconda3/envs/ComfyUI/bin/ffmpeg")
FFPROBE = Path("/opt/miniconda3/envs/ComfyUI/bin/ffprobe")

WORKSPACE = Path("/workdata/ComfyUI")
OUT = Path("/root/ComfyUI/output/wanling_huijuan")
WORK = OUT / "assemble"
FINAL = WORKSPACE / "wanling_qinshuhua.mp4"

CLIPS = [
    WORKSPACE / "s01_guqin.mp4",
    WORKSPACE / "s02_pullback.mp4",
    WORKSPACE / "s05_shufa.mp4",
    WORKSPACE / "s06_shu_wide.mp4",
    WORKSPACE / "s07_huihua.mp4",
    WORKSPACE / "s08_hua_wide.mp4",
]

NFRAMES = 158
FPS = 24.0
CLIP_T = NFRAMES / FPS
ART_FADE = 0.0          # 硬切，不再叠化
TAIL_CUT = 10 / FPS     # 远景末 10 帧还在动就切走
HEAD_CUT = 3 / FPS      # 下一幕近景跳过起幅静帧

# Warm gold + highlight bloom, matched to s1-s10 (majic / xianxia CGI).
# Per-clip audio: clock-correct 32k→48k only. Loudnorm once on the final.
VF = (
    f"fps={FPS},"
    "scale=1920:896:flags=lanczos,"
    "eq=contrast=1.07:brightness=0.012:saturation=1.06:gamma=0.97,"
    "colorbalance=rs=0.05:gs=0.015:bs=-0.045:rm=0.035:gm=0.01:bm=-0.03:rh=0.04:gh=0.015:bh=-0.025,"
    "split[s0][s1];"
    "[s1]eq=brightness=0.12:gamma=1.35,gblur=sigma=11[glow];"
    "[s0][glow]blend=all_mode=screen:all_opacity=0.14,"
    "unsharp=5:5:0.38:5:5:0.0,"
    "format=yuv420p"
)
AF = (
    "aresample=48000:async=1,"
    "highpass=f=70,"
    "equalizer=f=1800:t=q:w=1.0:g=0.8,"
    f"atrim=0:{CLIP_T:.6f},asetpts=PTS-STARTPTS"
)


def run(cmd: list[str]) -> None:
    print("+", " ".join(str(c) for c in cmd[:10]), "...", flush=True)
    subprocess.check_call(cmd)


def duration(path: Path) -> float:
    out = subprocess.check_output([
        str(FFPROBE), "-v", "error", "-show_entries", "format=duration",
        "-of", "json", str(path),
    ])
    return float(json.loads(out)["format"]["duration"])


def normalize(src: Path, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    run([
        str(FFMPEG), "-y", "-i", str(src),
        "-filter_complex", f"[0:v]{VF}[v];[0:a]{AF}[a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-frames:v", str(NFRAMES),
        "-t", f"{CLIP_T:.6f}",
        "-movflags", "+faststart",
        str(dst),
    ])
    return dst


def assemble(norms: list[Path], final: Path) -> None:
    """近→远硬切；琴|书|画 也硬切。远景尾 8 帧、下一幕近景头 2 帧裁掉，避免坐住。"""
    inputs: list[str] = []
    for p in norms:
        inputs += ["-i", str(p)]
    pair = CLIP_T * 2
    tail = TAIL_CUT
    head = HEAD_CUT
    qin = pair - tail
    shu = pair - head - tail
    hua = pair - head
    total = qin + shu + hua
    fade_out = 0.22
    fc = (
        f"[0:v][1:v]concat=n=2:v=1:a=0,trim=0:{qin:.6f},setpts=PTS-STARTPTS[qv];"
        f"[0:a][1:a]concat=n=2:v=0:a=1,atrim=0:{qin:.6f},asetpts=PTS-STARTPTS[qa];"
        f"[2:v][3:v]concat=n=2:v=1:a=0,trim={head:.6f}:{pair - tail:.6f},setpts=PTS-STARTPTS[sv];"
        f"[2:a][3:a]concat=n=2:v=0:a=1,atrim={head:.6f}:{pair - tail:.6f},asetpts=PTS-STARTPTS[sa];"
        f"[4:v][5:v]concat=n=2:v=1:a=0,trim={head:.6f},setpts=PTS-STARTPTS[hv];"
        f"[4:a][5:a]concat=n=2:v=0:a=1,atrim={head:.6f},asetpts=PTS-STARTPTS[ha];"
        f"[qv][sv][hv]concat=n=3:v=1:a=0[vout0];"
        f"[qa][sa][ha]concat=n=3:v=0:a=1[aout0];"
        f"[vout0]fade=t=in:st=0:d=0.08,fade=t=out:st={total - fade_out:.6f}:d={fade_out},"
        f"format=yuv420p[vout];"
        f"[aout0]afade=t=in:st=0:d=0.08,afade=t=out:st={total - fade_out:.6f}:d={fade_out},"
        f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
        f"loudnorm=I=-16:TP=-1.5:LRA=11,alimiter=limit=0.95[aout]"
    )
    final.parent.mkdir(parents=True, exist_ok=True)
    run([
        str(FFMPEG), "-y", *inputs,
        "-filter_complex", fc,
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "slow", "-crf", "16",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        str(final),
    ])


def main() -> int:
    missing = [p for p in CLIPS if not p.exists() or p.stat().st_size < 100_000]
    if missing:
        print("MISSING", *missing, file=sys.stderr)
        return 1
    WORK.mkdir(parents=True, exist_ok=True)
    reuse = "--reuse" in sys.argv
    norms = []
    for src in CLIPS:
        dst = WORK / f"norm_{src.name}"
        if reuse and dst.exists() and dst.stat().st_size > 100_000:
            print(f"reuse {dst.name}", flush=True)
            norms.append(dst)
            continue
        print(f"normalize {src.name}", flush=True)
        norms.append(normalize(src, dst))
    print(f"assemble -> {FINAL}", flush=True)
    assemble(norms, FINAL)
    also = OUT / "clips" / FINAL.name
    also.parent.mkdir(parents=True, exist_ok=True)
    also.write_bytes(FINAL.read_bytes())
    print(f"DONE {FINAL} ({FINAL.stat().st_size/1e6:.1f} MB)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
