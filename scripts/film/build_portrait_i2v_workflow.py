#!/usr/bin/env python3
"""Build UI workflow: H3 角色写真图生视频（首帧 I2VA + Turbo）

Uses the user's photoreal face stills as first_frame only (no last_frame bridge).
Official MiniMax H3 I2VA prompt structure + majicFlus cinematic portrait look.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, "/workdata/ComfyUI/scripts")
from build_master_set_workflows import (  # noqa: E402
    Graph,
    I2V_TMPL,
    USER,
    WORK,
    group_around,
    import_h3_flat,
    inject_h3_turbo,
    node,
    note,
    out,
    pack,
    w_in,
)

# Official I2VA Case 2 style (MiniMax h3-prompt-writing base-en.txt):
# instruction → integrated_multimodal_description → overall_soundscape → non_diegetic_music
PROMPT = """For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.

integrated_multimodal_description: [Shot 1] Live-action, cinematic, a medium close-up frames the young East Asian woman shown in <Picture 1>, preserving her appearance, clothing, warm rim light, and the night-city bokeh behind her. She draws a soft breath, her eyes shift with a small natural micro-expression, and loose hair strands drift across her face in a light breeze while the backlight continues to catch the edges of her hair. The camera pushes in with small amplitude at slow speed toward her eyes as her gaze settles.

overall_soundscape: A low night-city traffic bed continues under soft cloth movement. A faint breeze brushes past, with only a quiet breath near the microphone.

non_diegetic_music: Sparse soft-piano notes at a slow tempo, joined by a sustained low string pad that stays quiet and fades gently at the end."""

NOTE = (
    "# H3 · 角色写真图生视频\n\n"
    "**用途**：用你的写真静帧直接出一段麦橘气质角色视频（H3 I2VA 仅首帧）。\n\n"
    "**怎么用**\n"
    "1. 左栏换成 `portrait_*.png`（已预置 5 张）\n"
    "2. 提示词按官方 I2VA Case 2：首行指令 → Shot1 锚定 <Picture 1> → 可见动作 → 运镜(类型+幅度+速度) → soundscape / music\n"
    "3. **不要接尾帧**（避免跨构图硬桥导致分身）\n"
    "4. Turbo 8 步 · strength 1.0；只在 GPU0/GPU1 跑，并发 ≤ 2\n\n"
    "**画幅**：1920×896（≈21:9，匹配你的脸模）· ~6s\n\n"
    "**脸模文件**：`portrait_01_glow_look` … `portrait_05_backlit_turn`"
)


def build() -> dict:
    g = Graph()
    h3 = import_h3_flat(g, I2V_TMPL, id_offset=0, pos_shift=(420, 0))
    inject_h3_turbo(g, h3, lora_node_id=200)

    g.add(note(1, (0, 0), (380, 460), "⑥ 用法说明", NOTE))
    g.add(node(
        2, "LoadImage", (0, 500), (360, 340),
        title="首帧 · 角色写真（换这张）",
        inputs=[],
        outputs=[out("IMAGE", "IMAGE", 0), out("MASK", "MASK", 1)],
        widgets=["portrait_01_glow_look.png", "image"],
    ))

    h3n = g.find(h3[104])
    # first-frame only: clear last_frame link if template had one
    for inp in h3n["inputs"]:
        if inp.get("name") == "last_frame":
            lid = inp.get("link")
            if lid is not None:
                g.links = [L for L in g.links if L[0] != lid]
                inp["link"] = None
            break

    h3n["widgets_values"] = [PROMPT, 1920, 896, 158]
    h3n["title"] = "⑤ MiniMaxH3ImageToVideo · 写真 I2VA"
    g.find(h3[6])["widgets_values"] = ["minimax_h3_fl2va_pruned_bf16.safetensors", "default"]
    g.find(h3[13])["widgets_values"] = ["qwen3vl_32b_minimax_h3_bf16.safetensors", "minimax", "default"]
    g.find(h3[11])["widgets_values"] = ["minimax_h3_video_vae_fp16.safetensors"]
    g.find(h3[24])["widgets_values"] = ["minimax_h3_audio_vae_fp32.safetensors"]
    g.find(h3[91])["widgets_values"] = [24.0, 8]
    g.find(h3[111])["widgets_values"] = [6.0]
    g.find(h3[9])["widgets_values"] = ["simple", 8, 1]

    g.wire(2, 0, h3n["id"], "first_frame", "IMAGE")

    # retarget SaveVideo prefix if present
    for n in g.nodes:
        if n.get("type") == "SaveVideo":
            n["title"] = "保存写真视频"
            wv = n.get("widgets_values") or []
            if wv:
                wv[0] = "video/portrait_majic"
                n["widgets_values"] = wv

    groups = [
        group_around([g.find(1), g.find(2)], "素材 · 首帧写真", "#5a3d6e"),
        group_around([n for n in g.nodes if n["id"] not in (1, 2)], "H3 Turbo 图生视频", "#2d4a6f"),
    ]
    return pack(g, groups, scale=0.55, offset=[20, 40])


def main() -> None:
    data = build()
    name = "H3_角色写真_图生视频.json"
    for d in (WORK, USER):
        d.mkdir(parents=True, exist_ok=True)
        path = d / name
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        print("wrote", path)


if __name__ == "__main__":
    main()
