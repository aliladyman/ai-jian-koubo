#!/usr/bin/env python3
"""Turn accepted still-image assets into motion B-roll MP4 clips."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

from broll_lib import (
    assert_execution_gate,
    indexed,
    load_json,
    now_iso,
    require_command,
    resolve_plan_path,
    save_json,
    selected_approved_shots,
    sha256_file,
    validate_plan,
)


def asset_path(plan_path: Path, asset: dict) -> Path:
    if asset.get("type") in {"REAL_EVIDENCE", "EXISTING_MEDIA"}:
        value = asset.get("source_path")
    else:
        value = asset.get("generated_path")
    path = resolve_plan_path(plan_path, value)
    if path is None or not path.is_file():
        raise ValueError(f"asset file not found for {asset.get('asset_id')}: {path}")
    return path


def even(value: int) -> int:
    return value if value % 2 == 0 else value - 1


def motion_filter(preset: str, width: int, height: int, fps: float, frames: int) -> str:
    width, height = even(width), even(height)
    last = max(1, frames - 1)
    base = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1"
    if preset == "static_hold":
        return f"{base},fps={fps:.6f}"
    if preset == "slow_push":
        zoom = f"1+0.08*on/{last}"
        return (
            f"{base},zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d=1:s={width}x{height}:fps={fps:.6f}"
        )
    if preset == "slow_pull":
        zoom = f"1.08-0.08*on/{last}"
        return (
            f"{base},zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d=1:s={width}x{height}:fps={fps:.6f}"
        )
    if preset in {"pan_left", "pan_right"}:
        scale_w = even(math.ceil(width * 1.12))
        scale_h = even(math.ceil(height * 1.12))
        if preset == "pan_left":
            x = f"(iw-ow)*(1-n/{last})"
        else:
            x = f"(iw-ow)*(n/{last})"
        return (
            f"scale={scale_w}:{scale_h}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}:x='{x}':y='(ih-oh)/2':eval=frame,setsar=1,fps={fps:.6f}"
        )
    if preset == "diagonal_push":
        zoom = f"1+0.07*on/{last}"
        x = f"(iw-iw/zoom)*(on/{last})"
        y = f"(ih-ih/zoom)*(on/{last})"
        return (
            f"{base},zoompan=z='{zoom}':x='{x}':y='{y}':d=1:s={width}x{height}:fps={fps:.6f}"
        )
    raise ValueError(f"unsupported motion preset: {preset}")


def stored_path(plan_path: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(plan_path.parent.resolve()))
    except ValueError:
        return str(path.resolve())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--shot", action="append")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        require_command("ffmpeg")
        plan_path = args.plan.expanduser().resolve()
        plan = load_json(plan_path)
        errors = validate_plan(plan, plan_path=plan_path, check_files=True)
        if errors:
            raise ValueError("plan validation failed:\n- " + "\n- ".join(errors))
        requested = set(args.shot) if args.shot else None
        shots = selected_approved_shots(plan, requested)
        assert_execution_gate(plan, shots)
        if not shots:
            raise ValueError("no approved shots selected")
        assets = indexed(plan.get("assets", []), "asset_id")
        width = int(plan["source"]["width"])
        height = int(plan["source"]["height"])
        fps = float(plan["source"]["fps"])
        output_dir = args.output_dir.expanduser().resolve()
        commands: list[dict] = []
        for shot in shots:
            if shot.get("qa_status") != "accepted" and not args.dry_run:
                raise ValueError(f"{shot.get('shot_id')} has not passed image QA")
            asset = assets.get(str(shot.get("asset_id")))
            if not asset:
                raise ValueError(f"asset not found for {shot.get('shot_id')}")
            source_image = asset_path(plan_path, asset)
            if shot.get("qa_status") == "accepted" and shot.get("qa_asset_sha256") != sha256_file(source_image):
                raise ValueError(f"{shot.get('shot_id')} asset changed after QA acceptance")
            duration = float(shot["end_sec"]) - float(shot["start_sec"])
            frames = max(1, int(round(duration * fps)))
            destination = output_dir / Path(shot["output_name"]).name
            command = [
                "ffmpeg",
                "-y",
                "-loop",
                "1",
                "-i",
                str(source_image),
                "-vf",
                motion_filter(str(shot["motion_preset"]), width, height, fps, frames),
                "-frames:v",
                str(frames),
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "17",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(destination),
            ]
            commands.append({"shot_id": shot["shot_id"], "command": command})
        if args.dry_run:
            print(json.dumps(commands, ensure_ascii=False, indent=2))
            return 0

        output_dir.mkdir(parents=True, exist_ok=True)
        manifest = {"schema_version": "0.1", "created_at": now_iso(), "clips": []}
        for item, shot in zip(commands, shots):
            subprocess.run(item["command"], check=True, capture_output=True, text=True)
            destination = Path(item["command"][-1])
            if not destination.is_file() or destination.stat().st_size == 0:
                raise RuntimeError(f"rendered clip is empty: {destination}")
            shot["render_status"] = "rendered"
            shot["rendered_path"] = stored_path(plan_path, destination)
            shot["rendered_sha256"] = sha256_file(destination)
            shot["rendered_at"] = now_iso()
            manifest["clips"].append({
                "shot_id": shot["shot_id"],
                "source_asset": str(asset_path(plan_path, assets[shot["asset_id"]])),
                "output": str(destination),
                "motion_preset": shot["motion_preset"],
                "duration_sec": shot["duration_sec"],
            })
            print(f"BROLL_RENDERED {shot['shot_id']}: {destination}")
        save_json(plan_path, plan)
        save_json(output_dir / "broll-render-manifest.json", manifest)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
            print(exc.stderr[-2000:], file=sys.stderr)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
