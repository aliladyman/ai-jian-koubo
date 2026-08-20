#!/usr/bin/env python3
"""Export approved manual ChatGPT image tasks without calling any image API."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from broll_lib import (
    assert_execution_gate,
    indexed,
    load_json,
    now_iso,
    save_json,
    selected_approved_shots,
    validate_plan,
)


def markdown_for(export: dict) -> str:
    lines = [
        "# ChatGPT 手工生图任务",
        "",
        "逐条复制 Prompt 到 ChatGPT 生图。下载后必须使用任务指定文件名，放进同一个待导入目录。",
        "",
    ]
    for item in export["prompts"]:
        lines.extend([
            f"## {', '.join(item['shot_ids'])} · {item['asset_id']}",
            "",
            f"- 时间：{item['start_sec']:.3f}–{item['end_sec']:.3f} 秒",
            f"- 用途：{item['reason']}",
            f"- 目标比例：`{item['target_aspect_ratio']}`",
            f"- 保存文件名：`{item['filename']}`",
            "",
            "```text",
            item["prompt"],
            "```",
            "",
        ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--shot", action="append", help="limit to one approved shot ID; repeatable")
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
        segments = indexed(plan.get("segments", []), "segment_id")
        tasks: list[dict] = []
        seen: set[str] = set()
        timestamp = now_iso()
        for shot in shots:
            asset_id = str(shot.get("asset_id"))
            asset = assets.get(asset_id)
            if not asset or asset.get("type") != "GENERATED_IMAGE" or asset_id in seen:
                continue
            if asset.get("image_provider") != "manual_chatgpt" or asset.get("generation_mode") != "manual_chatgpt":
                raise ValueError(f"{asset_id} is not a manual ChatGPT image task")
            state = asset.get("generation_status")
            if state not in {"planned", "prompt_ready", "waiting_user_generation"}:
                raise ValueError(f"{asset_id} cannot export prompts from generation_status={state}; reset it first")
            related = [item for item in shots if str(item.get("asset_id")) == asset_id]
            related_segments = [segments.get(str(item.get("segment_id")), {}) for item in related]
            asset["generation_status"] = "prompt_ready"
            asset.setdefault("prompt_ready_at", timestamp)
            tasks.append({
                "asset_id": asset_id,
                "shot_ids": [str(item.get("shot_id")) for item in related],
                "start_sec": min(float(item["start_sec"]) for item in related),
                "end_sec": max(float(item["end_sec"]) for item in related),
                "reason": "；".join(str(item.get("route_reason", "")) for item in related_segments),
                "prompt": asset["prompt"],
                "target_aspect_ratio": asset["target_aspect_ratio"],
                "filename": asset["output_name"],
                "status": "waiting_user_generation",
            })
            seen.add(asset_id)
        if not tasks:
            raise ValueError("no approved manual ChatGPT image tasks selected")

        export = {
            "schema_version": "0.2",
            "type": "manual_chatgpt_image_prompts",
            "created_at": timestamp,
            "source_plan": str(plan_path),
            "instructions": "Copy each prompt into ChatGPT, download the result using the exact filename, then run import_generated_assets.py.",
            "prompts": tasks,
        }
        output = args.output.expanduser().resolve()
        save_json(output, export)
        if args.markdown:
            markdown = args.markdown.expanduser().resolve()
            markdown.parent.mkdir(parents=True, exist_ok=True)
            markdown.write_text(markdown_for(export), encoding="utf-8")
        for task in tasks:
            asset = assets[task["asset_id"]]
            asset["generation_status"] = "waiting_user_generation"
            asset["prompt_exported_at"] = timestamp
        save_json(plan_path, plan)
        print(f"IMAGE_PROMPTS_WRITTEN: {output}")
        if args.markdown:
            print(f"IMAGE_PROMPTS_MARKDOWN_WRITTEN: {args.markdown.expanduser().resolve()}")
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
