#!/usr/bin/env python3
"""Overnight story monitor: wait for GPU2-7, ensure shot01/02 recovery, concat, write morning brief."""

from __future__ import annotations

import json
import os
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
JOBS = ROOT / "logs" / "story_rain_day_jobs.json"
RECOVER_JOBS = ROOT / "logs" / "recover_shot01_02_jobs.json"
RECOVER_SCRIPT = ROOT / "scripts" / "recover_shot01_02.py"
CONCAT_SCRIPT = ROOT / "scripts" / "concat_story_rain_day.py"
FINAL = STORY / "story_rain_day_full.mp4"

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


def http_json(url: str, timeout: float = 30):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def find_mp4(pattern: str, directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(directory.glob(pattern))


def shot_files() -> dict[str, list[Path]]:
    return {name: find_mp4(pat, d) for name, pat, d in SHOTS}


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
            if q.get("queue_running") or q.get("queue_pending"):
                return "running"
        except Exception:
            pass
        return "unknown"
    return h[prompt_id].get("status", {}).get("status_str") or "unknown"


def recover_running() -> bool:
    try:
        out = subprocess.check_output(["pgrep", "-af", "recover_shot01_02.py"], text=True)
        return "recover_shot01_02.py" in out and "pgrep" not in out.splitlines()[0] or True
    except subprocess.CalledProcessError:
        return False


def ensure_recover() -> None:
    try:
        subprocess.check_output(["pgrep", "-f", "recover_shot01_02.py"])
        return
    except subprocess.CalledProcessError:
        pass
    log("recover script not running — restarting")
    subprocess.Popen(
        ["python", "-u", str(RECOVER_SCRIPT)],
        stdout=open(ROOT / "logs" / "recover_shot01_02.log", "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def write_status(extra: str = "") -> None:
    files = shot_files()
    lines = [
        f"Updated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "=== Rain-day story overnight status ===",
        "",
    ]
    n_ok = 0
    for name, _, _ in SHOTS:
        paths = files[name]
        if paths:
            n_ok += 1
            latest = paths[-1]
            lines.append(f"[OK] {name}: {latest} ({latest.stat().st_size/1e6:.1f} MB)")
        else:
            lines.append(f"[--] {name}: missing")

    lines += ["", f"Clips ready: {n_ok}/8"]
    if FINAL.exists():
        lines.append(f"FULL: {FINAL} ({FINAL.stat().st_size/1e6:.1f} MB)")
    else:
        lines.append("FULL: not concatenated yet")

    # live job hints
    if JOBS.exists():
        lines.append("")
        lines.append("--- surviving GPU2-7 ---")
        for j in json.loads(JOBS.read_text()):
            st = history_status(j["port"], j["prompt_id"])
            lines.append(f"  {j['id']} GPU{j['gpu']} :{j['port']} -> {st}")
    if RECOVER_JOBS.exists():
        lines.append("")
        lines.append("--- recovered shot01/02 ---")
        for k, v in json.loads(RECOVER_JOBS.read_text()).items():
            if isinstance(v, dict) and "prompt_id" in v:
                st = history_status(v["port"], v["prompt_id"])
                lines.append(f"  {k} :{v['port']} -> {st}")

    if extra:
        lines += ["", extra]
    STATUS.write_text("\n".join(lines) + "\n", encoding="utf-8")


def try_concat() -> bool:
    files = shot_files()
    if not all(files[n] for n, _, _ in SHOTS):
        return False
    if FINAL.exists() and FINAL.stat().st_size > 1000:
        log(f"full already exists: {FINAL}")
        return True
    log("all 8 clips present — concatenating")
    rc = subprocess.call(["python", str(CONCAT_SCRIPT)])
    log(f"concat rc={rc} exists={FINAL.exists()}")
    return FINAL.exists()


def main() -> int:
    log("overnight monitor started")
    ensure_recover()
    deadline = time.time() + 12 * 3600  # 12h safety
    last_concat_try = 0.0

    while time.time() < deadline:
        ensure_recover()
        write_status()
        files = shot_files()
        n_ok = sum(1 for n, _, _ in SHOTS if files[n])
        log(f"clips {n_ok}/8 recover_jobs={RECOVER_JOBS.exists()}")

        if n_ok == 8:
            if try_concat():
                write_status("DONE — all shots + full cut ready.")
                log("overnight complete")
                return 0

        # if recover already submitted, poll until those finish too
        if RECOVER_JOBS.exists() and n_ok < 8:
            data = json.loads(RECOVER_JOBS.read_text())
            pending = []
            for k, v in data.items():
                if isinstance(v, dict) and "prompt_id" in v:
                    st = history_status(v["port"], v["prompt_id"])
                    pending.append(f"{k}={st}")
            log("recover: " + ", ".join(pending))

        time.sleep(120)

    write_status("TIMEOUT after 12h — check logs.")
    log("timeout")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
