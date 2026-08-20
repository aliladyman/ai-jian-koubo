#!/usr/bin/env python3
"""Schema validation for Image B-roll plans."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from broll_core import (
    ASSET_STATUSES,
    ASSET_TYPES,
    BROLL_BUDGET_LIMITS,
    BROLL_SCORE_FIELDS,
    DURATION_CLASSES,
    EDIT_STATUSES,
    GENERATION_MODES,
    GENERATION_STATUSES,
    IMAGE_EXTENSIONS,
    IMAGE_PROVIDERS,
    MOTION_PRESETS,
    PLAN_APPROVALS,
    PROFILES,
    QA_STATUSES,
    ROUTES,
    SCHEMA_VERSION,
    SEMANTIC_ROLES,
    SHOT_APPROVALS,
    SPEAKER_DEPENDENCIES,
    TEMPLATES,
    _find_secrets,
    approval_is_intact,
    indexed,
    resolve_plan_path,
    sha256_file,
)

def _validate_graphic_spec(spec: Any, prefix: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(spec, dict):
        return [f"{prefix} must be an object"]
    kind = spec.get("kind")
    allowed = {"statement", "number", "relation", "split", "timeline"}
    if kind not in allowed:
        errors.append(f"{prefix}.kind must be one of: {', '.join(sorted(allowed))}")
        return errors
    if kind == "statement":
        if not isinstance(spec.get("title"), str) or not spec.get("title", "").strip():
            errors.append(f"{prefix}.title is required for statement")
    elif kind == "number":
        if not isinstance(spec.get("number"), str) or not spec.get("number", "").strip():
            errors.append(f"{prefix}.number is required for number")
        if not isinstance(spec.get("label"), str) or not spec.get("label", "").strip():
            errors.append(f"{prefix}.label is required for number")
    elif kind == "relation":
        steps = spec.get("steps")
        if not isinstance(steps, list) or not 2 <= len(steps) <= 4 or any(not isinstance(item, str) or not item.strip() for item in steps):
            errors.append(f"{prefix}.steps must contain 2..4 non-empty strings")
    elif kind == "split":
        for field in ("left", "right"):
            if not isinstance(spec.get(field), str) or not spec.get(field, "").strip():
                errors.append(f"{prefix}.{field} is required for split")
    elif kind == "timeline":
        items = spec.get("items")
        if not isinstance(items, list) or not 2 <= len(items) <= 5 or any(not isinstance(item, str) or not item.strip() for item in items):
            errors.append(f"{prefix}.items must contain 2..5 non-empty strings")
    return errors


def _validate_broll_score(score: Any, prefix: str) -> tuple[list[str], int | None]:
    errors: list[str] = []
    if not isinstance(score, dict):
        return [f"{prefix} must be an object"], None
    values: dict[str, int] = {}
    for field in BROLL_SCORE_FIELDS:
        value = score.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 10:
            errors.append(f"{prefix}.{field} must be an integer from 0 to 10")
        else:
            values[field] = value
    total = score.get("total")
    if not isinstance(total, int) or isinstance(total, bool):
        errors.append(f"{prefix}.total must be an integer")
        return errors, None
    if len(values) == len(BROLL_SCORE_FIELDS):
        expected = values["visual_value"] + values["comprehension_gain"] + values["rhythm_gain"] - values["generation_cost"]
        if total != expected:
            errors.append(f"{prefix}.total must equal visual_value + comprehension_gain + rhythm_gain - generation_cost ({expected})")
    return errors, total


def validate_plan(plan: dict[str, Any], *, plan_path: Path | None = None, check_files: bool = False) -> list[str]:
    errors: list[str] = []
    required_top = ("schema_version", "project", "source", "profile", "broll_budget", "segments", "assets", "shots", "approval", "edit")
    for field in required_top:
        if field not in plan:
            errors.append(f"missing top-level field: {field}")
    if str(plan.get("schema_version")) != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")

    secret_paths = _find_secrets(plan)
    if secret_paths:
        errors.append("credentials must not be stored in the plan: " + ", ".join(secret_paths))

    source = plan.get("source")
    source_duration = 0.0
    if not isinstance(source, dict):
        errors.append("source must be an object")
        source = {}
    else:
        if not isinstance(source.get("video_path"), str) or not source.get("video_path", "").strip():
            errors.append("source.video_path must be non-empty")
        if not isinstance(source.get("video_sha256"), str) or len(source.get("video_sha256", "")) != 64:
            errors.append("source.video_sha256 must be a SHA-256 hex string")
        source_duration_value = source.get("duration_sec")
        if not isinstance(source_duration_value, (int, float)) or source_duration_value <= 0:
            errors.append("source.duration_sec must be positive")
        else:
            source_duration = float(source_duration_value)
        for field in ("width", "height"):
            if not isinstance(source.get(field), int) or source.get(field, 0) <= 0:
                errors.append(f"source.{field} must be a positive integer")
        if not isinstance(source.get("fps"), (int, float)) or source.get("fps", 0) <= 0:
            errors.append("source.fps must be positive")
        if source.get("timebase") != "seconds":
            errors.append("source.timebase must be seconds")
        if check_files and plan_path is not None:
            source_path = resolve_plan_path(plan_path, source.get("video_path"))
            if source_path is None or not source_path.is_file():
                errors.append(f"source.video_path not found: {source_path}")
            elif source.get("video_sha256") != sha256_file(source_path):
                errors.append("source.video_sha256 does not match current source file")

    profile = plan.get("profile")
    profile_name = None
    if not isinstance(profile, dict):
        errors.append("profile must be an object")
        profile = {}
    else:
        profile_name = profile.get("name")
        if profile_name not in PROFILES:
            errors.append("profile.name must be simple, balanced, or rich")
        if not isinstance(profile.get("visual_style"), str) or not profile.get("visual_style", "").strip():
            errors.append("profile.visual_style must be non-empty")

    budget = plan.get("broll_budget")
    min_broll_score = 0
    max_total_broll = 0
    max_generated_images = 0
    if not isinstance(budget, dict):
        errors.append("broll_budget must be an object")
        budget = {}
    else:
        designed = budget.get("designed_for_video_sec")
        if not isinstance(designed, dict):
            errors.append("broll_budget.designed_for_video_sec must be an object")
        else:
            designed_min = designed.get("min")
            designed_max = designed.get("max")
            if not isinstance(designed_min, (int, float)) or not isinstance(designed_max, (int, float)) or not 0 < float(designed_min) <= float(designed_max):
                errors.append("broll_budget.designed_for_video_sec requires positive min <= max")
        max_total_broll = budget.get("max_total_broll")
        if not isinstance(max_total_broll, int) or isinstance(max_total_broll, bool) or not 0 <= max_total_broll <= BROLL_BUDGET_LIMITS["max_total_broll"]:
            errors.append(f"broll_budget.max_total_broll must be an integer from 0 to {BROLL_BUDGET_LIMITS['max_total_broll']}")
            max_total_broll = 0
        max_generated_images = budget.get("max_generated_images")
        if not isinstance(max_generated_images, int) or isinstance(max_generated_images, bool) or not 0 <= max_generated_images <= BROLL_BUDGET_LIMITS["max_generated_images"]:
            errors.append(f"broll_budget.max_generated_images must be an integer from 0 to {BROLL_BUDGET_LIMITS['max_generated_images']}")
            max_generated_images = 0
        elif isinstance(max_total_broll, int) and max_generated_images > max_total_broll:
            errors.append("broll_budget.max_generated_images cannot exceed max_total_broll")
        min_broll_score = budget.get("min_broll_score")
        if not isinstance(min_broll_score, int) or isinstance(min_broll_score, bool) or not 12 <= min_broll_score <= 30:
            errors.append("broll_budget.min_broll_score must be an integer from 12 to 30")
            min_broll_score = 0

    segments = plan.get("segments")
    if not isinstance(segments, list) or not segments:
        errors.append("segments must be a non-empty array")
        segments = []
    assets = plan.get("assets")
    if not isinstance(assets, list):
        errors.append("assets must be an array")
        assets = []
    shots = plan.get("shots")
    if not isinstance(shots, list):
        errors.append("shots must be an array")
        shots = []

    segment_ids: set[str] = set()
    unit_ids_seen: list[str] = []
    for index, segment in enumerate(segments):
        prefix = f"segments[{index}]"
        if not isinstance(segment, dict):
            errors.append(f"{prefix} must be an object")
            continue
        segment_id = segment.get("segment_id")
        if not isinstance(segment_id, str) or not segment_id:
            errors.append(f"{prefix}.segment_id must be non-empty")
        elif segment_id in segment_ids:
            errors.append(f"duplicate segment_id: {segment_id}")
        else:
            segment_ids.add(segment_id)
        unit_ids = segment.get("source_unit_ids")
        if not isinstance(unit_ids, list) or not unit_ids or any(not isinstance(item, str) or not item for item in unit_ids):
            errors.append(f"{prefix}.source_unit_ids must be a non-empty string array")
        else:
            unit_ids_seen.extend(unit_ids)
        start = segment.get("start_sec")
        end = segment.get("end_sec")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or not 0 <= float(start) < float(end):
            errors.append(f"{prefix} requires numeric start_sec < end_sec")
        elif source_duration and float(end) > source_duration + 0.15:
            errors.append(f"{prefix}.end_sec exceeds source duration")
        if not isinstance(segment.get("transcript_text"), str) or not segment.get("transcript_text", "").strip():
            errors.append(f"{prefix}.transcript_text must be non-empty")
        if segment.get("semantic_role") not in SEMANTIC_ROLES:
            errors.append(f"{prefix}.semantic_role is invalid")
        if segment.get("broll_need") not in {0, 1, 2, 3}:
            errors.append(f"{prefix}.broll_need must be 0..3")
        score_errors, score_total = _validate_broll_score(segment.get("broll_score"), f"{prefix}.broll_score")
        errors.extend(score_errors)
        if segment.get("speaker_dependency") not in SPEAKER_DEPENDENCIES:
            errors.append(f"{prefix}.speaker_dependency is invalid")
        if not isinstance(segment.get("evidence_required"), bool):
            errors.append(f"{prefix}.evidence_required must be boolean")
        route = segment.get("route")
        if route not in ROUTES:
            errors.append(f"{prefix}.route is invalid")
        if route == "KEEP_A_ROLL":
            if segment.get("shot_id") not in {None, ""}:
                errors.append(f"{prefix}.shot_id must be empty for KEEP_A_ROLL")
        else:
            if not isinstance(segment.get("shot_id"), str) or not segment.get("shot_id"):
                errors.append(f"{prefix}.shot_id is required for B-roll routes")
            if segment.get("broll_need", 0) < 2:
                errors.append(f"{prefix}.broll_need must be >= 2 when a B-roll route is selected")
            if score_total is not None and score_total < min_broll_score:
                errors.append(f"{prefix}.broll_score.total must be >= broll_budget.min_broll_score ({min_broll_score}) for a B-roll route")
        if route == "GENERATED_IMAGE" and segment.get("evidence_required") is True:
            errors.append(f"{prefix}: evidence_required content cannot use GENERATED_IMAGE")
        template_id = segment.get("template_id")
        if route == "KEEP_A_ROLL":
            if template_id not in {None, "", "NONE"}:
                errors.append(f"{prefix}.template_id must be NONE for KEEP_A_ROLL")
        elif template_id not in TEMPLATES:
            errors.append(f"{prefix}.template_id is invalid")
        if not isinstance(segment.get("route_reason"), str) or not segment.get("route_reason", "").strip():
            errors.append(f"{prefix}.route_reason must be non-empty")

    if len(unit_ids_seen) != len(set(unit_ids_seen)):
        errors.append("source_unit_ids may not be reused across segments")

    asset_ids: set[str] = set()
    for index, asset in enumerate(assets):
        prefix = f"assets[{index}]"
        if not isinstance(asset, dict):
            errors.append(f"{prefix} must be an object")
            continue
        asset_id = asset.get("asset_id")
        if not isinstance(asset_id, str) or not asset_id:
            errors.append(f"{prefix}.asset_id must be non-empty")
        elif asset_id in asset_ids:
            errors.append(f"duplicate asset_id: {asset_id}")
        else:
            asset_ids.add(asset_id)
        asset_type = asset.get("type")
        if asset_type not in ASSET_TYPES:
            errors.append(f"{prefix}.type is invalid")
        if asset.get("status") not in ASSET_STATUSES:
            errors.append(f"{prefix}.status is invalid")
        if not isinstance(asset.get("blocks_generation"), bool):
            errors.append(f"{prefix}.blocks_generation must be boolean")
        if not isinstance(asset.get("output_name"), str) or Path(asset.get("output_name", "")).name != asset.get("output_name"):
            errors.append(f"{prefix}.output_name must be a filename")
        elif Path(asset.get("output_name", "")).suffix.lower() not in IMAGE_EXTENSIONS:
            errors.append(f"{prefix}.output_name must be an image filename")
        source_path_value = asset.get("source_path")
        if asset_type in {"REAL_EVIDENCE", "EXISTING_MEDIA"}:
            if asset.get("status") == "provided":
                if not isinstance(source_path_value, str) or not source_path_value.strip():
                    errors.append(f"{prefix}.source_path is required when provided")
                elif check_files and plan_path is not None:
                    resolved = resolve_plan_path(plan_path, source_path_value)
                    if resolved is None or not resolved.is_file():
                        errors.append(f"{prefix}.source_path not found: {resolved}")
                    elif resolved.suffix.lower() not in IMAGE_EXTENSIONS:
                        errors.append(f"{prefix}.source_path must be a supported image")
            elif asset.get("status") == "missing" and asset.get("blocks_generation") is not True:
                errors.append(f"{prefix}.blocks_generation must be true for missing real assets")
        elif asset_type == "GENERATED_IMAGE":
            if not isinstance(asset.get("prompt"), str) or not asset.get("prompt", "").strip():
                errors.append(f"{prefix}.prompt is required for GENERATED_IMAGE")
            if asset.get("text_policy") != "no_text":
                errors.append(f"{prefix}.text_policy must be no_text for GENERATED_IMAGE")
            if asset.get("image_provider") not in IMAGE_PROVIDERS:
                errors.append(f"{prefix}.image_provider must be manual_chatgpt")
            if asset.get("generation_mode") not in GENERATION_MODES:
                errors.append(f"{prefix}.generation_mode must be manual_chatgpt")
            generation_status = asset.get("generation_status")
            if generation_status not in GENERATION_STATUSES:
                errors.append(f"{prefix}.generation_status is invalid")
            if asset.get("target_aspect_ratio") not in {"9:16", "16:9", "1:1"}:
                errors.append(f"{prefix}.target_aspect_ratio must be 9:16, 16:9, or 1:1")
            obsolete = sorted(key for key in ("provider", "model", "size", "quality") if key in asset)
            if obsolete:
                errors.append(f"{prefix} contains obsolete API fields: {', '.join(obsolete)}")
            if source_path_value not in {None, ""}:
                errors.append(f"{prefix}.source_path must be empty for manually generated assets; use generated_path")
            generated_path = asset.get("generated_path")
            if generation_status in {"planned", "prompt_ready", "waiting_user_generation"}:
                if asset.get("status") != "planned":
                    errors.append(f"{prefix}.status must be planned before the user imports an image")
                if generated_path not in {None, ""}:
                    errors.append(f"{prefix}.generated_path must be empty before user generation")
            elif generation_status in {"user_generated", "qa_passed", "inserted"}:
                if asset.get("status") != "provided":
                    errors.append(f"{prefix}.status must be provided after user generation")
                if not isinstance(generated_path, str) or not generated_path.strip():
                    errors.append(f"{prefix}.generated_path is required after user generation")
                elif check_files and plan_path is not None:
                    resolved = resolve_plan_path(plan_path, generated_path)
                    if resolved is None or not resolved.is_file():
                        errors.append(f"{prefix}.generated_path not found: {resolved}")
            elif generation_status == "rejected" and asset.get("status") != "rejected":
                errors.append(f"{prefix}.status must be rejected when generation_status=rejected")
            if asset.get("blocks_generation") is not False:
                errors.append(f"{prefix}.blocks_generation must be false for manual ChatGPT images")
        elif asset_type == "DETERMINISTIC_GRAPHIC":
            errors.extend(_validate_graphic_spec(asset.get("graphic_spec"), f"{prefix}.graphic_spec"))
        if asset.get("status") == "generated":
            generated_path = asset.get("generated_path")
            if not isinstance(generated_path, str) or not generated_path.strip():
                errors.append(f"{prefix}.generated_path is required when status=generated")
            elif check_files and plan_path is not None:
                resolved = resolve_plan_path(plan_path, generated_path)
                if resolved is None or not resolved.is_file():
                    errors.append(f"{prefix}.generated_path not found: {resolved}")

    shot_ids: set[str] = set()
    segment_by_id = indexed(segments, "segment_id")
    asset_by_id = indexed(assets, "asset_id")
    shot_ranges: list[tuple[float, float, str]] = []
    for index, shot in enumerate(shots):
        prefix = f"shots[{index}]"
        if not isinstance(shot, dict):
            errors.append(f"{prefix} must be an object")
            continue
        shot_id = shot.get("shot_id")
        if not isinstance(shot_id, str) or not shot_id:
            errors.append(f"{prefix}.shot_id must be non-empty")
        elif shot_id in shot_ids:
            errors.append(f"duplicate shot_id: {shot_id}")
        else:
            shot_ids.add(shot_id)
        segment = segment_by_id.get(str(shot.get("segment_id")))
        if not segment:
            errors.append(f"{prefix}.segment_id must reference a segment")
        elif segment.get("shot_id") != shot_id:
            errors.append(f"{prefix}: segment.shot_id must match shot_id")
        asset = asset_by_id.get(str(shot.get("asset_id")))
        if not asset:
            errors.append(f"{prefix}.asset_id must reference an asset")
        elif segment and segment.get("route") != asset.get("type"):
            errors.append(f"{prefix}: segment route must match asset type")
        start = shot.get("start_sec")
        end = shot.get("end_sec")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or not 0 <= float(start) < float(end):
            errors.append(f"{prefix} requires numeric start_sec < end_sec")
        else:
            start_value, end_value = float(start), float(end)
            shot_ranges.append((start_value, end_value, str(shot_id)))
            if segment and (start_value < float(segment.get("start_sec", start_value)) - 1e-6 or end_value > float(segment.get("end_sec", end_value)) + 1e-6):
                errors.append(f"{prefix} must stay inside its semantic segment")
            duration_value = shot.get("duration_sec")
            if not isinstance(duration_value, (int, float)) or abs(float(duration_value) - (end_value - start_value)) > 0.02:
                errors.append(f"{prefix}.duration_sec must equal end_sec - start_sec")
            duration_class = shot.get("duration_class")
            if duration_class not in DURATION_CLASSES:
                errors.append(f"{prefix}.duration_class is invalid")
            elif isinstance(duration_value, (int, float)):
                minimum, maximum = DURATION_CLASSES[duration_class]
                if not minimum - 0.02 <= float(duration_value) <= maximum + 0.02:
                    errors.append(f"{prefix}.duration_sec must be {minimum:g}..{maximum:g}s for duration_class={duration_class}")
        if shot.get("composition") != "fullscreen_replace":
            errors.append(f"{prefix}.composition must be fullscreen_replace")
        if shot.get("motion_preset") not in MOTION_PRESETS:
            errors.append(f"{prefix}.motion_preset is invalid")
        transition = shot.get("transition_sec")
        if not isinstance(transition, (int, float)) or not 0 <= float(transition) <= 0.5:
            errors.append(f"{prefix}.transition_sec must be 0..0.5")
        if shot.get("approval") not in SHOT_APPROVALS:
            errors.append(f"{prefix}.approval is invalid")
        if shot.get("qa_status") not in QA_STATUSES:
            errors.append(f"{prefix}.qa_status is invalid")
        if shot.get("qa_status") == "accepted":
            qa_hash = shot.get("qa_asset_sha256")
            if not isinstance(qa_hash, str) or len(qa_hash) != 64:
                errors.append(f"{prefix}.qa_asset_sha256 is required after QA acceptance")
            if asset and asset.get("type") == "GENERATED_IMAGE" and asset.get("generation_status") not in {"qa_passed", "inserted"}:
                errors.append(f"{prefix}: accepted manual image must have generation_status=qa_passed or inserted")
        if shot.get("edit_status") not in EDIT_STATUSES:
            errors.append(f"{prefix}.edit_status is invalid")
        elif shot.get("edit_status") == "inserted":
            if shot.get("qa_status") != "accepted":
                errors.append(f"{prefix}: inserted shot must have qa_status=accepted")
            if shot.get("render_status") != "rendered":
                errors.append(f"{prefix}: inserted shot must have render_status=rendered")
        output_name = shot.get("output_name")
        if not isinstance(output_name, str) or not output_name.lower().endswith(".mp4") or Path(output_name).name != output_name:
            errors.append(f"{prefix}.output_name must be an MP4 filename")
        if shot.get("approval") == "approved":
            if not shot.get("approval_fingerprint"):
                errors.append(f"{prefix}.approval_fingerprint is required when approved")
            elif not approval_is_intact(plan, shot):
                errors.append(f"{prefix}.approval_fingerprint no longer matches the plan")

    shot_ranges.sort()
    for previous, current in zip(shot_ranges, shot_ranges[1:]):
        if current[0] < previous[1] - 1e-6:
            errors.append(f"overlapping shot ranges: {previous[2]} and {current[2]}")

    for index, asset in enumerate(assets):
        if not isinstance(asset, dict) or asset.get("type") != "GENERATED_IMAGE":
            continue
        prefix = f"assets[{index}]"
        state = asset.get("generation_status")
        related = [shot for shot in shots if isinstance(shot, dict) and str(shot.get("asset_id")) == str(asset.get("asset_id"))]
        if not related:
            errors.append(f"{prefix}: GENERATED_IMAGE must be referenced by a shot")
            continue
        if state in {"planned", "prompt_ready", "waiting_user_generation", "user_generated"}:
            if any(shot.get("qa_status") == "accepted" or shot.get("edit_status") == "inserted" for shot in related):
                errors.append(f"{prefix}: generation_status={state} cannot have accepted or inserted shots")
        elif state == "qa_passed":
            if any(shot.get("qa_status") != "accepted" for shot in related):
                errors.append(f"{prefix}: generation_status=qa_passed requires every related shot to pass QA")
        elif state == "inserted":
            if any(shot.get("qa_status") != "accepted" for shot in related):
                errors.append(f"{prefix}: generation_status=inserted requires every related shot to pass QA")
            if not any(shot.get("edit_status") == "inserted" for shot in related):
                errors.append(f"{prefix}: generation_status=inserted requires an inserted shot")

    for index, segment in enumerate(segments):
        shot_id = segment.get("shot_id") if isinstance(segment, dict) else None
        if shot_id and shot_id not in shot_ids:
            errors.append(f"segments[{index}].shot_id references unknown shot: {shot_id}")

    if len(shots) > max_total_broll:
        errors.append(f"broll budget allows at most {max_total_broll} total shots")
    generated_image_count = sum(1 for asset in assets if isinstance(asset, dict) and asset.get("type") == "GENERATED_IMAGE")
    if generated_image_count > max_generated_images:
        errors.append(f"broll budget allows at most {max_generated_images} manually generated images")

    if profile_name in PROFILES and source_duration > 0:
        max_shots = math.ceil(source_duration / 60.0 * PROFILES[profile_name]["max_shots_per_minute"])
        if len(shots) > max_shots:
            errors.append(f"profile {profile_name} allows at most {max_shots} shots for this duration")
        total_coverage = sum(max(0.0, end - start) for start, end, _ in shot_ranges)
        coverage_ratio = total_coverage / source_duration
        if coverage_ratio > PROFILES[profile_name]["max_coverage_ratio"] + 1e-6:
            errors.append(
                f"profile {profile_name} coverage ratio {coverage_ratio:.3f} exceeds "
                f"{PROFILES[profile_name]['max_coverage_ratio']:.2f}"
            )

    approval = plan.get("approval")
    if not isinstance(approval, dict):
        errors.append("approval must be an object")
    else:
        if approval.get("status") not in PLAN_APPROVALS:
            errors.append("approval.status is invalid")
        approved_shots = approval.get("approved_shots")
        if not isinstance(approved_shots, list) or any(not isinstance(item, str) for item in approved_shots):
            errors.append("approval.approved_shots must be a string array")
        else:
            unknown = sorted(set(approved_shots) - shot_ids)
            if unknown:
                errors.append("approval.approved_shots contains unknown IDs: " + ", ".join(unknown))
            inconsistent = sorted(
                shot_id
                for shot_id in approved_shots
                if indexed(shots, "shot_id").get(shot_id, {}).get("approval") != "approved"
            )
            if inconsistent:
                errors.append("approval.approved_shots contains non-approved shots: " + ", ".join(inconsistent))

    edit = plan.get("edit")
    if not isinstance(edit, dict):
        errors.append("edit must be an object")
    else:
        if edit.get("enabled") is not True:
            errors.append("edit.enabled must be true")
        if edit.get("preserve_source_audio") is not True:
            errors.append("edit.preserve_source_audio must be true")
        output_name = edit.get("output_name")
        if not isinstance(output_name, str) or not output_name.lower().endswith(".mp4") or Path(output_name).name != output_name:
            errors.append("edit.output_name must be an MP4 filename")

    return errors
