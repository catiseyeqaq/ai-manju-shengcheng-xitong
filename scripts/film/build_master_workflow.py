#!/usr/bin/env python3
"""Build the annotated master workflow: 中文 -> 官方提示词 -> 写实图 -> 修脸 -> 放大 -> H3 视频.

Pipeline stages, each in its own titled group on the canvas:

  1  中文分镜草稿
  2  MiniMax 官方 h3-prompt-writing skill 双路润色（静帧 / 镜头）
  3  majicFlus 麦橘超然出写实首帧
  4  FaceDetailer 修远景小脸（Topaz 之外的开源解法之一）
  5  UltimateSDUpscale 分块放大到成片级分辨率
  6  MiniMax H3 首帧 -> 带立体声视频

Every node carries a Chinese title, and each group has a MarkdownNote spelling
out what the knobs do and which direction to turn them.
"""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path

TEMPLATE = Path("/workdata/ComfyUI/workflows/video_minimax_h3_i2v_bf16.json")
OUTPUTS = [
    Path("/workdata/ComfyUI/workflows/film_master_zh_prompt_flux_face_upscale_h3.json"),
    Path("/root/ComfyUI/user/default/workflows/film_master_zh_prompt_flux_face_upscale_h3.json"),
]

H3_ID_OFFSET = 3000
H3_POS_SHIFT = (8200, -4300)

DRAFT_ZH = (
    "雨夜霓虹城市街道，一位三十岁东亚女性穿米色风衣撑伞走过积水路面。"
    "浅景深，35mm 胶片质感，自然皮肤纹理，电影调色。镜头缓慢跟拍她的侧脸与脚步。"
    "环境声：雨声、远处车流；配乐低沉；皮鞋踩水声。"
)

NEGATIVE_TEXT = (
    "blurry, out of focus, low resolution, plastic skin, waxy skin, airbrushed, "
    "deformed face, extra fingers, bad anatomy, anime, illustration, 3d render, "
    "oversaturated, watermark, text"
)

FACE_WILDCARD = (
    "sharp detailed face, natural skin pores and texture, catchlight in the eyes, "
    "individual eyelashes, subtle skin blemishes, photorealistic"
)


class Graph:
    def __init__(self) -> None:
        self.nodes: list[dict] = []
        self.links: list[list] = []
        self._next_link = 1

    def add(self, n: dict) -> dict:
        self.nodes.append(n)
        return n

    def find(self, node_id: int) -> dict:
        return next(n for n in self.nodes if n["id"] == node_id)

    def slot(self, node_id: int, name: str) -> int:
        return next(i for i, s in enumerate(self.find(node_id)["inputs"]) if s["name"] == name)

    def connect(self, src: int, src_slot: int, dst: int, dst_slot: int, type_: str) -> int:
        lid = self._next_link
        self._next_link += 1
        self.links.append([lid, src, src_slot, dst, dst_slot, type_])
        o = self.find(src)["outputs"][src_slot]
        if o.get("links") is None:
            o["links"] = []
        o["links"].append(lid)
        self.find(dst)["inputs"][dst_slot]["link"] = lid
        return lid

    def wire(self, src: int, src_out: int, dst: int, dst_name: str, type_: str) -> int:
        return self.connect(src, src_out, dst, self.slot(dst, dst_name), type_)

    @property
    def last_link_id(self) -> int:
        return self._next_link - 1


def node(nid, type_, pos, size, *, title=None, inputs=None, outputs=None, widgets=None) -> dict:
    return {
        "id": nid,
        "type": type_,
        "pos": list(pos),
        "size": list(size),
        "flags": {},
        "order": nid,
        "mode": 0,
        "inputs": inputs or [],
        "outputs": outputs or [],
        "title": title or type_,
        "properties": {"Node name for S&R": type_},
        "widgets_values": widgets if widgets is not None else [],
    }


def w_in(name, type_):
    return {"name": name, "type": type_, "widget": {"name": name}, "link": None}


def p_in(name, type_):
    return {"name": name, "type": type_, "link": None}


def out(name, type_, slot):
    return {"name": name, "type": type_, "links": [], "slot_index": slot}


