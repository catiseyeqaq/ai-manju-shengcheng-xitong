#!/usr/bin/env python3
"""Build the studio UI workflow set (麦橘 / FLUX.2 / H3) into both workflow dirs.

Adapts existing film_master / H3 i2v-t2v / coherent-pipeline patterns.
"""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path

WORK = Path("/workdata/ComfyUI/workflows")
USER = Path("/root/ComfyUI/user/default/workflows")
I2V_TMPL = WORK / "video_minimax_h3_i2v_bf16.json"
T2V_TMPL = WORK / "video_minimax_h3_t2v_bf16.json"
MASTER_SRC = WORK / "film_master_zh_prompt_flux_face_upscale_h3.json"

# H3 Turbo (pruned): author sweet-spot v4 EMA @ 8 steps / strength 1.0
# Alternate: minimax_h3_fl2v_turbo_8step_v1.0_comfyui_resized_avg_rank_21_bf16.safetensors
H3_TURBO_LORA = "minimax_h3_turbo_v4_step600_ema_pruned_comfyui.safetensors"
H3_TURBO_STEPS = 8
H3_TURBO_STRENGTH = 1.0

CHAR_PROMPT = (
    "photorealistic live-action, majicFlus look, a 20-year-old Chinese mainland woman, "
    "long dark slightly wavy hair, soft youthful features, subtle freckles, "
    "realistic eyes with catchlights, contemporary Chinese casual fashion, "
    "standing on a modern Chinese mainland city street at golden hour, "
    "high-rises and shop fronts with Simplified Chinese characters only on any signs, "
    "natural skin texture, 35mm film, shallow depth of field, medium shot, face sharp"
)

NEG_PROMPT = (
    "blurry, out of focus, low resolution, plastic skin, waxy skin, airbrushed, "
    "deformed face, extra fingers, bad anatomy, anime, illustration, 3d render, "
    "oversaturated, watermark, text overlay, "
    "japanese shrine, torii, sakura festival, tokyo street, korean hangul signage, "
    "seoul street, english billboard, latin alphabet storefront, europe architecture, "
    "western downtown, japanese convenience store branding"
)

PLATE_PROMPT = (
    "photorealistic empty establishing plate, modern Chinese mainland city street at dusk, "
    "high-rise and shop fronts with Simplified Chinese characters only, wet pavement optional, "
    "volumetric light, cinematic grading, no people, no faces, no cars in foreground, wide shot"
)

DRAFT_ZH = (
    "中国大陆现代城市黄昏街道，一位二十岁中国大陆女性，麦橘超然写实气质，"
    "长发微卷，当代中式休闲穿搭，走过带简体中文招牌的商铺。浅景深，35mm 胶片质感，"
    "自然皮肤纹理。镜头缓慢跟拍她的侧脸与脚步。环境声：城市车流与人声；配乐轻柔。"
)

I2VA_PROMPT = (
    "I2VA continuity bridge. Keep identity, wardrobe, face, and framing consistent with "
    "<Picture 1> (first frame) and land cleanly on <Picture 2> (last frame). "
    "Photoreal live-action, 20-year-old Chinese mainland woman, majicFlus look, "
    "modern Chinese city, Simplified Chinese signs only. "
    "Camera: gentle tracking shot with small amplitude at slow speed. "
    "Audio: soft city ambience, footsteps, low non-diegetic score. "
    "No Japanese/Korean/European signage, no English billboards, no anime."
)

T2V_PROMPT = (
    "Realistic live-action cinematic look. A 20-year-old Chinese mainland woman in "
    "contemporary casual fashion walks through a modern Chinese city at dusk; "
    "shop signs use Simplified Chinese only. majicFlus photoreal beauty, natural skin, "
    "35mm film grain, shallow depth of field.\n\n"
    "[Shot 1] Medium tracking shot follows her along the sidewalk, soft golden hour light.\n"
    "[Shot 2] At 00:02.000, slight push-in with small amplitude at slow speed toward her face.\n"
    "[Shot 3] At 00:03.500, wider establishing of Chinese high-rises behind her, she keeps walking.\n\n"
    "overall_soundscape: city traffic, distant voices, footsteps on pavement.\n"
    "non_diegetic_music: soft warm underscore, low volume.\n"
    "No Japanese/Korean/European architecture, no English billboards, no anime or CG look."
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


def p_in(name, type_, *, shape=None):
    d = {"name": name, "type": type_, "link": None}
    if shape is not None:
        d["shape"] = shape
    return d


def out(name, type_, slot):
    return {"name": name, "type": type_, "links": [], "slot_index": slot}


def note(nid, pos, size, title, text) -> dict:
    n = node(nid, "MarkdownNote", pos, size, title=title, widgets=[text])
    n["properties"] = {}
    return n


def pack(g: Graph, groups: list[dict], *, scale=0.55, offset=None) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "revision": 0,
        "last_node_id": max(n["id"] for n in g.nodes),
        "last_link_id": g.last_link_id,
        "nodes": g.nodes,
        "links": g.links,
        "groups": groups,
        "config": {},
        "extra": {"ds": {"scale": scale, "offset": offset or [0, 0]}},
        "version": 0.4,
    }


