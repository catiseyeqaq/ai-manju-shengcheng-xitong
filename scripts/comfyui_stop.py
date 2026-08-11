#!/usr/bin/env python3
"""One-click stop for ComfyUI frontend + backend services."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import comfyui_service as svc


def main() -> int:
    print("Stopping ComfyUI services...")
    print(svc.status_text())
    print("---")
    svc.stop_services()
    print("---")
    print(svc.status_text())
    return 0 if not svc.port_open() else 1


if __name__ == "__main__":
    raise SystemExit(main())
