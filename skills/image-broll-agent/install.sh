#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
target_dir="${1:-${CODEX_HOME:-$HOME/.codex}/skills/image-broll-agent}"

if [[ -e "$target_dir" ]]; then
  echo "❌ 目标已存在: $target_dir" >&2
  echo "   请先移动或删除，避免覆盖本地配置。" >&2
  exit 2
fi

mkdir -p "$(dirname "$target_dir")"
cp -R "$repo_dir" "$target_dir"
python3 -m venv "$target_dir/.venv"
"$target_dir/.venv/bin/python" -m pip install --upgrade pip
"$target_dir/.venv/bin/python" -m pip install -r "$target_dir/requirements.txt"
chmod +x "$target_dir/install.sh" "$target_dir/scripts/prepare_broll.sh" "$target_dir/scripts/validate.sh"

echo "✅ 已安装到: $target_dir"
echo "接下来复制 .env.example 为 .env，并配置 OPENAI_API_KEY 与 AI_JIAN_KOUBO_DIR。"
