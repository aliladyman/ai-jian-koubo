#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from broll_lib import load_json, sha256_file, validate_plan  # noqa: E402


class ReviewParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.shot_cards = 0
        self.has_video = False
        self.has_approval = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "article" and "shot-card" in (values.get("class") or ""):
            self.shot_cards += 1
        if tag == "video" and values.get("id") == "source-video":
            self.has_video = True
        if values.get("id") == "copy-approval":
            self.has_approval = True


def run(*args: str) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(args, capture_output=True, text=True)
    if completed.returncode != 0:
        raise AssertionError(f"command failed: {' '.join(args)}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}")
    return completed


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        source = temp / "clean-cut.mp4"
        source.write_bytes(b"auto plan source")
        texts = [
            "你有没有发现，AI工具越来越多？",
            "根据官方研究报告，处理速度提升了35%。",
            "普通工具负责执行，而Agent负责决定下一步。",
            "第一步整理输入，然后执行任务，最后检查结果。",
            "AI助手就像任务调度中心的项目经理。",
            "我自己用了一周，觉得真人判断仍然重要。",
            "整个流程只需要3分钟。",
            "这个Skill的本质是把复杂任务拆成清晰模块。",
            "所以最终结论是，关键判断必须留给人。",
            "未来的工作空间仿佛有一组安静协作的数字助手。",
        ]
        units = []
        for index, text in enumerate(texts):
            start = index * 14.0
            units.append({
                "unit_id": f"U{index + 1:04d}", "start_sec": start, "end_sec": start + 6.0,
                "text": text, "source_word_start": index * 10, "source_word_end": index * 10 + 9,
                "boundary_reason": "strong_punctuation",
            })
        context = {
            "schema_version": "0.1",
            "source": {
                "video_path": str(source), "video_sha256": sha256_file(source), "duration_sec": 150.0,
                "width": 1080, "height": 1920, "fps": 30.0, "has_audio": True, "timebase": "seconds",
                "word_timestamps_path": str(temp / "subtitles_words.json"),
            },
            "units": units, "full_text": "".join(texts),
        }
        context_path = temp / "transcript-context.json"
        context_path.write_text(json.dumps(context, ensure_ascii=False), encoding="utf-8")
        plan_path = temp / "2_B-roll方案" / "broll-plan.json"
        run(sys.executable, str(SCRIPTS / "auto_plan.py"), str(context_path), "--output", str(plan_path), "--profile", "balanced")
        plan = load_json(plan_path)
        errors = validate_plan(plan, plan_path=plan_path, check_files=False)
        assert not errors, errors
        assert 1 <= len(plan["shots"]) <= 8
        assert sum(asset["type"] == "GENERATED_IMAGE" for asset in plan["assets"]) <= 5
        routes = {segment["route"] for segment in plan["segments"]}
        assert {"KEEP_A_ROLL", "REAL_EVIDENCE", "DETERMINISTIC_GRAPHIC", "GENERATED_IMAGE"}.issubset(routes), routes
        assert all(asset.get("image_provider") in {None, "manual_chatgpt"} for asset in plan["assets"])
        assert "model" not in json.dumps(plan)
        assert all(a["end_sec"] <= b["start_sec"] for a, b in zip(plan["shots"], plan["shots"][1:]))
        state = load_json(plan_path.parent.parent / "broll-handoff-state.json")
        assert state["state"] == "awaiting_broll_approval"

        html_path = temp / "broll-review.html"
        run(sys.executable, str(SCRIPTS / "generate_review_html.py"), str(plan_path), "--output", str(html_path))
        parser = ReviewParser()
        parser.feed(html_path.read_text(encoding="utf-8"))
        assert parser.shot_cards == len(plan["shots"])
        assert parser.has_video and parser.has_approval
        assert "CONFIRM_BROLL_PLAN" in html_path.read_text(encoding="utf-8")

    print("test_auto_planning passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
