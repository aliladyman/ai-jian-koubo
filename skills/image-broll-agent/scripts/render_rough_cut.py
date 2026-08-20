#!/usr/bin/env python3
"""Render AI剪口播's approved FCPXML locally and remap Volcengine word timestamps."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

from broll_lib import media_summary, now_iso, save_json, sha256_file


def rational_seconds(value: str) -> float:
    raw = str(value).strip()
    if raw.endswith("s"):
        raw = raw[:-1]
    if "/" in raw:
        numerator, denominator = raw.split("/", 1)
        return float(numerator) / float(denominator)
    return float(raw)


def parse_fcpxml(path: Path) -> tuple[Path, list[dict]]:
    root = ET.parse(path).getroot()
    asset = root.find(".//asset")
    if asset is None or not asset.get("src"):
        raise ValueError("FCPXML does not contain a source asset")
    parsed = urllib.parse.urlparse(asset.get("src", ""))
    if parsed.scheme != "file":
        raise ValueError("FCPXML source must use a local file URI")
    source_path = Path(urllib.parse.unquote(parsed.path)).resolve()
    keeps = []
    for clip in root.findall(".//asset-clip"):
        start = rational_seconds(clip.get("start", "0s"))
        duration = rational_seconds(clip.get("duration", "0s"))
        if duration > 0:
            keeps.append({"start": start, "end": start + duration})
    if not keeps:
        raise ValueError("FCPXML does not contain any kept asset clips")
    return source_path, keeps


def validate_receipt(review_dir: Path, receipt: dict) -> tuple[Path, Path]:
    if receipt.get("version") != 1 or not isinstance(receipt.get("artifacts"), dict):
        raise ValueError("rough-cut-export.receipt.json is invalid")
    artifacts = receipt["artifacts"]
    fcpxml_info = artifacts.get("fcpxml", {})
    review_info = artifacts.get("reviewLog", {})
    fcpxml = review_dir / str(fcpxml_info.get("file", ""))
    review_log = review_dir / str(review_info.get("file", "review_log.json"))
    for label, path, expected in (
        ("FCPXML", fcpxml, fcpxml_info.get("sha256")),
        ("review_log.json", review_log, review_info.get("sha256")),
    ):
        if not path.is_file():
            raise ValueError(f"{label} referenced by the receipt is missing: {path}")
        if not isinstance(expected, str) or sha256_file(path) != expected:
            raise ValueError(f"{label} no longer matches rough-cut-export.receipt.json")
    return fcpxml, review_log


def discover_export(review_dir: Path) -> tuple[Path, Path, dict | None]:
    receipt_path = review_dir / "rough-cut-export.receipt.json"
    if receipt_path.is_file():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        fcpxml, review_log = validate_receipt(review_dir, receipt)
        return fcpxml, review_log, receipt
    review_log = review_dir / "review_log.json"
    if not review_log.is_file():
        raise ValueError("review_log.json is missing; export the approved A-mode cut first")
    choices = sorted(review_dir.glob("*_cut.fcpxml"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not choices:
        raise ValueError("no *_cut.fcpxml was found in the review directory")
    return choices[0], review_log, None


def normalize_keeps(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    keeps = []
    for item in value:
        if not isinstance(item, dict):
            continue
        start, end = item.get("start"), item.get("end")
        if isinstance(start, (int, float)) and isinstance(end, (int, float)) and 0 <= float(start) < float(end):
            keeps.append({"start": float(start), "end": float(end)})
    return keeps


def render_video(source: Path, keeps: list[dict], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    chains = []
    concat_inputs = []
    for index, keep in enumerate(keeps):
        start, end = keep["start"], keep["end"]
        chains.append(f"[0:v]trim=start={start:.9f}:end={end:.9f},setpts=PTS-STARTPTS[v{index}]")
        chains.append(f"[0:a]atrim=start={start:.9f}:end={end:.9f},asetpts=PTS-STARTPTS[a{index}]")
        concat_inputs.append(f"[v{index}][a{index}]")
    chains.append("".join(concat_inputs) + f"concat=n={len(keeps)}:v=1:a=1[vout][aout]")
    command = [
        "ffmpeg", "-y", "-v", "error", "-i", str(source), "-filter_complex", ";".join(chains),
        "-map", "[vout]", "-map", "[aout]", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output),
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError("ffmpeg failed to render clean cut: " + completed.stderr.strip())


def map_words(words: list, keeps: list[dict], deleted_indices: set[int]) -> list[dict]:
    visible: list[dict] = []
    offsets: list[float] = []
    total = 0.0
    for keep in keeps:
        offsets.append(total)
        total += keep["end"] - keep["start"]
    for index, word in enumerate(words):
        if index in deleted_indices or not isinstance(word, dict) or bool(word.get("isGap", False)):
            continue
        start, end = word.get("start"), word.get("end")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or float(end) <= float(start):
            continue
        midpoint = (float(start) + float(end)) / 2.0
        for keep_index, keep in enumerate(keeps):
            if keep["start"] - 1e-6 <= midpoint <= keep["end"] + 1e-6:
                mapped_start = offsets[keep_index] + max(0.0, float(start) - keep["start"])
                mapped_end = offsets[keep_index] + min(keep["end"] - keep["start"], float(end) - keep["start"])
                if mapped_end > mapped_start:
                    visible.append({"text": str(word.get("text", "")), "start": round(mapped_start, 3), "end": round(mapped_end, 3), "isGap": False})
                break
    if not visible:
        raise ValueError("no kept words could be remapped to the clean-cut timeline")
    rebuilt: list[dict] = []
    cursor = 0.0
    for word in visible:
        if word["start"] > cursor + 0.015:
            rebuilt.append({"text": "", "start": round(cursor, 3), "end": word["start"], "isGap": True})
        rebuilt.append(word)
        cursor = max(cursor, float(word["end"]))
    if total > cursor + 0.015:
        rebuilt.append({"text": "", "start": round(cursor, 3), "end": round(total, 3), "isGap": True})
    return rebuilt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", type=Path)
    parser.add_argument("--video-output", type=Path, required=True)
    parser.add_argument("--words-output", type=Path, required=True)
    parser.add_argument("--state-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        review_dir = args.review_dir.expanduser().resolve()
        fcpxml, review_log_path, receipt = discover_export(review_dir)
        review_log = json.loads(review_log_path.read_text(encoding="utf-8"))
        xml_source, xml_keeps = parse_fcpxml(fcpxml)
        source_value = review_log.get("source", {}).get("path") if isinstance(review_log.get("source"), dict) else None
        source = Path(source_value).expanduser().resolve() if source_value else xml_source
        if source != xml_source:
            raise ValueError("review_log.json and FCPXML reference different source videos")
        if not source.is_file():
            raise ValueError(f"source video is missing: {source}")
        log_keeps = normalize_keeps(review_log.get("finalKeeps"))
        keeps = log_keeps or xml_keeps
        if log_keeps and (len(log_keeps) != len(xml_keeps) or any(abs(a[key] - b[key]) > 0.04 for a, b in zip(log_keeps, xml_keeps) for key in ("start", "end"))):
            raise ValueError("review_log.json finalKeeps do not match the committed FCPXML")

        words_path = review_dir.parent / "1_转录" / "subtitles_words.json"
        if not words_path.is_file():
            raise ValueError(f"Volcengine word timestamps are missing: {words_path}")
        text_authority = review_log.get("textAuthority") if isinstance(review_log.get("textAuthority"), dict) else {}
        expected_words_hash = text_authority.get("wordsSha256")
        if expected_words_hash and sha256_file(words_path) != expected_words_hash:
            raise ValueError("subtitles_words.json no longer matches review_log.json text authority")
        if receipt and receipt.get("wordsSha256") and expected_words_hash != receipt.get("wordsSha256"):
            raise ValueError("receipt and review_log.json disagree on the transcript fingerprint")
        deleted = text_authority.get("deletedWordIndices") or review_log.get("finalSelected") or []
        deleted_indices = {int(value) for value in deleted if isinstance(value, int) and not isinstance(value, bool)}

        video_output = args.video_output.expanduser().resolve()
        words_output = args.words_output.expanduser().resolve()
        state_output = args.state_output.expanduser().resolve()
        render_video(source, keeps, video_output)
        words = json.loads(words_path.read_text(encoding="utf-8"))
        remapped = map_words(words, keeps, deleted_indices)
        save_json(words_output, remapped)
        summary = media_summary(video_output)
        expected_duration = sum(item["end"] - item["start"] for item in keeps)
        if abs(summary["duration_sec"] - expected_duration) > 0.2:
            raise ValueError("rendered clean cut duration does not match the approved FCPXML")
        save_json(state_output, {
            "schema_version": "1", "state": "clean_cut_rendered", "updated_at": now_iso(),
            "source": {"video": str(source), "fcpxml": str(fcpxml), "review_log": str(review_log_path), "receipt_validated": receipt is not None},
            "artifacts": {"clean_cut_video": str(video_output), "remapped_volcengine_words": str(words_output)},
            "integrity": {"source_sha256": sha256_file(source), "fcpxml_sha256": sha256_file(fcpxml), "words_sha256": sha256_file(words_output), "kept_segments": len(keeps)},
        })
        print(f"CLEAN_CUT_WRITTEN: {video_output}")
        print(f"REMAPPED_WORDS_WRITTEN: {words_output}")
        print(f"KEPT_SEGMENTS: {len(keeps)}")
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, json.JSONDecodeError, ET.ParseError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
