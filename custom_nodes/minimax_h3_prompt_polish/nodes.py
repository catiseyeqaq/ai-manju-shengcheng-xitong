"""Rewrite drafts into MiniMax H3 prompts using MiniMax's official prompt-writing skill.

The reference guides under ``skills/references/`` are verbatim copies of
``MiniMax-AI/MiniMax-H3 -> skills/h3-prompt-writing``. They are fed to a local
OpenAI-compatible LLM so the rewrite follows the official field names, shot
notation and audio sections instead of ad-hoc prose.
"""

from __future__ import annotations

import functools
import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path

from typing_extensions import override

from comfy_api.latest import ComfyExtension, io

DEFAULT_BASE_URL = os.environ.get("COMFYUI_LLM_BASE_URL", "http://127.0.0.1:8030/v1")
# GraphInsight serves full bf16 Qwen3.6-35B-A3B as qwen3.6-fast (no AWQ).
DEFAULT_MODEL = os.environ.get("COMFYUI_LLM_MODEL", "qwen3.6-fast")

SKILL_DIR = Path(__file__).parent / "skills" / "references"

# H3 generation modes as named by the official skill.
MODES = ["T2VA", "I2VA", "FL2VA", "L2VA", "Ref2VA", "IMAGE_STILL"]

# base-en.txt covers the four keyframe/text modes; ref-en.txt covers Ref2VA.
MODE_GUIDE = {
    "T2VA": "base-en.txt",
    "I2VA": "base-en.txt",
    "FL2VA": "base-en.txt",
    "L2VA": "base-en.txt",
    "Ref2VA": "ref-en.txt",
}

BASE_SYSTEM = """You are the H3 prompt-writing skill from MiniMax.

Rewrite the user's draft (often Chinese) into ONE MiniMax H3 prompt for mode {mode}.

Follow the official guide below EXACTLY: same field names, same section order,
same shot and timing notation, same speaker/dialogue markup.

Hard rules:
- Output ONLY the rewritten prompt. No preface, no explanation, no markdown fences.
- Write the rewrite in English. Keep dialogue, lyrics and on-screen text verbatim in
  their original language.
- The requested duration is {duration:.2f} seconds. Every cut time must fall inside it.
- Never invent unresolved reference labels.

===== OFFICIAL GUIDE ({guide_name}) =====
{guide}
"""

# Still images have no timeline or audio, so H3's video structure does not apply.
STILL_SYSTEM = """You are a prompt engineer for a photorealistic text-to-image model
(Flux / majicFlus class) that produces the FIRST FRAME of a live-action film shot.

Rewrite the user's draft (often Chinese) into ONE English still-image prompt.

Hard rules:
- Output ONLY the prompt. No preface, no explanation, no markdown, no field names.
- Describe a SINGLE frozen moment. No timeline, no shot list, no camera movement, no audio.
- Photorealistic live-action only: real human skin texture with pores, natural asymmetry,
  believable fabric and hair. Never anime, illustration, 3D render or plastic skin.
- State subject, wardrobe, expression, pose, environment, lighting direction and quality,
  lens and depth of field, and colour grade.
- Faces must be described as clearly framed and in focus so they survive downstream
  video generation.
- Usually 60-150 words, comma-separated cinematic phrasing.
"""


@functools.lru_cache(maxsize=4)
def _load_guide(name: str) -> str:
    path = SKILL_DIR / name
    if not path.exists():
        raise RuntimeError(
            f"缺少官方提示词指南 {path}. 请重新安装 skills/references/ 下的 base-en.txt 与 ref-en.txt"
        )
    return path.read_text(encoding="utf-8")


def _system_prompt(mode: str, duration: float) -> str:
    if mode == "IMAGE_STILL":
        return STILL_SYSTEM
    guide_name = MODE_GUIDE[mode]
    return BASE_SYSTEM.format(
        mode=mode,
        duration=duration,
        guide_name=guide_name,
        guide=_load_guide(guide_name),
    )


def _chat_complete(
    base_url: str,
    model: str,
    system_text: str,
    user_text: str,
    temperature: float,
    max_tokens: int,
    timeout: float,
) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ],
        # Qwen3.x sometimes emits thinking; ask for final answer only when supported.
        "chat_template_kwargs": {"enable_thinking": False},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    content = body["choices"][0]["message"]["content"]
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    text = str(content).strip()
    if "</think>" in text:
        text = text.split("</think>", 1)[-1].strip()
    # Some models wrap the answer in a fence despite instructions.
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[-1].strip().startswith("```"):
            text = "\n".join(lines[1:-1]).strip()
    return text


