#!/usr/bin/env python3
"""Approval fingerprints and execution gates."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

from broll_io import indexed


def fingerprint_for(plan: dict[str, Any], shot: dict[str, Any]) -> str:
    segment = indexed(plan.get("segments", []), "segment_id").get(str(shot.get("segment_id")), {})
    asset = indexed(plan.get("assets", []), "asset_id").get(str(shot.get("asset_id")), {})
    payload = {
        "schema_version": plan.get("schema_version"),
        "source_video_sha256": plan.get("source", {}).get("video_sha256"),
        "profile": plan.get("profile"),
        "broll_budget": plan.get("broll_budget"),
        "segment": {key: segment.get(key) for key in ("segment_id", "source_unit_ids", "start_sec", "end_sec", "transcript_text", "route", "template_id", "evidence_required", "broll_score")},
        "asset": {key: asset.get(key) for key in ("asset_id", "type", "prompt", "text_policy", "image_provider", "generation_mode", "target_aspect_ratio", "source_path", "graphic_spec", "output_name")},
        "shot": {key: shot.get(key) for key in ("shot_id", "start_sec", "end_sec", "duration_class", "composition", "motion_preset", "transition_sec", "output_name")},
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def approval_is_intact(plan: dict[str, Any], shot: dict[str, Any]) -> bool:
    stored = shot.get("approval_fingerprint")
    return isinstance(stored, str) and stored == fingerprint_for(plan, shot)


def blocking_assets(plan: dict[str, Any], shots: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    assets = indexed(plan.get("assets", []), "asset_id")
    return [asset for shot in shots if (asset := assets.get(str(shot.get("asset_id")))) and asset.get("blocks_generation") is True and asset.get("status") == "missing"]


def selected_approved_shots(plan: dict[str, Any], requested: set[str] | None = None) -> list[dict[str, Any]]:
    approved = set(plan.get("approval", {}).get("approved_shots", []))
    return [shot for shot in plan.get("shots", []) if isinstance(shot, dict) and (requested is None or shot.get("shot_id") in requested) and shot.get("shot_id") in approved and shot.get("approval") == "approved"]


def assert_execution_gate(plan: dict[str, Any], shots: Iterable[dict[str, Any]]) -> None:
    selected = list(shots)
    if plan.get("approval", {}).get("status") not in {"approved", "partially_approved"}:
        raise ValueError("plan approval status is not approved")
    if not selected:
        raise ValueError("no approved shots selected")
    broken = [str(shot.get("shot_id")) for shot in selected if not approval_is_intact(plan, shot)]
    if broken:
        raise ValueError("approval fingerprint mismatch: " + ", ".join(broken))
    blockers = blocking_assets(plan, selected)
    if blockers:
        raise ValueError("execution blocked by missing assets: " + "; ".join(f"{item.get('asset_id')}: {item.get('description', 'missing asset')}" for item in blockers))
