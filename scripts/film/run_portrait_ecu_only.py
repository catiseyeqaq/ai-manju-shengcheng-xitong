#!/usr/bin/env python3
"""Run only portrait_03_ecu_hand (68da78...) I2VA."""
from __future__ import annotations

import shutil
import sys
import uuid
from pathlib import Path

sys.path.insert(0, "ComfyUI/scripts")
from run_after_school_road_60s import (  # noqa: E402
    H3_A,
    ensure_h3_workers,
    frames_for_duration,
    log,
    post,
    save_video,
    wait_prompt,
)
from run_portrait_majic_reel import DURATION, H, OUT, SHOTS, W, h3_graph  # noqa: E402


def main() -> int:
    ensure_h3_workers()
    shot = next(s for s in SHOTS if s["id"] == "03_ecu_hand")
    length = frames_for_duration(DURATION)
    log(f"ONLY {shot['id']} file={shot['file']} {W}x{H} length={length}")
    g = h3_graph(shot["file"], shot["prompt"], shot["seed"] + 100, length)
    g["15"]["inputs"]["filename_prefix"] = "video/portrait_majic_reel/03_ecu_hand"
    resp = post(H3_A, "/prompt", {"prompt": g, "client_id": str(uuid.uuid4())})
    if "prompt_id" not in resp:
        raise SystemExit(str(resp))
    pid = resp["prompt_id"]
    log(f"H3 {shot['id']} -> {H3_A} {pid}")
    entry = wait_prompt(H3_A, pid, timeout=5400)
    dst = save_video(entry, OUT / "clips", shot["id"])
    showcase = OUT / "portrait_current_ecu.mp4"
    shutil.copy2(dst, showcase)
    log(f"DONE {dst}")
    log(f"SHOWCASE {showcase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
