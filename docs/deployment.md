# 部署说明（本机约定，路径请按实际环境替换）

## 路径约定（示例，替换为你的部署环境）

| 用途 | 路径（示例） |
|---|---|
| ComfyUI 运行根目录 | `${COMFYUI_ROOT}` |
| 模型运行实体（本地盘，快） | `${MODEL_ROOT}/...` |
| MiniMax-H3 | `${MODEL_ROOT}/MiniMax-H3-ComfyUI` |
| 润色 LLM | `${MODEL_ROOT}/<llm-name>` |
| 备份（对象存储 / 网络盘，勿直接加载） | `${WORKSPACE_ROOT}/ComfyUI/models_backup/...` |
| 本仓库工作流 | `workflows/*.json` |

## 服务端口（示例，可用环境变量覆盖）

| 服务 | 端口（示例） | 说明 |
|---|---:|---|
| ComfyUI | `${COMFYUI_PORT:-8188}` | WebUI + 队列 API |
| SGLang 润色 | `${SGLANG_POLISH_PORT:-8030}` | OpenAI 兼容接口 |

## 推荐启动顺序

1. `python scripts/sglang_start_bg.py`（润色，可指定 GPU）
2. `python scripts/comfyui_start_bg.py`（或前台 `comfyui_start.py`）
3. 浏览器打开 `http://<host>:${COMFYUI_PORT:-8188}`，导入工作流

## 显卡占用建议（8 卡）

- ComfyUI / MiniMax-H3：优先使用空闲卡；H3 BF16 显存占用高，单任务常需大显存
- 润色 SGLang：默认 `CUDA_VISIBLE_DEVICES` 与 `TP_SIZE` 可用环境变量配置
- 同机若还有 Agent / VLM 等任务，请用环境变量错开卡号，避免 OOM

## 硬件摘要（示例机型）

- 8 × PPU-ZW810E（96GB / 卡）
- 多路 CPU，大容量内存
- Ubuntu 24.04
