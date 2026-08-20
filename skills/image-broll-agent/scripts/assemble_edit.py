#!/usr/bin/env python3
"""Overlay accepted B-roll clips by timestamp while preserving source speech."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from broll_lib import (
    assert_execution_gate,
    has_audio,
    indexed,
    load_json,
    media_summary,
    now_iso,
    probe_media,
    require_command,
    resolve_plan_path,
    save_json,
    selected_approved_shots,
    sha256_file,
    validate_plan,
)


def rendered_path(plan_path: Path, shot: dict) -> Path:
    path = resolve_plan_path(plan_path, shot.get("rendered_path"))
    if path is None or not path.is_file():
        raise ValueError(f"rendered B-roll clip not found for {shot.get('shot_id')}: {path}")
    return path


def build_command(plan: dict, plan_path: Path, shots: list[dict], output: Path) -> list[str]:
    source = resolve_plan_path(plan_path, plan["source"]["video_path"])
    if source is None:
        raise ValueError("source video path is empty")
    width = int(plan["source"]["width"])
    height = int(plan["source"]["height"])
    source_duration = float(plan["source"]["duration_sec"])
    command = ["ffmpeg", "-y", "-i", str(source)]
    for shot in shots:
        command.extend(["-stream_loop", "-1", "-i", str(rendered_path(plan_path, shot))])

    filters = ["[0:v]setpts=PTS-STARTPTS[v0]"]
    current = "v0"
    for index, shot in enumerate(shots, 1):
        start = float(shot["start_sec"])
        end = float(shot["end_sec"])
        duration = end - start
        transition = min(float(shot.get("transition_sec", 0.12)), duration / 3)
        filters.append(
            f"[{index}:v]trim=duration={duration:.6f},setpts=PTS-STARTPTS,"
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},format=rgba,"
            f"fade=t=in:st=0:d={transition:.6f}:alpha=1,"
            f"fade=t=out:st={max(0.0, duration-transition):.6f}:d={transition:.6f}:alpha=1,"
            f"setpts=PTS+{start:.6f}/TB[bv{index}]"
        )
        next_label = f"v{index}"
        filters.append(
            f"[{current}][bv{index}]overlay=0:0:eof_action=pass:"
            f"enable='between(t,{start:.6f},{end:.6f})'[{next_label}]"
        )
        current = next_label
    filters.append("[0:a]asetpts=PTS-STARTPTS[aout]")

    command.extend([
        "-filter_complex",
        ";".join(filters),
        "-map",
        f"[{current}]",
        "-map",
        "[aout]",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "17",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "256k",
        "-t",
        f"{source_duration:.6f}",
        "-movflags",
        "+faststart",
        str(output),
    ])
    return command


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--shot", action="append")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        require_command("ffmpeg")
        require_command("ffprobe")
        plan_path = args.plan.expanduser().resolve()
        plan = load_json(plan_path)
        errors = validate_plan(plan, plan_path=plan_path, check_files=True)
        if errors:
            raise ValueError("plan validation failed:\n- " + "\n- ".join(errors))
        requested = set(args.shot) if args.shot else None
        shots = selected_approved_shots(plan, requested)
        assert_execution_gate(plan, shots)
        shots = sorted(shots, key=lambda item: float(item["start_sec"]))
        if not shots:
            raise ValueError("no approved shots selected")
        for shot in shots:
            if shot.get("qa_status") != "accepted":
                raise ValueError(f"{shot.get('shot_id')} has not passed QA")
            if shot.get("render_status") != "rendered":
                raise ValueError(f"{shot.get('shot_id')} has not been rendered")
            clip_path = rendered_path(plan_path, shot)
            if shot.get("rendered_sha256") != sha256_file(clip_path):
                raise ValueError(f"{shot.get('shot_id')} rendered clip changed after rendering")
        source_path = resolve_plan_path(plan_path, plan["source"]["video_path"])
        if source_path is None or not source_path.is_file():
            raise ValueError(f"source video not found: {source_path}")
        if not has_audio(probe_media(source_path)):
            raise ValueError("source talking-head video must contain an audio stream")

        output = (args.output or plan_path.parent / plan["edit"]["output_name"]).expanduser().resolve()
        command = build_command(plan, plan_path, shots, output)
        if args.dry_run:
            print(json.dumps(command, ensure_ascii=False, indent=2))
            return 0

        output.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(command, capture_output=True, text=True)
        if completed.returncode != 0:
            raise RuntimeError("ffmpeg assembly failed:\n" + completed.stderr[-4000:])
        summary = media_summary(output)
        source_duration = float(plan["source"]["duration_sec"])
        if abs(float(summary["duration_sec"]) - source_duration) > 0.15:
            raise RuntimeError(
                f"output duration mismatch: source={source_duration:.3f}, output={summary['duration_sec']:.3f}"
            )
        if summary["width"] != int(plan["source"]["width"]) or summary["height"] != int(plan["source"]["height"]):
            raise RuntimeError("output frame size does not match source")
        if not summary["has_audio"]:
            raise RuntimeError("output is missing source speech audio")
        manifest = {
            "schema_version": "0.1",
            "created_at": now_iso(),
            "source": str(source_path),
            "output": str(output),
            "preserve_source_audio": True,
            "shots": [
                {
                    "shot_id": shot["shot_id"],
                    "clip": str(rendered_path(plan_path, shot)),
                    "start_sec": shot["start_sec"],
                    "end_sec": shot["end_sec"],
                }
                for shot in shots
            ],
            "output_probe": summary,
        }
        manifest_path = output.with_name("broll-edit-manifest.json")
        save_json(manifest_path, manifest)
        assets = indexed(plan.get("assets", []), "asset_id")
        inserted_at = now_iso()
        for shot in shots:
            shot["edit_status"] = "inserted"
            shot["inserted_at"] = inserted_at
            asset = assets.get(str(shot.get("asset_id")), {})
            if asset.get("type") == "GENERATED_IMAGE":
                asset["generation_status"] = "inserted"
                asset["inserted_at"] = inserted_at
                asset["inserted_output"] = str(output)
        save_json(plan_path, plan)
        print(f"FINAL_EDIT_WRITTEN: {output}")
        print(f"EDIT_MANIFEST_WRITTEN: {manifest_path}")
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
