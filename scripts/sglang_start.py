#!/usr/bin/env python3
"""Foreground start for ComfyUI prompt-polish SGLang (Qwen full bf16).

Ctrl+C / exit stops the service.
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

import sglang_service as svc

_CLEANED = False


def _cleanup(*_args) -> None:
    global _CLEANED
    if _CLEANED:
        return
    _CLEANED = True
    print("\nStopping SGLang polish service...")
    svc.stop_services()


def main() -> int:
    print("Starting SGLang polish LLM (foreground)...")
    print(f"Model : {svc.MODEL_PATH}")
    print(f"Name  : {svc.SERVED_NAME}")
    print(f"URL   : http://127.0.0.1:{svc.PORT}/v1")
    print(f"GPUs  : {svc.CUDA_VISIBLE_DEVICES} (tp={svc.TP_SIZE})")
    print(f"Log   : {svc.LOG_FILE}")
    print("Exit this script (Ctrl+C) to auto-stop.\n")

    try:
        proc = svc.start_process("fg")
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    atexit.register(_cleanup)
    signal.signal(signal.SIGINT, lambda *_: (_cleanup(), sys.exit(0)))
    signal.signal(signal.SIGTERM, lambda *_: (_cleanup(), sys.exit(0)))

    print("Waiting for API ready (model load can take several minutes)...")
    if svc.wait_until_ready(timeout=900):
        print(f"Ready: http://127.0.0.1:{svc.PORT}/v1  model={svc.SERVED_NAME}")
    else:
        print("WARNING: not ready in time; check log.", file=sys.stderr)

    print(svc.status_text())
    print("\nRunning... press Ctrl+C to stop.")

    try:
        while True:
            rc = proc.poll()
            if rc is not None:
                print(f"SGLang exited with code {rc}")
                break
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        _cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
