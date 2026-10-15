#!/usr/bin/env python3
"""Convert Volcengine word timestamps into conservative atomic transcript units."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from broll_lib import media_summary, now_iso, save_json, sha256_file

STRONG_END = set("。！？!?；;")
SOFT_END = set("，,、：:")


def normalize_words(value) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError("subtitles_words.json must contain an array")
    words = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        start, end = item.get("start"), item.get("end")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end < start:
            continue
        words.append({"index": index, "text": str(item.get("text", "")), "start": float(start), "end": float(end), "is_gap": bool(item.get("isGap", False))})
    if not words:
        raise ValueError("no usable word timestamps found")
    return words


def build_units(words: list[dict], silence_boundary: float, max_duration: float, max_chars: int) -> list[dict]:
    units, current = [], []

    def flush(reason: str) -> None:
        nonlocal current
        visible = [item for item in current if not item["is_gap"] and item["text"]]
        if visible:
            units.append({
                "unit_id": f"U{len(units) + 1:04d}",
                "start_sec": round(visible[0]["start"], 3),
                "end_sec": round(visible[-1]["end"], 3),
                "text": "".join(item["text"] for item in visible),
                "source_word_start": visible[0]["index"],
                "source_word_end": visible[-1]["index"],
                "boundary_reason": reason,
            })
        current = []

    for item in words:
        if item["is_gap"]:
            if current and item["end"] - item["start"] >= silence_boundary:
                flush("silence")
            continue
        if not item["text"]:
            continue
        current.append(item)
        text = "".join(part["text"] for part in current)
        duration = current[-1]["end"] - current[0]["start"]
        last = item["text"][-1]
        if last in STRONG_END:
            flush("strong_punctuation")
        elif last in SOFT_END and duration >= 3.0:
            flush("soft_punctuation_after_3s")
        elif duration >= max_duration or len(text) >= max_chars:
            flush("safety_limit")
    flush("end_of_transcript")
    if not units:
        raise ValueError("failed to build transcript units")
    return units


def write_markdown(path: Path, payload: dict) -> None:
    source = payload["source"]
    lines = [
        "# B-roll 语义分段输入", "",
        f"- 视频：`{source['video_path']}`",
        f"- 时长：{source['duration_sec']:.3f} 秒",
        f"- 画面：{source['width']}×{source['height']} / {source['fps']:.3f} fps",
        f"- 原子单元：{len(payload['units'])}", "",
        "> 这些单元只由标点和停顿得到。请继续按完整语义合并相邻单元。", "",
        "| ID | 时间 | 文本 | 初始边界 |", "|---|---:|---|---|",
    ]
    for unit in payload["units"]:
        text = unit["text"].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {unit['unit_id']} | {unit['start_sec']:.3f}–{unit['end_sec']:.3f} | {text} | {unit['boundary_reason']} |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--words", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--silence-boundary", type=float, default=0.45)
    parser.add_argument("--max-duration", type=float, default=6.5)
    parser.add_argument("--max-chars", type=int, default=32)
    args = parser.parse_args()
    try:
        video = args.video.expanduser().resolve()
        words_path = args.words.expanduser().resolve()
        words = normalize_words(json.loads(words_path.read_text(encoding="utf-8")))
        units = build_units(words, args.silence_boundary, args.max_duration, args.max_chars)
        summary = media_summary(video)
        payload = {
            "schema_version": "0.1", "created_at": now_iso(),
            "source": {
                "video_path": str(video), "video_sha256": sha256_file(video),
                "duration_sec": summary["duration_sec"], "width": summary["width"], "height": summary["height"],
                "fps": summary["fps"], "has_audio": summary["has_audio"], "timebase": "seconds",
                "word_timestamps_path": str(words_path)
            },
            "units": units, "full_text": "".join(unit["text"] for unit in units)
        }
        save_json(args.output, payload)
        write_markdown(args.markdown, payload)
        print(f"CONTEXT_WRITTEN: {args.output}\nUNITS: {len(units)}")
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
