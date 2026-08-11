"""Polish Chinese/raw prompts into MiniMax-H3-friendly English via local OpenAI-compatible LLM."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing_extensions import override

from comfy_api.latest import ComfyExtension, io

DEFAULT_BASE_URL = os.environ.get("COMFYUI_LLM_BASE_URL", "http://127.0.0.1:8030/v1")
# GraphInsight serves full bf16 Qwen3.6-35B-A3B as qwen3.6-fast (no AWQ).
DEFAULT_MODEL = os.environ.get("COMFYUI_LLM_MODEL", "qwen3.6-fast")

SYSTEM_PROMPT = """You are a prompt engineer for MiniMax H3 (image/video/audio joint generation in ComfyUI).

Goal: rewrite the user's draft (often Chinese) into ONE high-quality English generation prompt.

Rules:
1. Output ONLY the final English prompt. No preface, markdown, titles, or Chinese unless the user explicitly requires on-screen Chinese text.
2. Preserve the user's intent, characters, product, camera moves, and mood.
3. Prefer cinematic, concrete, observable language: lighting, materials, camera, motion, environment.
4. Include native audio cues in the same prompt (SFX / ambience / speech) because H3 generates stereo audio jointly.
5. If duration or shot structure is implied, use a short chronological timeline (e.g. [0s-2s] ...).
6. For image-to-video: keep first-frame identity and do not invent conflicting outfits/products.
7. Keep it dense but readable; usually 80–220 words.
8. If the draft is already excellent English, lightly refine only (clarity + audio + motion), do not over-rewrite.
"""


def _chat_complete(base_url: str, model: str, user_text: str, temperature: float, max_tokens: int, timeout: float) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        # Qwen3.x sometimes emits thinking; ask for final answer only when supported.
        "chat_template_kwargs": {"enable_thinking": False},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    content = body["choices"][0]["message"]["content"]
    if isinstance(content, list):
        # some servers return content parts
        content = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    text = str(content).strip()
    # strip accidental thinking wrappers
    if "</think>" in text:
        text = text.split("</think>", 1)[-1].strip()
    return text


class MiniMaxH3PromptPolish(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="MiniMaxH3PromptPolish",
            display_name="MiniMax H3 提示词润色 (Qwen)",
            category="text/minimax_h3",
            description="用本机 OpenAI 兼容 LLM（Qwen3.6-35B-A3B 全量 bf16 / sglang）把中文草稿润色成 MiniMax H3 英文提示词。",
            search_aliases=["prompt polish", "润色", "qwen", "minimax prompt", "中文提示词"],
            inputs=[
                io.String.Input(
                    "prompt_zh",
                    multiline=True,
                    dynamic_prompts=True,
                    default="赛博朋克夜景，女主撑伞走过霓虹巷，镜头缓推，雨声和远处车流。",
                    tooltip="中文或中英混写草稿",
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
                io.Int.Input("max_tokens", default=700, min=64, max=4096),
                io.Float.Input("timeout_sec", default=120.0, min=5.0, max=600.0, step=1.0),
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

        user_text = f"User draft prompt:\n{raw}"
        if extra_instructions and extra_instructions.strip():
            user_text += f"\n\nExtra instructions:\n{extra_instructions.strip()}"

        try:
            polished = _chat_complete(
                base_url=base_url,
                model=model,
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
