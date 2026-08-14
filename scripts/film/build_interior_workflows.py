#!/usr/bin/env python3
"""室内效果图：Qwen-Image-Edit 2511 多图图生图（毛胚/平面/正负样本）。"""

from __future__ import annotations

import shutil
from pathlib import Path

from build_master_set_workflows import (
    USER,
    WORK,
    Graph,
    node,
    note,
    w_in,
    p_in,
    out,
    pack,
    group_around,
    write_both,
)

INPUT = Path("/root/ComfyUI/input")

EDIT_NOTE = """# 室内效果图 · 毛胚 / 平面图改图（本地 Edit 2511）

官方能力（ComfyUI 教程 + Qwen-Image-Edit-2511）：
- **最多 3 张正向参考**（`TextEncodeQwenImageEditPlus`）
- **几何推理加强**：平面图、墙轴线比 2509 稳
- **工业设计 / 材质替换**：正样本材质可贴到毛胚结构上
- 采样：**euler / simple / 40 步 / CFG 4 / AuraFlow 3.1 / CFGNorm 1**
- 跑 **GPU2 / GPU3**，不要占 H3 的 GPU0/1

## 四张图怎么接

| 槽 | 作用 | 接到哪 |
|---|---|---|
| **毛胚 / 现场** | 锁机位、墙、窗、门洞、层高 | 正向 Picture 1 + 作为 latent 底图 |
| **平面图** | 只提供布局，不要把图纸画进成片 | 正向 Picture 2，没有就 Bypass |
| **正样本** | 喜欢的风格 / 材质 / 灯光 | 正向 Picture 3，没有就 Bypass |
| **负样本** | 不要的风格（杂乱、欧式、酒店风） | **负向编码器** Picture 1，没有就 Bypass |

提示词里必须写 `Picture 1 / 2 / 3`，模型和槽位才能对上。

## 建议打法

1. 第一遍：锁结构 + 正样本风格，负样本挡住不想要的味道
2. 第二遍：把第一遍结果当毛胚，再换材质 / 软装（一次只改一类）
3. 一次只改一类：结构定了再换材质 / 软装

不要把四张图都塞进正向槽——第 4 张必须走负向。
"""

POS_PROMPT = (
    "Picture 1 is the on-site unfinished apartment shell. Keep its camera angle, wall positions, "
    "window and door openings, ceiling height, beam locations, and spatial proportions exactly. "
    "Do not invent extra windows or move walls.\n"
    "Picture 2 is the floor plan. Use it only for room layout, circulation, and furniture placement. "
    "Do not render the plan drawing, labels, or dimension lines into the final image.\n"
    "Picture 3 is the positive style sample. Take material palette, furniture language, millwork, "
    "and lighting mood from it, scaled to the real room in Picture 1.\n\n"
    "Turn Picture 1 into a photoreal finished interior of a contemporary Chinese mainland apartment: "
    "light oak flooring, warm off-white walls, built-in storage, linen curtains, mixed natural and "
    "warm interior light, physically plausible materials, architectural photography, 24mm wide lens, "
    "vertical lines straight, no people, no floor-plan overlay."
)

NEG_PROMPT = (
    "Avoid the style, materials, clutter, color temperature, and taste of this negative sample. "
    "cartoon, anime, illustration, oversaturated luxury hotel, European palace, marble everywhere, "
    "distorted walls, extra windows, warped perspective, melted furniture, floor plan overlay, "
    "dimension text, watermark, people, pets, English billboards."
)


def _placeholder() -> str:
    path = INPUT / "interior_placeholder.png"
    if path.exists():
        return path.name
    try:
        from PIL import Image, ImageDraw, ImageFont

        img = Image.new("RGB", (1024, 768), (220, 220, 220))
        d = ImageDraw.Draw(img)
        d.rectangle([40, 40, 984, 728], outline=(160, 160, 160), width=4)
        d.text((80, 340), "OPTIONAL SLOT — replace or Bypass", fill=(90, 90, 90))
        img.save(path)
    except Exception:
        # last resort: copy any existing png
        src = next(INPUT.glob("*.png"), None)
        if src is None:
            raise RuntimeError("no image in ComfyUI input to use as placeholder")
        shutil.copy2(src, path)
    return path.name


