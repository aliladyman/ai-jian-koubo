#!/usr/bin/env python3
"""Create a draft B-roll plan template from transcript context."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from broll_lib import now_iso, save_json


def default_image_size(width: int, height: int) -> str:
    return "1536x1024" if width > height else "1024x1536" if height > width else "1024x1024"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("context", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=("simple", "balanced", "rich"), default="balanced")
    parser.add_argument("--visual-style", default="clean_editorial")
    parser.add_argument("--project-name")
    args = parser.parse_args()
    try:
        context = json.loads(args.context.read_text(encoding="utf-8"))
        source = dict(context["source"])
        name = args.project_name or Path(source["video_path"]).stem
        plan = {
            "schema_version": "0.1",
            "project": {"name": name, "created_at": now_iso()},
            "source": {
                "video_path": source["video_path"], "video_sha256": source["video_sha256"],
                "duration_sec": source["duration_sec"], "width": source["width"], "height": source["height"],
                "fps": source["fps"], "timebase": "seconds", "transcript_provider": "volcengine",
                "transcript_context_path": str(args.context.resolve())
            },
            "profile": {"name": args.profile, "visual_style": args.visual_style},
            "defaults": {
                "image_size": default_image_size(int(source["width"]), int(source["height"])),
                "image_quality": "medium", "image_model": "gpt-image-2-2026-04-21",
                "motion_preset": "slow_push", "transition_sec": 0.12
            },
            "segments": [], "assets": [], "shots": [],
            "approval": {"status": "pending", "approved_shots": [], "confirmation": None, "approved_at": None},
            "edit": {"enabled": True, "preserve_source_audio": True, "output_name": f"{name}_with_broll.mp4"}
        }
        save_json(args.output, plan)
        print(f"PLAN_TEMPLATE_WRITTEN: {args.output}")
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
