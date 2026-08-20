#!/usr/bin/env python3
from __future__ import annotations

import copy
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from broll_lib import load_json, save_json, sha256_file, validate_plan  # noqa: E402


def run(*args: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(args, capture_output=True, text=True)
    if completed.returncode != expected:
        raise AssertionError(
            f"command failed ({completed.returncode} != {expected}): {' '.join(args)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        source = temp / "source.mp4"
        source.write_bytes(b"manual flow source placeholder")
        plan = load_json(ROOT / "references" / "example-plan.json")
        plan["source"]["video_path"] = str(source)
        plan["source"]["video_sha256"] = sha256_file(source)
        plan_path = temp / "broll-plan.json"
        save_json(plan_path, plan)

        run(
            sys.executable,
            str(SCRIPTS / "plan_tool.py"),
            "approve",
            str(plan_path),
            "--shots",
            "B002",
            "--confirmation",
            "CONFIRM_BROLL_PLAN",
        )
        prompts_json = temp / "image-prompts.json"
        prompts_md = temp / "image-prompts.md"
        run(
            sys.executable,
            str(SCRIPTS / "export_image_prompts.py"),
            str(plan_path),
            "--output",
            str(prompts_json),
            "--markdown",
            str(prompts_md),
        )
        exported = load_json(prompts_json)
        assert exported["type"] == "manual_chatgpt_image_prompts"
        assert len(exported["prompts"]) == 1
        assert exported["prompts"][0]["filename"] == "B002.png"
        assert "OPENAI_API_KEY" not in prompts_json.read_text(encoding="utf-8")
        waiting = load_json(plan_path)
        assert waiting["assets"][1]["generation_status"] == "waiting_user_generation"

        download_dir = temp / "chatgpt-downloads"
        imported_dir = temp / "assets"
        download_dir.mkdir()
        Image.new("RGB", (540, 960), (40, 60, 80)).save(download_dir / "B002.png")
        run(
            sys.executable,
            str(SCRIPTS / "import_generated_assets.py"),
            str(plan_path),
            "--input-dir",
            str(download_dir),
            "--output-dir",
            str(imported_dir),
        )
        imported = load_json(plan_path)
        assert imported["assets"][1]["status"] == "provided"
        assert imported["assets"][1]["generation_status"] == "user_generated"
        assert (imported_dir / "B002.png").is_file()
        assert not validate_plan(imported, plan_path=plan_path, check_files=True)

        run(
            sys.executable,
            str(SCRIPTS / "plan_tool.py"),
            "qa",
            str(plan_path),
            "--shots",
            "B002",
            "--status",
            "accepted",
        )
        accepted = load_json(plan_path)
        assert accepted["assets"][1]["generation_status"] == "qa_passed"
        assert accepted["shots"][1]["qa_status"] == "accepted"
        premature = copy.deepcopy(accepted)
        premature["assets"][1]["generation_status"] = "inserted"
        errors = validate_plan(premature, plan_path=plan_path, check_files=True)
        assert any("requires an inserted shot" in error for error in errors), errors

    print("test_manual_image_flow passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
