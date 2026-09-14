# 《城市雨夜漫步》图生视频工作流使用说明

写实短剧单镜头生成链路：**首尾帧双控 I2V + MiniMax-H3 + 音画同出**。
两套用法任选：**命令行一键脚本**（推荐，稳定）或 **ComfyUI 网页工作流**（可视化调参）。

---

## 一、命令行一键脚本（推荐）

脚本：`ComfyUI/scripts/h3_i2v.py`

### 最常用三条命令

```bash
# 1) 8 步快速预览（约 5 分钟，挂 Turbo LoRA）
python ComfyUI/scripts/h3_i2v.py \
  --first 图片/我的首帧.png \
  --prompt-file 提示词.txt \
  --frames 124 --steps 8 --out test1

# 2) 32 步满血成片（约 20 分钟，画质最优，无 LoRA）
python ComfyUI/scripts/h3_i2v.py \
  --first 图片/我的首帧.png --last 图片/我的尾帧.png \
  --prompt-file 提示词.txt \
  --frames 124 --steps 32 --seed 2026091401 --out final_s01

# 3) 指定某张卡渲染（多卡并行不同镜头）
python ComfyUI/scripts/h3_i2v.py --port 8193 --first ... --out s02
```

### 参数速查

| 参数 | 说明 | 默认 |
|---|---|---|
| `--port` | 渲染卡：**8188** 主界面卡，**8191~8195** 并行卡 | 8188 |
| `--first` | 首帧图（任意尺寸，自动适配画布） | 必填 |
| `--last` | 尾帧图（可选；首尾帧双控动作终点） | 无 |
| `--prompt` / `--prompt-file` | 提示词文本 / 文件 | 二选一必填 |
| `--frames` | 帧数（24fps），**自动吸附 17k+5 网格**（5s→124，4s→107，6s→158） | 124 |
| `--steps` | **8=预览档**（自动挂 Turbo LoRA）；**32=满血成片档**（无 LoRA） | 32 |
| `--seed` | 固定种子可复现 / 换种子重摇 | 随机 |
| `--out` | 输出前缀（输出到 `ComfyUI/output/video/selfserve/`） | shot |

- 首帧图在项目任意目录都行，脚本自动拷入 ComfyUI
- 提示词按 H3 官方模板写（见下节），逐镜替换即可

---

## 二、ComfyUI 网页工作流（可视化）

文件：[`城市雨夜漫步_图生视频_首尾帧.json`](城市雨夜漫步_图生视频_首尾帧.json)

1. 启动服务：`python ComfyUI/scripts/start_h3_workers.py --max 3`（或已有 worker 在跑则跳过）
2. 浏览器打开 `http://<服务器地址>:8188`（8188 是对外主界面卡）
3. 把工作流 JSON 拖进画布（或左上角 Workflow → Open）
4. 改三个地方：
   - **LoadImage ×2**：首帧 / 尾帧（下拉选 input 里已有的图；不需要尾帧就把 `MiniMax H3 Image to Video` 节点的 `last_frame` 连线删掉）
   - **prompt 文本框**：粘贴提示词
   - **length / steps / seed**：帧数按 17k+5；**成片时 Bypass `MiniMax H3 Turbo LoRA` 节点（右键→Bypass）并把 steps 改 32**
5. Queue Prompt 运行，输出在 `ComfyUI/output/video/selfserve/`

---

## 三、档位约定（全片统一）

| 用途 | steps | LoRA | 单镜耗时（热机） |
|---|---|---|---|
| 选种子 / 调动作 | 8 | 8 步 Turbo 自动挂 | ~5 分钟 |
| **最终成片** | **32** | **无（满血）** | ~20 分钟 |

## 四、提示词模板（必须遵守）

按 H3 官方模板写：

```
For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.

integrated_multimodal_description: [Shot 1] Live-action cinematic ... (动作按时间写：At 00:01.500 ... From 00:02.000 to 00:04.400 ...)

overall_soundscape: (环境声)

non_diegetic_music: (配乐)
```

## 五、常见问题

- **帧数报错**：帧数必须是 17k+5（5/22/39/56/73/90/107/124/141/158…），脚本会自动吸附
- **卡住了不动**：查 `http://127.0.0.1:端口/queue`；或换一个端口卡
- **显存 / 内存**：同时渲染不要超过 6 个任务（内存护栏），大分辨率（1664×704 及以上）建议 ≤4 并发
- **成片画质发肉**：确认 steps=32 且没有挂 LoRA
