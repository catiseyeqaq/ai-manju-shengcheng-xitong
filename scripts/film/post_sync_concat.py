#!/usr/bin/env python3
"""Normalize H3 clips to 48kHz, trim A/V to frame-accurate length, concat full cut."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import av
import numpy as np

OUT = Path("ComfyUI/output/video/story_rain_day_v2")
FINAL = OUT / "story_rain_day_v2_full.mp4"
NORM = OUT / "normalized"

ORDER = [
    "01_cafe",
    "02_walk",
    "03_store",
    "04_aisle",
    "05_checkout",
    "06_homewalk",
    "07_entry",
    "08_kitchen",
]


def find_clip(shot_id: str) -> Path | None:
    cands = sorted(OUT.glob(f"{shot_id}*.mp4"))
    if cands:
        return cands[-1]
    # also search parent video/
    cands = sorted(Path("ComfyUI/output/video").rglob(f"*{shot_id}*.mp4"))
    return cands[-1] if cands else None


def normalize_clip(src: Path, dst: Path, target_fps: float = 24.0) -> Path:
    """Re-mux with audio resampled to 48kHz and trimmed to video duration."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    container = av.open(str(src))
    vstream = next(s for s in container.streams if s.type == "video")
    # count frames
    nframes = 0
    for _ in container.decode(video=0):
        nframes += 1
    container.close()
    duration = nframes / target_fps

    # ffmpeg-like via PyAV rewrite
    # Prefer system ffmpeg if present; else pure pyav
    ffmpeg = shutil_which("ffmpeg")
    if ffmpeg:
        cmd = [
            ffmpeg, "-y", "-i", str(src),
            "-vf", f"fps={target_fps}",
            "-af", f"aresample=48000,atrim=0:{duration:.6f},asetpts=PTS-STARTPTS",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            "-t", f"{duration:.6f}",
            "-movflags", "+faststart",
            str(dst),
        ]
        subprocess.check_call(cmd)
        return dst

    # fallback: copy video packets, resample audio with torchaudio if available
    import torch
    import torchaudio

    c_in = av.open(str(src))
    frames = [f.to_ndarray(format="rgb24") for f in c_in.decode(video=0)]
    audio_frames = []
    sr = 32000
    for f in c_in.decode(audio=0):
        sr = f.sample_rate
        audio_frames.append(f.to_ndarray())
    c_in.close()
    if audio_frames:
        # shape (channels, samples) after concat
        wav = np.concatenate(audio_frames, axis=1)
        wav_t = torch.from_numpy(wav.astype(np.float32))
        if sr != 48000:
            wav_t = torchaudio.functional.resample(wav_t, sr, 48000)
            sr = 48000
        target_samples = int(round(duration * sr))
        if wav_t.shape[-1] > target_samples:
            wav_t = wav_t[..., :target_samples]
        elif wav_t.shape[-1] < target_samples:
            pad = target_samples - wav_t.shape[-1]
            wav_t = torch.nn.functional.pad(wav_t, (0, pad))
    else:
        wav_t = torch.zeros(2, int(duration * 48000))
        sr = 48000

    c_out = av.open(str(dst), mode="w")
    vs = c_out.add_stream("libx264", rate=target_fps)
    vs.width = frames[0].shape[1]
    vs.height = frames[0].shape[0]
    vs.pix_fmt = "yuv420p"
    as_ = c_out.add_stream("aac", rate=sr)
    as_.layout = "stereo"
    for arr in frames:
        frame = av.VideoFrame.from_ndarray(arr, format="rgb24")
        for packet in vs.encode(frame):
            c_out.mux(packet)
    for packet in vs.encode():
        c_out.mux(packet)
    # audio in chunks
    chunk = 1024
    samples = wav_t.contiguous()
    for i in range(0, samples.shape[-1], chunk):
        sl = samples[:, i : i + chunk].numpy()
        aframe = av.AudioFrame.from_ndarray(sl, format="flt", layout="stereo")
        aframe.sample_rate = sr
        for packet in as_.encode(aframe):
            c_out.mux(packet)
    for packet in as_.encode():
        c_out.mux(packet)
    c_out.close()
    return dst


def shutil_which(cmd: str):
    from shutil import which
    return which(cmd)


def concat(files: list[Path], final: Path) -> None:
    final.parent.mkdir(parents=True, exist_ok=True)
    lst = NORM / "concat_list.txt"
    lst.write_text("".join(f"file '{f.resolve()}'\n" for f in files), encoding="utf-8")
    ffmpeg = shutil_which("ffmpeg")
    if ffmpeg:
        subprocess.check_call([
            ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
            "-c", "copy", str(final),
        ])
    else:
        # re-encode concat via filter_complex would be heavy; just copy first as fallback message
        raise RuntimeError("ffmpeg required for concat; install ffmpeg or use PyAV concat")


def main() -> int:
    global OUT, FINAL, NORM
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    args = ap.parse_args()
    OUT = args.out_dir
    FINAL = OUT / "final_story_full.mp4"
    NORM = OUT / "normalized"

    clips = []
    for sid in ORDER:
        p = find_clip(sid)
        if not p:
            print(f"MISSING {sid}")
            return 1
        print(f"found {sid}: {p}")
        clips.append(p)

    NORM.mkdir(parents=True, exist_ok=True)
    norms = []
    for p in clips:
        dst = NORM / p.name
        print(f"normalize {p.name} -> {dst}")
        norms.append(normalize_clip(p, dst))

    print(f"concat -> {FINAL}")
    concat(norms, FINAL)
    print(f"DONE {FINAL} ({FINAL.stat().st_size/1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
