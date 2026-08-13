# 满居 ComfyUI 制片管线 · 给 GPT 的使用说明

> 环境：8×PPU（约 96GB/卡）· ComfyUI v0.31 · 主 UI `http://10.100.18.193:8188`  
> 启动：`python ComfyUI/scripts/start_studio_4gpu.py`  
> UI 工作流目录：Load → 只保留 `大师_01`～`大师_05`

---

## 0. 一张图看懂「每一步用什么」

| 步骤 | 目的 | 用哪个工作流 | 核心模型 / 节点 | 跑在哪张卡 |
|------|------|--------------|-----------------|------------|
| ① 定妆人物 | 生成女主静帧（可锁脸） | **大师_01** | majicFlus v1.34 +（可选）PuLID + FaceDetailer + RealESRGAN | GPU2/3 |
| ② 空镜场景 | 无人环境板 | **大师_02** | FLUX.2-dev fp8 + Mistral TE + flux2-vae | GPU2/3 |
| ③ 图生视频 | 两张静帧桥成一段视频 | **大师_03** | MiniMax-H3 fl2va + **Turbo LoRA 8步** | GPU0/1 |
| ④ 文生视频 | 纯文字直接出带声视频 | **大师_04** | 同上 H3 + Turbo | GPU0/1 |
| ⑤ 一条龙 | 中文草稿→润色→静帧→修脸放大→H3 | **大师_05** | ①～④ 串在一张图里 | 静帧段 GPU2/3；H3 段 GPU0/1 |

**硬限制**：H3 全局最多 **同时 2 路**（GPU0+GPU1）。不要 4 路并行 H3（会 OOM）。

---

## 1. 推荐日常用法（两条路线）

### 路线 A：分步精修（推荐给短剧/连贯镜头）

1. **大师_01** 出女主定妆图（可开 PuLID 锁同一张脸）  
2. **大师_02** 出空镜/场景板（可选）  
3. 需要「从画面 A 过渡到画面 B」→ **大师_03**（首帧+尾帧）  
4. 需要「纯文字试镜头」→ **大师_04**  
5. 多段视频用 ffmpeg 脚本拼接（已有 `beautify_merge_rain_day.py`）

### 路线 B：一条龙草稿（大师_05）

1. 只改左上角**中文分镜草稿**  
2. Qwen 润色服务就绪后，把 polish 节点 bypass 关掉  
3. **先跑到「保存定妆图」**（不要一上来就跑 H3）  
4. 满意后再放开右侧 H3（仍只占 GPU0/1）

---

## 2. 各工作流逐步说明

### 大师_01 · 文字生图（麦橘人物 + 可选 PuLID）

**用途**：写实女主定妆静帧。

| 节点区 | 用什么 | 你要改什么 |
|--------|--------|------------|
| 模型 | `majicflus_v134` + `clip_l` + `t5xxl_fp16` + `flux1_ae` | 一般不用换 |
| 可选锁脸 | PuLID-Flux + InsightFace + EVA-CLIP | 换「脸参考图」；不用就断开 ApplyPulidFlux |
| 提示词 | 正向 / 负向（已默认 20 岁中国大陆女性、简体中文招牌） | 改正向描述即可 |
| 采样 | euler + beta · 约 24 步 · FluxGuidance **3.5** | 种子可随机 |
| 修脸 | FaceDetailer + YOLO face | 远景小脸糊时再开 |
| 放大 | UltimateSDUpscale + RealESRGAN_x4 | 出定妆成片 |
| 输出 | `film/majic_t2i_*.png` | — |

**GPU**：优先 GPU2/3（:8192 / :8193）。

---

### 大师_02 · 空镜场景板（FLUX.2）

**用途**：无人中国现代城市空镜，给后续 H3 当环境板。

| 节点区 | 用什么 | 你要改什么 |
|--------|--------|------------|
| 模型 | `flux2_dev_fp8mixed` + `mistral_3_small_flux2_bf16`(type=flux2) + `flux2-vae` | 一般不用换 |
| 提示词 | 空镜正向（无人）+ 负向禁人/禁外文招牌 | 改时间/天气/街道 |
| 采样 | euler + beta · ~20 步 · Guidance 3.5 | — |
| 输出 | `film/plates_flux2_*.png` | — |

**GPU**：GPU2/3。

---

### 大师_03 · 图生视频（H3 首尾帧 + Turbo）