def _pos(n: dict) -> list[float]:
    p = n.get("pos")
    if isinstance(p, dict):
        return [float(p.get("0", 0)), float(p.get("1", 0))]
    return [float(p[0]), float(p[1])]


def shift_nodes(nodes: list[dict], dx: float, dy: float) -> None:
    for n in nodes:
        p = _pos(n)
        n["pos"] = [p[0] + dx, p[1] + dy]


def bring_cluster(nodes: list[dict], origin: tuple[float, float]) -> None:
    """Translate cluster so its top-left sits at origin."""
    if not nodes:
        return
    xs = [_pos(n)[0] for n in nodes]
    ys = [_pos(n)[1] for n in nodes]
    shift_nodes(nodes, origin[0] - min(xs), origin[1] - min(ys))


def group_around(nodes: list[dict], title: str, color: str, pad: float = 40) -> dict:
    xs = [_pos(n)[0] for n in nodes]
    ys = [_pos(n)[1] for n in nodes]
    # rough size estimate from node size fields
    max_r = max(_pos(n)[0] + (n.get("size") or [300, 100])[0] for n in nodes)
    max_b = max(_pos(n)[1] + (n.get("size") or [300, 100])[1] for n in nodes)
    x0, y0 = min(xs) - pad, min(ys) - pad - 36
    return {
        "title": title,
        "bounding": [x0, y0, max_r - x0 + pad, max_b - y0 + pad],
        "color": color,
        "font_size": 20,
        "flags": {},
    }


def write_both(name: str, wf: dict) -> list[Path]:
    payload = json.dumps(wf, ensure_ascii=False, indent=2)
    paths = []
    for root in (WORK, USER):
        root.mkdir(parents=True, exist_ok=True)
        p = root / name
        p.write_text(payload, encoding="utf-8")
        paths.append(p)
        print(f"wrote {p}  nodes={len(wf['nodes'])} links={len(wf['links'])}")
    return paths


def import_h3_flat(g: Graph, tmpl: Path, id_offset: int = 0, pos_shift=(0, 0)) -> dict[int, int]:
    src = json.loads(tmpl.read_text())
    sub = src["definitions"]["subgraphs"][0]
    id_map: dict[int, int] = {}
    for original in sub["nodes"]:
        n = copy.deepcopy(original)
        new_id = n["id"] + id_offset
        id_map[n["id"]] = new_id
        n["id"] = new_id
        for i in n.get("inputs", []):
            i["link"] = None
        for o in n.get("outputs", []):
            o["links"] = []
        pos = n.get("pos")
        if isinstance(pos, dict):
            pos = [pos.get("0", 0), pos.get("1", 0)]
        n["pos"] = [pos[0] + pos_shift[0], pos[1] + pos_shift[1]]
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


def _unlink_model_outs(g: Graph, src_id: int) -> list[tuple[int, int]]:
    """Remove all MODEL outbound links from src; return list of (dst_id, dst_slot)."""
    consumers: list[tuple[int, int]] = []
    keep: list[list] = []
    drop_ids: set[int] = set()
    for link in g.links:
        lid, s, ss, t, ts, ty = link
        if s == src_id and ty == "MODEL":
            consumers.append((t, ts))
            drop_ids.add(lid)
            g.find(t)["inputs"][ts]["link"] = None
        else:
            keep.append(link)
    g.links = keep
    out0 = g.find(src_id)["outputs"][0]
    out0["links"] = [lid for lid in (out0.get("links") or []) if lid not in drop_ids]
    return consumers


def inject_h3_turbo(g: Graph, h3: dict[int, int], *, lora_node_id: int) -> None:
    """UNET → MiniMaxH3TurboLoRA → BasicGuider/BasicScheduler; Turbo Sampler; 8 steps."""
    unet_id = h3[6]
    sched_id = h3[9]
    ksel_id = h3[17]
    unet = g.find(unet_id)
    ux, uy = unet["pos"]

    consumers = _unlink_model_outs(g, unet_id)

    g.add(node(
        lora_node_id, "MiniMaxH3TurboLoRA", (ux + 480, uy), (420, 150),
        title="H3 Turbo LoRA · pruned v4 · 8步 · strength 1.0",
        inputs=[
            p_in("model", "MODEL"),
            w_in("lora_name", "COMBO"),
            w_in("strength", "FLOAT"),
            w_in("low_vram", "BOOLEAN"),
        ],
        outputs=[out("MODEL", "MODEL", 0)],
        widgets=[H3_TURBO_LORA, H3_TURBO_STRENGTH, False],
    ))
    g.wire(unet_id, 0, lora_node_id, "model", "MODEL")
    for dst, slot in consumers:
        g.connect(lora_node_id, 0, dst, slot, "MODEL")

    g.find(sched_id)["widgets_values"] = ["simple", H3_TURBO_STEPS, 1]
    g.find(sched_id)["title"] = f"BasicScheduler · Turbo {H3_TURBO_STEPS}步"

    ksel = g.find(ksel_id)
    ksel["type"] = "MiniMaxH3TurboSampler"
    ksel["title"] = "MiniMax-H3 Turbo Sampler"
    ksel["properties"] = {"Node name for S&R": "MiniMaxH3TurboSampler"}
    ksel["widgets_values"] = []
    ksel["inputs"] = []


