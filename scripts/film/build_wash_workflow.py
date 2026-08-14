#!/usr/bin/env python3
"""Build 洗图：反推提示词 + FLUX.2 官方图改图."""

from __future__ import annotations

import json
import shutil
import uuid
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
)

NOTE = """# 洗图 · 反推 + FLUX.2 图改图

目前本机最强本地链路：

1. **反推提示词**：Qwen-VL 看图，写出 FLUX.2 英文提示词（会明确写中国大陆五官，避免西化脸）
2. **图改图**：FLUX.2 官方 `ReferenceLatent` 编辑，**保住原图构图/光/衣服**，按「改图指令」重绘材质和脸

## 怎么用

1. 左上角 **换原图**
2. 中间改「改图指令」（默认是洗成更真实的中国大陆人物写真）
3. 点运行
4. 右边看：反推文本 / 原图 / 洗后图

## 只想反推、不改图

把右侧「③ FLUX.2 图改图」整组 **Bypass**。

## 只想改图、不反推

把「② 反推」Bypass，并断开 Concat 的反推输入，只留改图指令。

## 参数

- Guidance **4.0**（官方图编辑值，比生图 3.5 更听话）
- 画幅跟原图走，限制约 **2.0MP**、边长 16 倍数
- 跑在 **GPU2 / GPU3**，不要占 H3 的 GPU0/1
"""

EDIT_INSTRUCTION = (
    "Keep the same camera, pose, framing, wardrobe, and environment. "
    "Photoreal unretouched photograph of a 20-year-old Chinese mainland Han woman: "
    "black hair, almond eyes with epicanthic fold, oval face, natural East Asian bone structure, "
    "no mixed-race or Westernized features, no heavy freckles. "
    "Visible pores and peach fuzz, natural skin, shop-window key light, wet pavement if present. "
    "Single subject only."
)


