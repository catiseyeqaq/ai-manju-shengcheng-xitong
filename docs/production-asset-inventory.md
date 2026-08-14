# 部署资产清单与产能约束（写实 AI 电影 / 短剧）

> 本文档记录本机部署的出图 / 出视频 / 辅助模型资产、自动化脚本与已验证的产能边界（路径为部署侧实际位置，公开版以占位符表示）。

## 1. 运行时基线（示例）

| 项 | 值（示例） |
|----|-----|
| GPU | 8 × PPU-ZW810E（约 96GB 显存/卡） |
| 主机内存 | 大容量（按实际 cgroup 限制配置） |
| OS | Linux（Ubuntu 24.04） |
| ComfyUI | 部署侧 `COMFYUI_ROOT`，例如 v0.31.x |
| Python | conda env（如 `ComfyUI`） |
| 权重根目录 | `MODEL_ROOT`（部署侧实际位置） |
| 业务脚本/工作流 | `WORKSPACE_ROOT/ComfyUI/scripts`、`WORKSPACE_ROOT/ComfyUI/workflows` |

**运维硬限制（示例）：** MiniMax-H3 单卡显存占用高，建议同时最多 2 路 H3，避免多卡并行视频导致 OOM；`start_h3_workers.py` 内置 RAM 守卫，默认最多 2 worker。

## 2. 出图模型（Image）

- majicFlus v1.34（麦橘 · 主用写实人物）：UNET + CLIP(t5xxl) + VAE（FLUX 套件）
- FLUX.2-dev（高光感静帧，可选）
- FLUX.1-dev 组件（给 majicFlus / Flux 管线）
- 身份锁定 / 修脸 / 放大：PuLID-Flux、InsightFace antelopev2、EVA-CLIP、facexlib、FaceDetailer、hand detector、RealESRGAN ×4、UltimateSDUpscale

## 3. 出视频模型（Video · MiniMax-H3）

- FL2VA / I2VA：文生视频 + 首帧/首尾帧图生视频（连贯短剧主路径）
- Ref2VA：多参考图生视频
- 多模态文本编码、视频 VAE、音频 VAE

**推荐成片参数（示例）：** 1920×1088，5–7s/镜，24fps，steps≈20；先 1080p 再后期拉 2K，勿原生 4K H3。

## 4. 辅助 LLM / 向量（非直接出片）

- 中文润色 / 服务 LLM（如 Qwen 系列 MoE）
- 中文 embedding 模型
- Comfy 节点 `minimax_h3_prompt_polish`：内置 MiniMax 官方 h3-prompt skill，中文 → 官方 I2VA/T2VA 三段式英文提示词。

## 5. ComfyUI 自定义节点

- ComfyUI-Impact-Pack / Impact-Subpack、ComfyUI_UltimateSDUpscale、ComfyUI-PuLID-Flux-ll、minimax_h3_prompt_polish

## 6. 工作流与自动化脚本

### 工作流 JSON

- `film_master_zh_prompt_flux_face_upscale_h3.json`：大师链
- `film_coherent_photoreal_chain.json`：连贯片注解
- `h3_text_prompt_keyframe_video_bf16.json`：电影级关键帧分镜
- `video_minimax_h3_{t2v,i2v,r2v}_bf16.json`：H3 官方模板

### 关键脚本（`scripts/film/`）

- `film_coherent_pipeline.py`、`run_story_chain_i2v.py`、`start_h3_workers.py`、`post_sync_concat.py`、`build_master_workflow.py` / `build_film_workflow.py`、`install_pulid_flux.py` / `install_quality_nodes.py`、`link_image_models.py` / `download_image_models.py`、`smoke_test_image_chain.py`、`overnight_story_monitor.py`

## 7. 已验证产能与缺口（写实短剧）

**能做：**

- 麦橘风亚洲女性静帧 + PuLID 跨镜脸锁
- 中国现代城市场景板 + 关键帧构图
- H3 带声音短镜头（I2VA 首尾帧接戏）
- FaceDetailer 减轻远景糊脸
- 后期对齐拼接；静帧/成片可冲 2K

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
成片：对齐拼接 → RealESRGAN/USDU 拉 2K
对白：短中文；环境声用 H3，必要时后期换声
```

## 9. 路径速查（占位符）

```
ComfyUI:     ${COMFYUI_ROOT}
Weights:     ${MODEL_ROOT}
Scripts:     ${WORKSPACE_ROOT}/ComfyUI/scripts
Workflows:   ${WORKSPACE_ROOT}/ComfyUI/workflows
Stills out:  ${COMFYUI_ROOT}/output/film_coherent/
Video out:   ${COMFYUI_ROOT}/output/video/
```