# ---------------------------------------------------------------------------
# A) 文字生图 麦橘 + 可选 PuLID + 修脸放大
# ---------------------------------------------------------------------------
def build_01_t2i() -> dict:
    g = Graph()
    g.add(note(
        1, (20, -360), (420, 320), "① 用法说明",
        "# 麦橘人物 · 文生图\n\n"
        "**链路**：模型 →（可选锁脸）→ 采样 → 修脸 → 放大 → 保存\n\n"
        "- 底座：`majicflus_v134` + `clip_l` + `t5xxl_fp16` + `flux1_ae`\n"
        "- **PuLID 可选**：换左下角脸参考图；不用则断开 ApplyPulidFlux，把 UNET 直连引导器\n"
        "- 角色默认：20 岁中国大陆女性、麦橘气质、简体中文招牌\n"
        "- 建议跑在 **GPU2 / GPU3** 静帧 worker",
    ))

    g.add(node(
        10, "UNETLoader", (20, 0), (360, 90),
        title="麦橘 majicFlus v1.34",
        inputs=[w_in("unet_name", "COMBO"), w_in("weight_dtype", "COMBO")],
        outputs=[out("MODEL", "MODEL", 0)],
        widgets=["majicflus_v134.safetensors", "default"],
    ))
    g.add(node(
        11, "DualCLIPLoader", (20, 110), (360, 110),
        title="Flux CLIP (clip_l + t5)",
        inputs=[w_in("clip_name1", "COMBO"), w_in("clip_name2", "COMBO"), w_in("type", "COMBO")],
        outputs=[out("CLIP", "CLIP", 0)],
        widgets=["clip_l.safetensors", "t5xxl_fp16.safetensors", "flux"],
    ))
    g.add(node(
        12, "VAELoader", (20, 250), (360, 70),
        title="Flux.1 VAE",
        inputs=[w_in("vae_name", "COMBO")],
        outputs=[out("VAE", "VAE", 0)],
        widgets=["flux1_ae.safetensors"],
    ))

    # Optional PuLID
    g.add(node(
        50, "PulidFluxModelLoader", (20, 360), (360, 70),
        title="PuLID 模型（可选）",
        inputs=[w_in("pulid_file", "COMBO")],
        outputs=[out("PULIDFLUX", "PULIDFLUX", 0)],
        widgets=["pulid_flux_v0.9.1.safetensors"],
    ))
    g.add(node(
        51, "PulidFluxInsightFaceLoader", (20, 450), (360, 70),
        title="InsightFace",
        inputs=[w_in("provider", "COMBO")],
        outputs=[out("FACEANALYSIS", "FACEANALYSIS", 0)],
        widgets=["CPU"],
    ))
    g.add(node(
        52, "PulidFluxEvaClipLoader", (20, 540), (360, 50),
        title="EVA-CLIP",
        inputs=[],
        outputs=[out("EVA_CLIP", "EVA_CLIP", 0)],
        widgets=[],
    ))
    g.add(node(
        53, "LoadImage", (20, 620), (340, 280),
        title="脸参考图（PuLID）",
        inputs=[],
        outputs=[out("IMAGE", "IMAGE", 0), out("MASK", "MASK", 1)],
        widgets=["example.png", "image"],
    ))
    g.add(node(
        54, "ApplyPulidFlux", (420, 360), (360, 200),
        title="ApplyPulidFlux（可选锁脸）",
        inputs=[
            p_in("model", "MODEL"), p_in("pulid_flux", "PULIDFLUX"),
            p_in("eva_clip", "EVA_CLIP"), p_in("face_analysis", "FACEANALYSIS"),
            p_in("image", "IMAGE"),
            w_in("weight", "FLOAT"), w_in("start_at", "FLOAT"), w_in("end_at", "FLOAT"),
        ],
        outputs=[out("MODEL", "MODEL", 0)],
        widgets=[0.85, 0.0, 1.0],
    ))
    g.wire(10, 0, 54, "model", "MODEL")
    g.wire(50, 0, 54, "pulid_flux", "PULIDFLUX")
    g.wire(52, 0, 54, "eva_clip", "EVA_CLIP")
    g.wire(51, 0, 54, "face_analysis", "FACEANALYSIS")
    g.wire(53, 0, 54, "image", "IMAGE")

    g.add(node(
        13, "CLIPTextEncode", (420, 0), (380, 180),
        title="正向提示词",
        inputs=[w_in("text", "STRING"), p_in("clip", "CLIP")],
        outputs=[out("CONDITIONING", "CONDITIONING", 0)],
        widgets=[CHAR_PROMPT],
    ))
    g.wire(11, 0, 13, "clip", "CLIP")
    g.add(node(
        14, "CLIPTextEncode", (420, 200), (380, 140),
        title="负向（日韩欧/英文招牌）",
        inputs=[w_in("text", "STRING"), p_in("clip", "CLIP")],
        outputs=[out("CONDITIONING", "CONDITIONING", 0)],
        widgets=[NEG_PROMPT],
    ))
    g.wire(11, 0, 14, "clip", "CLIP")
    g.add(node(
        15, "FluxGuidance", (840, 0), (240, 60),
        title="FluxGuidance 3.5",
        inputs=[p_in("conditioning", "CONDITIONING"), w_in("guidance", "FLOAT")],
        outputs=[out("CONDITIONING", "CONDITIONING", 0)],
        widgets=[3.5],
    ))
    g.connect(13, 0, 15, 0, "CONDITIONING")

    g.add(node(
        16, "BasicGuider", (1120, 0), (240, 60),
        title="引导器",
        inputs=[p_in("model", "MODEL"), p_in("conditioning", "CONDITIONING")],
        outputs=[out("GUIDER", "GUIDER", 0)],
    ))
    g.connect(54, 0, 16, 0, "MODEL")
    g.connect(15, 0, 16, 1, "CONDITIONING")

    g.add(node(
        17, "EmptySD3LatentImage", (840, 100), (240, 100),
        title="画幅 1280×768",
        inputs=[w_in("width", "INT"), w_in("height", "INT"), w_in("batch_size", "INT")],
        outputs=[out("LATENT", "LATENT", 0)],
        widgets=[1280, 768, 1],
    ))
    g.add(node(
        18, "KSamplerSelect", (840, 230), (240, 60),
        title="采样器 euler",
        inputs=[w_in("sampler_name", "COMBO")],
        outputs=[out("SAMPLER", "SAMPLER", 0)],
        widgets=["euler"],
    ))
    g.add(node(
        19, "BasicScheduler", (840, 320), (240, 110),
        title="调度 beta / 24 步",
        inputs=[p_in("model", "MODEL"), w_in("scheduler", "COMBO"), w_in("steps", "INT"), w_in("denoise", "FLOAT")],
        outputs=[out("SIGMAS", "SIGMAS", 0)],
        widgets=["beta", 24, 1.0],
    ))
    g.connect(54, 0, 19, 0, "MODEL")
    g.add(node(
        20, "RandomNoise", (840, 460), (240, 80),
        title="种子",
        inputs=[w_in("noise_seed", "INT")],
        outputs=[out("NOISE", "NOISE", 0)],
        widgets=[20260812, "randomize"],
    ))
    g.add(node(
        21, "SamplerCustomAdvanced", (1120, 100), (280, 140),
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
        22, "VAEDecode", (1440, 100), (220, 60),
        title="解码",
        inputs=[p_in("samples", "LATENT"), p_in("vae", "VAE")],
        outputs=[out("IMAGE", "IMAGE", 0)],
    ))
    g.connect(21, 0, 22, 0, "LATENT")
    g.connect(12, 0, 22, 1, "VAE")
    g.add(node(
        23, "PreviewImage", (1440, 190), (260, 240),
        title="原始预览",
        inputs=[p_in("images", "IMAGE")],
    ))
    g.connect(22, 0, 23, 0, "IMAGE")

    # FaceDetailer
    g.add(node(
        30, "UltralyticsDetectorProvider", (1740, 0), (300, 70),
        title="人脸检测 YOLOv8m",
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
        31, "FaceDetailer", (2080, 0), (360, 620),
        title="FaceDetailer 修脸",
        inputs=face_inputs,
        outputs=[
            out("image", "IMAGE", 0), out("cropped_refined", "IMAGE", 1),
            out("cropped_enhanced_alpha", "IMAGE", 2), out("mask", "MASK", 3),
            out("detailer_pipe", "DETAILER_PIPE", 4), out("cnet_images", "IMAGE", 5),
        ],
        widgets=[
            1024, True, 1536, 42, "randomize", 25, 1.0, "euler", "beta",
            0.4, 8, True, True, 0.4, 10, 3.0,
            "center-1", 0, 0.93, 0, 0.7, "False", 10,
            "sharp detailed face, natural skin pores and texture, catchlight in the eyes",
            1,
        ],
    ))
    g.wire(22, 0, 31, "image", "IMAGE")
    g.wire(54, 0, 31, "model", "MODEL")
    g.wire(11, 0, 31, "clip", "CLIP")
    g.wire(12, 0, 31, "vae", "VAE")
    g.wire(15, 0, 31, "positive", "CONDITIONING")
    g.wire(14, 0, 31, "negative", "CONDITIONING")
    g.wire(30, 0, 31, "bbox_detector", "BBOX_DETECTOR")

    g.add(node(
        40, "UpscaleModelLoader", (2480, 0), (280, 60),
        title="RealESRGAN_x4",
        inputs=[w_in("model_name", "COMBO")],
        outputs=[out("UPSCALE_MODEL", "UPSCALE_MODEL", 0)],
        widgets=["RealESRGAN_x4.pth"],
    ))
    g.add(node(
        41, "UltimateSDUpscale", (2800, 0), (360, 580),
        title="UltimateSDUpscale 放大",
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
            1.5, 42, "randomize", 18, 1.0, "euler", "beta", 0.22,
            "Linear", 1024, 1024, 8, 32, "Half Tile", 1.0, 64, 8, 16, True, True, 1,
        ],
    ))
    g.wire(31, 0, 41, "image", "IMAGE")
    g.wire(54, 0, 41, "model", "MODEL")
    g.wire(15, 0, 41, "positive", "CONDITIONING")
    g.wire(14, 0, 41, "negative", "CONDITIONING")
    g.wire(12, 0, 41, "vae", "VAE")
    g.wire(40, 0, 41, "upscale_model", "UPSCALE_MODEL")

    g.add(node(
        42, "SaveImage", (3200, 0), (320, 300),
        title="保存定妆图",
        inputs=[p_in("images", "IMAGE"), w_in("filename_prefix", "STRING")],
        outputs=[{"name": "images", "type": "IMAGE", "links": None}],
        widgets=["film/majic_t2i"],
    ))
    g.connect(41, 0, 42, 0, "IMAGE")

    g1 = [g.find(i) for i in (1, 10, 11, 12, 50, 51, 52, 53, 54)]
    g2 = [g.find(i) for i in (13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23)]
    g3 = [g.find(i) for i in (30, 31, 40, 41, 42)]
    groups = [
        group_around(g1, "① 模型 + 可选 PuLID", "#3f5159"),
        group_around(g2, "② 生图采样", "#444a8a"),
        group_around(g3, "③ 修脸 + 放大", "#3f6b4a"),
    ]
    return pack(g, groups, scale=0.5, offset=[20, 80])


