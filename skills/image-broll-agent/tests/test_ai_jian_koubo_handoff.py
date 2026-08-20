#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from broll_lib import load_json, media_summary  # noqa: E402


def run(*args: str) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(args, capture_output=True, text=True)
    if completed.returncode != 0:
        raise AssertionError(f"command failed: {' '.join(args)}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}")
    return completed


def main() -> int:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise SystemExit("ffmpeg and ffprobe are required")
    with tempfile.TemporaryDirectory() as temp_dir:
        piece = Path(temp_dir) / "片子"
        source = piece / "source.mp4"
        words_dir = piece / "剪口播" / "1_转录"
        review_dir = piece / "剪口播" / "3_审核"
        words_dir.mkdir(parents=True)
        review_dir.mkdir(parents=True)
        run(
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=180x320:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "6", "-c:v", "libx264",
            "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source),
        )
        words = [
            {"text": "第一步", "start": 0.2, "end": 0.8, "isGap": False},
            {"text": "整理输入，", "start": 0.9, "end": 1.6, "isGap": False},
            {"text": "删除内容", "start": 2.2, "end": 2.8, "isGap": False},
            {"text": "然后", "start": 3.2, "end": 3.7, "isGap": False},
            {"text": "检查结果。", "start": 3.8, "end": 4.7, "isGap": False},
        ]
        (words_dir / "subtitles_words.json").write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
        fcpxml = f'''<?xml version="1.0" encoding="UTF-8"?>
<fcpxml version="1.8"><resources><asset id="r1" src="{source.as_uri()}" /></resources>
<library><event><project><sequence><spine>
<asset-clip ref="r1" start="0/1s" duration="2/1s" />
<asset-clip ref="r1" start="3/1s" duration="2/1s" />
</spine></sequence></project></event></library></fcpxml>'''
        (review_dir / "source_cut.fcpxml").write_text(fcpxml, encoding="utf-8")
        (review_dir / "review_log.json").write_text(json.dumps({"video": "source", "finalSelected": [2]}, ensure_ascii=False), encoding="utf-8")

        output = piece / "B-roll"
        run("bash", str(SCRIPTS / "handoff_from_ai_jian_koubo.sh"), str(review_dir), "--output", str(output), "--profile", "balanced")
        clean_cut = output / "0_干净口播" / "clean-cut.mp4"
        assert clean_cut.is_file()
        summary = media_summary(clean_cut)
        assert summary["has_audio"] is True
        assert abs(summary["duration_sec"] - 4.0) <= 0.2, summary
        remapped = json.loads((output / "1_转录" / "subtitles_words.json").read_text(encoding="utf-8"))
        visible = [item for item in remapped if not item["isGap"]]
        assert [item["text"] for item in visible] == ["第一步", "整理输入，", "然后", "检查结果。"]
        assert 2.1 <= visible[2]["start"] <= 2.3
        assert (output / "2_B-roll方案" / "broll-plan.json").is_file()
        assert (output / "2_B-roll方案" / "broll-review.html").is_file()
        state = load_json(output / "broll-handoff-state.json")
        assert state["state"] == "awaiting_broll_approval"

    print("test_ai_jian_koubo_handoff passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