class MiniMaxH3PromptPolish(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="MiniMaxH3PromptPolish",
            display_name="MiniMax H3 提示词润色 (官方 skill)",
            category="text/minimax_h3",
            description=(
                "用本机 OpenAI 兼容 LLM，按 MiniMax 官方 h3-prompt-writing skill "
                "把中文草稿改写成 H3 规范提示词；IMAGE_STILL 模式产出生图用静帧提示词。"
            ),
            search_aliases=["prompt polish", "润色", "qwen", "minimax prompt", "官方提示词", "skill"],
            inputs=[
                io.String.Input(
                    "prompt_zh",
                    multiline=True,
                    dynamic_prompts=True,
                    default="雨夜霓虹街道，女主撑伞走过积水路面，镜头缓推，雨声和远处车流。",
                    tooltip="中文或中英混写草稿",
                ),
                io.Combo.Input(
                    "mode",
                    options=MODES,
                    default="I2VA",
                    tooltip=(
                        "T2VA 纯文生视频 / I2VA 首帧 / FL2VA 首尾帧 / L2VA 尾帧 / "
                        "Ref2VA 多参考 / IMAGE_STILL 生图静帧提示词"
                    ),
                ),
                io.Float.Input(
                    "duration_sec",
                    default=5.0,
                    min=1.0,
                    max=15.0,
                    step=0.5,
                    tooltip="目标时长，用于约束官方格式里的切点时间；IMAGE_STILL 模式忽略",
                ),
                io.String.Input(
                    "base_url",
                    default=DEFAULT_BASE_URL,
                    tooltip="OpenAI 兼容接口，全量 bf16 默认 http://127.0.0.1:8030/v1",
                ),
                io.String.Input(
                    "model",
                    default=DEFAULT_MODEL,
                    tooltip="served model name，当前全量 bf16 服务名为 qwen3.6-fast",
                ),
                io.Float.Input("temperature", default=0.4, min=0.0, max=1.5, step=0.05),
                io.Int.Input("max_tokens", default=1200, min=64, max=8192),
                io.Float.Input("timeout_sec", default=180.0, min=5.0, max=600.0, step=1.0),
                io.Boolean.Input(
                    "bypass",
                    default=False,
                    tooltip="开启则直接返回原文，不调用 LLM",
                ),
                io.String.Input(
                    "extra_instructions",
                    multiline=True,
                    default="",
                    optional=True,
                    tooltip="额外约束，例如必须保留品牌名/字幕文字",
                ),
            ],
            outputs=[
                io.String.Output(display_name="prompt_en"),
            ],
        )

    @classmethod
    def execute(
        cls,
        prompt_zh: str,
        mode: str,
        duration_sec: float,
        base_url: str,
        model: str,
        temperature: float,
        max_tokens: int,
        timeout_sec: float,
        bypass: bool = False,
        extra_instructions: str = "",
    ) -> io.NodeOutput:
        raw = (prompt_zh or "").strip()
        if bypass or not raw:
            return io.NodeOutput(raw)

        user_text = f"Mode: {mode}\nTarget duration: {duration_sec:.2f}s\n\nUser draft:\n{raw}"
        if extra_instructions and extra_instructions.strip():
            user_text += f"\n\nExtra instructions:\n{extra_instructions.strip()}"

        try:
            polished = _chat_complete(
                base_url=base_url,
                model=model,
                system_text=_system_prompt(mode, duration_sec),
                user_text=user_text,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout_sec,
            )
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"无法连接润色 LLM ({base_url}). 请确认 sglang 已启动且模型为 {model}. 原始错误: {e}"
            ) from e
        except Exception as e:
            raise RuntimeError(f"润色 LLM 调用失败: {type(e).__name__}: {e}") from e

        if not polished:
            logging.warning("MiniMaxH3PromptPolish got empty LLM output; falling back to raw prompt")
            polished = raw
        return io.NodeOutput(polished)


class MiniMaxH3PromptPolishExtension(ComfyExtension):
    @override
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [MiniMaxH3PromptPolish]