def note(nid, pos, size, title, text) -> dict:
    n = node(nid, "MarkdownNote", pos, size, title=title, widgets=[text])
    n["properties"] = {}
    return n


def import_h3(g: Graph) -> dict[int, int]:
    src = json.loads(TEMPLATE.read_text())
    sub = src["definitions"]["subgraphs"][0]
    id_map: dict[int, int] = {}
    for original in sub["nodes"]:
        n = copy.deepcopy(original)
        id_map[n["id"]] = n["id"] + H3_ID_OFFSET
        n["id"] = id_map[original["id"]]
        for i in n.get("inputs", []):
            i["link"] = None
        for o in n.get("outputs", []):
            o["links"] = []
        pos = n.get("pos")
        if isinstance(pos, dict):
            pos = [pos.get("0", 0), pos.get("1", 0)]
        n["pos"] = [pos[0] + H3_POS_SHIFT[0], pos[1] + H3_POS_SHIFT[1]]
        g.add(n)
    for link in sub["links"]:
        if isinstance(link, dict):
            s, ss, t, ts, ty = (
                link["origin_id"], link["origin_slot"],
                link["target_id"], link["target_slot"], link["type"],
            )
        else:
            _, s, ss, t, ts, ty = link
        if s < 0 or t < 0:
            continue
        g.connect(id_map[s], ss, id_map[t], ts, ty)
    return id_map


