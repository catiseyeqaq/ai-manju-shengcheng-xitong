#!/usr/bin/env python3
"""Download Qwen-Image-Edit 2511 + Qwen-Image 2512 for interior visualization.

Runtime weights land under models; ComfyUI gets symlinks.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from modelscope import snapshot_download

RUNTIME_ROOT = Path("models")
COMFY_MODELS = Path("ComfyUI/models")

# (modelscope repo, allow_file_pattern, runtime subdir, comfy subfolder, link name)
FILES = [
    # Edit — 毛胚/平面图 → 效果图（主模型）
    (
        "Comfy-Org/Qwen-Image-Edit_ComfyUI",
        "split_files/diffusion_models/qwen_image_edit_2511_fp8mixed.safetensors",
        "Qwen-Image-Edit-ComfyUI",
        "diffusion_models",
        "qwen_image_edit_2511_fp8mixed.safetensors",
    ),
    (
        "Comfy-Org/Qwen-Image-Edit_ComfyUI",
        "split_files/diffusion_models/qwen_image_edit_2511_bf16.safetensors",
        "Qwen-Image-Edit-ComfyUI",
        "diffusion_models",
        "qwen_image_edit_2511_bf16.safetensors",
    ),
    # Shared TE + VAE (same as Qwen-Image T2I)
    (
        "Comfy-Org/Qwen-Image_ComfyUI",
        "split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors",
        "Qwen-Image-ComfyUI",
        "text_encoders",
        "qwen_2.5_vl_7b_fp8_scaled.safetensors",
    ),
    (
        "Comfy-Org/Qwen-Image_ComfyUI",
        "split_files/vae/qwen_image_vae.safetensors",
        "Qwen-Image-ComfyUI",
        "vae",
        "qwen_image_vae.safetensors",
    ),
    # T2I 2512 — 无现场图、纯平面/文字出效果图
    (
        "Comfy-Org/Qwen-Image_ComfyUI",
        "split_files/diffusion_models/qwen_image_2512_fp8_e4m3fn.safetensors",
        "Qwen-Image-ComfyUI",
        "diffusion_models",
        "qwen_image_2512_fp8_e4m3fn.safetensors",
    ),
]

GROUPS = {
    "edit": FILES[:1] + FILES[2:4],          # fp8mixed edit + TE + VAE (default)
    "edit-bf16": FILES[1:4],                  # full bf16 edit if VRAM allows
    "t2i": FILES[2:5],                        # TE + VAE + 2512 T2I
    "all": [FILES[0], FILES[2], FILES[3], FILES[4]],
}


def fetch(repo: str, pattern: str, dest: str) -> Path:
    target = RUNTIME_ROOT / dest
    target.mkdir(parents=True, exist_ok=True)
    print(f"[{time.strftime('%H:%M:%S')}] {repo} :: {pattern}", flush=True)
    snapshot_download(repo, allow_file_pattern=pattern, local_dir=str(target))
    return target / pattern


def link(src: Path, folder: str, name: str) -> None:
    dst_dir = COMFY_MODELS / folder
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / name
    if dst.is_symlink() or dst.exists():
        if dst.is_symlink() and dst.exists() and dst.resolve() == src.resolve():
            print(f"OK   {dst}")
            return
        dst.unlink()
    if not src.exists():
        print(f"SKIP missing {src}")
        return
    dst.symlink_to(src)
    print(f"LINK {dst} -> {src}  ({src.stat().st_size / 1e9:.2f} GB)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("group", nargs="?", default="all", choices=list(GROUPS))
    args = ap.parse_args()
    items = GROUPS[args.group]
    for repo, pattern, dest, folder, name in items:
        src = RUNTIME_ROOT / dest / pattern
        if src.exists() and src.stat().st_size > 1_000_000:
            print(f"ALREADY {src}")
        else:
            try:
                fetch(repo, pattern, dest)
            except Exception as exc:  # noqa: BLE001
                print(f"FAIL {repo}/{pattern}: {exc}", flush=True)
                continue
        link(RUNTIME_ROOT / dest / pattern, folder, name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
