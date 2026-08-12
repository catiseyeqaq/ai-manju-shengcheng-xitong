#!/usr/bin/env python3
"""Install the image-quality node packs and their models.

github.com is unreachable from this box, so node packs come from the official
Comfy registry CDN (cdn.comfy.org) and models come from ModelScope.

Installed:
  ComfyUI-Impact-Pack      FaceDetailer - fixes small/distant faces
  ComfyUI-Impact-Subpack   UltralyticsDetectorProvider - the YOLO face detector
  ComfyUI_UltimateSDUpscale tiled img2img upscale (the open Topaz substitute)
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

CUSTOM_NODES = Path("/root/ComfyUI/custom_nodes")
COMFY_MODELS = Path("/root/ComfyUI/models")
RUNTIME_ROOT = Path("/root/models")
REGISTRY = "https://api.comfy.org/nodes/{pkg}/versions?limit=1"

PACKS = [
    ("comfyui-impact-pack", "ComfyUI-Impact-Pack"),
    ("comfyui-impact-subpack", "ComfyUI-Impact-Subpack"),
    ("comfyui_ultimatesdupscale", "ComfyUI_UltimateSDUpscale"),
]

# sam2 is pulled from git and unreachable here; Impact Pack runs without it.
PIP_DEPS = [
    "segment-anything",
    "scikit-image",
    "piexif",
    "opencv-python-headless",
    "dill",
    "matplotlib",
    "ultralytics",
]

# (modelscope repo, file pattern, destination dir)
MODEL_FILES = [
    ("AI-ModelScope/Real-ESRGAN", "RealESRGAN_x4.pth", COMFY_MODELS / "upscale_models"),
]


def curl(url: str, timeout: int = 900) -> bytes:
    """Fetch over curl.

    Python's ssl handshake to api.comfy.org/cdn.comfy.org is reset in this
    network, while curl negotiates fine, so all fetching goes through curl.
    """
    proc = subprocess.run(
        ["curl", "-sL", "--retry", "3", "--retry-delay", "3", "--max-time", str(timeout), url],
        capture_output=True,
        check=True,
    )
    if not proc.stdout:
        raise RuntimeError(f"empty response from {url}")
    return proc.stdout


def http_json(url: str):
    import json

    return json.loads(curl(url, timeout=120).decode("utf-8"))


def latest_download_url(pkg: str) -> str:
    data = http_json(REGISTRY.format(pkg=pkg))
    versions = data if isinstance(data, list) else data.get("versions", [])
    if not versions:
        raise RuntimeError(f"registry returned no versions for {pkg}")
    top = versions[0]
    print(f"  {pkg} -> v{top.get('version')}")
    return top["downloadUrl"]


def install_pack(pkg: str, folder: str) -> None:
    dest = CUSTOM_NODES / folder
    if dest.exists():
        print(f"SKIP {folder} (already present)")
        return
    url = latest_download_url(pkg)
    print(f"  downloading {url}")
    blob = curl(url)
    tmp = CUSTOM_NODES / f".{folder}.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        zf.extractall(tmp)
    # Registry zips are sometimes wrapped in a single top-level directory.
    entries = [p for p in tmp.iterdir() if p.name not in {"__MACOSX"}]
    root = entries[0] if len(entries) == 1 and entries[0].is_dir() else tmp
    shutil.move(str(root), str(dest))
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"OK   {dest}  ({len(blob) / 1e6:.1f} MB)")


def install_deps() -> None:
    # Constraints keep pip from swapping the PPU-built torch stack for public wheels.
    constraints = Path("/tmp/ppu_torch_constraints.txt")
    constraints.write_text(
        "torch==2.10.0+ppu2.1.0.oe\n"
        "torchvision==0.25.0+ppu2.1.0\n"
        "torchaudio==2.10.0+ppu2.1.0\n",
        encoding="utf-8",
    )
    # The private PPU index resets TLS for these public packages, so fall back to
    # the Aliyun mirror; none of these deps ship CUDA/PPU binaries.
    for index in (None, "https://mirrors.aliyun.com/pypi/simple/"):
        cmd = [
            sys.executable, "-m", "pip", "install", "--timeout", "300",
            "--retries", "2",
            "--trusted-host", "art-pub.eng.t-head.cn",
            "--trusted-host", "mirrors.aliyun.com",
            "--constraint", str(constraints),
            "--upgrade-strategy", "only-if-needed",
        ]
        if index:
            cmd += ["-i", index]
        cmd += PIP_DEPS
        print("  " + " ".join(cmd), flush=True)
        if subprocess.run(cmd, check=False).returncode == 0:
            return
    print("  pip install failed on both indexes", flush=True)


def download_models() -> None:
    from modelscope import snapshot_download

    for repo, pattern, dest in MODEL_FILES:
        dest.mkdir(parents=True, exist_ok=True)
        if (dest / Path(pattern).name).exists():
            print(f"SKIP {dest / Path(pattern).name}")
            continue
        print(f"  {repo} :: {pattern} -> {dest}")
        snapshot_download(model_id=repo, allow_file_pattern=pattern, local_dir=str(dest))


def main() -> int:
    print("=== node packs ===")
    CUSTOM_NODES.mkdir(parents=True, exist_ok=True)
    for pkg, folder in PACKS:
        try:
            install_pack(pkg, folder)
        except Exception as exc:  # noqa: BLE001 - keep going, report at end
            print(f"FAIL {pkg}: {exc}")

    print("\n=== python deps ===")
    install_deps()

    print("\n=== models ===")
    try:
        download_models()
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL models: {exc}")

    print("\nDone. Restart ComfyUI to load the new nodes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
