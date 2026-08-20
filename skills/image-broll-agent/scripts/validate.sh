#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -n "${PYTHON:-}" ]]; then
  PYTHON="$PYTHON"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
else
  PYTHON="python3"
fi
TMP_DIR="$(mktemp -d)"; trap 'rm -rf "$TMP_DIR"' EXIT
"$PYTHON" -m py_compile "$ROOT"/scripts/*.py
bash -n "$ROOT/scripts/prepare_broll.sh"
bash -n "$ROOT/scripts/handoff_from_ai_jian_koubo.sh"
bash -n "$ROOT/install.sh"
"$PYTHON" "$ROOT/scripts/plan_tool.py" validate "$ROOT/references/example-plan.json"
"$PYTHON" "$ROOT/scripts/plan_tool.py" review "$ROOT/references/example-plan.json" --output "$TMP_DIR/review.md"
"$PYTHON" -m json.tool "$ROOT/schemas/broll-plan.schema.json" >/dev/null
"$PYTHON" "$ROOT/tests/test_plan_tool.py"
"$PYTHON" "$ROOT/tests/test_manual_image_flow.py"
"$PYTHON" "$ROOT/tests/test_auto_planning.py"
"$PYTHON" "$ROOT/tests/test_ai_jian_koubo_handoff.py"
"$PYTHON" "$ROOT/tests/test_media_pipeline.py"
"$PYTHON" - "$ROOT/SKILL.md" <<'PY'
from pathlib import Path
import sys
text = Path(sys.argv[1]).read_text(encoding="utf-8")
if not text.startswith("---\n"): raise SystemExit("SKILL.md is missing YAML frontmatter")
frontmatter = text.split("---\n", 2)[1]
for required in ("name: image-broll-agent", "description:"):
    if required not in frontmatter: raise SystemExit(f"SKILL.md is missing {required}")
print("Skill frontmatter passed")
PY
[[ ! -e "$ROOT/scripts/generate_image2.py" ]] || { echo "generate_image2.py must not exist" >&2; exit 1; }
if rg -n '^OPENAI_' "$ROOT/.env.example" || rg -n 'urllib\.request|/images/generations' "$ROOT/scripts" --glob '*.py'; then
  echo "Executable Image API residue found in Image B-roll Agent" >&2
  exit 1
fi
echo "Image B-roll Agent validation passed"