# ---------------------------------------------------------------------------
# B) FLUX.2 空镜场景板
# ---------------------------------------------------------------------------
def build_02_plates() -> dict:
    g = Graph()
    g.add(note(
        1, (20, -300), (380, 260), "② 用法说明",
        "# FLUX.2 · 空镜场景板\n\n"
        "**用途**：无人中国现代城市空镜，给后续 H3 当环境板。\n\n"
        "- 模型：`flux2_dev_fp8mixed` + mistral TE + `flux2-vae`\n"
        "- 提示词默认：简体中文招牌、无人、黄金时段\n"
        "- 跑在 **GPU2 / GPU3**",
    ))
    g.add(node(
        10, "UNETLoader", (20, 0), (340, 90),
        title="FLUX.2 Dev fp8mixed",
        inputs=[w_in("unet_name", "COMBO"), w_in("weight_dtype", "COMBO")],
        outputs=[out("MODEL", "MODEL", 0)],
        widgets=["flux2_dev_fp8mixed.safetensors", "default"],
    ))
    g.add(node(
        11, "CLIPLoader", (20, 110), (340, 110),
        title="FLUX.2 CLIP mistral",
        inputs=[w_in("clip_name", "COMBO"), w_in("type", "COMBO"), w_in("device", "COMBO")],
        outputs=[out("CLIP", "CLIP", 0)],
        widgets=["mistral_3_small_flux2_bf16.safetensors", "flux2", "default"],
    ))
    g.add(node(
        12, "VAELoader", (20, 250), (340, 70),
        title="FLUX.2 VAE",
        inputs=[w_in("vae_name", "COMBO")],
        outputs=[out("VAE", "VAE", 0)],
        widgets=["flux2-vae.safetensors"],
    ))
    g.add(node(
        13, "CLIPTextEncode", (400, 0), (400, 200),
        title="空镜正向",
        inputs=[w_in("text", "STRING"), p_in("clip", "CLIP")],
        outputs=[out("CONDITIONING", "CONDITIONING", 0)],
        widgets=[PLATE_PROMPT],
    ))
    g.wire(11, 0, 13, "clip", "CLIP")
    g.add(node(
        14, "CLIPTextEncode", (400, 220), (400, 140),
        title="负向（禁人/禁外文招牌）",
        inputs=[w_in("text", "STRING"), p_in("clip", "CLIP")],
        outputs=[out("CONDITIONING", "CONDITIONING", 0)],
        widgets=[NEG_PROMPT + ", people, person, crowd, face, portrait"],
    ))
    g.wire(11, 0, 14, "clip", "CLIP")
    g.add(node(
        15, "FluxGuidance", (840, 0), (240, 60),
        title="FluxGuidance 3.5",
        inputs=[p_in("conditioning", "CONDITIONING"), w_in("guidance", "FLOAT")],
        outputs=[out("CONDITIONING", "CONDITIONING", 0)],
        widgets=[3.5],
    ))
    g.connect(13, 0, 15, 0, "CONDITIONING")
    g.add(node(
        16, "BasicGuider", (1120, 0), (240, 60),
        title="引导器",
        inputs=[p_in("model", "MODEL"), p_in("conditioning", "CONDITIONING")],
        outputs=[out("GUIDER", "GUIDER", 0)],
    ))
    g.connect(10, 0, 16, 0, "MODEL")
    g.connect(15, 0, 16, 1, "CONDITIONING")
    g.add(node(
        17, "EmptySD3LatentImage", (840, 100), (240, 100),
        title="画幅 1280×768",
        inputs=[w_in("width", "INT"), w_in("height", "INT"), w_in("batch_size", "INT")],
        outputs=[out("LATENT", "LATENT", 0)],
        widgets=[1280, 768, 1],
    ))
    g.add(node(
        18, "KSamplerSelect", (840, 230), (240, 60),
        title="采样器 euler",
        inputs=[w_in("sampler_name", "COMBO")],
        outputs=[out("SAMPLER", "SAMPLER", 0)],
        widgets=["euler"],
    ))
    g.add(node(
        19, "BasicScheduler", (840, 320), (240, 110),
        title="调度 beta / 20 步",
        inputs=[p_in("model", "MODEL"), w_in("scheduler", "COMBO"), w_in("steps", "INT"), w_in("denoise", "FLOAT")],
        outputs=[out("SIGMAS", "SIGMAS", 0)],
        widgets=["beta", 20, 1.0],
    ))
    g.connect(10, 0, 19, 0, "MODEL")
    g.add(node(
        20, "RandomNoise", (840, 460), (240, 80),
        title="种子",
        inputs=[w_in("noise_seed", "INT")],
        outputs=[out("NOISE", "NOISE", 0)],
        widgets=[20260812, "randomize"],
    ))
    g.add(node(
        21, "SamplerCustomAdvanced", (1120, 100), (280, 140),
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
        22, "VAEDecode", (1440, 100), (220, 60),
        title="解码",
        inputs=[p_in("samples", "LATENT"), p_in("vae", "VAE")],
        outputs=[out("IMAGE", "IMAGE", 0)],
    ))
    g.connect(21, 0, 22, 0, "LATENT")
    g.connect(12, 0, 22, 1, "VAE")
    g.add(node(
        23, "SaveImage", (1700, 60), (320, 300),
        title="保存空镜场景板",
        inputs=[p_in("images", "IMAGE"), w_in("filename_prefix", "STRING")],
        outputs=[{"name": "images", "type": "IMAGE", "links": None}],
        widgets=["film/plates_flux2"],
    ))
    g.connect(22, 0, 23, 0, "IMAGE")
    groups = [group_around(g.nodes, "FLUX.2 空镜场景板", "#445566")]
    return pack(g, groups, scale=0.55, offset=[20, 80])


