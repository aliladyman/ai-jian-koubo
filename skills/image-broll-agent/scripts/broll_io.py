#!/usr/bin/env python3
"""I/O, environment, hashing, and media helpers."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from broll_constants import SECRET_KEYS


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_command(name: str) -> str:
    value = shutil.which(name)
    if not value:
        raise RuntimeError(f"required command not found: {name}")
    return value


def probe_media(path: Path) -> dict[str, Any]:
    require_command("ffprobe")
    if not path.is_file():
        raise ValueError(f"media file not found: {path}")
    command = ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=index,codec_type,width,height,avg_frame_rate,r_frame_rate", "-of", "json", str(path)]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise RuntimeError("ffprobe returned invalid JSON")
    return value


def has_audio(media: dict[str, Any]) -> bool:
    return any(stream.get("codec_type") == "audio" for stream in media.get("streams", []))


def video_stream(media: dict[str, Any]) -> dict[str, Any]:
    for stream in media.get("streams", []):
        if stream.get("codec_type") == "video":
            return stream
    raise ValueError("media has no video stream")


def parse_rate(value: str | None, default: float = 30.0) -> float:
    if not value or value in {"0/0", "N/A"}:
        return default
    try:
        numerator, denominator = value.split("/", 1)
        result = float(numerator) / float(denominator)
        return result if math.isfinite(result) and result > 0 else default
    except (ValueError, ZeroDivisionError):
        return default


def media_summary(path: Path) -> dict[str, Any]:
    media = probe_media(path)
    stream = video_stream(media)
    duration = float(media.get("format", {}).get("duration") or 0)
    width, height = int(stream.get("width") or 0), int(stream.get("height") or 0)
    if duration <= 0 or width <= 0 or height <= 0:
        raise ValueError("invalid media metadata")
    fps = parse_rate(stream.get("avg_frame_rate") or stream.get("r_frame_rate"))
    return {"duration_sec": round(duration, 3), "width": width, "height": height, "fps": round(fps, 3), "has_audio": has_audio(media)}


def resolve_plan_path(plan_path: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    return (path if path.is_absolute() else plan_path.parent / path).resolve()


def find_secrets(value: Any, trail: str = "root") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if SECRET_KEYS.search(str(key)):
                found.append(f"{trail}.{key}")
            found.extend(find_secrets(child, f"{trail}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(find_secrets(child, f"{trail}[{index}]"))
    return found


def indexed(items: Iterable[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {str(item.get(key)): item for item in items if isinstance(item, dict) and item.get(key)}


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() and key.strip() not in os.environ:
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


def load_skill_env() -> None:
    load_env_file(skill_root() / ".env")


def find_parent_skill() -> Path:
    load_skill_env()
    candidates = []
    configured = os.environ.get("AI_JIAN_KOUBO_DIR", "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())
    current = Path(__file__).resolve()
    if len(current.parents) >= 4:
        candidates.append(current.parents[3])
    for candidate in candidates:
        resolved = candidate.resolve()
        if (resolved / "scripts" / "run_transcribe.sh").is_file():
            return resolved
    raise ValueError("AI剪口播父 Skill 未找到；请设置 AI_JIAN_KOUBO_DIR")
