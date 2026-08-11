# 部署说明（本机约定）

## 路径约定

| 用途 | 路径 |
|---|---|
| ComfyUI 运行根目录 | `/root/ComfyUI` |
| 模型运行实体（本地盘，快） | `/root/models/...` |
| MiniMax-H3 | `/root/models/MiniMax-H3-ComfyUI` |
| Qwen3.6-35B-A3B | `/root/models/Qwen3.6-35B-A3B` |
| ossfs 备份（慢，勿直接加载） | `/workdata/ComfyUI/models_backup/...` |
| 本仓库工作流 | `workflows/*.json` |

## 服务端口

| 服务 | 端口 | 说明 |
|---|---:|---|
| ComfyUI | 8188 | WebUI + 队列 API |
| SGLang 润色 | 8030 | OpenAI 兼容接口 |

## 推荐启动顺序

1. `python scripts/sglang_start_bg.py`（润色，占 GPU 4,5）
2. `python scripts/comfyui_start_bg.py`（或前台 `comfyui_start.py`）
3. 浏览器打开 `http://<host>:8188`，导入工作流

## 显卡占用建议（8 卡）

- ComfyUI / MiniMax-H3：优先使用空闲卡；H3 BF16 显存占用高，单任务常需大显存
- 润色 SGLang：默认 `CUDA_VISIBLE_DEVICES=4,5`，`TP_SIZE=2`
- 同机若还有 Agent / VLM 等任务，请用环境变量错开卡号，避免 OOM

## 硬件摘要

- 8 × PPU-ZW810E（96GB / 卡）
- Hygon C86-4G × 2，256 逻辑线程
- ≈ 1.5 TiB 内存
- Ubuntu 24.04
