工作流使用说明
==============

一、启动
--------
  python ComfyUI/scripts/comfyui_start.py

  主界面: http://<主机IP>:8188


二、UI 工作流（Load 这些）
--------------------------
静帧 · GPU2/3
  麦橘人物_文生图.json                 麦橘 T2I + 可选 PuLID + 修脸 + 放大
  QwenImage2512_文生图.json            本地开源 Qwen 出图
  QwenImage3_文生图_云端.json          云端 3.0（需登录 Comfy.org）
  QwenImage3_图生图_云端.json          云端 3.0 编辑

视频 · GPU0/1（H3 并发 ≤ 2）
  H3_图生视频_首尾帧.json              首尾帧桥接 + Turbo 8 步
  H3_文生视频.json                     纯文字出带声视频 + Turbo
  H3_角色写真_图生视频.json            写真静帧 I2VA，只接首帧

全链路
  全链路_中文润色_麦橘_H3.json         中文草稿 → 润色 → 麦橘 → 修脸放大 → H3


三、项目工作流
--------------
  城市雨夜漫步_图生视频_首尾帧.json     写实短剧《城市雨夜漫步》首尾帧 I2V
                                        （用法见同名说明文档）


四、约定
--------
  H3 默认：Turbo LoRA v4 · 8 步 · strength 1.0 · scheduler simple。
  写真 I2VA：只接 first_frame，跨构图不要硬接 last_frame。


五、GPU
-------
  GPU0  :8188  主 UI + H3 #1
  GPU1  :8191  H3 #2
  GPU2  :8192  静帧
  GPU3  :8193  静帧 #2
