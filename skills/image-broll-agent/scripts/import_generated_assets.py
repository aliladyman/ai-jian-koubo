#!/usr/bin/env python3
"""Import images generated manually in ChatGPT and update the B-roll plan."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from PIL import Image

from broll_lib import (
    assert_execution_gate,
    indexed,
    load_json,
    now_iso,
    save_json,
    selected_approved_shots,
    sha256_file,
    validate_plan,
)


TARGET_RATIOS = {"9:16": 9 / 16, "16:9": 16 / 9, "1:1": 1.0}


def inspect_image(path: Path, target: str) -> tuple[int, int]:
    try:
        with Image.open(path) as image:
            width, height = image.size
            image.verify()
    except Exception as exc:
        raise ValueError(f"invalid image file: {path}: {exc}") from exc
    if width <= 0 or height <= 0:
        raise ValueError(f"invalid image dimensions: {path}")
    expected = TARGET_RATIOS[target]
    actual = width / height
    if abs(actual - expected) / expected > 0.08:
        raise ValueError(f"image aspect ratio mismatch for {path.name}: expected {target}, got {width}:{height}")
    return width, height


def stored_path(plan_path: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(plan_path.parent.resolve()))
    except ValueError:
        return str(path.resolve())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--shot", action="append", help="limit to one approved shot ID; repeatable")
    parser.add_argument("--replace", action="store_true", help="replace a different file already present in output-dir")
    args = parser.parse_args()
    try:
        plan_path = args.plan.expanduser().resolve()
        plan = load_json(plan_path)
        errors = validate_plan(plan, plan_path=plan_path, check_files=True)
        if errors:
            raise ValueError("plan validation failed:\n- " + "\n- ".join(errors))
        requested = set(args.shot) if args.shot else None
        shots = selected_approved_shots(plan, requested)
        assert_execution_gate(plan, shots)

        assets = indexed(plan.get("assets", []), "asset_id")
        input_dir = args.input_dir.expanduser().resolve()
        output_dir = args.output_dir.expanduser().resolve()
        jobs: list[tuple[dict, Path, Path, int, int]] = []
        seen: set[str] = set()
        for shot in shots:
            asset_id = str(shot.get("asset_id"))
            asset = assets.get(asset_id)
            if not asset or asset.get("type") != "GENERATED_IMAGE" or asset_id in seen:
                continue
            state = asset.get("generation_status")
            if state != "waiting_user_generation":
                raise ValueError(f"{asset_id} cannot be imported from generation_status={state}; export its prompt first")
            source = input_dir / Path(asset["output_name"]).name
            if not source.is_file():
                raise ValueError(f"generated image not found: {source}")
            width, height = inspect_image(source, str(asset["target_aspect_ratio"]))
            destination = output_dir / Path(asset["output_name"]).name
            if destination.exists() and source.resolve() != destination.resolve():
                if sha256_file(source) != sha256_file(destination) and not args.replace:
                    raise ValueError(f"destination already contains a different file: {destination}; use --replace to overwrite")
            jobs.append((asset, source, destination, width, height))
            seen.add(asset_id)
        if not jobs:
            raise ValueError("no approved manual ChatGPT image tasks selected")

        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = now_iso()
        for asset, source, destination, width, height in jobs:
            if source.resolve() != destination.resolve() and (not destination.exists() or sha256_file(source) != sha256_file(destination)):
                shutil.copy2(source, destination)
            asset["status"] = "provided"
            asset["generation_status"] = "user_generated"
            asset["generated_path"] = stored_path(plan_path, destination)
            asset["imported_at"] = timestamp
            asset["imported_sha256"] = sha256_file(destination)
            asset["imported_dimensions"] = {"width": width, "height": height}
            print(f"USER_IMAGE_IMPORTED {asset['asset_id']}: {destination}")
        save_json(plan_path, plan)
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
