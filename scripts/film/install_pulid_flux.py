#!/usr/bin/env python3
"""Install PuLID-Flux (+ face lock deps) via Comfy registry CDN + ModelScope.

github.com is unreachable; same pattern as install_quality_nodes.py.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

CUSTOM_NODES = Path("ComfyUI/custom_nodes")
COMFY_MODELS = Path("ComfyUI/models")
RUNTIME = Path("models")
REGISTRY = "https://api.comfy.org/nodes/{pkg}/versions?limit=1"

# Prefer the Flux-specific PuLID pack
PACKS = [
    ("comfyui_pulid_flux_ll", "ComfyUI-PuLID-Flux-ll"),
]

PIP_DEPS = [
    "insightface",
    "onnxruntime",
    "facexlib",
    "ftfy",
    "timm",
    "cython",
]


def curl(url: str, timeout: int = 900) -> bytes:
    proc = subprocess.run(
        ["curl", "-sL", "--retry", "3", "--retry-delay", "3", "--max-time", str(timeout), url],
        capture_output=True,
        check=True,
    )
    if not proc.stdout:
        raise RuntimeError(f"empty response from {url}")
    return proc.stdout


def latest_download_url(pkg: str) -> tuple[str, str]:
    data = json.loads(curl(REGISTRY.format(pkg=pkg), timeout=120).decode())
    versions = data if isinstance(data, list) else data.get("versions", [])
    if not versions:
        raise RuntimeError(f"no versions for {pkg}")
    top = versions[0]
    print(f"  {pkg} -> v{top.get('version')} deps={top.get('dependencies')}")
    return top["downloadUrl"], top.get("version", "?")


def extract_archive(blob: bytes, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    # detect zip vs tar
    if blob[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            zf.extractall(dest)
    else:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:*") as tf:
            tf.extractall(dest)
    # flatten if single top folder
    kids = [p for p in dest.iterdir() if p.name != "__MACOSX"]
    if len(kids) == 1 and kids[0].is_dir():
        tmp = dest.with_name(dest.name + "_tmp")
        if tmp.exists():
            shutil.rmtree(tmp)
        kids[0].rename(tmp)
        shutil.rmtree(dest)
        tmp.rename(dest)


def pip_install(pkgs: list[str]) -> None:
    py = "/opt/miniconda3/envs/ComfyUI/bin/python"
    cmd = [py, "-m", "pip", "install", "--quiet", *pkgs]
    print("pip:", " ".join(pkgs))
    subprocess.check_call(cmd)


def modelscope_get(repo: str, filename: str, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / filename
    if out.exists() and out.stat().st_size > 1000:
        print(f"  exists {out}")
        return out
    # modelscope CLI if available, else huggingface-style URL via modelscope
    url = f"https://www.modelscope.cn/models/{repo}/resolve/master/{filename}"
    print(f"  fetch {url}")
    blob = curl(url, timeout=1800)
    out.write_bytes(blob)
    print(f"  wrote {out} ({len(blob)/1e6:.1f} MB)")
    return out


def main() -> int:
    CUSTOM_NODES.mkdir(parents=True, exist_ok=True)
    print("=== pip deps ===")
    # onnxruntime-gpu often breaks on PPU; CPU onnxruntime is enough for insightface
    pip_install(PIP_DEPS)

    print("=== node packs ===")
    for pkg, folder in PACKS:
        url, ver = latest_download_url(pkg)
        print(f"  downloading {url}")
        blob = curl(url, timeout=600)
        extract_archive(blob, CUSTOM_NODES / folder)
        print(f"  installed {folder} v{ver}")

    print("=== PuLID / insightface weights ===")
    # Common paths used by PuLID-Flux packs
    pulid_dir = COMFY_MODELS / "pulid"
    insight_dir = COMFY_MODELS / "insightface" / "models"
    pulid_dir.mkdir(parents=True, exist_ok=True)
    insight_dir.mkdir(parents=True, exist_ok=True)

    # Try several known ModelScope / direct mirrors for pulid_flux weights
    candidates = [
        ("AI-ModelScope/PuLID", "pulid_flux_v0.9.1.safetensors", pulid_dir),
        ("AI-ModelScope/PuLID", "pulid_v1.bin", pulid_dir),
    ]
    for repo, name, ddir in candidates:
        try:
            modelscope_get(repo, name, ddir)
        except Exception as e:
            print(f"  skip {repo}/{name}: {e}")

    # antelopev2 for insightface — often needed
    antelope = insight_dir / "antelopev2"
    if not antelope.exists():
        print("  attempting antelopev2 via modelscope...")
        try:
            # some mirrors ship a zip
            url = "https://www.modelscope.cn/models/AI-ModelScope/antelopev2/resolve/master/antelopev2.zip"
            blob = curl(url, timeout=1800)
            antelope.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                zf.extractall(antelope)
            print("  antelopev2 ok")
        except Exception as e:
            print(f"  antelopev2 failed: {e}")

    # list what we got
    print("=== installed tree ===")
    for p in sorted((CUSTOM_NODES / PACKS[0][1]).rglob("*.py"))[:20]:
        print(" ", p.relative_to(CUSTOM_NODES))
    for p in pulid_dir.glob("*"):
        print(" ", p, p.stat().st_size)
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
