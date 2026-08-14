#!/usr/bin/env python3
"""万灵绘卷 — 琴书画（棋已砍），每幕近景 + 远景续写。

近景用静帧 I2VA；远景用上一镜视频尾帧当首帧，保证人物/姿势衔接。

  python run_wanling_huijuan.py --scene 2 --stage video --force
  python run_wanling_huijuan.py --scene 5 --stage still
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, "/workdata/ComfyUI/scripts")
from run_after_school_road_60s import (  # noqa: E402
    FFMPEG,
    H3_A,
    H3_B,
    STILLS_A,
    STILLS_B,
    flux_graph,
    frames_for_duration,
    get,
    h3_graph as _h3_graph,
    log,
    post,
    save_images,
    save_video,
    wait_prompt,
)

OUT = Path("/root/ComfyUI/output/wanling_huijuan")
INPUT = Path("/root/ComfyUI/input")
JOBS = Path("/workdata/ComfyUI/logs/wanling_huijuan_jobs.json")
WORKSPACE = Path("/workdata/ComfyUI")

W, H = 1920, 896
DURATION = 6.0
STILL_STEPS = 28

FACE = (
    "the same 20-year-old Chinese mainland Han woman, high traditional bun with tiny white "
    "flowers and dangling gold hair ornaments, almond eyes, epicanthic fold, oval face, "
    "natural pale-wheat skin with visible pores, ivory-and-pale-gold multilayer sheer hanfu"
)

PULID = "wanling_s01_guqin.png"

NEG_BASE = (
    "pipa, ruan, yueqin, round lute hugged to chest, instrument held vertically, "
    "looking at camera, twins, indoor study, bookshelf, blurry, plastic skin, "
    "anime, illustration, extra fingers, modern city, english signage"
)


def i2va(body: str, sound: str, music: str) -> str:
    return (
        "For the target video, at 0.00 seconds into the target video, "
        "<Picture 1> (from [Shot 1]) is fully referenced.\n\n"
        f"integrated_multimodal_description: {body}\n\n"
        f"overall_soundscape: {sound}\n\n"
        f"non_diegetic_music: {music}"
    )


SCENES = {
    1: {
        "act": "琴近",
        "stem": "wanling_s01_guqin",
        "clip": "s01_guqin",
        "first": "wanling_s01_guqin.png",
        "seed": 202608131,
        "still": (
            "photorealistic live-action cinema still, majicFlus look, ultra-wide 2.16:1 frame, "
            f"low-angle medium close-up of {FACE} seated behind a dark lacquered guqin that fills "
            "the lower foreground. She looks down at the strings, right fingertips resting on one "
            "string, left hand on the soundboard. Warm golden backlight rims her hair, shoulder and "
            "gauze; cool teal shadows; drifting sheer veils and a few out-of-focus petals; blurred "
            "Chinese palace eaves behind her. Shallow depth of field, volumetric god rays, 35mm film, "
            "single subject."
        ),
        "i2va": i2va(
            "[Shot 1] Live-action, cinematic, a low-angle medium close-up frames the young Chinese "
            "woman shown in <Picture 1>, preserving her high bun, dangling gold hair ornaments, "
            "ivory-and-pale-gold multilayer sheer hanfu, and the dark wooden guqin filling the lower "
            "foreground. Warm backlight rims her hair, shoulder, and translucent sleeves while "
            "out-of-focus silk veils drift behind her. She keeps her gaze on the strings; her right "
            "fingertips pluck one string slowly, then the next, while her left hand rests on the "
            "soundboard. A few blurred petals cross the near foreground. "
            "The camera pushes in with small amplitude at slow speed toward her face and the vibrating string.",
            "A courtyard breeze moves sheer silk with a soft rustle. Guqin strings speak in spaced, "
            "dry plucks close to the microphone. Distant water trickles under light leaf stir.",
            "A solo guzheng line at a slow tempo with long decaying notes, joined by a quiet "
            "low-string drone that stays under the plucks.",
        ),
    },
    2: {
        "act": "琴远·尾帧续写",
        "stem": "wanling_s02_qin_wide",
        "clip": "s02_pullback",
        "first": "wanling_s01_last.png",
        "from_clip": "s01_guqin",
        "skip_still": True,
        "seed": 202608136,
        "i2va": i2va(
            "[Shot 1] Live-action, cinematic, a low-angle medium close-up holds the young Chinese "
            "woman shown in <Picture 1>, preserving her high bun with white blossoms, ivory embroidered "
            "collar, downward gaze, and her fingertips on the dark guqin strings at the bottom of the "
            "frame. She plucks one string and a thin gold filament of light runs along it. Her right "
            "hand then lifts from the qin in a slow sealing gesture, the silk sleeve unfurling, while "
            "her left hand stays on the soundboard; gold motes and petals rise off the instrument. As "
            "the frame widens, the pavilion eave and sheer curtain behind her open onto a vast immortal "
            "mountain-palace garden: hanging white and red silk banners billow, a lotus pond appears at "
            "her knees, cliff pavilions and a tall waterfall fill the depth, and a sudden shaft of gold "
            "light flares through the mist. The long guqin stays lying flat on the low table in front of "
            "her as she keeps playing. "
            "The camera pulls out with large amplitude at slow speed, revealing the full courtyard as "
            "the gold light blooms.",
            "Close dry guqin plucks sit in the foreground. Sheer silk rustles. A waterfall grows louder "
            "as the frame widens. When the gold light appears, air shimmers with a brief high ring, "
            "then the waterfall continues.",
            "A solo guzheng line at a slow tempo with long decaying notes; a brighter high-string "
            "accent strikes once as the gold light appears, then the quiet low-string drone returns.",
        ),
    },
    5: {
        "act": "书近",
        "stem": "wanling_s05_shufa",
        "clip": "s05_shufa",
        "first": "wanling_s05_shufa.png",
        "pulid": PULID,
        "seed": 202608141,
        "still_host": STILLS_A,
        "still_neg": NEG_BASE + ", two people, weiqi, guqin",
        "still": (
            "photorealistic live-action cinema still, majicFlus look, ultra-wide 2.16:1 frame, "
            f"low-angle medium close-up of {FACE} on a cliff-side palace terrace, seated at a long "
            "black-lacquer writing table. Her right hand flicks a wolf-hair brush through a hanging "
            "monumental white silk; wet gold ink leaves the cloth and hangs in the air as a glowing "
            "seal-script character. Her left sleeve lifts with the motion. Ink stone on the table. "
            "Behind her colossal golden-roof palace halls, a tall waterfall, hanging lanterns, drifting "
            "petals, thick volumetric gold god rays through mist. Single subject, 35mm film."
        ),
        "i2va": i2va(
            "[Shot 1] Live-action, cinematic, a medium close-up frames the young Chinese woman "
            "shown in <Picture 1>, preserving her high bun with white flowers, ivory-gold sheer hanfu, "
            "the wolf-hair brush in her right hand, and the hanging white silk with wet ink. She draws "
            "one long slow stroke across the silk; her left sleeve shifts. Lighting stays the same "
            "warm daylight with no flash and no sudden brightness change. "
            "The camera pushes in with small amplitude at slow speed toward her eyes and the wet stroke.",
            "Brush hair whispers on silk. A drop of ink hits the stone. Distant wind moves hanging lanterns.",
            "A solo dizi at a slow tempo with long held notes, joined by a quiet low-string drone.",
        ),
    },
    6: {
        "act": "书远·尾帧续写",
        "stem": "wanling_s06_shu_wide",
        "clip": "s06_shu_wide",
        "first": "wanling_s05_last.png",
        "from_clip": "s05_shufa",
        "skip_still": True,
        "seed": 202608142,
        "i2va": i2va(
            "[Shot 1] Live-action, cinematic, the calligrapher shown in <Picture 1> keeps her face, bun, "
            "and ivory-gold hanfu. She lifts the brush from the silk; the written character leaves the "
            "scroll as a slow gold sigil that hangs in the air. Her right sleeve sweeps in a sealing "
            "arc. As the camera pulls back, the writing table sits on a cliff-side palace terrace: "
            "giant hanging silk banners, a mountain of golden-roof halls, waterfall mist, and a shaft "
            "of gold light through the written character. She remains the only person. "
            "The camera pulls out with large amplitude at slow speed as the gold sigil brightens.",
            "Brush leaves silk with a soft lift. Wind fills heavy banners. Waterfall and distant temple "
            "bells grow. A brief high ring as the character leaves the scroll.",
            "A solo dizi at a slow tempo; a brighter high-string accent strikes once as the sigil "
            "appears, then the quiet low-string drone returns.",
        ),
    },
    7: {
        "act": "画近",
        "stem": "wanling_s07_huihua",
        "clip": "s07_huihua",
        "first": "wanling_s07_huihua.png",
        "pulid": PULID,
        "seed": 202608232,
        "still_host": STILLS_A,
        "still_steps": 32,
        "pulid_weight": 0.95,
        "still_neg": (
            NEG_BASE + ", two people, weiqi, guqin, giant brush, oversized brush, night forest, "
            "lotus pond, standing in water, blue hanfu, teal dress, holding blank silk, "
            "full body, motion blur, deformed hands, extra fingers"
        ),
        "still": (
            "photorealistic live-action cinema still, majicFlus look, ultra-wide 2.16:1 frame, "
            f"low-angle medium close-up of {FACE} seated at a dark lacquer table on a cliff-side "
            "palace terrace. Ivory embroidered high-collar hanfu with pale-gold gauze sleeves, "
            "high bun with tiny white flowers and dangling gold hair ornaments. "
            "Her right hand holds a fine wolf-hair landscape brush, painting ink mountains and a "
            "waterfall onto hanging cream silk; her left hand steadies the silk. Ink stone and "
            "pigment dishes on the table. Warm golden backlight rims her hair; hanging lantern, "
            "sheer white curtain; blurred waterfall and golden-roof palaces behind her. "
            "Shallow depth of field, 35mm film, single subject."
        ),
        "i2va": i2va(
            "[Shot 1] Live-action, cinematic, a low-angle medium close-up frames the young Chinese "
            "woman shown in <Picture 1>, preserving her high bun with white flowers, ivory embroidered "
            "high-collar hanfu, the wolf-hair landscape brush in her right hand, and the hanging cream "
            "silk with ink mountains. She draws one long slow stroke down the silk; her left hand "
            "steadies the cloth. Lighting stays the same warm daylight with no flash and no sudden "
            "brightness change. "
            "The camera pushes in with small amplitude at slow speed toward her eyes and the wet stroke.",
            "Brush hair whispers on silk. A drop of ink hits the stone. Distant wind moves hanging lanterns.",
            "A solo xiao at a slow tempo with long decaying notes, joined by a quiet low-string drone.",
        ),
    },
    8: {
        "act": "画远·尾帧续写",
        "stem": "wanling_s08_hua_wide",
        "clip": "s08_hua_wide",
        "first": "wanling_s07_last.png",
        "from_clip": "s07_huihua",
        "skip_still": True,
        "seed": 202608251,
        "i2va": i2va(
            "[Shot 1] Live-action, cinematic, a low-angle medium close-up holds the young Chinese "
            "woman shown in <Picture 1>, preserving her high bun with white flowers, ivory embroidered "
            "high-collar hanfu, the wolf-hair brush in her right hand, and the cream silk painting of "
            "ink mountains held upright in her left. She finishes the stroke and opens her left fingers; "
            "the cream silk painting lifts off her hand as one long unfurling scroll, the ink mountains "
            "still painted on the cloth. The scroll flies upward, then orbits around her in a wide "
            "glowing ribbon loop around her shoulders and waist, gold light running along the scroll "
            "edges as it circles her once. She turns her head slightly to follow it, remaining the only "
            "person, still at the lacquer table. Lighting stays the same warm daylight with no flash "
            "and no sudden brightness change. "
            "The camera pulls out with small amplitude at slow speed until her upper body and the "
            "orbiting scroll fill the frame.",
            "Brush hair leaves silk with a dry lift. The painted scroll snaps as it takes air, then "
            "rushes past her ear with a paper-wind hiss as it orbits. Distant courtyard breeze under "
            "the loop.",
            "A solo xiao at a slow tempo; a brighter high-string accent strikes once as the scroll "
            "lifts, then the quiet low-string drone returns.",
        ),
    },
}


def _jobs() -> dict:
    if JOBS.exists():
        return json.loads(JOBS.read_text(encoding="utf-8"))
    return {}


def _save_jobs(data: dict) -> None:
    JOBS.parent.mkdir(parents=True, exist_ok=True)
    JOBS.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def clip_path(name: str) -> Path:
    for p in (OUT / "clips" / f"{name}.mp4", WORKSPACE / f"{name}.mp4"):
        if p.exists() and p.stat().st_size > 100_000:
            return p
    raise FileNotFoundError(name)


def extract_last_frame(mp4: Path, dest: Path) -> Path:
    import cv2
    dest.parent.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(mp4))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    frame = None
    for idx in (max(n - 1, 0), max(n - 2, 0), 0):
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if ok:
            break
    cap.release()
    if frame is None:
        raise RuntimeError(f"cannot read last frame from {mp4}")
    if not cv2.imwrite(str(dest), frame):
        raise RuntimeError(f"cannot write {dest}")
    inp = INPUT / dest.name
    if dest.resolve() != inp.resolve():
        shutil.copy2(dest, inp)
    shutil.copy2(dest, WORKSPACE / dest.name)
    log(f"last frame {mp4.name} -> {dest}")
    return dest


def still_host_ok(url: str) -> bool:
    try:
        get(url, "/system_stats")
        return True
    except Exception:
        return False


def pick_still_host(preferred: str | None = None) -> str:
    order = []
    if preferred:
        order.append(preferred)
    order.extend([STILLS_A, STILLS_B])
    seen = []
    for host in order:
        if host in seen:
            continue
        seen.append(host)
        if still_host_ok(host):
            q = get(host, "/queue")
            if not q.get("queue_running") and not q.get("queue_pending"):
                return host
    for host in seen:
        if still_host_ok(host):
            return host
    raise RuntimeError("GPU2/3 静帧 worker 未就绪")


def pick_h3_host(preferred: str | None = None) -> str:
    order = []
    if preferred:
        order.append(preferred)
    # GPU0 busy with S03 → prefer GPU1
    order.extend([H3_B, H3_A])
    seen = []
    for host in order:
        if host in seen:
            continue
        seen.append(host)
        try:
            get(host, "/system_stats")
        except Exception:
            continue
        q = get(host, "/queue")
        if not q.get("queue_running") and not q.get("queue_pending"):
            return host
    for host in seen:
        try:
            get(host, "/system_stats")
            return host
        except Exception:
            continue
    raise RuntimeError("H3 worker 未就绪")


def prepare_first_frame(cfg: dict, force: bool = False) -> str:
    first = cfg["first"]
    dest = INPUT / first
    if cfg.get("from_clip"):
        if force or not dest.exists() or dest.stat().st_size < 10_000:
            src = clip_path(cfg["from_clip"])
            extract_last_frame(src, dest)
        else:
            shutil.copy2(dest, WORKSPACE / first)
        return first
    return first


def stage_still(scene: int, force: bool = False) -> Path:
    cfg = SCENES[scene]
    if cfg.get("skip_still") or cfg.get("from_clip"):
        name = prepare_first_frame(cfg, force=force)
        log(f"s{scene:02d} {cfg.get('act','')} uses last-frame first {INPUT / name}")
        return INPUT / name
    stem = cfg["stem"]
    dest = OUT / "stills" / f"{stem}.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 10_000 and not force:
        log(f"skip still {dest}")
        shutil.copy2(dest, INPUT / f"{stem}.png")
        shutil.copy2(dest, WORKSPACE / f"{stem}.png")
        return dest
    host = pick_still_host(cfg.get("still_host"))
    g = flux_graph(
        cfg["still"], stem, W, H, int(cfg.get("still_steps", STILL_STEPS)), cfg["seed"],
        backend="majic", pulid_ref=cfg.get("pulid"), face=False, upscale=False,
    )
    if cfg.get("pulid_weight") and "54" in g:
        g["54"]["inputs"]["weight"] = float(cfg["pulid_weight"])
    if cfg.get("still_neg"):
        g["14"]["inputs"]["text"] = cfg["still_neg"]
    if cfg.get("img2img"):
        ref = cfg["img2img"]
        if not (INPUT / ref).exists():
            raise FileNotFoundError(INPUT / ref)
        g["80"] = {"class_type": "LoadImage", "inputs": {"image": ref}}
        g["81"] = {"class_type": "ImageScale", "inputs": {
            "image": ["80", 0], "upscale_method": "lanczos",
            "width": W, "height": H, "crop": "center"}}
        g["17"] = {"class_type": "VAEEncode", "inputs": {
            "pixels": ["81", 0], "vae": ["12", 0]}}
        g["19"]["inputs"]["denoise"] = float(cfg.get("denoise", 0.55))
    g["99"]["inputs"]["filename_prefix"] = f"wanling_huijuan/{stem}"
    resp = post(host, "/prompt", {"prompt": g, "client_id": str(uuid.uuid4())})
    if "prompt_id" not in resp:
        raise RuntimeError(resp)
    pid = resp["prompt_id"]
    log(f"still s{scene:02d} {cfg.get('act','')} {stem} -> {host} {pid}")
    jobs = _jobs()
    jobs[f"still_s{scene:02d}"] = pid
    _save_jobs(jobs)
    entry = wait_prompt(host, pid, timeout=2400)
    dst = save_images(entry, dest.parent, stem)
    shutil.copy2(dst, INPUT / f"{stem}.png")
    shutil.copy2(dst, WORKSPACE / f"{stem}.png")
    log(f"saved still {dst}")
    return dst


def stage_video(scene: int, force: bool = False, host: str | None = None) -> Path:
    cfg = SCENES[scene]
    first = prepare_first_frame(cfg, force=True if cfg.get("from_clip") else force)
    if not (INPUT / first).exists():
        raise FileNotFoundError(f"missing first frame {INPUT / first}; run --stage still")
    dest = OUT / "clips" / f"{cfg['clip']}.mp4"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 100_000 and not force:
        log(f"skip video {dest}")
        return dest
    h3 = host or pick_h3_host()
    length = frames_for_duration(DURATION)
    g = _h3_graph(first, None, cfg["i2va"], cfg["seed"] + 10, length)
    g["15"]["inputs"]["filename_prefix"] = f"video/wanling_huijuan/{cfg['clip']}"
    g["6"]["inputs"]["width"] = W
    g["6"]["inputs"]["height"] = H
    resp = post(h3, "/prompt", {"prompt": g, "client_id": str(uuid.uuid4())})
    if "prompt_id" not in resp:
        raise RuntimeError(resp)
    pid = resp["prompt_id"]
    log(f"H3 s{scene:02d} {cfg.get('act','')} -> {h3} {pid} length={length} {W}x{H} first={first}")
    jobs = _jobs()
    jobs[f"video_s{scene:02d}"] = pid
    jobs[f"video_s{scene:02d}_host"] = h3
    _save_jobs(jobs)
    entry = wait_prompt(h3, pid, timeout=5400)
    dst = save_video(entry, dest.parent, cfg["clip"])
    shutil.copy2(dst, WORKSPACE / f"{cfg['clip']}.mp4")
    extract_last_frame(dst, OUT / "stills" / f"{cfg['clip']}_last.png")
    log(f"clip {dst}")
    return dst


def main() -> int:
    ap = argparse.ArgumentParser(
        description="万灵绘卷 琴书画：1琴近 2琴远 5书近 6书远 7画近 8画远（棋已砍）"
    )
    ap.add_argument("--scene", type=int, choices=sorted(SCENES), default=1)
    ap.add_argument("--stage", choices=["still", "video", "all"], default="all")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--host", default="", help="optional H3 host override, e.g. http://127.0.0.1:8191")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.stage in ("all", "still"):
        stage_still(args.scene, force=args.force)
    if args.stage in ("all", "video"):
        stage_video(args.scene, force=args.force, host=args.host or None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
