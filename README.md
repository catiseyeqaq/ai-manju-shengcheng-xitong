# AI 漫剧生成系统（ComfyUI + MiniMax-H3）

面向 **AI 出图 / 出视频 / 电影级漫剧与短片生成** 的本地部署工程。基于 [ComfyUI](https://github.com/Comfy-Org/ComfyUI) 工作流框架，集成 **MiniMax-H3** 音视频联合生成模型，并配套 **Qwen3.6** 提示词润色服务，支持文生视频（T2V）、图生视频（I2V）、参考生视频（R2V）。

> 仓库定位：部署配置、模板工作流、运维脚本与项目文档。**不包含** 百 GB 级模型权重与完整 ComfyUI 上游源码（请按文档自行拉取）。

---

## 项目简介

本项目服务于「AI 漫剧 / 影视内容」生产链路：从中文创意草稿 → 英文影视级提示词 → ComfyUI 节点图推理 → 带立体声音轨的视频片段。可扩展到分镜、角色一致性、多镜头拼接等后续能力。

当前阶段已具备：

- MiniMax-H3 BF16 权重本地加载（约 129G）
- 8 套可直接导入的模板工作流（视频 T2V / I2V / R2V + 电影级关键帧/分镜/连贯片管线）
- ComfyUI `0.31.0` 一键启停脚本（含 PPU 加速参数与注意力后端切换）
- 基于 SGLang 的 Qwen3.6-35B-A3B 提示词润色自定义节点（已接入 MiniMax 官方 H3 提示词写作技能）
- 写实短剧全链：majicFlus 人物出图 + PuLID 跨镜脸锁 + FaceDetailer/USDU 画质链 + H3 首尾帧接戏 + 48k 音画对齐拼接（见 [`docs/production-asset-inventory.md`](docs/production-asset-inventory.md)）

---

## 成果展示

初稿短片《story · rain day v2》：由本系统 T2V/I2V 工作流产出的镜头素材拼接而成（含音轨）。

<video src="https://raw.githubusercontent.com/catiseyeqaq/ai-manju-shengcheng-xitong/main/showcase/story_rain_day_v2_full.mp4" controls width="100%"></video>

> 文件：[`showcase/story_rain_day_v2_full.mp4`](showcase/story_rain_day_v2_full.mp4)（约 39MB）；生成素材版权归原作者所有，未经授权不得转载或商用。

电影级关键帧（film_coherent 连贯片管线产出，同一角色跨镜头）：

| 镜头 1 · 咖啡馆外 | 镜头 4 · 超市货架 |
|:---:|:---:|
| <img src="showcase/frames/01_cafe_00001_.png" width="420" /> | <img src="showcase/frames/04_aisle_00001_.png" width="420" /> |

场景一致性底版（film_coherent 管线产出，用于多镜头场景统一）：

| 咖啡馆 | 街道 | 市场 |
|:---:|:---:|:---:|
| <img src="showcase/frames/plate_cafe.png" width="280" /> | <img src="showcase/frames/plate_street.png" width="280" /> | <img src="showcase/frames/plate_market.png" width="280" /> |

---

## 功能与作用

| 能力 | 说明 |
|---|---|
| 文生视频 T2V | 文本直接生成带音频的视频镜头 |
| 图生视频 I2V | 以首帧/尾帧图像驱动运镜与动作 |
| 参考生视频 R2V | 以参考图保持角色/产品一致性 |
| 提示词润色 | 中文草稿 → MiniMax-H3 友好英文提示（含运镜、光影、音效） |
| 音画同出 | H3 原生联合生成立体声音轨，减少后期配音成本 |
| 服务化部署 | ComfyUI（8188）+ SGLang 润色（8030）前后台启停 |

**典型用途**

- AI 漫剧 / 短剧分镜与镜头预演
- 产品广告、角色 PV、概念片快速出片
- 教学演示、内容工作室批量化素材生产
- 二次开发：对接业务 API、队列调度、多卡批处理

---

## 技术路线

```mermaid
flowchart LR
  A[中文创意 / 分镜稿] --> B[MiniMaxH3PromptPolish]
  B --> C[Qwen3.6-35B-A3B via SGLang]
  C --> D[英文影视级 Prompt]
  D --> E[ComfyUI 工作流]
  E --> F{模式}
  F -->|T2V| G[minimax_h3_fl2va]
  F -->|I2V| G
  F -->|R2V| H[minimax_h3_ref2va]
  G --> I[Video VAE + Audio VAE]
  H --> I
  I --> J[带音频的视频输出]
```

**栈摘要**

| 层级 | 选型 |
|---|---|
| 编排与 UI | ComfyUI 0.31.0（节点图 / API） |
| 视频大模型 | MiniMax-H3（fl2va / ref2va pruned BF16） |
| 文本编码 | Qwen3-VL-32B（H3 配套 text encoder） |
| 提示词 LLM | Qwen3.6-35B-A3B 全量 BF16 + SGLang（TP=2） |
| 加速硬件 | 8× PPU-ZW810E（单卡 96GB，合计约 768GB 显存） |
| 运行环境 | Ubuntu 24.04、Conda 环境 `ComfyUI`、海光 Hygon CPU |

---

## 服务器硬件配置（当前部署机）

| 项目 | 规格 |
|---|---|
| 加速卡 | **8 × PPU-ZW810E**，单卡显存 **98304 MiB（96GB）**，功耗上限约 400W |
| 显存合计 | 约 **768 GB** |
| CPU | **Hygon C86-4G (OPN:7490)** × 2 Socket，64 核/路，合计 **256 逻辑线程** |
| 内存 | 约 **1.5 TiB**（`MemTotal ≈ 1580 GB`） |
| 系统 | Ubuntu 24.04.2 LTS（x86_64） |
| 存储策略 | 运行权重在本地盘 `models`；``（ossfs）仅作持久备份 |

更完整的探测输出见 [`docs/hardware_snapshot.txt`](docs/hardware_snapshot.txt)。

> 说明：本机加速卡为国产 PPU（`nvidia-smi`/`ppu-smi` 兼容展示为 PPU-ZW810E），与常规 NVIDIA 卡在驱动与算子栈上有差异，部署时需使用适配后的 PyTorch / 启动脚本。

---

## 已部署大模型

### 1）MiniMax-H3（主推理）

| 组件 | 文件 | 约大小 |
|---|---|---:|
| Diffusion（FL2VA） | `minimax_h3_fl2va_pruned_bf16.safetensors` | 38G |
| Diffusion（Ref2VA） | `minimax_h3_ref2va_pruned_bf16.safetensors` | 38G |
| Text Encoder | `qwen3vl_32b_minimax_h3_bf16.safetensors` | 48G |
| Video VAE | `minimax_h3_video_vae_fp16.safetensors` | 4.9G |
| Audio VAE | `minimax_h3_audio_vae_fp32.safetensors` | 578M |
| **合计** | | **≈ 129G** |

- 运行路径：`models/MiniMax-H3-ComfyUI`
- 备份路径：`ComfyUI/models_backup/MiniMax-H3-ComfyUI`
- 上游参考：[MiniMaxAI/MiniMax-H3](https://huggingface.co/MiniMaxAI/MiniMax-H3)

### 2）Qwen3.6-35B-A3B（提示词润色）

| 项目 | 值 |
|---|---|
| 路径 | `models/Qwen3.6-35B-A3B` |
| 大小 | ≈ 67G（全量 BF16） |
| 服务 | SGLang，默认端口 `8030`，`TP_SIZE=2`，默认占用 GPU `4,5` |
| 对外名 | `qwen3.6-fast`（OpenAI 兼容 `/v1/chat/completions`） |

### 3）同机其他模型（非本仓库主链路，可共用）

服务器上另有 Qwen3.6-27B、Embedding、检测器等，详见机内清单；本项目主链路仅依赖 **H3 + Qwen3.6-35B-A3B**。

权重清单说明：[`docs/models.md`](docs/models.md)。

---

## ComfyUI 框架与工作流

### 框架

- ComfyUI 版本：`0.31.0`（`comfyui_version.py`）
- WebUI / API 默认：`http://0.0.0.0:8188`
- 额外模型路径：`configs/extra_model_paths.yaml`
- 自定义节点：`custom_nodes/minimax_h3_prompt_polish`（`MiniMax H3 提示词润色 (Qwen)`），内置 MiniMax 官方 H3 提示词写作技能参考（`skills/references/`），按模式（T2VA/I2VA/FL2VA/L2VA/Ref2VA）套用官方字段名、镜头标记与音频段落规范改写提示词

### 模板工作流（8 个）

| 文件 | 模式 | 用途 |
|---|---|---|
| [`workflows/video_minimax_h3_t2v_bf16.json`](workflows/video_minimax_h3_t2v_bf16.json) | Text → Video | 文生视频（BF16） |
| [`workflows/video_minimax_h3_i2v_bf16.json`](workflows/video_minimax_h3_i2v_bf16.json) | Image → Video | 图生视频（首/尾帧，BF16） |
| [`workflows/video_minimax_h3_r2v_bf16.json`](workflows/video_minimax_h3_r2v_bf16.json) | Reference → Video | 参考图一致性生成（BF16） |
| [`workflows/video_minimax_h3_t2v.json`](workflows/video_minimax_h3_t2v.json) | Text → Video | 文生视频（通用版） |
| [`workflows/h3_text_prompt_keyframe_video_bf16.json`](workflows/h3_text_prompt_keyframe_video_bf16.json) | Text → 关键帧 → Video | 电影级关键帧分镜管线 |
| [`workflows/film_zh2prompt_flux_h3.json`](workflows/film_zh2prompt_flux_h3.json) | 中文 → 提示词 → Flux 出图 | 中文草稿转影视级提示词并出图 |
| [`workflows/film_master_zh_prompt_flux_face_upscale_h3.json`](workflows/film_master_zh_prompt_flux_face_upscale_h3.json) | 出图 + 面部修复 + 放大 | 电影级母版出图（含面部修复与高清放大） |
| [`workflows/film_coherent_photoreal_chain.json`](workflows/film_coherent_photoreal_chain.json) | PuLID + 首尾帧 I2VA | 连贯片生产链注解（写实短剧主路径） |

在 ComfyUI 中：`Load` → 选择上述 JSON → 修改提示词 / 分辨率 / 上传参考图 → `Queue Prompt`。

官方模板对照：

- [I2V](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/video_minimax_h3_i2v.json)
- [T2V](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/video_minimax_h3_t2v.json)
- [R2V](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/video_minimax_h3_r2v.json)

---

## 目录结构

```text
ai-manju-shengcheng-xitong/
├── README.md
├── LICENSE
├── .gitignore
├── configs/
│   └── extra_model_paths.yaml      # MiniMax-H3 路径注册示例
├── workflows/                      # 8 套模板工作流（视频 + 电影级关键帧/连贯片）
├── showcase/                       # 成果展示（视频 + 关键帧/场景底版）
├── scripts/                        # ComfyUI / SGLang 启停与注册
│   ├── film/                       # 写实短剧自动化（人物圣经/首尾帧链/RAM守卫/48k拼接）
│   ├── comfyui_start.py
│   ├── comfyui_start_bg.py
│   ├── comfyui_stop.py
│   ├── comfyui_service.py
│   ├── sglang_start.py
│   ├── sglang_start_bg.py
│   ├── sglang_stop.py
│   ├── sglang_service.py
│   └── register_h3_models.py
├── custom_nodes/
│   └── minimax_h3_prompt_polish/   # 提示词润色节点
└── docs/
    ├── hardware_snapshot.txt
    ├── models.md
    ├── deployment.md
    └── commercial.md
```

---

## 快速开始

### 1. 准备 ComfyUI 与权重

```bash
# 拉取 ComfyUI（示例）
git clone https://github.com/Comfy-Org/ComfyUI.git
cd ComfyUI
# 按官方文档创建 conda/venv 并安装依赖（需匹配本机 PPU/CUDA 栈）

# 下载 MiniMax-H3 ComfyUI 打包权重到本地盘，例如：
# models/MiniMax-H3-ComfyUI/{diffusion_models,text_encoders,vae}/

# 复制本仓库自定义节点
cp -r custom_nodes/minimax_h3_prompt_polish /path/to/ComfyUI/custom_nodes/
```

### 2. 注册模型路径

编辑或生成 `extra_model_paths.yaml`（可参考 `configs/extra_model_paths.yaml`），保证指向本地 H3 目录，然后：

```bash
python scripts/register_h3_models.py
```

### 3. 启动润色 LLM（可选但推荐）

```bash
# 前台
python scripts/sglang_start.py
# 或后台
python scripts/sglang_start_bg.py
```

### 4. 启动 ComfyUI

```bash
python scripts/comfyui_start.py
# 浏览器打开 http://127.0.0.1:8188
```

### 5. 导入工作流并出片

加载 `workflows/video_minimax_h3_*.json`，用润色节点处理中文草稿后排队生成。

常用环境变量（可按需覆盖）：

| 变量 | 默认 | 含义 |
|---|---|---|
| `COMFYUI_ROOT` | `ComfyUI` | ComfyUI 根目录 |
| `COMFYUI_PORT` | `8188` | WebUI 端口 |
| `COMFYUI_H3_MODEL_SRC` | `models/MiniMax-H3-ComfyUI` | H3 权重 |
| `SGLANG_POLISH_PORT` | `8030` | 润色服务端口 |
| `SGLANG_POLISH_GPUS` | `4,5` | 润色占用卡 |
| `COMFYUI_LLM_BASE_URL` | `http://127.0.0.1:8030/v1` | 润色 API |

---

## 商用说明

详见 [`docs/commercial.md`](docs/commercial.md)。要点：

- **本仓库代码**：以仓库 `LICENSE` 为准（MIT），可用于二次开发与商业集成（需保留版权声明）。
- **MiniMax-H3**：遵循 MiniMax H3 Community License，商用前请阅读官方协议。
- **Qwen / 其它第三方权重**：遵循各自模型许可证与可接受使用政策。
- **内容合规**：生成内容需遵守当地法律法规与平台规范，禁止用于违法违规用途。

---

## 路线图（简）

- [x] MiniMax-H3 BF16 本地部署与三套模板工作流
- [x] Qwen 提示词润色节点 + SGLang 服务脚本
- [ ] 漫剧分镜批处理与镜头级队列
- [ ] 角色 / 场景资产库与一致性管线
- [ ] 对外 REST/队列 API 与鉴权
- [ ] 多卡并行调度与成本监控面板

---

## 作者

- GitHub：[catiseyeqaq](https://github.com/catiseyeqaq)（YuXuanLin）
- 方向：人工智能应用落地、多模态生成与行业智能系统

---

## 致谢

- [Comfy-Org/ComfyUI](https://github.com/Comfy-Org/ComfyUI)
- [MiniMaxAI/MiniMax-H3](https://huggingface.co/MiniMaxAI/MiniMax-H3)
- [Qwen](https://github.com/QwenLM) / SGLang

---

## License

本仓库文档与自研脚本默认采用 [MIT License](LICENSE)。第三方模型与上游框架版权归原作者所有。