# ---------------------------------------------------------------------------
# C) H3 图生视频 首尾帧
# ---------------------------------------------------------------------------
NOTE_03 = (
    "# H3 · 图生视频（首尾帧 + Turbo）\n\n"
    "**用途**：用两张静帧桥接一段连贯视频（I2VA）。\n\n"
    "**怎么用**\n"
    "1. 左栏换上 **首帧 / 尾帧** 图\n"
    "2. 核对中间 `MiniMaxH3ImageToVideo` 提示词（身份/服化/构图连续）\n"
    "3. 默认 **Turbo 8 步 · strength 1.0**（作者甜点）；大动作拖影可试 strength 1.05–1.2\n"
    "4. 只在 **GPU0 / GPU1** 跑；全局 H3 并发 ≤ 2\n\n"
    "**默认画幅**：1920×1088 · length≈124（~5s @24fps）\n\n"
    "**LoRA**：`minimax_h3_turbo_v4_step600_ema_pruned_comfyui`\n"
    "备选：专用 8 步 LightX2V 文件（同目录）"
)

NOTE_04 = (
    "# H3 · 文生视频（Turbo）\n\n"
    "**用途**：纯文字直接出带声视频（不接首尾帧）。\n\n"
    "**怎么用**\n"
    "1. 改 `MiniMaxH3` 节点里的英文分镜提示词\n"
    "2. 保持 **Turbo 8 步 · strength 1.0 · simple**\n"
    "3. 仅 **GPU0 或 GPU1**；勿与另一路 H3 合计超过 2\n\n"
    "**默认**：1920×1088 / length 124 / fps 24\n\n"
    "**角色默认**：20 岁中国大陆女性、麦橘气质、简体中文招牌"
)


