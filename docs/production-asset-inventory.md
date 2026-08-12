# 部署资产清单与产能约束（写实 AI 电影 / 短剧）

> 本文档记录本机部署的出图 / 出视频 / 辅助模型资产、自动化脚本与已验证的产能边界。
> 权重不随仓库分发；路径为部署侧实际位置，替换部署环境时按此结构放置即可。

## 1. 运行时基线

| 项 | 值 |
|----|-----|
| GPU | 8 × PPU-ZW810E（约 96GB 显存/卡） |
| 主机内存 | ~1.5 TiB 可见；**cgroup 常限约 632 GiB**（关键约束） |
| OS | Linux（Ubuntu 24.04） |
| ComfyUI | `/root/ComfyUI` v0.31.0 |
| Python | conda env `ComfyUI`，torch 2.10.0 |
| 关键环境变量 | `COMFY_KITCHEN_DISABLE_CUDA=1` |
| ffmpeg | conda 环境内 `ffmpeg` |
| 权重根目录 | `/root/models`（Comfy 下多为软链） |
| 业务脚本/工作流 | `/workdata/ComfyUI/scripts`、`/workdata/ComfyUI/workflows` |

**运维硬限制：** MiniMax-H3 ~1080p 单卡约 90–100GiB RSS → **同时最多 2 路 H3**，禁止 8 卡并行视频（已 OOM 验证）。`start_h3_workers.py` 内置 RAM 守卫，默认最多 2 worker。

## 2. 出图模型（Image）

### 2.1 majicFlus v1.34（麦橘 · 主用写实人物）

- UNET：`majicflus_v134.safetensors`（~11.1 GB）→ `/root/models/majicFlus-v134/`
- CLIP：`clip_l.safetensors` + `t5xxl_fp16.safetensors`（FLUX.1 套件）
- VAE：`flux1_ae.safetensors`（即 FLUX.1 `ae.safetensors`）
- **用途**：角色圣经、关键帧；指定「麦橘长相」的人物应用此栈

### 2.2 FLUX.2-dev（高光感静帧，可选）

- Unet：`flux2_dev_fp8mixed.safetensors`（~33 GB）
- TE：`mistral_3_small_flux2_bf16.safetensors`（~33 GB）
- VAE：`flux2-vae.safetensors`
- 路径：`/root/models/FLUX.2-dev-ComfyUI/`
- **用途**：光影/材质优先的空镜、场景板；人物亦可，但「麦橘脸」优先 majicFlus

### 2.3 FLUX.1-dev 组件（给 majicFlus / Flux 管线）

- `/root/models/FLUX.1-dev-ComfyUI/`：`clip_l`、`t5xxl_fp16`、`ae`

### 2.4 身份锁定 / 修脸 / 放大

| 组件 | 文件 | 作用 |
|------|------|------|
| PuLID-Flux | `pulid_flux_v0.9.1.safetensors` + 节点 `ComfyUI-PuLID-Flux-ll` | 跨镜锁同一张脸 |
| InsightFace antelopev2 | 5 × ONNX（检测/识别等） | PuLID 人脸分析 |
| EVA-CLIP | `EVA02_CLIP_L_336_psz14_s6B.pt` | PuLID 视觉编码 |
| facexlib | detection / parsing `.pth` | 人脸对齐辅助 |
| FaceDetailer | Impact Pack + `face_yolov8m.pt` | 远景小脸二次修 |
| hand detector | `hand_yolov8s.pt` | 可选手部检测 |
| RealESRGAN ×4 | `RealESRGAN_x4.pth` | 像素放大 |
| UltimateSDUpscale | 自定义节点 | 分块重绘放大到 ~2K 静帧 |

## 3. 出视频模型（Video · MiniMax-H3）

路径：`/root/models/MiniMax-H3-ComfyUI/`

| 文件 | 用途 |
|------|------|
| `minimax_h3_fl2va_pruned_bf16.safetensors`（~38 GB） | **FL2VA / I2VA**：文生视频 + 首帧/首尾帧图生视频（连贯短剧主路径） |
| `minimax_h3_ref2va_pruned_bf16.safetensors`（~38 GB） | **Ref2VA**：多参考图生视频（易漂景，连贯片慎用并行） |
| `qwen3vl_32b_minimax_h3_bf16.safetensors`（~49 GB） | H3 多模态文本编码 |
| `minimax_h3_video_vae_fp16.safetensors`（~5 GB） | 视频 VAE |
| `minimax_h3_audio_vae_fp32.safetensors`（~0.6 GB） | 音频 VAE（H3 自带环境声/对白） |

