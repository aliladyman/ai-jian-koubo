#!/usr/bin/env python3
"""Schema constants for the Image B-roll Agent."""

import re

SCHEMA_VERSION = "0.2"
ROUTES = {"KEEP_A_ROLL", "REAL_EVIDENCE", "EXISTING_MEDIA", "DETERMINISTIC_GRAPHIC", "GENERATED_IMAGE"}
ASSET_TYPES = {"REAL_EVIDENCE", "EXISTING_MEDIA", "DETERMINISTIC_GRAPHIC", "GENERATED_IMAGE"}
ASSET_STATUSES = {"missing", "planned", "provided", "generated", "rejected"}
GENERATION_STATUSES = {
    "planned",
    "prompt_ready",
    "waiting_user_generation",
    "user_generated",
    "qa_passed",
    "inserted",
    "rejected",
}
IMAGE_PROVIDERS = {"manual_chatgpt"}
GENERATION_MODES = {"manual_chatgpt"}
SHOT_APPROVALS = {"pending", "approved", "rejected"}
PLAN_APPROVALS = {"pending", "partially_approved", "approved", "rejected"}
QA_STATUSES = {"pending", "accepted", "rejected"}
EDIT_STATUSES = {"pending", "inserted"}
PROFILES = {
    "simple": {"max_shots_per_minute": 5, "max_coverage_ratio": 0.30},
    "balanced": {"max_shots_per_minute": 8, "max_coverage_ratio": 0.42},
    "rich": {"max_shots_per_minute": 12, "max_coverage_ratio": 0.58},
}
BROLL_BUDGET_LIMITS = {
    "max_total_broll": 8,
    "max_generated_images": 5,
}
BROLL_SCORE_FIELDS = ("visual_value", "comprehension_gain", "rhythm_gain", "generation_cost")
DURATION_CLASSES = {
    "short_point": (2.0, 4.0),
    "concept_explanation": (5.0, 8.0),
    "process_explanation": (8.0, 12.0),
    "chapter_transition": (2.5, 3.5),
}
TEMPLATES = {
    "I01_STATEMENT_CARD", "I02_CONCEPT_HERO", "I03_NUMBER_IMPACT", "I04_EVIDENCE_FRAME",
    "I05_RELATION_FLOW", "I06_SPLIT_COMPARISON", "I07_TIMELINE_TAXONOMY", "I08_CINEMATIC_METAPHOR",
}
MOTION_PRESETS = {"static_hold", "slow_push", "slow_pull", "pan_left", "pan_right", "diagonal_push"}
SEMANTIC_ROLES = {"hook", "problem", "concept", "comparison", "process", "evidence", "example", "number", "emotion", "conclusion", "cta", "other"}
SPEAKER_DEPENDENCIES = {"high", "medium", "low"}
CONFIRMATION = "CONFIRM_BROLL_PLAN"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
SECRET_KEYS = re.compile(r"(api[_-]?key|authorization|access[_-]?token|secret)", re.I)
