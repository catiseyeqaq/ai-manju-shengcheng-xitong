大师工作流使用说明
==================

一、启动 4-GPU 工作室
--------------------
  python ComfyUI/scripts/start_studio_4gpu.py

  主界面: http://<主机IP>:8188


二、UI 工作流（只保留这 5 套）
----------------------------
  大师_01_文字生图_麦橘人物_PuLID.json
      麦橘人物 T2I + 可选 PuLID + 修脸 + 放大（GPU2/3）

  大师_02_场景板_FLUX2空镜.json
      FLUX.2 无人中国城市空镜（GPU2/3）

  大师_03_图生视频_H3_首尾帧.json
      H3 I2VA 首尾帧桥接 + Turbo 8步（GPU0/1）

  大师_04_文生视频_H3.json
      H3 文生视频 + Turbo 8步（GPU0/1）

  大师_05_全链路_中文润色_麦橘_修脸_放大_H3.json
      中文草稿 → 润色 → 麦橘 → 修脸放大 → H3


三、布局约定
------------
  每套工作流节点已收紧到同一视野；左上角 Markdown 注释写清用途/步骤/GPU。
  H3 默认：Turbo LoRA v4 · 8 步 · strength 1.0 · scheduler simple。


四、4-GPU 分配
--------------
  GPU0  :8188  主 UI + H3 #1
  GPU1  :8191  H3 #2
  GPU2  :8192  静帧
  GPU3  :8193  静帧 #2

  H3 并发上限 = 2（勿同时跑 4 路 H3）。
