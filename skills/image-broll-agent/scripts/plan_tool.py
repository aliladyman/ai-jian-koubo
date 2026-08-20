#!/usr/bin/env python3
"""Validate, review, approve, reset, and QA Image B-roll plans."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from broll_lib import (
    CONFIRMATION,
    approval_is_intact,
    blocking_assets,
    fingerprint_for,
    indexed,
    load_json,
    now_iso,
    resolve_plan_path,
    save_json,
    sha256_file,
    validate_plan,
)


def parse_shot_selection(value: str, all_ids: list[str]) -> list[str]:
    if value.strip().lower() == "all":
        return list(all_ids)
    selected = [item.strip() for item in value.split(",") if item.strip()]
    unknown = sorted(set(selected) - set(all_ids))
    if unknown:
        raise ValueError("unknown shot IDs: " + ", ".join(unknown))
    if not selected:
        raise ValueError("no shots selected")
    return selected


def asset_ready(plan_path: Path, asset: dict) -> tuple[bool, str]:
    asset_type = asset.get("type")
    if asset_type in {"REAL_EVIDENCE", "EXISTING_MEDIA"}:
        path = resolve_plan_path(plan_path, asset.get("source_path"))
        return (path is not None and path.is_file(), str(path))
    path = resolve_plan_path(plan_path, asset.get("generated_path"))
    if asset_type == "GENERATED_IMAGE":
        ready = asset.get("status") == "provided" and asset.get("generation_status") in {"user_generated", "qa_passed", "inserted"}
    else:
        ready = asset.get("status") == "generated"
    return (ready and path is not None and path.is_file(), str(path))


def review_markdown(plan: dict) -> str:
    routes = Counter(item.get("route", "UNKNOWN") for item in plan.get("segments", []))
    assets_by_id = indexed(plan.get("assets", []), "asset_id")
    segments_by_id = indexed(plan.get("segments", []), "segment_id")
    approval = plan.get("approval", {})
    generated_count = sum(1 for asset in plan.get("assets", []) if asset.get("type") == "GENERATED_IMAGE")
    budget = plan.get("broll_budget", {})
    lines = [
        f"# {plan.get('project', {}).get('name', 'B-roll 方案')}",
        "",
        f"- 输入视频：`{plan.get('source', {}).get('video_path', '')}`",
        f"- 时长：{plan.get('source', {}).get('duration_sec', 0):.3f} 秒",
        f"- Profile：`{plan.get('profile', {}).get('name', '')}` / `{plan.get('profile', {}).get('visual_style', '')}`",
        f"- 语义段落：{len(plan.get('segments', []))}",
        f"- B-roll 镜头：{len(plan.get('shots', []))}",
        f"- B-roll 预算：最多 {budget.get('max_total_broll', 0)} 个；ChatGPT 手工生图最多 {budget.get('max_generated_images', 0)} 张",
        f"- 当前 ChatGPT 手工生图任务：{generated_count}",
        f"- 审批状态：`{approval.get('status', 'pending')}`",
        f"- 已批准：{', '.join(approval.get('approved_shots', [])) or '无'}",
        "- 路由分布：" + "；".join(f"{key} {value}" for key, value in sorted(routes.items())),
        "",
        "## 分镜",
        "",
    ]
    if not plan.get("shots"):
        lines.append("没有计划插入 B-roll。")
    for shot in plan.get("shots", []):
        segment = segments_by_id.get(shot.get("segment_id"), {})
        asset = assets_by_id.get(shot.get("asset_id"), {})
        lines.extend([
            f"### {shot.get('shot_id')} · {segment.get('template_id', '')}",
            "",
            f"- 时间：{shot.get('start_sec', 0):.3f}–{shot.get('end_sec', 0):.3f} 秒",
            f"- 原文：{segment.get('transcript_text', '')}",
            f"- 语义：`{segment.get('semantic_role', '')}`；B-roll 需求 `{segment.get('broll_need', '')}`",
            f"- 价值评分：`{segment.get('broll_score', {}).get('total', '')}`（门槛 `{budget.get('min_broll_score', '')}`）",
            f"- 路由：`{segment.get('route', '')}`",
            f"- 原因：{segment.get('route_reason', '')}",
            f"- 素材：`{asset.get('asset_id', '')}` / `{asset.get('type', '')}` / `{asset.get('status', '')}`",
            f"- 运镜：`{shot.get('motion_preset', '')}`；转场 {shot.get('transition_sec', 0):.2f}s",
            f"- 时长类型：`{shot.get('duration_class', '')}`；实际 {shot.get('duration_sec', 0):.2f}s",
            f"- 审批：`{shot.get('approval', 'pending')}`；QA：`{shot.get('qa_status', 'pending')}`",
        ])
        if asset.get("description"):
            lines.append(f"- 素材说明：{asset.get('description')}")
        if asset.get("source_path"):
            lines.append(f"- 真实素材：`{asset.get('source_path')}`")
        if asset.get("prompt"):
            lines.extend([
                f"- 生图方式：`{asset.get('image_provider', '')}` / `{asset.get('generation_status', '')}`",
                "",
                "**复制到 ChatGPT 的生图提示词**",
                "",
                asset.get("prompt", ""),
            ])
        if asset.get("graphic_spec"):
            lines.extend([
                "",
                "**确定性图形**",
                "",
                "```json",
                json.dumps(asset.get("graphic_spec"), ensure_ascii=False, indent=2),
                "```",
            ])
        if segment.get("aigc_disclosure_required"):
            lines.append("- AIGC 标注：需要")
        lines.append("")
    lines.extend([
        "## 审批方式",
        "",
        "明确批准镜头编号，例如：`批准 B001、B003`。Agent 随后执行：",
        "",
        "```bash",
        "python3 scripts/plan_tool.py approve broll-plan.json --shots B001,B003 --confirmation CONFIRM_BROLL_PLAN",
        "```",
        "",
        "批准后导出 Prompt；用户在 ChatGPT 内生图并保存为任务指定文件名，再运行导入脚本。",
    ])
    return "\n".join(lines) + "\n"


def validate_or_raise(plan: dict, plan_path: Path, *, check_files: bool = False) -> None:
    errors = validate_plan(plan, plan_path=plan_path, check_files=check_files)
    if errors:
        raise ValueError("plan validation failed:\n- " + "\n- ".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("plan", type=Path)
    validate_parser.add_argument("--check-files", action="store_true")

    review_parser = subparsers.add_parser("review")
    review_parser.add_argument("plan", type=Path)
    review_parser.add_argument("--output", type=Path, required=True)

    approve_parser = subparsers.add_parser("approve")
    approve_parser.add_argument("plan", type=Path)
    approve_parser.add_argument("--shots", required=True)
    approve_parser.add_argument("--confirmation", required=True)

    reset_parser = subparsers.add_parser("reset")
    reset_parser.add_argument("plan", type=Path)
    reset_parser.add_argument("--shots", default="all")

    qa_parser = subparsers.add_parser("qa")
    qa_parser.add_argument("plan", type=Path)
    qa_parser.add_argument("--shots", required=True)
    qa_parser.add_argument("--status", choices=("accepted", "rejected"), required=True)

    args = parser.parse_args()
    try:
        plan_path = args.plan.expanduser().resolve()
        plan = load_json(plan_path)

        if args.command == "validate":
            validate_or_raise(plan, plan_path, check_files=args.check_files)
            print(f"VALID: {plan_path}")
            return 0

        if args.command == "review":
            validate_or_raise(plan, plan_path)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(review_markdown(plan), encoding="utf-8")
            print(f"REVIEW_WRITTEN: {args.output}")
            return 0

        all_ids = [shot["shot_id"] for shot in plan.get("shots", [])]

        if args.command == "reset":
            selected = set(parse_shot_selection(args.shots, all_ids))
            selected_asset_ids = {
                str(shot.get("asset_id"))
                for shot in plan.get("shots", [])
                if shot.get("shot_id") in selected
            }
            for shot in plan.get("shots", []):
                if shot.get("shot_id") in selected:
                    shot["approval"] = "pending"
                    shot["approval_fingerprint"] = None
                    shot["qa_status"] = "pending"
                    shot["qa_asset_sha256"] = None
                    shot["render_status"] = "pending"
                    shot["rendered_path"] = None
                    shot["rendered_sha256"] = None
                    shot["edit_status"] = "pending"
            remaining_approved_assets = {
                str(shot.get("asset_id"))
                for shot in plan.get("shots", [])
                if shot.get("shot_id") not in selected and shot.get("approval") == "approved"
            }
            for asset in plan.get("assets", []):
                if asset.get("type") == "GENERATED_IMAGE" and str(asset.get("asset_id")) in selected_asset_ids - remaining_approved_assets:
                    asset["status"] = "planned"
                    asset["generation_status"] = "planned"
                    asset["generated_path"] = None
                    for field in ("prompt_ready_at", "prompt_exported_at", "imported_at", "imported_sha256", "imported_dimensions", "qa_passed_at", "inserted_at", "inserted_output"):
                        asset.pop(field, None)
            approved_ids = [shot["shot_id"] for shot in plan.get("shots", []) if shot.get("approval") == "approved"]
            plan["approval"] = {
                "status": "pending" if not approved_ids else "partially_approved",
                "approved_shots": approved_ids,
                "confirmation": None,
                "approved_at": None,
            }
            save_json(plan_path, plan)
            print("RESET: " + ",".join(sorted(selected)))
            return 0

        if args.command == "approve":
            if args.confirmation != CONFIRMATION:
                raise ValueError(f"approval requires exact confirmation: {CONFIRMATION}")
            validate_or_raise(plan, plan_path, check_files=True)
            selected_ids = parse_shot_selection(args.shots, all_ids)
            shots_by_id = indexed(plan.get("shots", []), "shot_id")
            selected_shots = [shots_by_id[shot_id] for shot_id in selected_ids]
            blockers = blocking_assets(plan, selected_shots)
            if blockers:
                details = "; ".join(f"{asset.get('asset_id')}: {asset.get('description', '缺失素材')}" for asset in blockers)
                raise ValueError("approval blocked by missing assets: " + details)
            selected_set = set(selected_ids)
            for shot in plan.get("shots", []):
                if shot.get("shot_id") in selected_set:
                    shot["approval"] = "approved"
                    shot["approval_fingerprint"] = fingerprint_for(plan, shot)
                    shot["qa_status"] = "pending"
                    shot["qa_asset_sha256"] = None
            approved_ids = [shot["shot_id"] for shot in plan.get("shots", []) if shot.get("approval") == "approved"]
            plan["approval"] = {
                "status": "approved" if set(approved_ids) == set(all_ids) else "partially_approved",
                "approved_shots": approved_ids,
                "confirmation": CONFIRMATION,
                "approved_at": now_iso(),
            }
            save_json(plan_path, plan)
            print("APPROVED: " + ",".join(selected_ids))
            return 0

        if args.command == "qa":
            validate_or_raise(plan, plan_path, check_files=True)
            selected_ids = parse_shot_selection(args.shots, all_ids)
            shots_by_id = indexed(plan.get("shots", []), "shot_id")
            assets_by_id = indexed(plan.get("assets", []), "asset_id")
            for shot_id in selected_ids:
                shot = shots_by_id[shot_id]
                if shot.get("approval") != "approved" or not approval_is_intact(plan, shot):
                    raise ValueError(f"{shot_id} is not currently approved")
                asset = assets_by_id.get(shot.get("asset_id"), {})
                shot["qa_status"] = args.status
                if args.status == "accepted":
                    ready, path = asset_ready(plan_path, asset)
                    if not ready:
                        raise ValueError(f"{shot_id} asset is not ready for QA: {path}")
                    shot["qa_asset_sha256"] = sha256_file(Path(path))
                else:
                    shot["qa_asset_sha256"] = None
                    asset["status"] = "rejected"
                    if asset.get("type") == "GENERATED_IMAGE":
                        asset["generation_status"] = "rejected"
            affected_asset_ids = {
                str(shots_by_id[shot_id].get("asset_id"))
                for shot_id in selected_ids
            }
            for asset_id in affected_asset_ids:
                asset = assets_by_id.get(asset_id, {})
                if asset.get("type") != "GENERATED_IMAGE" or asset.get("generation_status") == "rejected":
                    continue
                related = [shot for shot in plan.get("shots", []) if str(shot.get("asset_id")) == asset_id]
                if related and all(shot.get("qa_status") == "accepted" for shot in related):
                    asset["generation_status"] = "qa_passed"
                    asset["qa_passed_at"] = now_iso()
                else:
                    asset["generation_status"] = "user_generated"
            save_json(plan_path, plan)
            print(f"QA_{args.status.upper()}: " + ",".join(selected_ids))
            return 0

        raise ValueError(f"unsupported command: {args.command}")
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