def _title_h3_nodes(g: Graph, h3: dict[int, int]) -> None:
    mapping = {
        h3[6]: "① H3 UNET fl2va bf16",
        h3[13]: "② CLIP Qwen3-VL",
        h3[11]: "③ 视频 VAE",
        h3[24]: "④ 音频 VAE",
        h3[104]: "⑤ MiniMaxH3ImageToVideo",
        h3[15]: "⑥ 噪声种子",
        h3[16]: "⑦ BasicGuider",
        h3[17]: "⑧ Turbo Sampler",
        h3[9]: "⑨ Scheduler · Turbo 8步",
        h3[14]: "⑩ 采样 SamplerCustomAdvanced",
        h3[10]: "⑪ 视频解码 VAEDecode",
        h3[23]: "⑫ 音频解码 VAEDecodeAudio",
        h3[91]: "⑬ CreateVideo fps=24",
        h3[111]: "时长（秒）",
        h3[107]: "帧数公式 length",
    }
    for nid, title in mapping.items():
        if nid in {n["id"] for n in g.nodes}:
            g.find(nid)["title"] = title
    if any(n["id"] == 200 for n in g.nodes):
        g.find(200)["title"] = "①′ Turbo LoRA · v4 · strength 1.0"


def build_03_i2v() -> dict:
    g = Graph()
    h3 = import_h3_flat(g, I2V_TMPL, id_offset=0, pos_shift=(0, 0))
    inject_h3_turbo(g, h3, lora_node_id=200)

    g.add(note(1, (0, 0), (360, 420), "③ 用法说明", NOTE_03))
    g.add(node(
        2, "LoadImage", (0, 450), (340, 300),
        title="首帧 first_frame",
        inputs=[],
        outputs=[out("IMAGE", "IMAGE", 0), out("MASK", "MASK", 1)],
        widgets=["example.png", "image"],
    ))
    g.add(node(
        3, "LoadImage", (0, 780), (340, 300),
        title="尾帧 last_frame",
        inputs=[],
        outputs=[out("IMAGE", "IMAGE", 0), out("MASK", "MASK", 1)],
        widgets=["example.png", "image"],
    ))

    h3n = g.find(h3[104])
    h3n["widgets_values"] = [I2VA_PROMPT, 1920, 1088, 124]
    g.find(h3[6])["widgets_values"] = ["minimax_h3_fl2va_pruned_bf16.safetensors", "default"]
    g.find(h3[13])["widgets_values"] = ["qwen3vl_32b_minimax_h3_bf16.safetensors", "minimax", "default"]
    g.find(h3[11])["widgets_values"] = ["minimax_h3_video_vae_fp16.safetensors"]
    g.find(h3[24])["widgets_values"] = ["minimax_h3_audio_vae_fp32.safetensors"]
    g.find(h3[91])["widgets_values"] = [24.0, 8]
    g.find(h3[111])["widgets_values"] = [5.0]

    g.wire(2, 0, h3n["id"], "first_frame", "IMAGE")
    g.wire(3, 0, h3n["id"], "last_frame", "IMAGE")

    cv = g.find(h3[91])
    g.add(node(
        4, "SaveVideo", (0, 0), (340, 160),
        title="⑭ 保存 H3 I2VA",
        inputs=[p_in("video", "VIDEO")],
        outputs=[{"name": "video", "type": "VIDEO", "links": None}],
        widgets=["video/H3_I2VA", "auto", "auto"],
    ))
    g.connect(cv["id"], 0, 4, 0, "VIDEO")

    _title_h3_nodes(g, h3)
    # Pull H3 template nodes (exclude UI rail + SaveVideo placeholder) up from y≈4670
    h3_ids = set(h3.values()) | {200}
    pipeline = [n for n in g.nodes if n["id"] in h3_ids]
    bring_cluster(pipeline, (400, 40))
    # Park SaveVideo to the right of CreateVideo
    cv = g.find(h3[91])
    g.find(4)["pos"] = [cv["pos"][0] + 360, cv["pos"][1]]
    # Left rail stays put
    g.find(1)["pos"] = [20, 40]
    g.find(2)["pos"] = [20, 440]
    g.find(3)["pos"] = [20, 780]

    left = [g.find(1), g.find(2), g.find(3)]
    pipe = [n for n in g.nodes if n["id"] not in (1, 2, 3)]
    groups = [
        group_around(left, "① 首尾帧输入", "#3f5159"),
        group_around(pipe, "② H3 I2VA + Turbo 8步", "#6b4a3f"),
    ]
    return pack(g, groups, scale=0.55, offset=[40, 20])