def build() -> dict:
    g = Graph()
    g.add(note(1, (20, -380), (520, 420), "用法", NOTE))

    # ---- source ----
    g.add(node(
        10, "LoadImage", (20, 80), (340, 320),
        title="原图",
        inputs=[w_in("image", "COMBO"), w_in("upload", "IMAGEUPLOAD")],
        outputs=[out("IMAGE", "IMAGE", 0), out("MASK", "MASK", 1)],
        widgets=["wash_src.png", "image"],
    ))
    g.add(node(
        11, "ImageScaleToTotalPixels", (400, 80), (280, 110),
        title="限制 2.0MP / 16 对齐",
        inputs=[
            p_in("image", "IMAGE"),
            w_in("upscale_method", "COMBO"),
            w_in("megapixels", "FLOAT"),
            w_in("resolution_steps", "INT"),
        ],
        outputs=[out("IMAGE", "IMAGE", 0)],
        widgets=["lanczos", 2.0, 16],
    ))
    g.wire(10, 0, 11, "image", "IMAGE")
    g.add(node(
        12, "PreviewImage", (400, 230), (280, 280),
        title="原图预览",
        inputs=[p_in("images", "IMAGE")],
    ))
    g.connect(11, 0, 12, 0, "IMAGE")
    g.add(node(
        13, "GetImageSize", (400, 540), (240, 80),
        title="读取宽高",
        inputs=[p_in("image", "IMAGE")],
        outputs=[out("width", "INT", 0), out("height", "INT", 1), out("batch_size", "INT", 2)],
    ))
    g.connect(11, 0, 13, 0, "IMAGE")

    # ---- reverse ----
    g.add(node(
        20, "ImageReversePrompt", (720, 80), (400, 180),
        title="反推提示词 Qwen-VL",
        inputs=[
            p_in("image", "IMAGE"),
            w_in("task", "COMBO"),
            w_in("device", "COMBO"),
            w_in("extra_instructions", "STRING"),
        ],
        outputs=[out("prompt", "STRING", 0)],
        widgets=["more_detailed", "cuda:0", "强调这是中国大陆年轻女性，五官不要西化。"],
    ))
    g.wire(11, 0, 20, "image", "IMAGE")
    g.add(node(
        21, "PreviewAny", (720, 300), (400, 200),
        title="反推结果（可复制）",
        inputs=[p_in("source", "*")],
        outputs=[out("STRING", "STRING", 0)],
    ))
    g.connect(20, 0, 21, 0, "*")
    g.add(node(
        22, "MiniMaxH3PromptPolish", (720, 540), (400, 250),
        title="可选：润色成生图提示词（需 sglang）",
        inputs=[
            w_in("prompt_zh", "STRING"),
            w_in("mode", "COMBO"),
            w_in("duration_sec", "FLOAT"),
            w_in("base_url", "STRING"),
            w_in("model", "STRING"),
            w_in("temperature", "FLOAT"),
            w_in("max_tokens", "INT"),
            w_in("timeout_sec", "FLOAT"),
            w_in("bypass", "BOOLEAN"),
            w_in("extra_instructions", "STRING"),
        ],
        outputs=[out("prompt_en", "STRING", 0)],
        widgets=[
            "", "IMAGE_STILL", 5.0,
            "http://127.0.0.1:8030/v1", "qwen3.6-fast",
            0.4, 700, 120.0, True, "",
        ],
    ))
    g.wire(20, 0, 22, "prompt_zh", "STRING")
    g.add(node(
        23, "PreviewAny", (720, 820), (400, 160),
        title="润色结果（默认 Bypass）",
        inputs=[p_in("source", "*")],
        outputs=[out("STRING", "STRING", 0)],
    ))
    g.connect(22, 0, 23, 0, "*")

    # ---- edit instruction + concat ----
    g.add(node(
        30, "PrimitiveStringMultiline", (1180, 80), (420, 220),
        title="改图指令（图改图主控）",
        inputs=[w_in("value", "STRING")],
        outputs=[out("STRING", "STRING", 0)],
        widgets=[EDIT_INSTRUCTION],
    ))
    g.add(node(
        31, "StringConcatenate", (1180, 330), (420, 140),
        title="指令 + 反推场景",
        inputs=[
            p_in("string_a", "STRING"),
            p_in("string_b", "STRING"),
            w_in("delimiter", "STRING"),
        ],
        outputs=[out("STRING", "STRING", 0)],
        widgets=["\n\nScene from photo:\n"],
    ))
    g.wire(30, 0, 31, "string_a", "STRING")
    g.wire(20, 0, 31, "string_b", "STRING")

    # ---- flux2 ----
    g.add(node(
        40, "UNETLoader", (1660, 80), (340, 90),
        title="FLUX.2 Dev fp8mixed",
        inputs=[w_in("unet_name", "COMBO"), w_in("weight_dtype", "COMBO")],
        outputs=[out("MODEL", "MODEL", 0)],
        widgets=["flux2_dev_fp8mixed.safetensors", "default"],
    ))
    g.add(node(
        41, "CLIPLoader", (1660, 190), (340, 110),
        title="FLUX.2 CLIP mistral",
        inputs=[w_in("clip_name", "COMBO"), w_in("type", "COMBO"), w_in("device", "COMBO")],
        outputs=[out("CLIP", "CLIP", 0)],
        widgets=["mistral_3_small_flux2_bf16.safetensors", "flux2", "default"],
    ))
    g.add(node(
        42, "VAELoader", (1660, 330), (340, 70),
        title="FLUX.2 VAE",
        inputs=[w_in("vae_name", "COMBO")],
        outputs=[out("VAE", "VAE", 0)],
        widgets=["flux2-vae.safetensors"],
    ))
    g.add(node(
        43, "CLIPTextEncode", (2040, 80), (400, 160),
        title="编辑条件",
        inputs=[w_in("text", "STRING"), p_in("clip", "CLIP")],
        outputs=[out("CONDITIONING", "CONDITIONING", 0)],
        widgets=[""],
    ))
    g.wire(31, 0, 43, "text", "STRING")
    g.wire(41, 0, 43, "clip", "CLIP")
    g.add(node(
        44, "FluxGuidance", (2040, 270), (280, 60),
        title="FluxGuidance 4.0（官方编辑）",
        inputs=[p_in("conditioning", "CONDITIONING"), w_in("guidance", "FLOAT")],
        outputs=[out("CONDITIONING", "CONDITIONING", 0)],
        widgets=[4.0],
    ))
    g.connect(43, 0, 44, 0, "CONDITIONING")
    g.add(node(
        45, "VAEEncode", (2040, 360), (280, 50),
        title="原图编码（构图锚）",
        inputs=[p_in("pixels", "IMAGE"), p_in("vae", "VAE")],
        outputs=[out("LATENT", "LATENT", 0)],
    ))
    g.wire(11, 0, 45, "pixels", "IMAGE")
    g.wire(42, 0, 45, "vae", "VAE")
    g.add(node(
        46, "ReferenceLatent", (2040, 440), (280, 60),
        title="Set Reference Latent",
        inputs=[p_in("conditioning", "CONDITIONING"), p_in("latent", "LATENT")],
        outputs=[out("CONDITIONING", "CONDITIONING", 0)],
    ))
    g.connect(44, 0, 46, 0, "CONDITIONING")
    g.wire(45, 0, 46, "latent", "LATENT")
    g.add(node(
        47, "BasicGuider", (2360, 80), (260, 60),
        title="引导器",
        inputs=[p_in("model", "MODEL"), p_in("conditioning", "CONDITIONING")],
        outputs=[out("GUIDER", "GUIDER", 0)],
    ))
    g.connect(40, 0, 47, 0, "MODEL")
    g.connect(46, 0, 47, 1, "CONDITIONING")
    g.add(node(
        48, "EmptyFlux2LatentImage", (2360, 170), (260, 110),
        title="输出画布（跟原图）",
        inputs=[w_in("width", "INT"), w_in("height", "INT"), w_in("batch_size", "INT")],
        outputs=[out("LATENT", "LATENT", 0)],
        widgets=[1024, 1024, 1],
    ))
    g.wire(13, 0, 48, "width", "INT")
    g.wire(13, 1, 48, "height", "INT")
    g.add(node(
        49, "KSamplerSelect", (2360, 310), (260, 60),
        title="euler",
        inputs=[w_in("sampler_name", "COMBO")],
        outputs=[out("SAMPLER", "SAMPLER", 0)],
        widgets=["euler"],
    ))
    g.add(node(
        50, "Flux2Scheduler", (2360, 390), (260, 110),
        title="Flux.2 调度 20 步",
        inputs=[w_in("steps", "INT"), w_in("width", "INT"), w_in("height", "INT")],
        outputs=[out("SIGMAS", "SIGMAS", 0)],
        widgets=[20, 1024, 1024],
    ))
    g.wire(13, 0, 50, "width", "INT")
    g.wire(13, 1, 50, "height", "INT")
    g.add(node(
        51, "RandomNoise", (2360, 530), (260, 80),
        title="种子",
        inputs=[w_in("noise_seed", "INT")],
        outputs=[out("NOISE", "NOISE", 0)],
        widgets=[0, "randomize"],
    ))
    g.add(node(
        52, "SamplerCustomAdvanced", (2660, 80), (300, 160),
        title="FLUX.2 编辑采样",
        inputs=[
            p_in("noise", "NOISE"), p_in("guider", "GUIDER"), p_in("sampler", "SAMPLER"),
            p_in("sigmas", "SIGMAS"), p_in("latent_image", "LATENT"),
        ],
        outputs=[out("output", "LATENT", 0), out("denoised_output", "LATENT", 1)],
    ))
    g.connect(51, 0, 52, 0, "NOISE")
    g.connect(47, 0, 52, 1, "GUIDER")
    g.connect(49, 0, 52, 2, "SAMPLER")
    g.connect(50, 0, 52, 3, "SIGMAS")
    g.connect(48, 0, 52, 4, "LATENT")
    g.add(node(
        53, "VAEDecode", (2660, 280), (240, 50),
        title="解码",
        inputs=[p_in("samples", "LATENT"), p_in("vae", "VAE")],
        outputs=[out("IMAGE", "IMAGE", 0)],
    ))
    g.connect(52, 0, 53, 0, "LATENT")
    g.wire(42, 0, 53, "vae", "VAE")
    g.add(node(
        54, "PreviewImage", (2940, 80), (320, 320),
        title="洗后预览",
        inputs=[p_in("images", "IMAGE")],
    ))
    g.connect(53, 0, 54, 0, "IMAGE")
    g.add(node(
        55, "SaveImage", (2940, 430), (320, 90),
        title="保存洗后图",
        inputs=[p_in("images", "IMAGE"), w_in("filename_prefix", "STRING")],
        outputs=[{"name": "images", "type": "IMAGE", "links": None}],
        widgets=["wash/flux2_edit"],
    ))
    g.connect(53, 0, 55, 0, "IMAGE")

    groups = [
        group_around([g.find(n) for n in (10, 11, 12, 13)], "① 原图", "#3f5159"),
        group_around([g.find(n) for n in (20, 21, 22, 23)], "② 反推提示词", "#5a4a3a"),
        group_around(
            [g.find(n) for n in (30, 31, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55)],
            "③ FLUX.2 图改图（官方 ReferenceLatent）",
            "#3d4a6b",
        ),
    ]
    return pack(g, groups, scale=0.48, offset=[40, 80])


def main() -> int:
    wf = build()
    name = "洗图_反推_FLUX2图改图.json"
    payload = json.dumps(wf, ensure_ascii=False, indent=2)
    USER.mkdir(parents=True, exist_ok=True)
    for p in (WORK / name, USER / name):
        p.write_text(payload, encoding="utf-8")
        print(f"wrote {p} nodes={len(wf['nodes'])} links={len(wf['links'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
