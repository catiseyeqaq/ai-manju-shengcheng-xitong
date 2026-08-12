#!/usr/bin/env python3
"""Generate the full 文字 -> 提示词 -> 生图 -> 生视频 ComfyUI workflow.

Stage 1  中文草稿 -> MiniMaxH3PromptPolish (two variants: still / shots+audio)
Stage 2  majicFlus (Flux.1-dev finetune) 出写实首帧
Stage 3  MiniMax H3 fl2va 把首帧变成带立体声的镜头

The H3 half is lifted out of the official I2V template's subgraph and flattened
so every knob is visible on one canvas.
"""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path

TEMPLATE = Path("/workdata/ComfyUI/workflows/video_minimax_h3_i2v_bf16.json")
OUTPUTS = [
    Path("/workdata/ComfyUI/workflows/film_zh2prompt_flux_h3.json"),
    Path("/root/ComfyUI/user/default/workflows/film_zh2prompt_flux_h3.json"),
]

H3_ID_OFFSET = 2000
H3_POS_SHIFT = (5200, -4200)

IMAGE_PROMPT_RULES = (
    "Output ONE single-frame photographic still description only. "
    "No timeline, no shot list, no audio. Photorealistic live-action, real human skin texture, "
    "35mm cinema lens, natural lighting, shallow depth of field. Never anime or illustration."
)
VIDEO_PROMPT_RULES = (
    "Output a cinematic shot description: scene, then timed shots with camera movement, "
    "then an Audio line covering dialogue, SFX and music. "
    "Photorealistic live-action only, never anime or illustration."
)
DRAFT_ZH = (
    "雨夜霓虹城市街道，一位三十岁东亚女性穿米色风衣撑伞走过积水路面，"
    "浅景深，35mm 胶片质感，自然皮肤纹理，电影调色。镜头缓慢跟拍她的侧脸与脚步。"
    "环境声：雨声、远处车流、低沉配乐、皮鞋踩水声。"
)


class Graph:
    def __init__(self) -> None:
        self.nodes: list[dict] = []
        self.links: list[list] = []
        self._next_link = 1

    def add(self, node: dict) -> dict:
        self.nodes.append(node)
        return node

    def find(self, node_id: int) -> dict:
        return next(n for n in self.nodes if n["id"] == node_id)

    def connect(self, src_id: int, src_slot: int, dst_id: int, dst_slot: int, type_: str) -> int:
        link_id = self._next_link
        self._next_link += 1
        self.links.append([link_id, src_id, src_slot, dst_id, dst_slot, type_])

        src = self.find(src_id)
        out = src["outputs"][src_slot]
        if out.get("links") is None:
            out["links"] = []
        out["links"].append(link_id)

        self.find(dst_id)["inputs"][dst_slot]["link"] = link_id
        return link_id

    def slot(self, node_id: int, name: str) -> int:
        return next(i for i, s in enumerate(self.find(node_id)["inputs"]) if s["name"] == name)

    @property
    def last_link_id(self) -> int:
        return self._next_link - 1


def node(
    node_id: int,
    type_: str,
    pos: tuple[int, int],
    size: tuple[int, int],
    *,
    title: str | None = None,
    inputs: list[dict] | None = None,
    outputs: list[dict] | None = None,
    widgets: list | None = None,
) -> dict:
    return {
        "id": node_id,
        "type": type_,
        "pos": list(pos),
        "size": list(size),
        "flags": {},
        "order": node_id,
        "mode": 0,
        "inputs": inputs or [],
        "outputs": outputs or [],
        "title": title or type_,
        "properties": {"Node name for S&R": type_},
        "widgets_values": widgets if widgets is not None else [],
    }


def widget_in(name: str, type_: str) -> dict:
    return {"name": name, "type": type_, "widget": {"name": name}, "link": None}


def plain_in(name: str, type_: str) -> dict:
    return {"name": name, "type": type_, "link": None}


def out(name: str, type_: str, slot: int) -> dict:
    return {"name": name, "type": type_, "links": [], "slot_index": slot}


def note(node_id: int, pos, size, title: str, text: str) -> dict:
    n = node(node_id, "MarkdownNote", pos, size, title=title, widgets=[text])
    n["properties"] = {}
    return n


