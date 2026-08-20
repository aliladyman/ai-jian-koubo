#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from broll_lib import approval_is_intact, load_json, save_json, sha256_file, validate_plan  # noqa: E402


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
        source.write_bytes(b"test source placeholder")
        plan = load_json(ROOT / "references" / "example-plan.json")
        plan["source"]["video_path"] = str(source)
        plan["source"]["video_sha256"] = sha256_file(source)
        plan_path = temp / "plan.json"
        save_json(plan_path, plan)

        errors = validate_plan(plan, plan_path=plan_path, check_files=True)
        assert not errors, errors

        run(
            sys.executable,
            str(SCRIPTS / "plan_tool.py"),
            "approve",
            str(plan_path),
            "--shots",
            "all",
            "--confirmation",
            "CONFIRM_BROLL_PLAN",
        )
        approved = load_json(plan_path)
        assert approved["approval"]["status"] == "approved"
        assert all(shot["approval"] == "approved" for shot in approved["shots"])
        assert all(approval_is_intact(approved, shot) for shot in approved["shots"])

        tampered = copy.deepcopy(approved)
        tampered["assets"][1]["prompt"] += " changed"
        errors = validate_plan(tampered, plan_path=plan_path, check_files=False)
        assert any("approval_fingerprint" in error for error in errors), errors

        run(
            sys.executable,
            str(SCRIPTS / "plan_tool.py"),
            "reset",
            str(plan_path),
            "--shots",
            "all",
        )
        reset = load_json(plan_path)
        assert reset["approval"]["status"] == "pending"
        assert all(shot["approval_fingerprint"] is None for shot in reset["shots"])

        blocked = copy.deepcopy(reset)
        blocked["segments"][1]["route"] = "REAL_EVIDENCE"
        blocked["segments"][1]["template_id"] = "I04_EVIDENCE_FRAME"
        blocked["assets"][0] = {
            "asset_id": "A001",
            "type": "REAL_EVIDENCE",
            "status": "missing",
            "blocks_generation": True,
            "description": "官方截图",
            "output_name": "A001.png",
            "source_path": None,
            "generated_path": None,
        }
        blocked_path = temp / "blocked.json"
        save_json(blocked_path, blocked)
        result = run(
            sys.executable,
            str(SCRIPTS / "plan_tool.py"),
            "approve",
            str(blocked_path),
            "--shots",
            "B001",
            "--confirmation",
            "CONFIRM_BROLL_PLAN",
            expected=2,
        )
        assert "missing assets" in result.stderr

        over_budget = copy.deepcopy(reset)
        over_budget["broll_budget"]["max_generated_images"] = 0
        errors = validate_plan(over_budget, plan_path=plan_path, check_files=False)
        assert any("manually generated images" in error for error in errors), errors

        too_many_shots = copy.deepcopy(reset)
        too_many_shots["broll_budget"]["max_total_broll"] = 1
        errors = validate_plan(too_many_shots, plan_path=plan_path, check_files=False)
        assert any("total shots" in error for error in errors), errors

        low_score = copy.deepcopy(reset)
        low_score["segments"][1]["broll_score"] = {
            "visual_value": 3,
            "comprehension_gain": 3,
            "rhythm_gain": 2,
            "generation_cost": 4,
            "total": 4,
        }
        errors = validate_plan(low_score, plan_path=plan_path, check_files=False)
        assert any("min_broll_score" in error for error in errors), errors

        fixed_six_seconds = copy.deepcopy(reset)
        fixed_six_seconds["shots"][0]["end_sec"] = fixed_six_seconds["shots"][0]["start_sec"] + 6
        fixed_six_seconds["shots"][0]["duration_sec"] = 6
        errors = validate_plan(fixed_six_seconds, plan_path=plan_path, check_files=False)
        assert any("duration_class=short_point" in error for error in errors), errors

        legacy_api = copy.deepcopy(reset)
        legacy_api["assets"][1]["model"] = "gpt-image-2"
        errors = validate_plan(legacy_api, plan_path=plan_path, check_files=False)
        assert any("obsolete API fields" in error for error in errors), errors

    print("test_plan_tool passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
