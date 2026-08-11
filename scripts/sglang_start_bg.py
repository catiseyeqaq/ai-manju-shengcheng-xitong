#!/usr/bin/env python3
"""Background / daemon start for ComfyUI prompt-polish SGLang."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sglang_service as svc


def main() -> int:
    if svc.api_ready() or (svc.read_pid() and svc.pid_alive(svc.read_pid() or 0)):
        print("SGLang polish service appears to be already running:")
        print(svc.status_text())
        print("Use sglang_stop.py first if you want a clean restart.")
        return 1

    print("Starting SGLang polish LLM in background...")
    print(f"Model : {svc.MODEL_PATH}")
    print(f"Name  : {svc.SERVED_NAME}")
    print(f"GPUs  : {svc.CUDA_VISIBLE_DEVICES} (tp={svc.TP_SIZE})")
    try:
        proc = svc.start_process("bg")
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    time.sleep(0.5)
    if proc.poll() is not None:
        print(f"ERROR: process exited early with code {proc.returncode}", file=sys.stderr)
        print(f"See log: {svc.LOG_FILE}", file=sys.stderr)
        svc.clear_runtime()
        return 1

    print("Waiting for API ready (model load can take several minutes)...")
    if svc.wait_until_ready(timeout=900):
        print(f"Ready: http://127.0.0.1:{svc.PORT}/v1  model={svc.SERVED_NAME}")
    else:
        print("WARNING: not ready yet; check log.", file=sys.stderr)

    print(svc.status_text())
    print("\nDaemon started. Closing this terminal will NOT stop SGLang.")
    print("Stop later with:")
    print(f"  python {ROOT / 'sglang_stop.py'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
