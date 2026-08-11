#!/usr/bin/env python3
"""Background / daemon start for ComfyUI.

Starts frontend+backend in an independent process session so they keep
running after you close the IDE/SSH session. Stop with comfyui_stop.py.

Also auto-registers MiniMax-H3 model weights before launch.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import comfyui_service as svc


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if svc.port_open() or (svc.read_pid() and svc.pid_alive(svc.read_pid() or 0)):
        print("ComfyUI appears to be already running:")
        print(svc.status_text())
        print("Use comfyui_stop.py first if you want a clean restart.")
        return 1

    print("Starting ComfyUI in background (survives IDE/SSH close)...")
    print(f"Root : {svc.COMFY_ROOT}")
    print(f"Models: {svc.H3_MODEL_SRC}")
    try:
        proc = svc.start_process("bg", extra_args=argv)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    # Detach: do not wait on child; just confirm readiness.
    time.sleep(0.5)
    if proc.poll() is not None:
        print(f"ERROR: process exited early with code {proc.returncode}", file=sys.stderr)
        print(f"See log: {svc.LOG_FILE}", file=sys.stderr)
        svc.clear_runtime()
        return 1

    if svc.wait_until_ready(timeout=180):
        print(f"Ready: http://127.0.0.1:{svc.PORT}")
    else:
        print("WARNING: not ready yet; it may still be starting. Check log.", file=sys.stderr)

    print(svc.status_text())
    print("\nDaemon started. Closing this terminal/IDE will NOT stop ComfyUI.")
    print("Stop later with:")
    print(f"  python {ROOT / 'comfyui_stop.py'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
