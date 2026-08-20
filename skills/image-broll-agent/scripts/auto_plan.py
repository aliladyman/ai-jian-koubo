#!/usr/bin/env python3
"""Build a conservative, deterministic Image B-roll plan from transcript context."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

from broll_lib import now_iso, save_json, validate_plan


EVIDENCE_TERMS = ("官方", "论文", "研究", "报告", "数据显示", "数据表明", "来源", "引用", "文档", "新闻", "截图", "网页", "测评结果")
PROCESS_TERMS = ("第一", "第二", "第三", "首先", "然后", "接着", "最后", "步骤", "流程", "先", "再")
COMPARISON_TERMS = ("相比", "对比", "区别", "不同", "而不是", "不是", "一边", "另一边", "优点", "缺点", "更适合")
CONCLUSION_TERMS = ("所以", "因此", "总结", "最终", "核心是", "结论", "这就是", "换句话说")
CTA_TERMS = ("关注", "点赞", "评论", "收藏", "转发", "试试看", "你也可以")
PERSONAL_TERMS = ("我觉得", "我认为", "我的", "我用", "我试", "亲测", "我的经验", "我建议")
ABSTRACT_TERMS = ("像", "就像", "仿佛", "想象", "未来", "空间", "世界", "大脑", "助手", "管家", "经理", "中枢", "生态")
QUESTION_TERMS = ("为什么", "怎么", "如何", "有没有", "是不是", "吗", "？", "?")

PROFILE_LIMITS = {"simple": 5, "balanced": 8, "rich": 8}


def contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def merge_units(units: list[dict]) -> list[dict]:
    """Merge only short adjacent atoms; keep source text and boundaries unchanged."""
    beats: list[dict] = []
    current: list[dict] = []

    def flush() -> None:
        nonlocal current
        if not current:
            return
        beats.append({
            "source_unit_ids": [str(item["unit_id"]) for item in current],
            "start_sec": round(float(current[0]["start_sec"]), 3),
            "end_sec": round(float(current[-1]["end_sec"]), 3),
            "transcript_text": "".join(str(item.get("text", "")) for item in current),
        })
        current = []

    for unit in units:
        if not current:
            current = [unit]
            continue
        start = float(current[0]["start_sec"])
        candidate_end = float(unit["end_sec"])
        current_duration = float(current[-1]["end_sec"]) - start
        candidate_duration = candidate_end - start
        current_text = "".join(str(item.get("text", "")) for item in current)
        should_merge = (
            current_duration < 2.5
            or (candidate_duration <= 8.0 and not current_text.rstrip().endswith(("。", "！", "？", "!", "?", "；", ";")))
            or (candidate_duration <= 10.0 and contains_any(current_text, PROCESS_TERMS))
        )
        if should_merge and candidate_duration <= 12.0:
            current.append(unit)
        else:
            flush()
            current = [unit]
    flush()
    return beats


def classify(text: str, index: int, start_sec: float) -> tuple[str, bool, str]:
    evidence = contains_any(text, EVIDENCE_TERMS)
    if evidence:
        return "evidence", True, "low"
    if index == 0 and start_sec < 10 and contains_any(text, QUESTION_TERMS):
        return "hook", False, "high"
    if contains_any(text, CTA_TERMS):
        return "cta", False, "high"
    if contains_any(text, CONCLUSION_TERMS):
        return "conclusion", False, "high"
    if contains_any(text, PERSONAL_TERMS):
        return "emotion", False, "high"
    if contains_any(text, PROCESS_TERMS):
        return "process", False, "low"
    if contains_any(text, COMPARISON_TERMS):
        return "comparison", False, "low"
    if re.search(r"\d+(?:\.\d+)?\s*(?:%|％|万|亿|倍|个|次|天|小时|分钟|秒|元)?", text):
        return "number", False, "low"
    if "例如" in text or "比如" in text or "举个例" in text:
        return "example", False, "medium"
    if contains_any(text, QUESTION_TERMS):
        return "problem", False, "high"
    if any(term in text for term in ("就是", "叫做", "指的是", "本质", "概念", "AI", "Agent", "Skill", "工具")):
        return "concept", False, "medium"
    return "other", False, "medium"


def route_for(role: str, text: str, evidence: bool, speaker_dependency: str, duration: float) -> str:
    if evidence:
        return "REAL_EVIDENCE"
    if speaker_dependency == "high":
        return "KEEP_A_ROLL"
    if duration < 2.0:
        return "KEEP_A_ROLL"
    if role in {"comparison", "process", "number"}:
        return "DETERMINISTIC_GRAPHIC"
    if role in {"concept", "example"} and contains_any(text, ABSTRACT_TERMS):
        return "GENERATED_IMAGE"
    if role == "concept" and len(text) >= 18:
        return "DETERMINISTIC_GRAPHIC"
    return "KEEP_A_ROLL"


def score_for(route: str, role: str) -> dict[str, int]:
    if route == "REAL_EVIDENCE":
        values = (8, 10, 4, 2)
    elif route == "DETERMINISTIC_GRAPHIC":
        values = (8, 9 if role in {"process", "comparison"} else 8, 5, 2)
    elif route == "GENERATED_IMAGE":
        values = (8, 7, 5, 5)
    else:
        values = (3, 2, 2, 0)
    visual, comprehension, rhythm, cost = values
    return {
        "visual_value": visual,
        "comprehension_gain": comprehension,
        "rhythm_gain": rhythm,
        "generation_cost": cost,
        "total": visual + comprehension + rhythm - cost,
    }


def desired_shot_count(profile: str, duration_sec: float) -> int:
    coverage_limit = {"simple": 0.30, "balanced": 0.42, "rich": 0.58}[profile]
    if duration_sec * coverage_limit < 2.0:
        return 0
    per_minute = {"simple": 2.2, "balanced": 3.0, "rich": 4.0}[profile]
    return max(1, min(PROFILE_LIMITS[profile], int(math.ceil(duration_sec / 60.0 * per_minute))))


def choose_candidates(candidates: list[dict], limit: int, generated_limit: int) -> set[int]:
    selected: list[dict] = []
    generated = 0
    for candidate in sorted(candidates, key=lambda item: (-item["score"]["total"], item["start_sec"])):
        if len(selected) >= limit:
            break
        if candidate["route"] == "GENERATED_IMAGE" and generated >= generated_limit:
            continue
        # Avoid a burst of near-adjacent overlays even when every segment scores highly.
        if any(abs(candidate["start_sec"] - item["start_sec"]) < 4.0 for item in selected):
            continue
        selected.append(candidate)
        if candidate["route"] == "GENERATED_IMAGE":
            generated += 1
    return {int(item["index"]) for item in selected}


def compact_parts(text: str, limit: int = 4) -> list[str]:
    cleaned = re.sub(r"[。！？!?；;]", "，", text)
    parts = [part.strip(" ，、：:") for part in re.split(r"，|、|然后|接着|最后|其次", cleaned) if part.strip(" ，、：:")]
    return [part[:16] for part in parts[:limit]]


def graphic_spec(role: str, text: str) -> tuple[str, dict]:
    if role == "number":
        match = re.search(r"\d+(?:\.\d+)?\s*(?:%|％|万|亿|倍|个|次|天|小时|分钟|秒|元)?", text)
        number = match.group(0).strip() if match else "关键数字"
        label = text.replace(number, "").strip("，。！？ ：:")[:18] or "核心数据"
        return "I03_NUMBER_IMPACT", {"kind": "number", "number": number, "label": label}
    if role == "comparison":
        parts = compact_parts(text, 2)
        if len(parts) >= 2:
            return "I06_SPLIT_COMPARISON", {"kind": "split", "left": parts[0], "right": parts[1]}
    if role == "process":
        parts = compact_parts(text, 4)
        if len(parts) >= 2:
            return "I05_RELATION_FLOW", {"kind": "relation", "steps": parts}
    return "I01_STATEMENT_CARD", {"kind": "statement", "title": text.strip("。！？!?")[:24]}


def manual_prompt(text: str, aspect: str, style: str) -> str:
    framing = "vertical" if aspect == "9:16" else "horizontal" if aspect == "16:9" else "square"
    subject = text.strip().replace("\n", " ")[:80]
    return (
        f"Create a realistic editorial photograph that visualizes this idea: {subject}. "
        f"Use a concrete physical scene, documentary lighting, restrained {style.replace('_', ' ')} styling, "
        f"clear foreground and background separation, {framing} composition, and keep the main subject inside the central 70% safe area. "
        "No readable text, no letters, no numbers, no logos, no watermark, no user interface, no charts, "
        "no fake documents, no fake screenshots, and no claim of being real evidence."
    )


def shot_timing(start: float, end: float, role: str) -> tuple[float, float, str]:
    available = end - start
    if role == "process" and available >= 8.0:
        duration_class, duration = "process_explanation", min(12.0, available)
    elif available >= 5.0:
        duration_class, duration = "concept_explanation", min(8.0, available)
    else:
        duration_class, duration = "short_point", min(4.0, available)
    duration = round(duration, 3)
    return round(start, 3), round(start + duration, 3), duration_class


def update_run_state(output_path: Path, plan: dict) -> None:
    root = output_path.parent.parent if output_path.parent.name == "2_B-roll方案" else output_path.parent
    state_path = root / "broll-handoff-state.json"
    state: dict = {}
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {}
    state.update({
        "schema_version": "1",
        "state": "awaiting_broll_approval",
        "updated_at": now_iso(),
        "artifacts": {
            **(state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}),
            "broll_plan": str(output_path.resolve()),
            "transcript_context": str(Path(plan["source"]["transcript_context_path"]).resolve()),
        },
    })
    save_json(state_path, state)


def build_plan(context: dict, context_path: Path, profile: str, visual_style: str, project_name: str | None) -> dict:
    source = dict(context["source"])
    units = context.get("units")
    if not isinstance(units, list) or not units:
        raise ValueError("transcript context contains no units")
    beats = merge_units(units)
    candidates: list[dict] = []
    analyses: list[dict] = []
    for index, beat in enumerate(beats):
        text = beat["transcript_text"]
        duration = float(beat["end_sec"]) - float(beat["start_sec"])
        role, evidence, dependency = classify(text, index, float(beat["start_sec"]))
        route = route_for(role, text, evidence, dependency, duration)
        score = score_for(route, role)
        item = {**beat, "index": index, "role": role, "evidence": evidence, "dependency": dependency, "route": route, "score": score}
        analyses.append(item)
        if route != "KEEP_A_ROLL" and score["total"] >= 12:
            candidates.append(item)

    max_total = min(8, desired_shot_count(profile, float(source["duration_sec"])))
    selected = choose_candidates(candidates, max_total, 5)
    aspect = "16:9" if int(source["width"]) > int(source["height"]) else "9:16" if int(source["height"]) > int(source["width"]) else "1:1"
    segments: list[dict] = []
    assets: list[dict] = []
    shots: list[dict] = []
    shot_number = 0

    for item in analyses:
        chosen = item["index"] in selected
        route = item["route"] if chosen else "KEEP_A_ROLL"
        score = item["score"] if chosen else score_for("KEEP_A_ROLL", item["role"])
        shot_id = None
        template_id = "NONE"
        route_reason = "保留真人表达，避免低价值或过密的 B-roll"
        if chosen:
            shot_number += 1
            shot_id = f"B{shot_number:03d}"
            asset_id = f"A{shot_number:03d}"
            output_name = f"{shot_id}.png"
            if route == "REAL_EVIDENCE":
                template_id = "I04_EVIDENCE_FRAME"
                route_reason = "原文包含来源、研究或真实数据，必须使用可核验截图"
                asset = {
                    "asset_id": asset_id, "type": route, "status": "missing", "blocks_generation": True,
                    "description": f"为“{item['transcript_text'][:32]}”提供可核验的官方/原始截图",
                    "output_name": output_name, "source_path": None, "generated_path": None,
                }
            elif route == "DETERMINISTIC_GRAPHIC":
                template_id, spec = graphic_spec(item["role"], item["transcript_text"])
                route_reason = "精确数字、流程或对比关系适合本地确定性图形"
                asset = {
                    "asset_id": asset_id, "type": route, "status": "planned", "blocks_generation": False,
                    "description": item["transcript_text"][:48], "output_name": output_name,
                    "source_path": None, "generated_path": None, "graphic_spec": spec,
                }
            else:
                template_id = "I08_CINEMATIC_METAPHOR"
                route_reason = "抽象概念适合少量无字场景图，不承担事实证明"
                asset = {
                    "asset_id": asset_id, "type": route, "status": "planned", "generation_status": "planned",
                    "blocks_generation": False, "description": item["transcript_text"][:48], "output_name": output_name,
                    "source_path": None, "generated_path": None,
                    "prompt": manual_prompt(item["transcript_text"], aspect, visual_style),
                    "text_policy": "no_text", "image_provider": "manual_chatgpt",
                    "generation_mode": "manual_chatgpt", "target_aspect_ratio": aspect,
                }
            assets.append(asset)
            shot_start, shot_end, duration_class = shot_timing(float(item["start_sec"]), float(item["end_sec"]), item["role"])
            shots.append({
                "shot_id": shot_id, "segment_id": f"S{item['index'] + 1:03d}", "asset_id": asset_id,
                "start_sec": shot_start, "end_sec": shot_end, "duration_sec": round(shot_end - shot_start, 3),
                "duration_class": duration_class, "composition": "fullscreen_replace",
                "motion_preset": "static_hold" if route in {"REAL_EVIDENCE", "DETERMINISTIC_GRAPHIC"} else "slow_push",
                "transition_sec": 0.12, "approval": "pending", "approval_fingerprint": None,
                "qa_status": "pending", "edit_status": "pending", "output_name": f"{shot_id}.mp4",
            })

        segments.append({
            "segment_id": f"S{item['index'] + 1:03d}", "source_unit_ids": item["source_unit_ids"],
            "start_sec": item["start_sec"], "end_sec": item["end_sec"], "transcript_text": item["transcript_text"],
            "semantic_role": item["role"], "broll_need": 3 if chosen and route != "GENERATED_IMAGE" else 2 if chosen else 0,
            "broll_score": score, "speaker_dependency": item["dependency"], "evidence_required": bool(item["evidence"]),
            "route": route, "template_id": template_id, "route_reason": route_reason,
            "shot_id": shot_id, "aigc_disclosure_required": route == "GENERATED_IMAGE",
        })

    name = project_name or Path(source["video_path"]).stem
    return {
        "schema_version": "0.2", "project": {"name": name, "created_at": now_iso()},
        "source": {
            "video_path": source["video_path"], "video_sha256": source["video_sha256"],
            "duration_sec": source["duration_sec"], "width": int(source["width"]), "height": int(source["height"]),
            "fps": source["fps"], "timebase": "seconds", "transcript_provider": "volcengine",
            "transcript_context_path": str(context_path.resolve()),
        },
        "profile": {"name": profile, "visual_style": visual_style},
        "broll_budget": {"designed_for_video_sec": {"min": 120, "max": 180}, "max_total_broll": max_total, "max_generated_images": min(5, max_total), "min_broll_score": 12},
        "defaults": {"image_provider": "manual_chatgpt", "generation_mode": "manual_chatgpt", "target_aspect_ratio": aspect, "motion_preset": "slow_push", "transition_sec": 0.12},
        "segments": segments, "assets": assets, "shots": shots,
        "approval": {"status": "pending", "approved_shots": [], "confirmation": None, "approved_at": None},
        "edit": {"enabled": True, "preserve_source_audio": True, "output_name": f"{name}_with_broll.mp4"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("context", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=("simple", "balanced", "rich"), default="balanced")
    parser.add_argument("--visual-style", default="clean_editorial")
    parser.add_argument("--project-name")
    args = parser.parse_args()
    try:
        context_path = args.context.expanduser().resolve()
        output_path = args.output.expanduser().resolve()
        context = json.loads(context_path.read_text(encoding="utf-8"))
        plan = build_plan(context, context_path, args.profile, args.visual_style, args.project_name)
        errors = validate_plan(plan, plan_path=output_path, check_files=False)
        if errors:
            raise ValueError("auto plan failed validation:\n- " + "\n- ".join(errors))
        save_json(output_path, plan)
        update_run_state(output_path, plan)
        print(f"AUTO_PLAN_WRITTEN: {output_path}")
        print(f"SEGMENTS: {len(plan['segments'])}")
        print(f"SHOTS: {len(plan['shots'])}/{plan['broll_budget']['max_total_broll']}")
        print(f"MANUAL_CHATGPT_IMAGES: {sum(1 for asset in plan['assets'] if asset['type'] == 'GENERATED_IMAGE')}/{plan['broll_budget']['max_generated_images']}")
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