def build() -> dict:
    g = Graph()
    h3 = import_h3(g)

    # ============ 1. 中文草稿 + 官方 skill 润色 ============
    g.add(note(
        1, (-2700, -700), (540, 760), "总览 / 怎么用",
        "# 写实真人 AI 电影 · 全链路\n\n"
        "```\n中文草稿 → 官方提示词 → 写实首帧 → 修脸 → 放大 → 带声视频\n```\n\n"
        "## 一次跑通的顺序\n"
        "1. 只改 **中文分镜草稿** 这一个输入框\n"
        "2. 起了 Qwen 服务后，把两个润色节点的 `bypass` 改成 **false**\n"
        "3. 先只跑到 **保存首帧** 看脸满不满意\n"
        "4. 满意后再放开 H3 出视频（单卡约 30s/step）\n\n"
        "## 提示词用的是官方规范\n"
        "润色节点内置 MiniMax 官方 `h3-prompt-writing` skill 的两份指南：\n"
        "- `base-en.txt`（T2VA / I2VA / FL2VA / L2VA）\n"
        "- `ref-en.txt`（Ref2VA 多参考）\n\n"
        "所以输出会严格带 `integrated_multimodal_description` / "
        "`overall_soundscape` / `non_diegetic_music` 三段式，"
        "镜头写成 `[Shot 2] At 00:03.500, the camera cuts to…`，"
        "运镜写成 `pushes in with small amplitude at slow speed`。\n\n"
        "`IMAGE_STILL` 模式则不套视频格式，产出纯静帧生图提示词。\n\n"
        "## 关于 Topaz\n"
        "Topaz 是闭源商业软件，本机跑不了。等效替代已经接好："
        "**FaceDetailer 修脸 + UltimateSDUpscale 分块重绘放大**，"
        "配 `RealESRGAN_x4` 放大模型。",
    ))

    g.add(node(
        2, "PrimitiveStringMultiline", (-2100, -700), (480, 240),
        title="① 中文分镜草稿（只改这里）",
        outputs=[out("STRING", "STRING", 0)],
        widgets=[DRAFT_ZH],
    ))

    def polish_inputs():
        return [
            w_in("prompt_zh", "STRING"), w_in("mode", "COMBO"), w_in("duration_sec", "FLOAT"),
            w_in("base_url", "STRING"), w_in("model", "STRING"), w_in("temperature", "FLOAT"),
            w_in("max_tokens", "INT"), w_in("timeout_sec", "FLOAT"), w_in("bypass", "BOOLEAN"),
            w_in("extra_instructions", "STRING"),
        ]

    g.add(node(
        3, "MiniMaxH3PromptPolish", (-1560, -700), (480, 340),
        title="②a 官方 skill → 静帧提示词（喂生图）",
        inputs=polish_inputs(),
        outputs=[out("prompt_en", "STRING", 0)],
        widgets=[
            DRAFT_ZH, "IMAGE_STILL", 5.0, "http://127.0.0.1:8030/v1", "qwen3.6-fast",
            0.3, 700, 180.0, True,
            "Frame the face large enough to stay sharp: medium shot or closer. "
            "Explicitly mention eyes in focus.",
        ],
    ))
    g.add(node(
        4, "MiniMaxH3PromptPolish", (-1560, -320), (480, 340),
        title="②b 官方 skill → I2VA 镜头提示词（喂 H3）",
        inputs=polish_inputs(),
        outputs=[out("prompt_en", "STRING", 0)],
        widgets=[
            DRAFT_ZH, "I2VA", 5.0, "http://127.0.0.1:8030/v1", "qwen3.6-fast",
            0.4, 1400, 180.0, True,
            "Keep the identity, wardrobe and framing of <Picture 1> unchanged.",
        ],
    ))
    g.wire(2, 0, 3, "prompt_zh", "STRING")
    g.wire(2, 0, 4, "prompt_zh", "STRING")

    g.add(node(
        5, "PreviewAny", (-1020, -700), (380, 220),
        title="静帧提示词（可核对）",
        inputs=[p_in("source", "*")],
        outputs=[{"name": "STRING", "type": "STRING", "links": None}],
    ))
    g.add(node(
        6, "PreviewAny", (-1020, -440), (380, 260),
        title="镜头提示词（官方三段式）",
        inputs=[p_in("source", "*")],
        outputs=[{"name": "STRING", "type": "STRING", "links": None}],
    ))
    g.connect(3, 0, 5, 0, "*")
    g.connect(4, 0, 6, 0, "*")

    g.add(note(
        7, (-2700, 120), (540, 420), "提示词要点（官方规范摘要）",
        "## 官方写法\n"
        "- **第一个镜头不写时间戳**，之后每个 `[Shot N]` 必须给严格递增的切点\n"
        "- 运镜三要素：**类型 + 幅度 + 速度**\n"
        "  `Push In / Tracking Shot / Arc Shot` + `with small amplitude` + `at slow speed`\n"
        "- 台词放 `<d>[English] …</d>`，说话人固定 ID `(S1)`\n"
        "- 画面里出现的字，用英文双引号原样保留\n"
        "- `overall_soundscape` 只写环境音与动作音，不重复台词\n"
        "- `non_diegetic_music` 只写观众听得到、角色听不到的配乐\n\n"
        "## 写实真人的关键词\n"
        "`photorealistic, live-action, natural skin texture, 35mm, "
        "shallow depth of field, natural lighting`\n\n"
        "反过来要压掉：`anime, illustration, 3d render, plastic skin`",
    ))

    # ============ 2. majicFlus 首帧 ============
    g.add(node(
        10, "UNETLoader", (-2100, 620), (480, 100),
        title="③ 麦橘超然 majicFlus v1.34",
        inputs=[w_in("unet_name", "COMBO"), w_in("weight_dtype", "COMBO")],
        outputs=[out("MODEL", "MODEL", 0)],
        widgets=["majicflus_v134.safetensors", "default"],
    ))
    g.add(node(
        11, "DualCLIPLoader", (-2100, 770), (480, 130),
        title="Flux 文本编码器 (clip_l + t5xxl)",
        inputs=[w_in("clip_name1", "COMBO"), w_in("clip_name2", "COMBO"), w_in("type", "COMBO")],
        outputs=[out("CLIP", "CLIP", 0)],
        widgets=["clip_l.safetensors", "t5xxl_fp16.safetensors", "flux"],
    ))
    g.add(node(
        12, "VAELoader", (-2100, 950), (480, 80),
        title="Flux.1 VAE",
        inputs=[w_in("vae_name", "COMBO")],
        outputs=[out("VAE", "VAE", 0)],
        widgets=["flux1_ae.safetensors"],
    ))

    g.add(node(
        13, "CLIPTextEncode", (-1560, 620), (440, 180),
        title="正向（来自官方润色）",
        inputs=[w_in("text", "STRING"), p_in("clip", "CLIP")],
        outputs=[out("CONDITIONING", "CONDITIONING", 0)],
        widgets=[""],
    ))
    g.wire(3, 0, 13, "text", "STRING")
    g.wire(11, 0, 13, "clip", "CLIP")

    g.add(node(
        14, "CLIPTextEncode", (-1560, 840), (440, 180),
        title="负向（给修脸/放大用）",
        inputs=[w_in("text", "STRING"), p_in("clip", "CLIP")],
        outputs=[out("CONDITIONING", "CONDITIONING", 0)],
        widgets=[NEGATIVE_TEXT],
    ))
    g.wire(11, 0, 14, "clip", "CLIP")

    g.add(node(
        15, "FluxGuidance", (-1060, 620), (300, 60),
        title="Flux 引导 3.5（官方推荐）",
        inputs=[p_in("conditioning", "CONDITIONING"), w_in("guidance", "FLOAT")],
        outputs=[out("CONDITIONING", "CONDITIONING", 0)],
        widgets=[3.5],
    ))
    g.connect(13, 0, 15, 0, "CONDITIONING")

    g.add(node(
        16, "BasicGuider", (-720, 620), (280, 60),
        title="引导器",
        inputs=[p_in("model", "MODEL"), p_in("conditioning", "CONDITIONING")],
        outputs=[out("GUIDER", "GUIDER", 0)],
    ))
    g.connect(10, 0, 16, 0, "MODEL")
    g.connect(15, 0, 16, 1, "CONDITIONING")

    g.add(node(
        17, "EmptySD3LatentImage", (-1560, 1060), (300, 130),
        title="首帧画幅 1344x768（对齐 H3）",
        inputs=[w_in("width", "INT"), w_in("height", "INT"), w_in("batch_size", "INT")],
        outputs=[out("LATENT", "LATENT", 0)],
        widgets=[1344, 768, 1],
    ))
    g.add(node(
        18, "KSamplerSelect", (-1560, 1240), (300, 60),
        title="采样器 euler",
        inputs=[w_in("sampler_name", "COMBO")],
        outputs=[out("SAMPLER", "SAMPLER", 0)],
        widgets=["euler"],
    ))
    g.add(node(
        19, "BasicScheduler", (-1560, 1350), (300, 140),
        title="调度 beta / 28 步（皮肤质感）",
        inputs=[p_in("model", "MODEL"), w_in("scheduler", "COMBO"), w_in("steps", "INT"), w_in("denoise", "FLOAT")],
        outputs=[out("SIGMAS", "SIGMAS", 0)],
        widgets=["beta", 28, 1.0],
    ))
    g.connect(10, 0, 19, 0, "MODEL")

    g.add(node(
        20, "RandomNoise", (-1560, 1530), (300, 90),
        title="首帧种子",
        inputs=[w_in("noise_seed", "INT")],
        outputs=[out("NOISE", "NOISE", 0)],
        widgets=[42, "randomize"],
    ))

    g.add(node(
        21, "SamplerCustomAdvanced", (-720, 780), (320, 180),
        title="生图采样",
        inputs=[
            p_in("noise", "NOISE"), p_in("guider", "GUIDER"), p_in("sampler", "SAMPLER"),
            p_in("sigmas", "SIGMAS"), p_in("latent_image", "LATENT"),
        ],
        outputs=[out("output", "LATENT", 0), out("denoised_output", "LATENT", 1)],
    ))
    g.connect(20, 0, 21, 0, "NOISE")
    g.connect(16, 0, 21, 1, "GUIDER")
    g.connect(18, 0, 21, 2, "SAMPLER")
    g.connect(19, 0, 21, 3, "SIGMAS")
    g.connect(17, 0, 21, 4, "LATENT")

    g.add(node(
        22, "VAEDecode", (-340, 780), (260, 60),
        title="解码原始首帧",
        inputs=[p_in("samples", "LATENT"), p_in("vae", "VAE")],
        outputs=[out("IMAGE", "IMAGE", 0)],
    ))
    g.connect(21, 0, 22, 0, "LATENT")
    g.connect(12, 0, 22, 1, "VAE")

    g.add(node(
        23, "PreviewImage", (-340, 900), (300, 300),
        title="原始首帧（修脸前）",
        inputs=[p_in("images", "IMAGE")],
    ))
    g.connect(22, 0, 23, 0, "IMAGE")

    g.add(note(
        24, (-2700, 620), (540, 460), "生图参数说明",
        "## majicFlus（麦橘超然）官方推荐\n"
        "| 参数 | 值 |\n|---|---|\n"
        "| steps | 20~30 |\n"
        "| FluxGuidance | 3.5 |\n"
        "| 采样 | `euler + simple/beta` 通用 |\n"
        "| 采样 | `dpmpp_2m + sgm_uniform` 更出皮肤质感 |\n"
        "| 底座 | Flux.1-dev，clip_l + t5xxl_fp16 |\n\n"
        "## 画幅\n"
        "这里设 **1344×768**，直接对齐 H3 原生画布，"
        "首帧不用再缩放，避免二次插值糊掉细节。\n\n"
        "竖屏人像可改 **832×1216**，但送 H3 前要改成 H3 支持的比例。\n\n"
        "## 想换 FLUX.2\n"
        "把 UNETLoader 换 `flux2_dev_fp8mixed`，"
        "文本编码器改用单个 `CLIPLoader` 载入 `mistral_3_small_flux2_bf16`，"
        "VAE 换 `flux2-vae`。FLUX.2 自带多参考锁角色，跨镜头保脸更强。",
    ))

    # ============ 3. FaceDetailer 修脸 ============
    g.add(node(
        30, "UltralyticsDetectorProvider", (0, 620), (340, 80),
        title="④ 人脸检测器 YOLOv8m",
        inputs=[w_in("model_name", "COMBO")],
        outputs=[out("BBOX_DETECTOR", "BBOX_DETECTOR", 0), out("SEGM_DETECTOR", "SEGM_DETECTOR", 1)],
        widgets=["bbox/face_yolov8m.pt"],
    ))

    face_inputs = [
        p_in("image", "IMAGE"), p_in("model", "MODEL"), p_in("clip", "CLIP"), p_in("vae", "VAE"),
        w_in("guide_size", "FLOAT"), w_in("guide_size_for", "BOOLEAN"), w_in("max_size", "FLOAT"),
        w_in("seed", "INT"), w_in("steps", "INT"), w_in("cfg", "FLOAT"),
        w_in("sampler_name", "COMBO"), w_in("scheduler", "COMBO"),
        p_in("positive", "CONDITIONING"), p_in("negative", "CONDITIONING"),
        w_in("denoise", "FLOAT"), w_in("feather", "INT"), w_in("noise_mask", "BOOLEAN"),
        w_in("force_inpaint", "BOOLEAN"), w_in("bbox_threshold", "FLOAT"),
        w_in("bbox_dilation", "INT"), w_in("bbox_crop_factor", "FLOAT"),
        w_in("sam_detection_hint", "COMBO"), w_in("sam_dilation", "INT"), w_in("sam_threshold", "FLOAT"),
        w_in("sam_bbox_expansion", "INT"), w_in("sam_mask_hint_threshold", "FLOAT"),
        w_in("sam_mask_hint_use_negative", "COMBO"), w_in("drop_size", "INT"),
        p_in("bbox_detector", "BBOX_DETECTOR"), w_in("wildcard", "STRING"), w_in("cycle", "INT"),
    ]
    g.add(node(
        31, "FaceDetailer", (400, 620), (420, 700),
        title="④ 修远景小脸 FaceDetailer",
        inputs=face_inputs,
        outputs=[
            out("image", "IMAGE", 0), out("cropped_refined", "IMAGE", 1),
            out("cropped_enhanced_alpha", "IMAGE", 2), out("mask", "MASK", 3),
            out("detailer_pipe", "DETAILER_PIPE", 4), out("cnet_images", "IMAGE", 5),
        ],
        widgets=[
            1024,          # guide_size: 小脸放大到 1024 再重绘
            True,          # guide_size_for bbox
            1536,          # max_size
            42, "randomize",
            25,            # steps
            1.0,           # cfg: Flux 走蒸馏，cfg 保持 1
            "euler", "beta",
            0.45,          # denoise: 0.3~0.5，越高越敢改脸
            8,             # feather
            True,          # noise_mask
            True,          # force_inpaint
            0.4,           # bbox_threshold: 调低才能抓到远景小脸
            10,            # bbox_dilation
            3.0,           # bbox_crop_factor
            "center-1", 0, 0.93, 0, 0.7, "False",
            10,            # drop_size
            FACE_WILDCARD,
            1,             # cycle
        ],
    ))
    g.wire(22, 0, 31, "image", "IMAGE")
    g.wire(10, 0, 31, "model", "MODEL")
    g.wire(11, 0, 31, "clip", "CLIP")
    g.wire(12, 0, 31, "vae", "VAE")
    g.wire(15, 0, 31, "positive", "CONDITIONING")
    g.wire(14, 0, 31, "negative", "CONDITIONING")
    g.wire(30, 0, 31, "bbox_detector", "BBOX_DETECTOR")

    g.add(node(
        32, "PreviewImage", (400, 1360), (320, 300),
        title="修脸后对比",
        inputs=[p_in("images", "IMAGE")],
    ))
    g.connect(31, 0, 32, 0, "IMAGE")

    g.add(note(
        33, (0, 740), (360, 560), "④ 远景脸模糊怎么修",
        "## 原理\n"
        "YOLO 检测脸 → 裁出来单独放大重绘 → 羽化贴回。\n"
        "所以**小脸也能拿到足够像素**再画。\n\n"
        "## 关键参数\n"
        "| 参数 | 作用 | 调法 |\n|---|---|---|\n"
        "| `bbox_threshold` | 检测灵敏度 | 远景小脸 **调低到 0.3~0.4** |\n"
        "| `guide_size` | 裁剪块放大到多少 | Flux 用 **1024** |\n"
        "| `max_size` | 上限，防爆显存 | 1536 |\n"
        "| `denoise` | 敢改多少 | **0.3~0.5**；越怪就调低 |\n"
        "| `bbox_crop_factor` | 带多少上下文 | 3.0；特写可降到 2.0 |\n"
        "| `feather` | 边缘羽化 | 5~20，防补丁感 |\n"
        "| `cfg` | Flux 蒸馏模型 | **必须 1.0** |\n\n"
        "## 越修越怪时\n"
        "1. 先看检测框对不对（看 `mask` 输出）\n"
        "2. 降 `denoise`\n"
        "3. 降 `guide_size`\n\n"
        "**它不是换脸工具**，不保证跨镜头身份一致；那个要靠 H3 的 R2V 或 FLUX.2 多参考。",
    ))

    # ============ 4. UltimateSDUpscale 放大 ============
    g.add(node(
        40, "UpscaleModelLoader", (880, 620), (320, 60),
        title="⑤ 放大模型 RealESRGAN x4",
        inputs=[w_in("model_name", "COMBO")],
        outputs=[out("UPSCALE_MODEL", "UPSCALE_MODEL", 0)],
        widgets=["RealESRGAN_x4.pth"],
    ))

    g.add(node(
        41, "UltimateSDUpscale", (1260, 620), (420, 660),
        title="⑤ 分块重绘放大（Topaz 开源替代）",
        inputs=[
            p_in("image", "IMAGE"), p_in("model", "MODEL"),
            p_in("positive", "CONDITIONING"), p_in("negative", "CONDITIONING"), p_in("vae", "VAE"),
            w_in("upscale_by", "FLOAT"), w_in("seed", "INT"), w_in("steps", "INT"), w_in("cfg", "FLOAT"),
            w_in("sampler_name", "COMBO"), w_in("scheduler", "COMBO"), w_in("denoise", "FLOAT"),
            p_in("upscale_model", "UPSCALE_MODEL"), w_in("mode_type", "COMBO"),
            w_in("tile_width", "INT"), w_in("tile_height", "INT"), w_in("mask_blur", "INT"),
            w_in("tile_padding", "INT"), w_in("seam_fix_mode", "COMBO"), w_in("seam_fix_denoise", "FLOAT"),
            w_in("seam_fix_width", "INT"), w_in("seam_fix_mask_blur", "INT"), w_in("seam_fix_padding", "INT"),
            w_in("force_uniform_tiles", "BOOLEAN"), w_in("tiled_decode", "BOOLEAN"), w_in("batch_size", "INT"),
        ],
        outputs=[out("IMAGE", "IMAGE", 0)],
        widgets=[
            2.0,           # upscale_by: 1344x768 -> 2688x1536
            42, "randomize",
            18,            # steps
            1.0,           # cfg (Flux)
            "euler", "beta",
            0.22,          # denoise: 只补细节，别重画内容
            "Linear",
            1024, 1024,    # tile size
            8,             # mask_blur
            32,            # tile_padding
            "Half Tile",   # seam fix
            1.0, 64, 8, 16,
            True,          # force_uniform_tiles
            True,          # tiled_decode 省显存
            1,
        ],
    ))
    g.wire(31, 0, 41, "image", "IMAGE")
    g.wire(10, 0, 41, "model", "MODEL")
    g.wire(15, 0, 41, "positive", "CONDITIONING")
    g.wire(14, 0, 41, "negative", "CONDITIONING")
    g.wire(12, 0, 41, "vae", "VAE")
    g.wire(40, 0, 41, "upscale_model", "UPSCALE_MODEL")

    g.add(node(
        42, "SaveImage", (1740, 620), (380, 420),
        title="⑤ 保存成片级定妆图",
        inputs=[p_in("images", "IMAGE"), w_in("filename_prefix", "STRING")],
        outputs=[{"name": "images", "type": "IMAGE", "links": None}],
        widgets=["film/keyframe_2k"],
    ))
    g.connect(41, 0, 42, 0, "IMAGE")

    g.add(note(
        43, (880, 720), (360, 560), "⑤ 放大说明",
        "## 为什么不用 Topaz\n"
        "Topaz Photo/Video AI 是闭源付费桌面软件，"
        "这台机器是无界面容器，装不了也没授权。\n\n"
        "开源等效链路：\n"
        "`RealESRGAN 像素放大` + `分块 img2img 重绘补细节`。\n\n"
        "## 关键参数\n"
        "| 参数 | 作用 | 调法 |\n|---|---|---|\n"
        "| `upscale_by` | 放大倍数 | 2.0 起步；4.0 很慢 |\n"
        "| `denoise` | 补多少细节 | **0.15~0.3**；>0.4 会改内容 |\n"
        "| `tile_width/height` | 分块大小 | 1024；显存紧就 768 |\n"
        "| `seam_fix_mode` | 接缝修复 | `Half Tile` 通常够 |\n"
        "| `tiled_decode` | 省显存 | 大图开 |\n\n"
        "## 顺序很重要\n"
        "**先修脸再放大**：脸在小尺寸时检测更准，"
        "放大后 YOLO 反而容易漏检。\n"
        "追极限可以放大后再修一次脸。\n\n"
        "## 视频要放大？\n"
        "H3 出片后逐帧过一遍这条链路，"
        "或直接把 H3 的 `megapixels` 拉到 0.98 出原生 1344×768。",
    ))

    # ============ 5. H3 视频 ============
    h3_node = g.find(h3[104])
    h3_node["title"] = "⑥ MiniMax H3 首帧 → 带声视频"
    g.wire(4, 0, h3_node["id"], "prompt", "STRING")
    # 送修脸后的图；想省时间可以改接节点 22 的原始首帧
    g.wire(31, 0, h3_node["id"], "first_frame", "IMAGE")

    g.find(h3[6])["widgets_values"] = ["minimax_h3_fl2va_pruned_bf16.safetensors", "default"]
    g.find(h3[6])["title"] = "H3 UNET fl2va bf16"
    g.find(h3[13])["widgets_values"] = ["qwen3vl_32b_minimax_h3_bf16.safetensors", "minimax", "default"]
    g.find(h3[13])["title"] = "H3 文本编码器 Qwen3-VL"
    g.find(h3[11])["widgets_values"] = ["minimax_h3_video_vae_fp16.safetensors"]
    g.find(h3[11])["title"] = "视频 VAE"
    g.find(h3[24])["widgets_values"] = ["minimax_h3_audio_vae_fp32.safetensors"]
    g.find(h3[24])["title"] = "音频 VAE"
    g.find(h3[15])["widgets_values"] = [42, "randomize"]
    g.find(h3[15])["title"] = "视频种子"
    g.find(h3[111])["widgets_values"] = [5.0]
    g.find(h3[111])["title"] = "时长（秒）"
    g.find(h3[9])["widgets_values"] = ["simple", 20, 1]
    g.find(h3[9])["title"] = "H3 调度 / 步数"
    g.find(h3[91])["title"] = "合成 MP4（画面 + 立体声）"

    res_pos = (h3_node["pos"][0] - 540, h3_node["pos"][1] + 430)
    g.add(node(
        50, "ResolutionSelector", res_pos, (300, 170),
        title="视频画幅 16:9 · 0.98MP",
        inputs=[w_in("aspect_ratio", "COMBO"), w_in("megapixels", "FLOAT"), w_in("multiple", "INT")],
        outputs=[out("width", "INT", 0), out("height", "INT", 1)],
        widgets=["16:9 (Widescreen)", 0.98, 32],
    ))
    g.wire(50, 0, h3_node["id"], "width", "INT")
    g.wire(50, 1, h3_node["id"], "height", "INT")

    cv = g.find(h3[91])
    g.add(node(
        51, "SaveVideo", (cv["pos"][0] + 430, cv["pos"][1]), (420, 200),
        title="⑥ 保存电影片段",
        inputs=[p_in("video", "VIDEO")],
        outputs=[{"name": "video", "type": "VIDEO", "links": None}],
        widgets=["video/Film_H3", "auto", "auto"],
    ))
    g.connect(cv["id"], 0, 51, 0, "VIDEO")

    g.add(note(
        52, (h3_node["pos"][0] - 540, h3_node["pos"][1] - 340), (520, 320), "⑥ H3 说明",
        "## 输入\n"
        "- `first_frame` 接的是 **修脸后的图**（节点 ④）\n"
        "  想快点出草稿，可以改接节点 ㉒ 的原始首帧\n"
        "- `prompt` 来自 **I2VA 官方格式**润色\n\n"
        "## 速度预期（单张 PPU）\n"
        "1344×768 / 5 秒 / 20 步 ≈ **12 分钟**，约 30s/step。\n"
        "想快：降 `megapixels` 到 0.4、步数降到 12~16、时长缩到 3 秒。\n\n"
        "## 共享机注意\n"
        "H3 峰值吃 **90+GB**，跑之前先 `ppu-smi` 看有没有空卡，"
        "否则会 OOM 起不来。",
    ))

    groups = [
        {"title": "① 中文草稿 → MiniMax 官方提示词", "bounding": [-2750, -800, 2200, 780],
         "color": "#3f5159", "font_size": 24, "flags": {}},
        {"title": "② majicFlus 生成写实首帧", "bounding": [-2750, 560, 2500, 1120],
         "color": "#444a8a", "font_size": 24, "flags": {}},
        {"title": "③ 修脸 + 分块放大（Topaz 替代）", "bounding": [-40, 560, 2200, 1120],
         "color": "#3f6b4a", "font_size": 24, "flags": {}},
        {"title": "④ MiniMax H3 → 带立体声视频", "bounding": [5500, 100, 3500, 1800],
         "color": "#6b4a3f", "font_size": 24, "flags": {}},
    ]

    return {
        "id": str(uuid.uuid4()),
        "revision": 0,
        "last_node_id": max(n["id"] for n in g.nodes),
        "last_link_id": g.last_link_id,
        "nodes": g.nodes,
        "links": g.links,
        "groups": groups,
        "config": {},
        "extra": {"ds": {"scale": 0.4, "offset": [3000, 900]}},
        "version": 0.4,
    }


def main() -> int:
    wf = build()
    payload = json.dumps(wf, ensure_ascii=False, indent=2)
    for p in OUTPUTS:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(payload, encoding="utf-8")
        print(f"wrote {p}  nodes={len(wf['nodes'])} links={len(wf['links'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
