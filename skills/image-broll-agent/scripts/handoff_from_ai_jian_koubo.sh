#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'TXT'
用法: handoff_from_ai_jian_koubo.sh <剪口播/3_审核> [--output DIR]
       [--profile simple|balanced|rich] [--style clean_editorial] [--open-review]

读取已导出的 FCPXML / review_log / receipt，在本地渲染干净口播、重映射火山逐字稿，
然后自动生成 B-roll 计划和可视化审核页。不会调用图片 API，也不会再次调用 ASR。
TXT
}

[[ $# -ge 1 ]] || { usage; exit 2; }
REVIEW_DIR="$1"; shift
OUTPUT_DIR=""; PROFILE="balanced"; VISUAL_STYLE="clean_editorial"; OPEN_REVIEW=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --output) OUTPUT_DIR="${2:?--output requires a directory}"; shift 2 ;;
    --profile) PROFILE="${2:?--profile requires a value}"; shift 2 ;;
    --style) VISUAL_STYLE="${2:?--style requires a value}"; shift 2 ;;
    --open-review) OPEN_REVIEW="--open-review"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "❌ 未知参数: $1" >&2; usage; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="$SKILL_DIR/.venv/bin/python"; [[ -x "$PYTHON" ]] || PYTHON="$(command -v python3)"
REVIEW_DIR="$($PYTHON -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).expanduser().resolve())' "$REVIEW_DIR")"
[[ -d "$REVIEW_DIR" ]] || { echo "❌ 审核目录不存在: $REVIEW_DIR" >&2; exit 2; }
if [[ -z "$OUTPUT_DIR" ]]; then
  OUTPUT_DIR="$($PYTHON -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).parents[1] / "B-roll")' "$REVIEW_DIR")"
fi
OUTPUT_DIR="$($PYTHON -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).expanduser().resolve())' "$OUTPUT_DIR")"
VIDEO_OUTPUT="$OUTPUT_DIR/0_干净口播/clean-cut.mp4"
WORDS_OUTPUT="$OUTPUT_DIR/1_转录/subtitles_words.json"
STATE_OUTPUT="$OUTPUT_DIR/broll-handoff-state.json"

echo "1/2 读取 A 模式正本并在本地渲染干净口播..."
"$PYTHON" "$SCRIPT_DIR/render_rough_cut.py" "$REVIEW_DIR" \
  --video-output "$VIDEO_OUTPUT" \
  --words-output "$WORDS_OUTPUT" \
  --state-output "$STATE_OUTPUT"

echo "2/2 自动生成 B-roll 方案与可视化审核页..."
bash "$SCRIPT_DIR/prepare_broll.sh" "$VIDEO_OUTPUT" \
  --output "$OUTPUT_DIR" \
  --words "$WORDS_OUTPUT" \
  --profile "$PROFILE" \
  --style "$VISUAL_STYLE" \
  $OPEN_REVIEW

echo "✅ AI剪口播 → B-roll 默认交接完成"
echo "审核页: $OUTPUT_DIR/2_B-roll方案/broll-review.html"
