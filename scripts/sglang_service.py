#!/usr/bin/env python3
"""Shared helpers for ComfyUI prompt-polish SGLang (Qwen3.6-35B-A3B full bf16).

Runtime weights must live under the local model root (local disk). The shared backup volume is fallback only.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

COMFY_ROOT = Path(os.environ.get("COMFYUI_ROOT", "ComfyUI")).resolve()
RUN_DIR = COMFY_ROOT / "run"
LOG_DIR = COMFY_ROOT / "logs"

PID_FILE = RUN_DIR / "sglang_polish.pid"
PGID_FILE = RUN_DIR / "sglang_polish.pgid"
MODE_FILE = RUN_DIR / "sglang_polish.mode"
LOG_FILE = Path(os.environ.get("SGLANG_POLISH_LOG", str(LOG_DIR / "sglang_polish.log")))

# Canonical runtime path per MODEL_LOCATIONS_20260810.md
MODEL_PATH = Path(
    os.environ.get("SGLANG_POLISH_MODEL_PATH", "models/Qwen3.6-35B-A3B")
).resolve()
SERVED_NAME = os.environ.get("SGLANG_POLISH_MODEL_NAME", "qwen3.6-fast")
HOST = os.environ.get("SGLANG_POLISH_HOST", "0.0.0.0")
PORT = int(os.environ.get("SGLANG_POLISH_PORT", "8030"))
TP_SIZE = int(os.environ.get("SGLANG_POLISH_TP_SIZE", "2"))
# Leave GPU0 for ComfyUI H3 by default.
CUDA_VISIBLE_DEVICES = os.environ.get("SGLANG_POLISH_GPUS", "4,5")
DTYPE = os.environ.get("SGLANG_POLISH_DTYPE", "bfloat16")
MEM_FRACTION = os.environ.get("SGLANG_POLISH_MEM_FRACTION", "0.90")
CONTEXT_LENGTH = os.environ.get("SGLANG_POLISH_CONTEXT_LENGTH", "65536")
LAUNCHER = Path(
    os.environ.get(
        "SGLANG_POLISH_LAUNCHER",
        "GNN+LLM/services/sglang_launch_ppu.py",
    )
)
PYTHON_BIN = Path(os.environ.get("SGLANG_POLISH_PYTHON", "/usr/local/bin/python3"))


def ensure_dirs() -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


def port_open(host: str = "127.0.0.1", port: int = PORT, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def api_ready(timeout: float = 3.0) -> bool:
    url = f"http://127.0.0.1:{PORT}/v1/models"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            data = json.loads(resp.read().decode())
            return bool(data.get("data"))
    except Exception:
        return False


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def read_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
    except (ValueError, OSError):
        return None
    return pid if pid > 1 else None


def read_pgid() -> int | None:
    if not PGID_FILE.exists():
        return None
    try:
        pgid = int(PGID_FILE.read_text().strip())
    except (ValueError, OSError):
        return None
    return pgid if pgid > 1 else None


def write_runtime(pid: int, pgid: int, mode: str) -> None:
    ensure_dirs()
    PID_FILE.write_text(f"{pid}\n")
    PGID_FILE.write_text(f"{pgid}\n")
    MODE_FILE.write_text(f"{mode}\n")


def clear_runtime() -> None:
    for p in (PID_FILE, PGID_FILE, MODE_FILE):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass


def find_sglang_pids() -> list[int]:
    """Discover sglang launchers bound to our port / model."""
    try:
        out = subprocess.check_output(["pgrep", "-af", "sglang_launch_ppu"], text=True)
    except subprocess.CalledProcessError:
        return []
    pids: list[int] = []
    for line in out.splitlines():
        if "sglang_launch_ppu" not in line:
            continue
        if f"--port {PORT}" not in line and f"--port={PORT}" not in line:
            continue
        try:
            pids.append(int(line.split(None, 1)[0]))
        except ValueError:
            continue
    seen: set[int] = set()
    uniq: list[int] = []
    for p in pids:
        if p not in seen and p != os.getpid():
            seen.add(p)
            uniq.append(p)
    return uniq


def status_text() -> str:
    pid = read_pid()
    pgid = read_pgid()
    mode = MODE_FILE.read_text().strip() if MODE_FILE.exists() else "?"
    alive = bool(pid and pid_alive(pid))
    listening = port_open()
    ready = api_ready() if listening else False
    lines = [
        f"model={MODEL_PATH}",
        f"served_name={SERVED_NAME}",
        f"url=http://127.0.0.1:{PORT}/v1",
        f"gpus={CUDA_VISIBLE_DEVICES} tp={TP_SIZE} dtype={DTYPE}",
        f"pid={pid} alive={alive}",
        f"pgid={pgid}",
        f"mode={mode}",
        f"port_{PORT}_open={listening}",
        f"api_ready={ready}",
        f"log={LOG_FILE}",
        f"discovered_pids={find_sglang_pids()}",
    ]
    return "\n".join(lines)


def build_cmd() -> list[str]:
    if not PYTHON_BIN.exists():
        raise FileNotFoundError(f"Python not found: {PYTHON_BIN}")
    if not LAUNCHER.exists():
        raise FileNotFoundError(f"SGLang launcher not found: {LAUNCHER}")
    if not MODEL_PATH.is_dir():
        raise FileNotFoundError(
            f"Model missing: {MODEL_PATH}\n"
            "Runtime weights must be under models (see MODEL_LOCATIONS_20260810.md)."
        )
    return [
        str(PYTHON_BIN),
        str(LAUNCHER),
        "--model-path",
        str(MODEL_PATH),
        "--served-model-name",
        SERVED_NAME,
        "--port",
        str(PORT),
        "--host",
        HOST,
        "--tp-size",
        str(TP_SIZE),
        "--dtype",
        DTYPE,
        "--trust-remote-code",
        "--context-length",
        CONTEXT_LENGTH,
        "--mem-fraction-static",
        MEM_FRACTION,
        "--chunked-prefill-size",
        "4096",
        "--max-running-requests",
        "16",
        "--max-prefill-tokens",
        "16384",
        "--reasoning-parser",
        "qwen3",
        "--tool-call-parser",
        "qwen3_coder",
        "--disable-cuda-graph",
    ]


def start_process(mode: str) -> subprocess.Popen:
    ensure_dirs()
    if api_ready():
        raise RuntimeError(
            f"SGLang already healthy on :{PORT}. "
            "Use sglang_stop.py first if you want a clean restart."
        )
    if port_open():
        raise RuntimeError(f"Port {PORT} already in use but API not ready.")

    existing = read_pid()
    if existing and pid_alive(existing):
        raise RuntimeError(f"Tracked SGLang already running with pid={existing}")

    cmd = build_cmd()
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["CUDA_VISIBLE_DEVICES"] = CUDA_VISIBLE_DEVICES
    env.setdefault("FLASHINFER_DISABLE_VERSION_CHECK", "1")
    env.setdefault("SGLANG_ALLOW_OVERWRITE_LONGER_CONTEXT_LEN", "1")
    env.setdefault("SGLANG_MAMBA_CONV_DTYPE", DTYPE)

    log_f = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
    log_f.write(f"\n===== start mode={mode} at {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
    log_f.write("cmd: " + " ".join(cmd) + "\n")
    log_f.write(f"CUDA_VISIBLE_DEVICES={CUDA_VISIBLE_DEVICES}\n")
    log_f.flush()

    proc = subprocess.Popen(
        cmd,
        cwd=str(LAUNCHER.parent.parent),
        env=env,
        stdout=log_f,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    pgid = os.getpgid(proc.pid)
    write_runtime(proc.pid, pgid, mode)
    return proc


def wait_until_ready(timeout: float = 900.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if api_ready():
            return True
        pid = read_pid()
        if pid and not pid_alive(pid) and not port_open():
            return False
        time.sleep(2.0)
    return api_ready()


def stop_services(timeout: float = 30.0) -> int:
    """Stop tracked polish SGLang, and any launcher on our port."""
    ensure_dirs()
    targets: list[tuple[str, int]] = []

    pgid = read_pgid()
    pid = read_pid()
    if pgid and pid_alive(pgid):
        targets.append(("pgid", pgid))
    elif pid and pid_alive(pid):
        targets.append(("pid", pid))

    for orphan in find_sglang_pids():
        targets.append(("orphan", orphan))

    seen: set[tuple[str, int]] = set()
    uniq: list[tuple[str, int]] = []
    for kind, value in targets:
        key = (kind, value)
        if key in seen:
            continue
        seen.add(key)
        uniq.append((kind, value))

    if not uniq and not port_open():
        clear_runtime()
        print("SGLang polish service is not running.")
        return 0

    signaled = 0
    for kind, value in uniq:
        try:
            if kind == "pgid":
                os.killpg(value, signal.SIGTERM)
            else:
                os.kill(value, signal.SIGTERM)
            signaled += 1
            print(f"sent SIGTERM to {kind}={value}")
        except ProcessLookupError:
            pass
        except PermissionError as e:
            print(f"permission error stopping {kind}={value}: {e}", file=sys.stderr)

    deadline = time.time() + timeout
    while time.time() < deadline:
        still = []
        if pgid and pid_alive(pgid):
            still.append(pgid)
        if pid and pid_alive(pid):
            still.append(pid)
        still.extend([p for p in find_sglang_pids() if pid_alive(p)])
        if not still and not port_open():
            break
        time.sleep(0.5)

    leftovers = []
    if pgid and pid_alive(pgid):
        leftovers.append(("pgid", pgid))
    for orphan in find_sglang_pids():
        leftovers.append(("pid", orphan))
    for kind, value in leftovers:
        try:
            if kind == "pgid":
                os.killpg(value, signal.SIGKILL)
            else:
                os.kill(value, signal.SIGKILL)
            print(f"sent SIGKILL to {kind}={value}")
            signaled += 1
        except ProcessLookupError:
            pass

    # scheduler workers may linger after launcher exit
    try:
        subprocess.run(["pkill", "-f", "sglang::scheduler_TP"], check=False)
    except Exception:
        pass

    clear_runtime()
    if port_open():
        print(f"warning: port {PORT} still open after stop", file=sys.stderr)
        return signaled or 1
    print("SGLang polish service stopped.")
    return signaled
