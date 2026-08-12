#!/usr/bin/env python3
"""Symlink downloaded image-gen weights into ComfyUI's model folders.

Weights stay on local disk under /root/models; ComfyUI only gets symlinks so a
single copy is shared and /workdata stays a pure backup.
"""

from __future__ import annotations

import sys
from pathlib import Path

COMFY_MODELS = Path("/root/ComfyUI/models")
RUNTIME_ROOT = Path("/root/models")

# (source relative to RUNTIME_ROOT, ComfyUI subfolder, link name)
LINKS = [
    # FLUX.2 [dev]
    (
        "FLUX.2-dev-ComfyUI/split_files/diffusion_models/flux2_dev_fp8mixed.safetensors",
        "diffusion_models",
        "flux2_dev_fp8mixed.safetensors",
    ),
    (
        "FLUX.2-dev-ComfyUI/split_files/text_encoders/mistral_3_small_flux2_bf16.safetensors",
        "text_encoders",
        "mistral_3_small_flux2_bf16.safetensors",
    ),
    (
        "FLUX.2-dev-ComfyUI/split_files/vae/flux2-vae.safetensors",
        "vae",
        "flux2-vae.safetensors",
    ),
    # majicFlus (麦橘超然) on Flux.1-dev
    (
        "majicFlus-v134/majicflus_v134.safetensors",
        "diffusion_models",
        "majicflus_v134.safetensors",
    ),
    ("FLUX.1-dev-ComfyUI/clip_l.safetensors", "text_encoders", "clip_l.safetensors"),
    ("FLUX.1-dev-ComfyUI/t5xxl_fp16.safetensors", "text_encoders", "t5xxl_fp16.safetensors"),
    ("FLUX.1-dev-ComfyUI/ae.safetensors", "vae", "flux1_ae.safetensors"),
]


def main() -> int:
    missing = []
    for rel, folder, name in LINKS:
        src = RUNTIME_ROOT / rel
        dst_dir = COMFY_MODELS / folder
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / name

        if not src.exists():
            missing.append(str(src))
            print(f"SKIP (not downloaded yet): {src}")
            continue

        if dst.is_symlink() or dst.exists():
            if dst.is_symlink() and dst.resolve() == src.resolve():
                print(f"OK   {dst} -> {src}")
                continue
            dst.unlink()

        dst.symlink_to(src)
        size_gb = src.stat().st_size / 1e9
        print(f"LINK {dst} -> {src}  ({size_gb:.2f} GB)")

    if missing:
        print(f"\n{len(missing)} file(s) still downloading; rerun when finished.")
        return 1
    print("\nAll links in place. Restart ComfyUI to refresh model lists.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
