#!/usr/bin/env python3
"""ASR_SUPERVISOR_V2: wait stills → keys → priority H3 → all video → merge."""
from __future__ import annotations
import subprocess, time, sys
from pathlib import Path

PYB = "/opt/miniconda3/envs/ComfyUI/bin/python"
SCR = "/workdata/ComfyUI/scripts/run_after_school_road_60s.py"
OUT = Path("/root/ComfyUI/output/after_school_road")
LOG = Path("/workdata/ComfyUI/logs/asr_supervisor.log")

def log(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")

def count(sub: str, pat: str) -> int:
    d = OUT / sub
    return len(list(d.glob(pat))) if d.exists() else 0

def run_stage(*args: str) -> None:
    cmd = [PYB, "-u", SCR, *args]
    log(f"exec {' '.join(args)}")
    rc = subprocess.call(cmd)
    log(f"rc={rc} for {' '.join(args)}")
    if rc != 0:
        raise SystemExit(rc)

def main() -> int:
    log("ASR_SUPERVISOR_V2 start")
    while count("bible", "asr_bible_*.png") < 6:
        log(f"wait bible {count('bible','asr_bible_*.png')}/6")
        time.sleep(30)
    while count("plates", "asr_plate_*.png") < 4:
        n = count("plates", "asr_plate_*.png")
        log(f"wait plates {n}/4")
        if subprocess.call(["pgrep", "-f", "stage plates"], stdout=subprocess.DEVNULL) != 0:
            log("relaunch plates")
            subprocess.Popen([PYB, "-u", SCR, "--stage", "plates"],
                             stdout=open("/workdata/ComfyUI/logs/asr_plates.log", "a"),
                             stderr=subprocess.STDOUT, start_new_session=True)
        time.sleep(30)
    run_stage("--stage", "keys", "--pulid", "asr_face_ref.png")
    run_stage("--stage", "priority")  # auto-starts H3 workers
    run_stage("--stage", "video")
    run_stage("--stage", "merge")
    log("ALL DONE")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
