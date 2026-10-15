#!/usr/bin/env python3
"""Generate explicitly approved GPT Image 2 assets and update the plan."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from broll_lib import (
    assert_execution_gate,
    indexed,
    load_json,
    load_skill_env,
    now_iso,
    save_json,
    selected_approved_shots,
    validate_plan,
)


def api_call(url: str, key: str, payload: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenAI network error: {exc}") from exc
    try:
        result = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"OpenAI returned non-JSON data: {body[:1000]}") from exc
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError("OpenAI API error: " + json.dumps(result["error"], ensure_ascii=False))
    return result


def decode_result(result: dict, destination: Path, timeout: float) -> None:
    data = result.get("data")
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise RuntimeError("OpenAI image response missing data[0]")
    item = data[0]
    encoded = item.get("b64_json")
    if isinstance(encoded, str) and encoded:
        try:
            destination.write_bytes(base64.b64decode(encoded, validate=True))
        except (ValueError, base64.binascii.Error) as exc:
            raise RuntimeError("OpenAI returned invalid base64 image data") from exc
        return
    url = item.get("url")
    if isinstance(url, str) and url.startswith(("https://", "http://")):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                destination.write_bytes(response.read())
        except urllib.error.URLError as exc:
            raise RuntimeError(f"image download failed: {exc}") from exc
        return
    raise RuntimeError("OpenAI image response contains neither b64_json nor url")


def payload_for(asset: dict) -> dict:
    return {
        "model": asset["model"],
        "prompt": asset["prompt"],
        "size": asset["size"],
        "quality": asset["quality"],
        "n": 1,
        "output_format": "png",
    }


def stored_path(plan_path: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(plan_path.parent.resolve()))
    except ValueError:
        return str(path.resolve())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--approved", action="store_true", help="required for real paid API calls")
    parser.add_argument("--shot", action="append", help="limit to one shot ID; repeatable")
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()
    try:
        load_skill_env()
        plan_path = args.plan.expanduser().resolve()
        plan = load_json(plan_path)
        errors = validate_plan(plan, plan_path=plan_path, check_files=False)
        if errors:
            raise ValueError("plan validation failed:\n- " + "\n- ".join(errors))

        requested = set(args.shot) if args.shot else None
        if args.dry_run:
            shots = [
                shot
                for shot in plan.get("shots", [])
                if requested is None or shot.get("shot_id") in requested
            ]
        else:
            shots = selected_approved_shots(plan, requested)
            assert_execution_gate(plan, shots)
            if not args.approved:
                raise ValueError("real image generation is blocked without --approved")

        assets_by_id = indexed(plan.get("assets", []), "asset_id")
        generated_assets: list[tuple[dict, list[str]]] = []
        seen: set[str] = set()
        for shot in shots:
            asset_id = str(shot.get("asset_id"))
            asset = assets_by_id.get(asset_id)
            if not asset or asset.get("type") != "GENERATED_IMAGE" or asset_id in seen:
                continue
            seen.add(asset_id)
            shot_ids = [item["shot_id"] for item in shots if item.get("asset_id") == asset_id]
            generated_assets.append((asset, shot_ids))
        if not generated_assets:
            raise ValueError("no GPT Image 2 assets selected")

        printable = [
            {
                "asset_id": asset["asset_id"],
                "shot_ids": shot_ids,
                "endpoint": "/images/generations",
                "payload": payload_for(asset),
            }
            for asset, shot_ids in generated_assets
        ]
        if args.dry_run:
            print(json.dumps(printable, ensure_ascii=False, indent=2))
            return 0

        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key or key == "your_openai_api_key":
            raise ValueError("OPENAI_API_KEY is not configured")
        base = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1").rstrip("/")
        output_dir = args.output_dir.expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = output_dir / "image-generation-manifest.json"
        manifest = {
            "schema_version": "0.1",
            "started_at": now_iso(),
            "base_url": base,
            "assets": [],
        }
        save_json(manifest_path, manifest)

        for asset, shot_ids in generated_assets:
            record = {
                "asset_id": asset["asset_id"],
                "shot_ids": shot_ids,
                "model": asset["model"],
                "payload": payload_for(asset),
                "status": "submitting",
                "started_at": now_iso(),
            }
            manifest["assets"].append(record)
            save_json(manifest_path, manifest)
            try:
                result = api_call(base + "/images/generations", key, payload_for(asset), args.timeout)
                destination = output_dir / Path(asset["output_name"]).name
                decode_result(result, destination, args.timeout)
                if not destination.is_file() or destination.stat().st_size == 0:
                    raise RuntimeError("generated image file is empty")
                asset["status"] = "generated"
                asset["generated_path"] = stored_path(plan_path, destination)
                asset["generated_at"] = now_iso()
                record.update({
                    "status": "generated",
                    "output": str(destination),
                    "completed_at": now_iso(),
                    "usage": result.get("usage"),
                })
                save_json(plan_path, plan)
                save_json(manifest_path, manifest)
                print(f"GENERATED {asset['asset_id']}: {destination}")
            except Exception as exc:
                record.update({"status": "failed", "error": str(exc), "failed_at": now_iso()})
                save_json(manifest_path, manifest)
                raise
        manifest["completed_at"] = now_iso()
        save_json(manifest_path, manifest)
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