def import_h3_subgraph(g: Graph) -> dict[int, int]:
    """Flatten the H3 subgraph from the official template into the top level."""
    src = json.loads(TEMPLATE.read_text())
    sub = src["definitions"]["subgraphs"][0]

    id_map: dict[int, int] = {}
    for original in sub["nodes"]:
        n = copy.deepcopy(original)
        id_map[n["id"]] = n["id"] + H3_ID_OFFSET
        n["id"] = id_map[original["id"]]
        for inp in n.get("inputs", []):
            inp["link"] = None
        for o in n.get("outputs", []):
            o["links"] = []
        pos = n.get("pos")
        if isinstance(pos, dict):
            pos = [pos.get("0", 0), pos.get("1", 0)]
        n["pos"] = [pos[0] + H3_POS_SHIFT[0], pos[1] + H3_POS_SHIFT[1]]
        g.add(n)

    for link in sub["links"]:
        if isinstance(link, dict):
            src_id, src_slot = link["origin_id"], link["origin_slot"]
            dst_id, dst_slot, type_ = link["target_id"], link["target_slot"], link["type"]
        else:
            _, src_id, src_slot, dst_id, dst_slot, type_ = link
        # Negative ids are the subgraph's own input/output proxies.
        if src_id < 0 or dst_id < 0:
            continue
        g.connect(id_map[src_id], src_slot, id_map[dst_id], dst_slot, type_)

    return id_map