def build_edit(placeholder: str) -> dict:
    g = Graph()
    g.add(note(1, (20, -420), (560, 400), "用法 · 室内改效果图", EDIT_NOTE))

    def load(nid, pos, title, fname):
        g.add(node(
            nid, "LoadImage", pos, (320, 300),
            title=title,
            inputs=[],
            outputs=[out("IMAGE", "IMAGE", 0), out("MASK", "MASK", 1)],
            widgets=[fname, "image"],
        ))

    load(10, (20, 20), "① 毛胚 / 现场（必填）", placeholder)
    load(11, (360, 20), "② 平面图（可选）", placeholder)
    load(12, (700, 20), "③ 正样本风格（可选）", placeholder)
    load(13, (1040, 20), "④ 负样本（可选，接负向）", placeholder)

    g.add(node(
        14, "PreviewImage", (20, 340), (320, 240),
        title="毛胚预览",
        inputs=[p_in("images", "IMAGE")],
    ))
    g.connect(10, 0, 14, 0, "IMAGE")

    g.add(node(
        20, "UNETLoader", (20, 620), (380, 90),
        title="UNet · Edit 2511 fp8",
        inputs=[w_in("unet_name", "COMBO"), w_in("weight_dtype", "COMBO")],
        outputs=[out("MODEL", "MODEL", 0)],
        widgets=["qwen_image_edit_2511_fp8mixed.safetensors", "default"],
    ))
    g.add(node(
        21, "CLIPLoader", (20, 730), (380, 120),
        title="CLIP · qwen_2.5_vl_7b（勿换 3.6）",
        inputs=[w_in("clip_name", "COMBO"), w_in("type", "COMBO"), w_in("device", "COMBO")],
        outputs=[out("CLIP", "CLIP", 0)],
        widgets=["qwen_2.5_vl_7b_fp8_scaled.safetensors", "qwen_image", "default"],
    ))
    g.add(node(
        22, "VAELoader", (20, 870), (380, 70),
        title="VAE · qwen_image_vae",
        inputs=[w_in("vae_name", "COMBO")],
        outputs=[out("VAE", "VAE", 0)],
        widgets=["qwen_image_vae.safetensors"],
    ))
    g.add(node(
        23, "ModelSamplingAuraFlow", (430, 620), (280, 60),
        title="AuraFlow shift 3.1",
        inputs=[p_in("model", "MODEL"), w_in("shift", "FLOAT")],
        outputs=[out("MODEL", "MODEL", 0)],
        widgets=[3.1],
    ))
    g.wire(20, 0, 23, "model", "MODEL")
    g.add(node(
        24, "CFGNorm", (430, 710), (280, 80),
        title="CFGNorm 1.0",
        inputs=[p_in("model", "MODEL"), w_in("strength", "FLOAT")],
        outputs=[out("MODEL", "MODEL", 0)],
        widgets=[1.0],
    ))
    g.wire(23, 0, 24, "model", "MODEL")

    g.add(node(
        30, "TextEncodeQwenImageEditPlus", (740, 360), (460, 280),
        title="正向 · 毛胚+平面+正样本",
        inputs=[
            p_in("clip", "CLIP"),
            p_in("vae", "VAE", shape=7),
            p_in("image1", "IMAGE", shape=7),
            p_in("image2", "IMAGE", shape=7),
            p_in("image3", "IMAGE", shape=7),
            w_in("prompt", "STRING"),
        ],
        outputs=[out("CONDITIONING", "CONDITIONING", 0)],
        widgets=[POS_PROMPT],
    ))
    g.wire(21, 0, 30, "clip", "CLIP")
    g.wire(22, 0, 30, "vae", "VAE")
    g.wire(10, 0, 30, "image1", "IMAGE")
    g.wire(11, 0, 30, "image2", "IMAGE")
    g.wire(12, 0, 30, "image3", "IMAGE")

    g.add(node(
        31, "TextEncodeQwenImageEditPlus", (740, 680), (460, 220),
        title="负向 · 负样本+文本",
        inputs=[
            p_in("clip", "CLIP"),
            p_in("vae", "VAE", shape=7),
            p_in("image1", "IMAGE", shape=7),
            p_in("image2", "IMAGE", shape=7),
            p_in("image3", "IMAGE", shape=7),
            w_in("prompt", "STRING"),
        ],
        outputs=[out("CONDITIONING", "CONDITIONING", 0)],
        widgets=[NEG_PROMPT],
    ))
    g.wire(21, 0, 31, "clip", "CLIP")
    g.wire(22, 0, 31, "vae", "VAE")
    g.wire(13, 0, 31, "image1", "IMAGE")

    g.add(node(
        40, "FluxKontextImageScale", (1240, 360), (280, 50),
        title="毛胚缩放到编辑画幅",
        inputs=[p_in("image", "IMAGE")],
        outputs=[out("IMAGE", "IMAGE", 0)],
    ))
    g.wire(10, 0, 40, "image", "IMAGE")
    g.add(node(
        41, "VAEEncode", (1240, 440), (280, 50),
        title="编码毛胚 latent",
        inputs=[p_in("pixels", "IMAGE"), p_in("vae", "VAE")],
        outputs=[out("LATENT", "LATENT", 0)],
    ))
    g.wire(40, 0, 41, "pixels", "IMAGE")
    g.wire(22, 0, 41, "vae", "VAE")

    g.add(node(
        50, "KSampler", (1560, 360), (280, 280),
        title="采样 40 步 cfg4 euler",
        inputs=[
            p_in("model", "MODEL"),
            p_in("positive", "CONDITIONING"),
            p_in("negative", "CONDITIONING"),
            p_in("latent_image", "LATENT"),
            w_in("seed", "INT"),
            w_in("steps", "INT"),
            w_in("cfg", "FLOAT"),
            w_in("sampler_name", "COMBO"),
            w_in("scheduler", "COMBO"),
            w_in("denoise", "FLOAT"),
        ],
        outputs=[out("LATENT", "LATENT", 0)],
        widgets=[20260813, "fixed", 40, 4.0, "euler", "simple", 1.0],
    ))
    g.wire(24, 0, 50, "model", "MODEL")
    g.wire(30, 0, 50, "positive", "CONDITIONING")
    g.wire(31, 0, 50, "negative", "CONDITIONING")
    g.wire(41, 0, 50, "latent_image", "LATENT")

    g.add(node(
        51, "VAEDecode", (1880, 360), (220, 50),
        title="解码",
        inputs=[p_in("samples", "LATENT"), p_in("vae", "VAE")],
        outputs=[out("IMAGE", "IMAGE", 0)],
    ))
    g.wire(50, 0, 51, "samples", "LATENT")
    g.wire(22, 0, 51, "vae", "VAE")
    g.add(node(
        52, "PreviewImage", (1880, 440), (320, 280),
        title="效果图预览",
        inputs=[p_in("images", "IMAGE")],
    ))
    g.connect(51, 0, 52, 0, "IMAGE")
    g.add(node(
        53, "SaveImage", (1880, 740), (320, 80),
        title="保存效果图",
        inputs=[p_in("images", "IMAGE"), w_in("filename_prefix", "STRING")],
        outputs=[{"name": "images", "type": "IMAGE", "links": None}],
        widgets=["interior/edit2511"],
    ))
    g.connect(51, 0, 53, 0, "IMAGE")

    groups = [
        group_around([g.find(n) for n in (1, 10, 11, 12, 13, 14)], "① 参考图 · 毛胚/平面/正负样本", "#3f5159"),
        group_around([g.find(n) for n in (20, 21, 22, 23, 24)], "② 模型 Edit 2511", "#444a8a"),
        group_around([g.find(n) for n in (30, 31, 40, 41)], "③ 正负向编码", "#3f6b4a"),
        group_around([g.find(n) for n in (50, 51, 52, 53)], "④ 采样出图", "#6b4a3f"),
    ]
    wf = pack(g, groups, scale=0.42, offset=[20, 40])
    wf["id"] = "interior-edit-2511"
    return wf


def main() -> int:
    INPUT.mkdir(parents=True, exist_ok=True)
    ph = _placeholder()
    write_both("室内效果图_毛胚平面改图.json", build_edit(ph))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