# ---------------------------------------------------------------------------
# D) H3 文生视频
# ---------------------------------------------------------------------------
def build_04_t2v() -> dict:
    g = Graph()
    h3 = import_h3_flat(g, T2V_TMPL, id_offset=0, pos_shift=(0, 0))
    inject_h3_turbo(g, h3, lora_node_id=200)

    g.add(note(1, (0, 0), (360, 380), "④ 用法说明", NOTE_04))

    h3n = g.find(h3[104])
    h3n["widgets_values"] = [T2V_PROMPT, 1920, 1088, 124]
    g.find(h3[6])["widgets_values"] = ["minimax_h3_fl2va_pruned_bf16.safetensors", "default"]
    g.find(h3[13])["widgets_values"] = ["qwen3vl_32b_minimax_h3_bf16.safetensors", "minimax", "default"]
    g.find(h3[11])["widgets_values"] = ["minimax_h3_video_vae_fp16.safetensors"]
    g.find(h3[24])["widgets_values"] = ["minimax_h3_audio_vae_fp32.safetensors"]
    g.find(h3[91])["widgets_values"] = [24.0, 8]
    g.find(h3[111])["widgets_values"] = [5.0]

    cv = g.find(h3[91])
    g.add(node(
        2, "SaveVideo", (0, 0), (340, 160),
        title="⑭ 保存 H3 T2V",
        inputs=[p_in("video", "VIDEO")],
        outputs=[{"name": "video", "type": "VIDEO", "links": None}],
        widgets=["video/H3_T2V", "auto", "auto"],
    ))
    g.connect(cv["id"], 0, 2, 0, "VIDEO")

    _title_h3_nodes(g, h3)
    g.find(h3[104])["title"] = "⑤ MiniMaxH3 文生视频（无帧）"

    h3_ids = set(h3.values()) | {200}
    pipeline = [n for n in g.nodes if n["id"] in h3_ids]
    bring_cluster(pipeline, (400, 40))
    cv = g.find(h3[91])
    g.find(2)["pos"] = [cv["pos"][0] + 360, cv["pos"][1]]
    g.find(1)["pos"] = [20, 40]

    pipe = [n for n in g.nodes if n["id"] != 1]
    groups = [
        group_around([g.find(1)], "① 说明", "#3f5159"),
        group_around(pipe, "② H3 文生视频 + Turbo 8步", "#6b4a3f"),
    ]
    return pack(g, groups, scale=0.55, offset=[40, 20])


