#!/usr/bin/env python3
"""One-click stop for ComfyUI prompt-polish SGLang."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sglang_service as svc


def main() -> int:
    print("Stopping SGLang polish service...")
    print(svc.status_text())
    print("---")
    # Note: if GraphInsight started the same :8030 instance, this will stop that too.
    svc.stop_services()
    print("---")
    print(svc.status_text())
    return 0 if not svc.port_open() else 1


if __name__ == "__main__":
    raise SystemExit(main())
