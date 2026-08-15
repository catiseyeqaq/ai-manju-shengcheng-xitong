#!/usr/bin/env python3
"""Download realistic image-generation weights from ModelScope for ComfyUI.

Runtime weights land under the local model root (local disk); the shared backup
volume is fallback only, per MODEL_LOCATIONS_20260810.md.

Two stacks are fetched:
  - FLUX.2 [dev]  : newest base, multi-reference character locking
  - majicFlus v1.34 (麦橘超然) : Flux.1-dev finetune tuned for Asian portraits
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from modelscope import snapshot_download

RUNTIME_ROOT = Path("models")

# (model_id, file_pattern, destination subdir under RUNTIME_ROOT)
FLUX2 = [
    (
        "Comfy-Org/flux2-dev",
        "split_files/diffusion_models/flux2_dev_fp8mixed.safetensors",
        "FLUX.2-dev-ComfyUI",
    ),
    (
        "Comfy-Org/flux2-dev",
        "split_files/text_encoders/mistral_3_small_flux2_bf16.safetensors",
        "FLUX.2-dev-ComfyUI",
    ),
    (
        "Comfy-Org/flux2-dev",
        "split_files/vae/flux2-vae.safetensors",
        "FLUX.2-dev-ComfyUI",
    ),
]

MAJICFLUS = [
    ("MAILAND/majicflus_v1", "majicflus_v134.safetensors", "majicFlus-v134"),
    ("AI-ModelScope/flux_text_encoders", "clip_l.safetensors", "FLUX.1-dev-ComfyUI"),
    ("AI-ModelScope/flux_text_encoders", "t5xxl_fp16.safetensors", "FLUX.1-dev-ComfyUI"),
    ("black-forest-labs/FLUX.1-dev", "ae.safetensors", "FLUX.1-dev-ComfyUI"),
]

GROUPS = {"flux2": FLUX2, "majicflus": MAJICFLUS}


def fetch(model_id: str, pattern: str, dest: str, retries: int = 3) -> Path:
    target = RUNTIME_ROOT / dest
    target.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, retries + 1):
        try:
            print(f"[{time.strftime('%H:%M:%S')}] {model_id} :: {pattern} -> {target}", flush=True)
            snapshot_download(
                model_id=model_id,
                allow_file_pattern=pattern,
                local_dir=str(target),
            )
            return target
        except Exception as exc:  # noqa: BLE001 - network retries
            print(f"  attempt {attempt}/{retries} failed: {exc}", flush=True)
            if attempt == retries:
                raise
            time.sleep(10 * attempt)
    raise RuntimeError("unreachable")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("groups", nargs="*", choices=list(GROUPS))
    args = ap.parse_args()
    groups = args.groups or list(GROUPS)

    for name in groups:
        print(f"\n===== {name} =====", flush=True)
        for model_id, pattern, dest in GROUPS[name]:
            fetch(model_id, pattern, dest)

    print("\nDone.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
