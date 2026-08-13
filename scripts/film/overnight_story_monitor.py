#!/usr/bin/env python3
"""Studio-aware rain-day story monitor (replaces the inline AGENT_LOOP bash).

Does NOT auto-launch recover_shot01_02.py (that script waits on obsolete GPU2-7
ports 8192-8197). Polls 4-GPU studio + filesystem, writes MORNING_STATUS.txt.
"""

from __future__ import annotations

import json
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path("ComfyUI")
OUT = Path("ComfyUI/output/video")
STORY = OUT / "story_rain_day"
STATUS = ROOT / "logs" / "MORNING_STATUS.txt"
LOG = ROOT / "logs" / "overnight_monitor.log"
CAFE_JOB = ROOT / "logs" / "shot01_cafe_job.json"
BEAUTY = STORY / "story_rain_day_02to08_beauty.mp4"
V2 = OUT / "story_rain_day_v2" / "story_rain_day_v2_full.mp4"

STUDIO = [
    {"gpu": 0, "port": 8188, "role": "UI+H3#1"},
    {"gpu": 1, "port": 8191, "role": "H3#2"},
    {"gpu": 2, "port": 8192, "role": "stills"},
    {"gpu": 3, "port": 8193, "role": "stills#2"},
]

SHOTS = [
    ("shot01", "Cafe_POV_Umbrella_1080*.mp4", OUT),
    ("shot02", "02_walk_umbrella*.mp4", STORY),
    ("shot03", "03_store_arrive*.mp4", STORY),
    ("shot04", "04_shopping_aisle*.mp4", STORY),
    ("shot05", "05_checkout*.mp4", STORY),
    ("shot06", "06_walk_home*.mp4", STORY),
    ("shot07", "07_home_entrance*.mp4", STORY),
    ("shot08", "08_home_kitchen*.mp4", STORY),
]


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def http_json(url: str, timeout: float = 20):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def find_mp4(pattern: str, directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(directory.glob(pattern))


def history_status(port: int, prompt_id: str) -> str:
    if not port_open(port):
        return "port_down"
    try:
        h = http_json(f"http://127.0.0.1:{port}/history/{prompt_id}")
    except Exception as e:
        return f"err:{e}"
    if prompt_id not in h:
        try:
            q = http_json(f"http://127.0.0.1:{port}/queue")
            running = q.get("queue_running") or []
            pending = q.get("queue_pending") or []
            for item in list(running) + list(pending):
                # queue items are [number, prompt_id, ...] or nested
                flat = json.dumps(item)
                if prompt_id in flat:
                    return "queued_or_running"
        except Exception:
            pass
        return "unknown"
    return h[prompt_id].get("status", {}).get("status_str") or "unknown"


def studio_lines() -> list[str]:
    lines = ["--- 4-GPU studio ---"]
    for w in STUDIO:
        if not port_open(w["port"]):
            lines.append(f"  GPU{w['gpu']} :{w['port']} DOWN  ({w['role']})")
            continue
        try:
            q = http_json(f"http://127.0.0.1:{w['port']}/queue")
            nr = len(q.get("queue_running") or [])
            np_ = len(q.get("queue_pending") or [])
            lines.append(
                f"  GPU{w['gpu']} :{w['port']} UP  q={nr}run/{np_}pend  ({w['role']})"
            )
        except Exception as e:
            lines.append(f"  GPU{w['gpu']} :{w['port']} UP  (queue err: {e})")
    return lines


def write_status(extra: str = "") -> None:
    lines = [
        f"Updated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "=== Rain-day story status (studio monitor) ===",
        "",
    ]
    n_ok = 0
    for name, pat, d in SHOTS:
        paths = find_mp4(pat, d)
        if paths:
            n_ok += 1
            latest = paths[-1]
            lines.append(f"[OK] {name}: {latest.name} ({latest.stat().st_size/1e6:.1f} MB)")
        else:
            lines.append(f"[--] {name}: missing")

    lines += ["", f"Clips ready: {n_ok}/8", ""]
    if BEAUTY.exists():
        lines.append(f"[OK] beauty 02-08: {BEAUTY} ({BEAUTY.stat().st_size/1e6:.1f} MB)")
    else:
        lines.append("[--] beauty 02-08: missing")
    if V2.exists():
        lines.append(f"[OK] v2_full (copy of beauty): {V2} ({V2.stat().st_size/1e6:.1f} MB)")
    else:
        lines.append("[--] v2_full: missing")

    lines += ["", *studio_lines()]

    if CAFE_JOB.exists():
        try:
            job = json.loads(CAFE_JOB.read_text())
            st = history_status(job["port"], job["prompt_id"])
            lines += [
                "",
                "--- shot01 cafe job ---",
                f"  prompt {job['prompt_id']} :{job['port']} -> {st}",
                f"  submitted {job.get('submitted_at', '?')}",
            ]
        except Exception as e:
            lines += ["", f"cafe job file unreadable: {e}"]

    if extra:
        lines += ["", extra]
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cafe_done() -> bool:
    return bool(find_mp4("Cafe_POV_Umbrella_1080*.mp4", OUT))


def main() -> int:
    log("studio story monitor started (no auto-recover)")
    deadline = time.time() + 12 * 3600
    while time.time() < deadline:
        write_status()
        if cafe_done() and BEAUTY.exists():
            write_status("DONE — shot01 present + beauty 02-08 ready. Full 01-08 concat still optional.")
            log("monitor complete (shot01 + beauty)")
            return 0
        n = sum(1 for name, pat, d in SHOTS if find_mp4(pat, d))
        log(f"clips {n}/8 cafe_done={cafe_done()}")
        time.sleep(60)
    write_status("TIMEOUT after 12h")
    log("timeout")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
