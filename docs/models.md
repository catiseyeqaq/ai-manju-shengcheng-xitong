# MiniMax-H3 权重清单（本仓库不包含权重文件）

| 目录 | 文件 | 约大小 |
|---|---|---:|
| diffusion_models | minimax_h3_fl2va_pruned_bf16.safetensors | 38G |
| diffusion_models | minimax_h3_ref2va_pruned_bf16.safetensors | 38G |
| text_encoders | qwen3vl_32b_minimax_h3_bf16.safetensors | 48G |
| vae | minimax_h3_video_vae_fp16.safetensors | 4.9G |
| vae | minimax_h3_audio_vae_fp32.safetensors | 578M |

合计约 **129G**。运行路径：`${MODEL_ROOT}/MiniMax-H3-ComfyUI`；备份：`${WORKSPACE_ROOT}/ComfyUI/models_backup/MiniMax-H3-ComfyUI`。

## 提示词润色 LLM

| 模型 | 大小 | 用途 |
|---|---:|---|
| 中文润色 MoE（如 Qwen 系列） | ~67G | SGLang 服务，MiniMax H3 中文提示词润色 |
