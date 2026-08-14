#!/usr/bin/env python3
"""Download a local vision model for image → prompt (洗图反推)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from modelscope import snapshot_download

DEST_ROOT = Path("/root/models")
COMFY_LLM = Path("/root/ComfyUI/models/LLM")

# Try frontier first, then smaller fallbacks.
CANDIDATES = [
    ("Qwen/Qwen3-VL-8B-Instruct", "Qwen3-VL-8B-Instruct"),
    ("Qwen/Qwen2.5-VL-7B-Instruct", "Qwen2.5-VL-7B-Instruct"),
    ("Qwen/Qwen2.5-VL-3B-Instruct", "Qwen2.5-VL-3B-Instruct"),
    ("AI-ModelScope/Florence-2-large", "Florence-2-large"),
]


def link_into_comfy(src: Path) -> None:
    COMFY_LLM.mkdir(parents=True, exist_ok=True)
    dst = COMFY_LLM / src.name
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    dst.symlink_to(src)
    print(f"LINK {dst} -> {src}")


def main() -> int:
    for name in ("Qwen3.6-35B-A3B", "Qwen3.6-27B"):
        dest = DEST_ROOT / name
        if dest.is_dir() and any(dest.glob("*.safetensors")):
            print(f"SKIP download: already have multimodal {dest}")
            print("ImageReversePrompt will use this (or SGLang :8030) instead of Qwen3-VL-8B.")
            link_into_comfy(dest)
            return 0

    last_err = None
    for repo, folder in CANDIDATES:
        dest = DEST_ROOT / folder
        dest.mkdir(parents=True, exist_ok=True)
        if any(dest.glob("*.safetensors")) or any(dest.glob("*.bin")):
            print(f"ALREADY {dest}")
            link_into_comfy(dest)
            return 0
        print(f"[{time.strftime('%H:%M:%S')}] TRY {repo} -> {dest}", flush=True)
        try:
            snapshot_download(repo, local_dir=str(dest))
            print(f"OK {repo}")
            link_into_comfy(dest)
            return 0
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            print(f"FAIL {repo}: {exc}", flush=True)
    print(f"ALL FAILED: {last_err}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