**用途**：I2VA——首帧过渡到尾帧，带同步音频。

| 节点区 | 用什么 | 你要改什么 |
|--------|--------|------------|
| 输入 | LoadImage ×2 | **首帧 / 尾帧** 两张图 |
| 底座 | `minimax_h3_fl2va_pruned_bf16` + Qwen3-VL TE + video/audio VAE | 勿换错 pruned |
| 加速 | **MiniMaxH3TurboLoRA**（v4 EMA pruned）+ Turbo Sampler | 默认 **8 步 · strength 1.0 · simple** |
| 核心 | `MiniMaxH3ImageToVideo` | 提示词保持身份/服化/构图连续 |
| 画幅 | 1920×1088 · length≈124（约 5s @24fps） | 可按需改时长 |
| 输出 | `video/H3_I2VA_*.mp4` | — |

**GPU**：只 GPU0（:8188）或 GPU1（:8191）。  
**调参口诀**：大动作拖影 → strength 略升到 1.05–1.2；过锐 → 略降到 0.8–0.95。勿超过 8 步太多。

---

### 大师_04 · 文生视频（H3 + Turbo）

**用途**：纯文字出带声短片（不接图）。

| 节点区 | 用什么 | 说明 |
|--------|--------|------|
| 与 03 相同底座 + Turbo | 同上 | 不接 first/last frame |
| 提示词 | 英文分镜 + soundscape + music | 按 H3 官方结构写 |
| 输出 | `video/H3_T2V_*.mp4` | — |

**GPU**：GPU0/1，规则同 03。

---

### 大师_05 · 全链路

**用途**：一张图走完「中文 → 静帧 → 修脸放大 → H3」。

| 区段 | 用什么 | 注意 |
|------|--------|------|
| ① 中文草稿 | `PrimitiveStringMultiline` | 只改这里 |
| ② 润色 | `MiniMaxH3PromptPolish` ×2（静帧提示词 + I2VA 提示词） | 需 Qwen 服务；未就绪保持 bypass |
| ③ 麦橘生图 | 同大师_01 底座 | 先出首帧 |
| ④ 修脸+放大 | FaceDetailer + USDU | 定妆级 |
| ⑤ H3 | 同大师_03（可再接 Turbo） | 最后再跑 |

**顺序铁律**：先静帧满意 → 再 H3。H3 仍只占 2 卡。

---

## 3. 角色与提示词默认约定（全项目统一）

- 人物：约 **20 岁中国大陆女性**，麦橘超然写实气质  
- 场景：中国现代城市；招牌 **仅简体中文**  
- 负向统一压制：日韩欧街景、英文/拉丁招牌、二次元等  
- H3 运镜习惯：`类型 + 幅度 + 速度`（如 tracking / small amplitude / slow speed）  
- H3 音频：`overall_soundscape` + `non_diegetic_music` 分层写

---

## 4. GPU / 端口速查

| GPU | 端口 | 角色 |
|-----|------|------|
| 0 | **8188**（浏览器打开这个） | 主 UI + H3 #1 |
| 1 | 8191 | H3 #2 |
| 2 | 8192 | 静帧（麦橘 / FLUX.2） |
| 3 | 8193 | 静帧 #2 |

启动命令：

```bash
python ComfyUI/scripts/start_studio_4gpu.py
```

浏览器：`http://10.100.18.193:8188`

---

## 5. 常见问答（给 GPT 的约束）

1. **不要**建议同时跑超过 2 路 H3。  
2. **不要**把系统 PATH 的 ffmpeg 当成一定存在；拼接用  
   `/opt/miniconda3/envs/ComfyUI/bin/ffmpeg`。  
3. H3 权重必须用 **pruned** 底座 + 对应 Turbo LoRA（已装  
   `minimax_h3_turbo_v4_step600_ema_pruned_comfyui.safetensors`）。  
4. 雨天故事现成成片（无 shot01）：  
   `ComfyUI/output/video/story_rain_day_v2/story_rain_day_v2_full.mp4`（约 35s，02–08）。  
5. 改工作流后若节点丢失：确认已用 `start_studio_4gpu.py` 重启过（Turbo 自定义节点需加载）。

---

## 6. 一句话总结

**静帧用 01/02（麦橘/FLUX.2，GPU2/3）；视频用 03/04（H3+Turbo 8步，GPU0/1）；要一条龙用 05，但先出图再出片。**
