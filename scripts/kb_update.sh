#!/bin/bash
# 知识库自动更新：增量抓取 9 个频道最近视频字幕 → 入库 ChromaDB
# 由 launchd 每周触发（com.xingguo.fg-kb-update）
LOG="/tmp/fg_kb_update.log"
REPO="/Users/xingguo/learning_backtrader"
PY="$REPO/.venv/bin/yt-dlp"
PROXY="http://127.0.0.1:7890"
OUT="$REPO/Data/kb/subtitles"
echo "==== kb update $(date '+%F %T') ====" >> "$LOG"

cd "$REPO" || exit 1

# 1. 各频道最近 10 个视频 ID
declare -a PAIRS
PAIRS=(
  "Duomo|https://www.youtube.com/@Duomoinitiative/videos"
  "SecretMindset|https://www.youtube.com/@TheSecretMindset/videos"
  "TradingChannel|https://www.youtube.com/@thetradingchannel/videos"
  "RaynerTeo|https://www.youtube.com/@tradingwithrayner/videos"
  "ChatWithTraders|https://www.youtube.com/@ChatWithTradersPodcast/videos"
  "PBoyle|https://www.youtube.com/@PBoyle/videos"
  "BenFelix|https://www.youtube.com/@BenFelixCSI/videos"
  "ThePlainBagel|https://www.youtube.com/@ThePlainBagel/videos"
  "QuantPy|https://www.youtube.com/@QuantPy/videos"
)

# 2. 抓取缺失字幕（幂等）
for pair in "${PAIRS[@]}"; do
  url="${pair#*|}"
  ids=$($PY --proxy "$PROXY" --flat-playlist --print "%(id)s" --playlist-end 10 "$url" 2>/dev/null)
  for id in $ids; do
    if ls "$OUT/$id.en.vtt" "$OUT/$id.en-orig.vtt" >/dev/null 2>&1; then
      continue
    fi
    $PY --proxy "$PROXY" --skip-download --write-auto-subs --sub-langs "en.*" \
        --sub-format vtt -o "$OUT/%(id)s" "https://www.youtube.com/watch?v=$id" \
        >> "$LOG" 2>&1
    sleep 1
  done
done

# 3. 增量入库（幂等，已入库自动跳过）
"$REPO/.venv/bin/python" "$REPO/scripts/kb_build.py" >> "$LOG" 2>&1

echo "done $(date '+%F %T')" >> "$LOG"