def build() -> dict:
    g = Graph()
    h3 = import_h3_subgraph(g)

    # ---------- stage 1: prompt ----------
    g.add(note(
        1, (-2600, -450), (520, 620), "① 用法",
        "## 文字 → 提示词 → 生图 → 生视频\n\n"
        "1. 在 **中文分镜草稿** 里写你的镜头\n"
        "2. 两个润色节点分别产出 **静帧提示词** 和 **镜头提示词**\n"
        "3. `majicFlus` 出写实首帧（麦橘超然，亚洲人像）\n"
        "4. `MiniMax H3` 把首帧变成带立体声的视频\n\n"
        "**润色默认 bypass=true**（不依赖 8030）。\n"
        "起了 Qwen 服务后把 bypass 关掉，才会真正 中文→英文 润色。\n\n"
        "**换底座**：想用 FLUX.2 就把 UNETLoader 换成 "
        "`flux2_dev_fp8mixed`，文本编码器换 `mistral_3_small_flux2_bf16`（单 CLIPLoader），"
        "VAE 换 `flux2-vae`。",
    ))

    g.add(node(
        2, "PrimitiveStringMultiline", (-2000, -450), (460, 220),
        title="中文分镜草稿",
        outputs=[out("STRING", "STRING", 0)],
        widgets=[DRAFT_ZH],
    ))

    polish_inputs = lambda: [  # noqa: E731 - short local factory
        widget_in("prompt_zh", "STRING"),
        widget_in("base_url", "STRING"),
        widget_in("model", "STRING"),
        widget_in("temperature", "FLOAT"),
        widget_in("max_tokens", "INT"),
        widget_in("timeout_sec", "FLOAT"),
        widget_in("bypass", "BOOLEAN"),
        widget_in("extra_instructions", "STRING"),
    ]

    g.add(node(
        3, "MiniMaxH3PromptPolish", (-1460, -450), (470, 300),
        title="②a 润色 → 静帧提示词（生图用）",
        inputs=polish_inputs(),
        outputs=[out("prompt_en", "STRING", 0)],
        widgets=[DRAFT_ZH, "http://127.0.0.1:8030/v1", "qwen3.6-fast", 0.3, 500, 120.0, True, IMAGE_PROMPT_RULES],
    ))
    g.add(node(
        4, "MiniMaxH3PromptPolish", (-1460, -110), (470, 300),
        title="②b 润色 → 镜头提示词（生视频用）",
        inputs=polish_inputs(),
        outputs=[out("prompt_en", "STRING", 0)],
        widgets=[DRAFT_ZH, "http://127.0.0.1:8030/v1", "qwen3.6-fast", 0.4, 900, 120.0, True, VIDEO_PROMPT_RULES],
    ))
    g.connect(2, 0, 3, g.slot(3, "prompt_zh"), "STRING")
    g.connect(2, 0, 4, g.slot(4, "prompt_zh"), "STRING")

    g.add(node(
        5, "PreviewAny", (-940, -450), (360, 200),
        title="静帧提示词预览",
        inputs=[plain_in("source", "*")],
        outputs=[{"name": "STRING", "type": "STRING", "links": None}],
    ))
    g.add(node(
        6, "PreviewAny", (-940, -210), (360, 200),
        title="镜头提示词预览",
        inputs=[plain_in("source", "*")],
        outputs=[{"name": "STRING", "type": "STRING", "links": None}],
    ))
    g.connect(3, 0, 5, 0, "*")
    g.connect(4, 0, 6, 0, "*")

    # ---------- stage 2: majicFlus keyframe ----------
    g.add(node(
        10, "UNETLoader", (-2000, 300), (460, 100),
        title="③ 麦橘超然 majicFlus v1.34",
        inputs=[widget_in("unet_name", "COMBO"), widget_in("weight_dtype", "COMBO")],
        outputs=[out("MODEL", "MODEL", 0)],
        widgets=["majicflus_v134.safetensors", "default"],
    ))
    g.add(node(
        11, "DualCLIPLoader", (-2000, 450), (460, 130),
        title="Flux 文本编码器",
        inputs=[widget_in("clip_name1", "COMBO"), widget_in("clip_name2", "COMBO"), widget_in("type", "COMBO")],
        outputs=[out("CLIP", "CLIP", 0)],
        widgets=["clip_l.safetensors", "t5xxl_fp16.safetensors", "flux"],
    ))
    g.add(node(
        12, "VAELoader", (-2000, 630), (460, 80),
        title="Flux.1 VAE",
        inputs=[widget_in("vae_name", "COMBO")],
        outputs=[out("VAE", "VAE", 0)],
        widgets=["flux1_ae.safetensors"],
    ))

    g.add(node(
        13, "CLIPTextEncode", (-1460, 300), (440, 180),
        title="正向（来自润色）",
        inputs=[widget_in("text", "STRING"), plain_in("clip", "CLIP")],
        outputs=[out("CONDITIONING", "CONDITIONING", 0)],
        widgets=[""],
    ))
    g.connect(3, 0, 13, g.slot(13, "text"), "STRING")
    g.connect(11, 0, 13, g.slot(13, "clip"), "CLIP")

    g.add(node(
        14, "FluxGuidance", (-980, 300), (300, 60),
        title="Flux 引导强度",
        inputs=[plain_in("conditioning", "CONDITIONING"), widget_in("guidance", "FLOAT")],
        outputs=[out("CONDITIONING", "CONDITIONING", 0)],
        widgets=[3.5],
    ))
    g.connect(13, 0, 14, 0, "CONDITIONING")

    g.add(node(
        15, "BasicGuider", (-640, 300), (280, 60),
        title="引导器",
        inputs=[plain_in("model", "MODEL"), plain_in("conditioning", "CONDITIONING")],
        outputs=[out("GUIDER", "GUIDER", 0)],
    ))
    g.connect(10, 0, 15, 0, "MODEL")
    g.connect(14, 0, 15, 1, "CONDITIONING")

    g.add(node(
        16, "EmptySD3LatentImage", (-1460, 540), (300, 130),
        title="画幅（竖屏人像 832x1216）",
        inputs=[widget_in("width", "INT"), widget_in("height", "INT"), widget_in("batch_size", "INT")],
        outputs=[out("LATENT", "LATENT", 0)],
        widgets=[832, 1216, 1],
    ))
    g.add(node(
        17, "KSamplerSelect", (-1460, 720), (300, 60),
        title="采样器",
        inputs=[widget_in("sampler_name", "COMBO")],
        outputs=[out("SAMPLER", "SAMPLER", 0)],
        widgets=["euler"],
    ))
    g.add(node(
        18, "BasicScheduler", (-1460, 830), (300, 140),
        title="调度（皮肤质感 beta）",
        inputs=[plain_in("model", "MODEL"), widget_in("scheduler", "COMBO"), widget_in("steps", "INT"), widget_in("denoise", "FLOAT")],
        outputs=[out("SIGMAS", "SIGMAS", 0)],
        widgets=["beta", 28, 1.0],
    ))
    g.connect(10, 0, 18, 0, "MODEL")

    g.add(node(
        19, "RandomNoise", (-1460, 1010), (300, 90),
        title="种子",
        inputs=[widget_in("noise_seed", "INT")],
        outputs=[out("NOISE", "NOISE", 0)],
        widgets=[42, "randomize"],
    ))

    g.add(node(
        20, "SamplerCustomAdvanced", (-640, 450), (320, 180),
        title="生图采样",
        inputs=[
            plain_in("noise", "NOISE"),
            plain_in("guider", "GUIDER"),
            plain_in("sampler", "SAMPLER"),
            plain_in("sigmas", "SIGMAS"),
            plain_in("latent_image", "LATENT"),
        ],
        outputs=[out("output", "LATENT", 0), out("denoised_output", "LATENT", 1)],
    ))
    g.connect(19, 0, 20, 0, "NOISE")
    g.connect(15, 0, 20, 1, "GUIDER")
    g.connect(17, 0, 20, 2, "SAMPLER")
    g.connect(18, 0, 20, 3, "SIGMAS")
    g.connect(16, 0, 20, 4, "LATENT")

    g.add(node(
        21, "VAEDecode", (-280, 450), (260, 60),
        title="解码首帧",
        inputs=[plain_in("samples", "LATENT"), plain_in("vae", "VAE")],
        outputs=[out("IMAGE", "IMAGE", 0)],
    ))
    g.connect(20, 0, 21, 0, "LATENT")
    g.connect(12, 0, 21, 1, "VAE")

    g.add(node(
        22, "SaveImage", (60, 300), (380, 400),
        title="④ 保存定妆/首帧",
        inputs=[plain_in("images", "IMAGE"), widget_in("filename_prefix", "STRING")],
        outputs=[{"name": "images", "type": "IMAGE", "links": None}],
        widgets=["film/keyframe"],
    ))
    g.connect(21, 0, 22, 0, "IMAGE")

    g.add(note(
        23, (-2600, 300), (520, 420), "生图说明",
        "## 生图段（majicFlus 麦橘超然）\n\n"
        "- 底座 **Flux.1-dev**，作者麦橘，专长亚洲写实人像\n"
        "- 官方推荐：steps 20~30，`FluxGuidance` 3.5，"
        "皮肤质感用 `DPM2M + sgm_uniform`，通用用 `euler + simple/beta`\n"
        "- 竖屏人像 832×1216；要给 H3 当首帧时改成 16:9\n\n"
        "**首帧会直接送进右侧 H3**，不需要手动导出再上传。",
    ))

    # ---------- stage 3: H3 video ----------
    h3_node = g.find(h3[104])
    h3_node["title"] = "⑤ MiniMax H3 图生视频"
    g.connect(4, 0, h3_node["id"], g.slot(h3_node["id"], "prompt"), "STRING")
    g.connect(21, 0, h3_node["id"], g.slot(h3_node["id"], "first_frame"), "IMAGE")

    g.find(h3[6])["widgets_values"] = ["minimax_h3_fl2va_pruned_bf16.safetensors", "default"]
    g.find(h3[13])["widgets_values"] = ["qwen3vl_32b_minimax_h3_bf16.safetensors", "minimax", "default"]
    g.find(h3[11])["widgets_values"] = ["minimax_h3_video_vae_fp16.safetensors"]
    g.find(h3[24])["widgets_values"] = ["minimax_h3_audio_vae_fp32.safetensors"]
    g.find(h3[15])["widgets_values"] = [42, "randomize"]
    g.find(h3[111])["widgets_values"] = [5.0]
    g.find(h3[111])["title"] = "时长（秒）"
    g.find(h3[9])["widgets_values"] = ["simple", 20, 1]

    res_pos = (h3_node["pos"][0] - 520, h3_node["pos"][1] + 420)
    g.add(node(
        30, "ResolutionSelector", res_pos, (300, 170),
        title="视频画幅 16:9",
        inputs=[widget_in("aspect_ratio", "COMBO"), widget_in("megapixels", "FLOAT"), widget_in("multiple", "INT")],
        outputs=[out("width", "INT", 0), out("height", "INT", 1)],
        widgets=["16:9 (Widescreen)", 0.98, 32],
    ))
    g.connect(30, 0, h3_node["id"], g.slot(h3_node["id"], "width"), "INT")
    g.connect(30, 1, h3_node["id"], g.slot(h3_node["id"], "height"), "INT")

    create_video = g.find(h3[91])
    g.add(node(
        31, "SaveVideo", (create_video["pos"][0] + 420, create_video["pos"][1]), (420, 200),
        title="⑥ 保存电影片段",
        inputs=[plain_in("video", "VIDEO")],
        outputs=[{"name": "video", "type": "VIDEO", "links": None}],
        widgets=["video/Film_H3", "auto", "auto"],
    ))
    g.connect(create_video["id"], 0, 31, 0, "VIDEO")

    groups = [
        {"title": "① 中文 → 英文电影提示词", "bounding": [-2650, -540, 2160, 700], "color": "#3f5159", "font_size": 24, "flags": {}},
        {"title": "② majicFlus 生成写实首帧", "bounding": [-2650, 230, 3160, 900], "color": "#88A", "font_size": 24, "flags": {}},
        {"title": "③ MiniMax H3 首帧 → 带声视频", "bounding": [2500, 350, 3400, 1700], "color": "#8A8", "font_size": 24, "flags": {}},
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
        "extra": {"ds": {"scale": 0.45, "offset": [2900, 700]}},
        "version": 0.4,
    }


def main() -> int:
    wf = build()
    payload = json.dumps(wf, ensure_ascii=False, indent=2)
    for path in OUTPUTS:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        print(f"wrote {path}  nodes={len(wf['nodes'])} links={len(wf['links'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
