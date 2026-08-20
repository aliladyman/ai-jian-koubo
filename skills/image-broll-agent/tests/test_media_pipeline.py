#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from broll_lib import load_json, media_summary, save_json, sha256_file, validate_plan  # noqa: E402


def run(*args: str) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(args, capture_output=True, text=True)
    if completed.returncode != 0:
        raise AssertionError(
            f"command failed: {' '.join(args)}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def main() -> int:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise SystemExit("ffmpeg and ffprobe are required")
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        source = temp / "source.mp4"
        run(
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=360x640:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            "8",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        )
        words = [
            {"text": "Tool", "start": 0.2, "end": 0.6, "isGap": False},
            {"text": "负责", "start": 0.6, "end": 1.0, "isGap": False},
            {"text": "执行", "start": 1.0, "end": 1.4, "isGap": False},
            {"text": "，", "start": 1.4, "end": 1.5, "isGap": False},
            {"text": "Agent", "start": 1.5, "end": 2.0, "isGap": False},
            {"text": "决定下一步", "start": 2.0, "end": 2.8, "isGap": False},
            {"text": "。", "start": 2.8, "end": 2.9, "isGap": False},
            {"text": "", "start": 2.9, "end": 3.6, "isGap": True},
            {"text": "这是结论", "start": 3.6, "end": 4.4, "isGap": False},
            {"text": "。", "start": 4.4, "end": 4.5, "isGap": False},
            {"text": "", "start": 4.5, "end": 5.0, "isGap": True},
            {"text": "这是一个抽象概念", "start": 5.0, "end": 7.1, "isGap": False},
            {"text": "。", "start": 7.1, "end": 7.2, "isGap": False},
        ]
        words_path = temp / "subtitles_words.json"
        words_path.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
        context_path = temp / "context.json"
        context_md = temp / "context.md"
        run(
            sys.executable,
            str(SCRIPTS / "build_context.py"),
            "--video",
            str(source),
            "--words",
            str(words_path),
            "--output",
            str(context_path),
            "--markdown",
            str(context_md),
        )
        context = load_json(context_path)
        assert len(context["units"]) == 3, context["units"]
        assert context["units"][0]["text"] == "Tool负责执行，Agent决定下一步。"

        plan = {
            "schema_version": "0.2",
            "project": {"name": "pipeline-test", "created_at": "2026-08-20T00:00:00+00:00"},
            "source": {
                "video_path": str(source),
                "video_sha256": sha256_file(source),
                "duration_sec": 8.0,
                "width": 360,
                "height": 640,
                "fps": 30.0,
                "timebase": "seconds",
                "transcript_provider": "volcengine",
                "transcript_context_path": str(context_path),
            },
            "profile": {"name": "rich", "visual_style": "clean_editorial"},
            "broll_budget": {
                "designed_for_video_sec": {"min": 120, "max": 180},
                "max_total_broll": 8,
                "max_generated_images": 5,
                "min_broll_score": 12,
            },
            "segments": [
                {
                    "segment_id": "S001",
                    "source_unit_ids": ["U0001"],
                    "start_sec": 0.2,
                    "end_sec": 2.9,
                    "transcript_text": "Tool负责执行，Agent决定下一步。",
                    "semantic_role": "comparison",
                    "broll_need": 3,
                    "broll_score": {
                        "visual_value": 8,
                        "comprehension_gain": 9,
                        "rhythm_gain": 5,
                        "generation_cost": 2,
                        "total": 20,
                    },
                    "speaker_dependency": "low",
                    "evidence_required": False,
                    "route": "DETERMINISTIC_GRAPHIC",
                    "template_id": "I06_SPLIT_COMPARISON",
                    "route_reason": "职责对比需要准确文字",
                    "shot_id": "B001",
                    "aigc_disclosure_required": False,
                },
                {
                    "segment_id": "S002",
                    "source_unit_ids": ["U0002"],
                    "start_sec": 3.6,
                    "end_sec": 4.5,
                    "transcript_text": "这是结论。",
                    "semantic_role": "conclusion",
                    "broll_need": 0,
                    "broll_score": {
                        "visual_value": 2,
                        "comprehension_gain": 1,
                        "rhythm_gain": 1,
                        "generation_cost": 0,
                        "total": 4,
                    },
                    "speaker_dependency": "high",
                    "evidence_required": False,
                    "route": "KEEP_A_ROLL",
                    "template_id": "NONE",
                    "route_reason": "结论保留真人",
                    "shot_id": None,
                    "aigc_disclosure_required": False,
                },
                {
                    "segment_id": "S003",
                    "source_unit_ids": ["U0003"],
                    "start_sec": 5.0,
                    "end_sec": 7.2,
                    "transcript_text": "这是一个抽象概念。",
                    "semantic_role": "concept",
                    "broll_need": 2,
                    "broll_score": {
                        "visual_value": 8,
                        "comprehension_gain": 7,
                        "rhythm_gain": 4,
                        "generation_cost": 5,
                        "total": 14,
                    },
                    "speaker_dependency": "low",
                    "evidence_required": False,
                    "route": "GENERATED_IMAGE",
                    "template_id": "I08_CINEMATIC_METAPHOR",
                    "route_reason": "抽象概念需要场景隐喻",
                    "shot_id": "B002",
                    "aigc_disclosure_required": True,
                },
            ],
            "assets": [
                {
                    "asset_id": "A001",
                    "type": "DETERMINISTIC_GRAPHIC",
                    "status": "planned",
                    "blocks_generation": False,
                    "description": "Tool/Agent 对比",
                    "output_name": "A001.png",
                    "source_path": None,
                    "generated_path": None,
                    "graphic_spec": {
                        "kind": "split",
                        "title": "职责不同",
                        "left": "Tool：执行",
                        "right": "Agent：决策",
                    },
                },
                {
                    "asset_id": "A002",
                    "type": "GENERATED_IMAGE",
                    "status": "planned",
                    "generation_status": "planned",
                    "blocks_generation": False,
                    "description": "抽象概念隐喻",
                    "output_name": "B002.png",
                    "source_path": None,
                    "generated_path": None,
                    "prompt": "A calm abstract editorial scene with one central object and layered depth. No readable text, no letters, no numbers, no logos, no watermark, no UI, no charts, no fake evidence.",
                    "text_policy": "no_text",
                    "image_provider": "manual_chatgpt",
                    "generation_mode": "manual_chatgpt",
                    "target_aspect_ratio": "9:16",
                },
            ],
            "shots": [
                {
                    "shot_id": "B001",
                    "segment_id": "S001",
                    "asset_id": "A001",
                    "start_sec": 0.6,
                    "end_sec": 2.6,
                    "duration_sec": 2.0,
                    "duration_class": "short_point",
                    "composition": "fullscreen_replace",
                    "motion_preset": "slow_push",
                    "transition_sec": 0.12,
                    "approval": "pending",
                    "approval_fingerprint": None,
                    "qa_status": "pending",
                    "edit_status": "pending",
                    "output_name": "B001.mp4",
                },
                {
                    "shot_id": "B002",
                    "segment_id": "S003",
                    "asset_id": "A002",
                    "start_sec": 5.0,
                    "end_sec": 7.0,
                    "duration_sec": 2.0,
                    "duration_class": "short_point",
                    "composition": "fullscreen_replace",
                    "motion_preset": "slow_push",
                    "transition_sec": 0.12,
                    "approval": "pending",
                    "approval_fingerprint": None,
                    "qa_status": "pending",
                    "edit_status": "pending",
                    "output_name": "B002.mp4",
                },
            ],
            "approval": {"status": "pending", "approved_shots": [], "confirmation": None, "approved_at": None},
            "edit": {"enabled": True, "preserve_source_audio": True, "output_name": "final.mp4"},
        }
        plan_path = temp / "plan.json"
        save_json(plan_path, plan)
        run(sys.executable, str(SCRIPTS / "plan_tool.py"), "validate", str(plan_path), "--check-files")
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
        asset_dir = temp / "assets"
        download_dir = temp / "chatgpt-downloads"
        clip_dir = temp / "clips"
        final_path = temp / "final.mp4"
        download_dir.mkdir()
        run(
            sys.executable,
            str(SCRIPTS / "export_image_prompts.py"),
            str(plan_path),
            "--output",
            str(temp / "image-prompts.json"),
        )
        Image.new("RGB", (360, 640), (50, 70, 90)).save(download_dir / "B002.png")
        run(
            sys.executable,
            str(SCRIPTS / "import_generated_assets.py"),
            str(plan_path),
            "--input-dir",
            str(download_dir),
            "--output-dir",
            str(asset_dir),
        )
        run(sys.executable, str(SCRIPTS / "prepare_assets.py"), str(plan_path), "--output-dir", str(asset_dir))
        run(
            sys.executable,
            str(SCRIPTS / "plan_tool.py"),
            "qa",
            str(plan_path),
            "--shots",
            "all",
            "--status",
            "accepted",
        )
        run(sys.executable, str(SCRIPTS / "render_broll.py"), str(plan_path), "--output-dir", str(clip_dir))
        run(sys.executable, str(SCRIPTS / "assemble_edit.py"), str(plan_path), "--output", str(final_path))
        summary = media_summary(final_path)
        assert summary["width"] == 360 and summary["height"] == 640, summary
        assert summary["has_audio"] is True, summary
        assert abs(summary["duration_sec"] - 8.0) <= 0.15, summary
        assert (temp / "broll-edit-manifest.json").is_file()
        completed = load_json(plan_path)
        assert completed["assets"][1]["generation_status"] == "inserted"
        assert all(shot["edit_status"] == "inserted" for shot in completed["shots"])
        assert not validate_plan(completed, plan_path=plan_path, check_files=True)

    print("test_media_pipeline passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
