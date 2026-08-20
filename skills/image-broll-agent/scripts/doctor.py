#!/usr/bin/env python3
"""Check local dependencies and credentials for the Image B-roll Agent."""

from __future__ import annotations

import shutil

from broll_lib import find_parent_skill, load_skill_env, skill_root


def status(ok: bool, message: str) -> None:
    print(("✅ " if ok else "❌ ") + message)


def main() -> int:
    load_skill_env()
    failures = 0
    for command in ("python3", "ffmpeg", "ffprobe", "bash", "curl"):
        found = shutil.which(command)
        status(found is not None, f"{command}: {found or '未安装'}")
        failures += int(found is None)

    try:
        import PIL  # noqa: F401
        status(True, "Pillow: 已安装")
    except ImportError:
        status(False, "Pillow: 未安装（运行 pip install -r requirements.txt）")
        failures += 1

    try:
        parent = find_parent_skill()
        status(True, f"父 Skill: {parent}")
    except ValueError as exc:
        status(False, str(exc))
        failures += 1

    status(True, "生图方式: 用户在 ChatGPT 内手工生成（无需 OpenAI API Key）")
    status((skill_root() / "SKILL.md").is_file(), f"Skill 入口: {skill_root() / 'SKILL.md'}")

    if failures:
        print(f"\n共有 {failures} 项未通过。")
        return 1
    print("\n环境检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