**推荐成片参数（本机）：** 1920×1088，5–7s/镜，24fps，steps≈20；先 1080p 再后期拉 2K，勿原生 4K H3。

## 4. 辅助 LLM / 向量（非直接出片）

| 模型 | 路径 | 用途 |
|------|------|------|
| Qwen3.6-27B | `/root/models/Qwen3.6-27B`（~52G） | 中文润色 / 服务（SGLang 脚本已备） |
| Qwen3.6-35B-A3B | `/root/models/Qwen3.6-35B-A3B`（~67G） | 更大 MoE 可选 |
| BAAI-bge-small-zh-v1.5 | `/root/models/BAAI-bge-small-zh-v1.5` | 中文 embedding |

Comfy 节点 **`minimax_h3_prompt_polish`**：内置 MiniMax 官方 h3-prompt skill，中文 → 官方 I2VA/T2VA 三段式英文提示词。

## 5. ComfyUI 自定义节点

- `ComfyUI-Impact-Pack` / `ComfyUI-Impact-Subpack` — FaceDetailer 等
- `ComfyUI_UltimateSDUpscale` — 分块放大
- `ComfyUI-PuLID-Flux-ll` — Flux 脸锁（已打 Comfy 0.31 API 兼容补丁）
- `minimax_h3_prompt_polish` — 官方提示词润色

## 6. 工作流与自动化脚本

### 工作流 JSON

| 文件 | 内容 |
|------|------|
| `film_master_zh_prompt_flux_face_upscale_h3.json` | **大师链**：中文 → 润色 → majicFlus → FaceDetailer → USDU → H3 |
| `film_coherent_photoreal_chain.json` | 连贯片注解：PuLID + 首尾帧 I2VA |
| `h3_text_prompt_keyframe_video_bf16.json` | 电影级关键帧分镜管线 |
| `video_minimax_h3_{t2v,i2v,r2v}_bf16.json` | H3 官方模板 |

### 关键脚本（`scripts/film/`）

| 脚本 | 作用 |
|------|------|
| `film_coherent_pipeline.py` | 角色圣经 + 场景板 + PuLID 关键帧 |
| `run_story_chain_i2v.py` | 串行/双卡 H3 首尾帧链（max 2） |
| `start_h3_workers.py` | **RAM 守卫**启 worker，默认最多 2 |
| `post_sync_concat.py` | 48kHz 音画齐帧、轻度调色、交叉淡化、合并 |
| `build_master_workflow.py` / `build_film_workflow.py` | 程序化生成大师链/电影链工作流 JSON |
| `install_pulid_flux.py` / `install_quality_nodes.py` | PuLID 与画质节点一键安装 |
| `link_image_models.py` / `download_image_models.py` | 出图模型软链 / 下载 |
| `smoke_test_image_chain.py` | 出图链冒烟测试 |
| `overnight_story_monitor.py` | 过夜批量出片监控 |

## 7. 已验证产能与缺口（写实短剧）

**能做：**

- 麦橘风亚洲女性静帧 + PuLID 跨镜脸锁
- 中国现代城市场景板 + 关键帧构图
- H3 带声音短镜头（I2VA 首尾帧接戏）
- FaceDetailer 减轻远景糊脸
- 后期 48k 对齐 + 拼接；静帧/成片可冲 2K

**弱项 / 勿承诺：**

- 完美唇形同步、多分钟单镜零闪烁
- 8 卡并行 H3
- 自动智能剪辑（仅规则化对齐拼接）
- 画面文字「永远不出现非中文」需**提示词强约束 + 人工筛镜**，模型不保证 100%

## 8. 生产模板（写实短剧新项目）

```
人物锁：majicFlus + PuLID（角色圣经 4–8 张）
场景锁：现代城市空镜板（按项目约束配置地域锁定负向词）
镜头：5–7s @1920×1088 I2VA 首尾帧桥接，≤2 GPU
成片：48k 对齐拼接 → RealESRGAN/USDU 拉 2K
对白：短中文；环境声用 H3，必要时后期换声
```

## 9. 路径速查

```
ComfyUI:     /root/ComfyUI
Weights:     /root/models
Scripts:     /workdata/ComfyUI/scripts
Workflows:   /workdata/ComfyUI/workflows
Stills out:  /root/ComfyUI/output/film_coherent/
Video out:   /root/ComfyUI/output/video/
```
