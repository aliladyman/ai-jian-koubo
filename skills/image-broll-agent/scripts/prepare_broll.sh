#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'TXT'
用法: prepare_broll.sh <clean-cut.mp4> [--output DIR] [--profile simple|balanced|rich]
       [--style clean_editorial] [--flash|--v3-standard|--auto]
       [--words subtitles_words.json] [--blank-plan] [--open-review]

默认会纯本地自动完成语义分段、评分、路由并生成 Markdown + HTML 审核页。
--words 用于复用 AI剪口播 已有的火山逐字稿，避免再次转录。
TXT
}
[[ $# -ge 1 ]] || { usage; exit 2; }
VIDEO_PATH="$1"; shift
PROFILE="balanced"; VISUAL_STYLE="clean_editorial"; ENGINE="--auto"; OUTPUT_DIR=""; WORDS_PATH=""; BLANK_PLAN=0; OPEN_REVIEW=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --output) OUTPUT_DIR="${2:?--output requires a directory}"; shift 2 ;;
    --profile) PROFILE="${2:?--profile requires a value}"; shift 2 ;;
    --style) VISUAL_STYLE="${2:?--style requires a value}"; shift 2 ;;
    --words) WORDS_PATH="${2:?--words requires a file}"; shift 2 ;;
    --blank-plan) BLANK_PLAN=1; shift ;;
    --open-review) OPEN_REVIEW=1; shift ;;
    --flash|--v3-standard|--auto) ENGINE="$1"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "❌ 未知参数: $1" >&2; usage; exit 2 ;;
  esac
done
case "$PROFILE" in simple|balanced|rich) ;; *) echo "❌ profile 必须是 simple / balanced / rich" >&2; exit 2 ;; esac
VIDEO_PATH="$(python3 -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).expanduser().resolve())' "$VIDEO_PATH")"
[[ -f "$VIDEO_PATH" ]] || { echo "❌ 视频不存在: $VIDEO_PATH" >&2; exit 2; }
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="$SKILL_DIR/.venv/bin/python"; [[ -x "$PYTHON" ]] || PYTHON="$(command -v python3)"
if [[ -f "$SKILL_DIR/.env" ]]; then set -a; source "$SKILL_DIR/.env"; set +a; fi
if [[ -n "${AI_JIAN_KOUBO_DIR:-}" ]]; then
  PARENT_DIR="$(cd "$AI_JIAN_KOUBO_DIR" && pwd)"
else
  CANDIDATE="$(cd "$SCRIPT_DIR/../../.." && pwd)"
  [[ -f "$CANDIDATE/scripts/run_transcribe.sh" ]] || { echo "❌ 找不到父 Skill，请设置 AI_JIAN_KOUBO_DIR" >&2; exit 2; }
  PARENT_DIR="$CANDIDATE"
fi
[[ -f "$PARENT_DIR/scripts/run_transcribe.sh" ]] || { echo "❌ 父 Skill 路径不正确: $PARENT_DIR" >&2; exit 2; }
if [[ -z "$OUTPUT_DIR" ]]; then
  NAME="$(basename "$VIDEO_PATH")"; NAME="${NAME%.*}"
  OUTPUT_DIR="$HOME/Desktop/output/$(date +%Y-%m-%d_%H-%M)_${NAME}/B-roll"
fi
OUTPUT_DIR="$(python3 -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).expanduser().resolve())' "$OUTPUT_DIR")"
PLAN_DIR="$OUTPUT_DIR/2_B-roll方案"; ASSET_DIR="$OUTPUT_DIR/3_B-roll素材"; CLIP_DIR="$OUTPUT_DIR/4_B-roll片段"; FINAL_DIR="$OUTPUT_DIR/5_成片"
mkdir -p "$OUTPUT_DIR/1_转录" "$PLAN_DIR" "$ASSET_DIR" "$CLIP_DIR" "$FINAL_DIR"
printf '📹 视频: %s\n📁 输出: %s\n🎚️ Profile: %s / %s\n\n' "$VIDEO_PATH" "$OUTPUT_DIR" "$PROFILE" "$VISUAL_STYLE"
if [[ -n "$WORDS_PATH" ]]; then
  WORDS_PATH="$(python3 -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).expanduser().resolve())' "$WORDS_PATH")"
  [[ -f "$WORDS_PATH" ]] || { echo "❌ 逐字稿不存在: $WORDS_PATH" >&2; exit 2; }
  TARGET_WORDS="$OUTPUT_DIR/1_转录/subtitles_words.json"
  if [[ "$WORDS_PATH" != "$TARGET_WORDS" ]]; then
    if [[ -f "$TARGET_WORDS" ]] && ! cmp -s "$WORDS_PATH" "$TARGET_WORDS"; then
      echo "❌ 目标逐字稿已存在且内容不同，拒绝覆盖: $TARGET_WORDS" >&2
      exit 2
    fi
    cp "$WORDS_PATH" "$TARGET_WORDS"
  fi
  echo "1/4 复用 AI剪口播 的火山逐字稿（不再次调用 ASR）..."
else
  echo "1/4 火山引擎重新转写 clean-cut 视频..."
  bash "$PARENT_DIR/scripts/run_transcribe.sh" "$VIDEO_PATH" "$OUTPUT_DIR" "$ENGINE"
fi
echo "2/4 构建保守原子时间单元..."
"$PYTHON" "$SCRIPT_DIR/build_context.py" --video "$VIDEO_PATH" --words "$OUTPUT_DIR/1_转录/subtitles_words.json" --output "$PLAN_DIR/transcript-context.json" --markdown "$PLAN_DIR/transcript-context.md"
if [[ "$BLANK_PLAN" -eq 1 ]]; then
  echo "3/4 创建空白 B-roll 计划模板..."
  "$PYTHON" "$SCRIPT_DIR/create_plan_template.py" "$PLAN_DIR/transcript-context.json" --output "$PLAN_DIR/broll-plan.json" --profile "$PROFILE" --visual-style "$VISUAL_STYLE"
  echo "4/4 空白计划已创建；需人工填写后再生成审核页。"
else
  echo "3/4 本地自动完成语义分段、评分和信息载体路由..."
  "$PYTHON" "$SCRIPT_DIR/auto_plan.py" "$PLAN_DIR/transcript-context.json" --output "$PLAN_DIR/broll-plan.json" --profile "$PROFILE" --visual-style "$VISUAL_STYLE"
  "$PYTHON" "$SCRIPT_DIR/plan_tool.py" validate "$PLAN_DIR/broll-plan.json" --check-files
  echo "4/4 生成文字版与可视化审核页..."
  "$PYTHON" "$SCRIPT_DIR/plan_tool.py" review "$PLAN_DIR/broll-plan.json" --output "$PLAN_DIR/broll-review.md"
  "$PYTHON" "$SCRIPT_DIR/generate_review_html.py" "$PLAN_DIR/broll-plan.json" --output "$PLAN_DIR/broll-review.html"
  if [[ "$OPEN_REVIEW" -eq 1 ]] && command -v open >/dev/null 2>&1; then
    open "$PLAN_DIR/broll-review.html"
  fi
fi
echo "✅ 准备完成：$PLAN_DIR"
echo "下一步：在 broll-review.html 播放并选择镜头；复制批准文本后，由 Agent 记录批准并导出 ChatGPT 生图 Prompt。"
