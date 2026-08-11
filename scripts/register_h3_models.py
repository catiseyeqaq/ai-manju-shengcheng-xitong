#!/usr/bin/env python3
"""Register MiniMax-H3 weights into ComfyUI (wrapper around comfyui_service)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import comfyui_service as svc


def main() -> int:
    try:
        svc.register_models(verbose=True)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print("\nDone. Restart ComfyUI (or use comfyui_start*.py) to refresh UI list.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
