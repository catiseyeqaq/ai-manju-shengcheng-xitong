#!/bin/bash
LOG=/workdata/ComfyUI/logs/asr_monitor.log
OUT=/root/ComfyUI/output/after_school_road
echo "===== ASR monitor started $(date '+%F %T') =====" | tee -a "$LOG"
while true; do
  {
    echo ""
    echo "======== $(date '+%F %T') ========"
    # queues
    for p in 8188 8191 8192 8193; do
      q=$(curl -s -m 2 "http://127.0.0.1:$p/queue" 2>/dev/null)
      if [ -n "$q" ]; then
        echo "$q" | /opt/miniconda3/envs/ComfyUI/bin/python -c "import sys,json;d=json.load(sys.stdin);print(f'  :$p  run={len(d.get(\"queue_running\")or[])} pend={len(d.get(\"queue_pending\")or[])}')" 2>/dev/null
      else
        echo "  :$p  DOWN"
      fi
    done
    # file counts
    b=$(ls "$OUT/bible"/asr_bible_*.png 2>/dev/null | wc -l)
    p=$(ls "$OUT/plates"/asr_plate_*.png 2>/dev/null | wc -l)
    k=$(ls "$OUT/keys"/asr_key_*.png 2>/dev/null | wc -l)
    c=$(ls "$OUT/clips"/*.mp4 2>/dev/null | wc -l)
    echo "  bible $b/6 | plates $p/4 | keys $k/10 | clips $c/10"
    if [ -f "$OUT/after_school_road_60s.mp4" ]; then
      ls -lh "$OUT/after_school_road_60s.mp4" | awk '{print "  FINAL",$5,$9}'
    else
      echo "  FINAL pending"
    fi
    # GPU
    nvidia-smi --query-gpu=index,utilization.gpu,memory.used --format=csv,noheader 2>/dev/null | awk -F', ' 'NR<=4{printf "  GPU%s util=%s mem=%s\n",$1,$2,$3}'
    # procs
    ps -ef | grep -E 'run_after_school_road|asr_supervisor' | grep -v grep | awk '{print "  proc",$2,$NF}' | head -6
    # latest log lines
    echo "  -- bible log --"
    tail -3 /workdata/ComfyUI/logs/asr_bible.log 2>/dev/null | sed 's/^/  /'
    echo "  -- plates log --"
    tail -2 /workdata/ComfyUI/logs/asr_plates.log 2>/dev/null | sed 's/^/  /'
    echo "  -- supervisor --"
    tail -3 /workdata/ComfyUI/logs/asr_supervisor.log 2>/dev/null | sed 's/^/  /'
  } | tee -a "$LOG"
  # stop if final exists and clips complete
  if [ -f "$OUT/after_school_road_60s.mp4" ] && [ "$(ls "$OUT/clips"/*.mp4 2>/dev/null | wc -l)" -ge 10 ]; then
    echo "===== ALL DONE $(date '+%F %T') =====" | tee -a "$LOG"
    break
  fi
  sleep 60
done