# ---------------------------------------------------------------------------
# E) 全链路：压缩现有 master（源模板已删，就地收紧）
# ---------------------------------------------------------------------------
def build_05_full_chain() -> dict:
    src = WORK / "全链路_中文润色_麦橘_H3.json"
    if not src.exists():
        src = USER / "全链路_中文润色_麦橘_H3.json"
    wf = json.loads(src.read_text(encoding="utf-8"))
    by_id = {n["id"]: n for n in wf["nodes"]}

    # 1) Normalize whole canvas to origin
    bring_cluster(wf["nodes"], (40, 40))

    # 2) Pull H3 cluster (ids>=3000 + 50/51/52) right next to stills SaveImage
    h3_nodes = [n for n in wf["nodes"] if n["id"] >= 3000 or n["id"] in (50, 51, 52)]
    still_nodes = [n for n in wf["nodes"] if n["id"] < 50 or n["id"] in (40, 41, 42, 43)]
    if h3_nodes and still_nodes:
        still_right = max(_pos(n)[0] + (n.get("size") or [300, 100])[0] for n in still_nodes)
        bring_cluster(h3_nodes, (still_right + 80, 80))

    if 1 in by_id:
        by_id[1]["title"] = "用法 · 全链路"
        by_id[1]["widgets_values"] = [
            "# 全链路 · 中文润色 → 麦橘 → H3\n\n"
            "```\n中文草稿 → 润色 → 麦橘生图 → 修脸 → 放大 → H3 视频\n```\n\n"
            "**默认角色**：20 岁中国大陆女性、麦橘气质、简体中文招牌\n\n"
            "**顺序**\n"
            "1. 只改左上角中文草稿\n"
            "2. Qwen 润色服务就绪后，把 polish 的 bypass 改 false\n"
            "3. 先跑到「保存定妆图」\n"
            "4. 再放开右侧 H3（仅 GPU0/GPU1，并发 ≤ 2）\n"
        ]
        by_id[1]["size"] = [360, 340]

    def ids(*xs):
        return [by_id[i] for i in xs if i in by_id]

    g_draft = ids(1, 2, 3, 4, 5, 6, 7)
    g_still = ids(10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24)
    g_face = ids(30, 31, 32, 33, 40, 41, 42, 43)
    wf["groups"] = [x for x in [
        group_around(g_draft, "① 中文草稿 → 官方润色", "#3f5159") if g_draft else None,
        group_around(g_still, "② 麦橘生图", "#444a8a") if g_still else None,
        group_around(g_face, "③ 修脸 + 放大", "#3f6b4a") if g_face else None,
        group_around(h3_nodes, "④ H3 视频", "#6b4a3f") if h3_nodes else None,
    ] if x]
    wf["extra"] = {"ds": {"scale": 0.42, "offset": [40, 40]}}
    wf["id"] = str(uuid.uuid4())
    return wf


def main() -> int:
    outs: list[Path] = []
    outs += write_both("麦橘人物_文生图.json", build_01_t2i())
    outs += write_both("FLUX2_空镜场景板.json", build_02_plates())
    outs += write_both("H3_图生视频_首尾帧.json", build_03_i2v())
    outs += write_both("H3_文生视频.json", build_04_t2v())
    try:
        outs += write_both("全链路_中文润色_麦橘_H3.json", build_05_full_chain())
    except Exception as e:
        print(f"skip 全链路: {e}")

    # 官方模板只留在 workdata，不进 UI
    for junk in ("video_minimax_h3_r2v_bf16.json", "video_minimax_h3_i2v_bf16.json", "video_minimax_h3_t2v_bf16.json"):
        p = USER / junk
        if p.exists():
            p.unlink()
            print(f"removed UI clutter {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
