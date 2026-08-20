#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
TMP_DIR="$(mktemp -d)"; trap 'rm -rf "$TMP_DIR"' EXIT
"$PYTHON" -m py_compile "$ROOT"/scripts/*.py
bash -n "$ROOT/scripts/prepare_broll.sh"
bash -n "$ROOT/install.sh"
"$PYTHON" "$ROOT/scripts/plan_tool.py" validate "$ROOT/references/example-plan.json"
"$PYTHON" "$ROOT/scripts/plan_tool.py" review "$ROOT/references/example-plan.json" --output "$TMP_DIR/review.md"
"$PYTHON" "$ROOT/scripts/generate_image2.py" "$ROOT/references/example-plan.json" --output-dir "$TMP_DIR/assets" --dry-run >/dev/null
"$PYTHON" "$ROOT/tests/test_plan_tool.py"
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
echo "Image B-roll Agent validation passed"
