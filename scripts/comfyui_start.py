#!/usr/bin/env python3
"""Foreground one-click start for ComfyUI (frontend + backend).

Starts the full ComfyUI stack and keeps it attached to this terminal.
When you press Ctrl+C or otherwise exit this script, services are stopped
automatically.

Also auto-registers MiniMax-H3 model weights before launch.
"""

from __future__ import annotations

import atexit
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import comfyui_service as svc

_CLEANED = False


def _cleanup(*_args) -> None:
    global _CLEANED
    if _CLEANED:
        return
    _CLEANED = True
    print("\nStopping ComfyUI services...")
    svc.stop_services()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    print("Starting ComfyUI (foreground)...")
    print(f"Root : {svc.COMFY_ROOT}")
    print(f"Models: {svc.H3_MODEL_SRC}")
    print(f"URL  : http://127.0.0.1:{svc.PORT}  (listen {svc.HOST})")
    print(f"Log  : {svc.LOG_FILE}")
    print("Exit this script (Ctrl+C) to auto-stop all services.\n")

    try:
        proc = svc.start_process("fg", extra_args=argv)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    atexit.register(_cleanup)
    signal.signal(signal.SIGINT, lambda *_: (_cleanup(), sys.exit(0)))
    signal.signal(signal.SIGTERM, lambda *_: (_cleanup(), sys.exit(0)))

    if svc.wait_until_ready(timeout=180):
        print(f"Ready: http://127.0.0.1:{svc.PORT}")
    else:
        print("WARNING: server did not become ready in time; check log.", file=sys.stderr)

    print(svc.status_text())
    print("\nRunning... press Ctrl+C to stop.")

    try:
        while True:
            rc = proc.poll()
            if rc is not None:
                print(f"ComfyUI exited with code {rc}")
                break
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        _cleanup()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
