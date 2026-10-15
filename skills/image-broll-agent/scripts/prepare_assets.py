#!/usr/bin/env python3
"""Render deterministic graphic assets for approved B-roll shots."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

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


def find_font() -> Path:
    configured = os.environ.get("BROLL_FONT_PATH", "").strip()
    candidates = [
        configured,
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
    ]
    for value in candidates:
        if value and Path(value).expanduser().is_file():
            return Path(value).expanduser().resolve()
    raise RuntimeError("no usable font found; set BROLL_FONT_PATH to a Chinese font file")


def font(path: Path, size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size=max(12, size), index=index)


def wrap_text(draw: ImageDraw.ImageDraw, text: str, text_font: ImageFont.FreeTypeFont, max_width: float) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        if current and draw.textlength(candidate, font=text_font) > max_width:
            lines.append(current)
            current = char
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def draw_centered_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    center_x: float,
    center_y: float,
    text_font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    spacing: int,
) -> tuple[int, int, int, int]:
    boxes = [draw.textbbox((0, 0), line, font=text_font) for line in lines]
    heights = [box[3] - box[1] for box in boxes]
    widths = [box[2] - box[0] for box in boxes]
    total_height = sum(heights) + spacing * max(0, len(lines) - 1)
    y = center_y - total_height / 2
    min_x, min_y, max_x, max_y = 10**9, 10**9, 0, 0
    for line, width, height in zip(lines, widths, heights):
        x = center_x - width / 2
        draw.text((x, y), line, font=text_font, fill=fill)
        min_x, min_y = min(min_x, int(x)), min(min_y, int(y))
        max_x, max_y = max(max_x, int(x + width)), max(max_y, int(y + height))
        y += height + spacing
    return min_x, min_y, max_x, max_y


def palette(style: str) -> dict[str, tuple[int, int, int]]:
    if style == "paper_archive":
        return {
            "bg": (238, 232, 219),
            "fg": (24, 23, 21),
            "muted": (110, 103, 92),
            "panel": (250, 246, 236),
            "accent": (197, 55, 43),
            "line": (164, 154, 137),
        }
    if style == "minimal_tech":
        return {
            "bg": (9, 16, 24),
            "fg": (236, 244, 250),
            "muted": (128, 151, 168),
            "panel": (19, 31, 43),
            "accent": (54, 183, 182),
            "line": (67, 91, 108),
        }
    return {
        "bg": (18, 18, 20),
        "fg": (242, 239, 232),
        "muted": (151, 147, 138),
        "panel": (31, 31, 34),
        "accent": (235, 91, 59),
        "line": (83, 81, 77),
    }


def render_statement(image: Image.Image, draw: ImageDraw.ImageDraw, spec: dict, fonts: dict, colors: dict) -> None:
    width, height = image.size
    title = spec["title"]
    lines = wrap_text(draw, title, fonts["title"], width * 0.72)
    box = draw_centered_lines(draw, lines, width / 2, height * 0.48, fonts["title"], colors["fg"], int(height * 0.015))
    underline_y = box[3] + int(height * 0.035)
    draw.rounded_rectangle(
        (width * 0.29, underline_y, width * 0.71, underline_y + max(6, int(height * 0.006))),
        radius=8,
        fill=colors["accent"],
    )
    subtitle = spec.get("subtitle")
    if subtitle:
        sub_lines = wrap_text(draw, str(subtitle), fonts["small"], width * 0.65)
        draw_centered_lines(draw, sub_lines, width / 2, underline_y + height * 0.09, fonts["small"], colors["muted"], 8)


def render_number(image: Image.Image, draw: ImageDraw.ImageDraw, spec: dict, fonts: dict, colors: dict) -> None:
    width, height = image.size
    number = str(spec["number"])
    label = str(spec["label"])
    unit = str(spec.get("unit", ""))
    number_box = draw.textbbox((0, 0), number, font=fonts["number"])
    number_width = number_box[2] - number_box[0]
    draw.text(((width - number_width) / 2, height * 0.31), number, font=fonts["number"], fill=colors["accent"])
    if unit:
        unit_box = draw.textbbox((0, 0), unit, font=fonts["small"])
        draw.text((width / 2 + number_width / 2 + width * 0.02, height * 0.41), unit, font=fonts["small"], fill=colors["muted"])
    label_lines = wrap_text(draw, label, fonts["subtitle"], width * 0.72)
    draw_centered_lines(draw, label_lines, width / 2, height * 0.64, fonts["subtitle"], colors["fg"], 10)


def rounded_node(draw: ImageDraw.ImageDraw, box: tuple[float, float, float, float], text: str, text_font, colors: dict) -> None:
    draw.rounded_rectangle(box, radius=int(min(box[2] - box[0], box[3] - box[1]) * 0.12), fill=colors["panel"], outline=colors["line"], width=2)
    lines = wrap_text(draw, text, text_font, (box[2] - box[0]) * 0.78)
    draw_centered_lines(draw, lines, (box[0] + box[2]) / 2, (box[1] + box[3]) / 2, text_font, colors["fg"], 6)


def render_relation(image: Image.Image, draw: ImageDraw.ImageDraw, spec: dict, fonts: dict, colors: dict) -> None:
    width, height = image.size
    steps = [str(item) for item in spec["steps"]]
    portrait = height >= width
    if portrait:
        node_width, node_height = width * 0.66, height * 0.12
        x0 = (width - node_width) / 2
        gap = height * 0.06
        total = len(steps) * node_height + (len(steps) - 1) * gap
        y0 = (height - total) / 2
        boxes = [(x0, y0 + i * (node_height + gap), x0 + node_width, y0 + i * (node_height + gap) + node_height) for i in range(len(steps))]
        for index, (step, box) in enumerate(zip(steps, boxes)):
            rounded_node(draw, box, step, fonts["node"], colors)
            if index < len(boxes) - 1:
                x = width / 2
                start_y = box[3] + height * 0.012
                end_y = boxes[index + 1][1] - height * 0.012
                draw.line((x, start_y, x, end_y), fill=colors["accent"], width=max(4, int(width * 0.005)))
                draw.polygon([(x, end_y), (x - width * 0.012, end_y - height * 0.012), (x + width * 0.012, end_y - height * 0.012)], fill=colors["accent"])
    else:
        node_width, node_height = width * 0.18, height * 0.22
        gap = width * 0.055
        total = len(steps) * node_width + (len(steps) - 1) * gap
        x0 = (width - total) / 2
        y0 = (height - node_height) / 2
        boxes = [(x0 + i * (node_width + gap), y0, x0 + i * (node_width + gap) + node_width, y0 + node_height) for i in range(len(steps))]
        for index, (step, box) in enumerate(zip(steps, boxes)):
            rounded_node(draw, box, step, fonts["node"], colors)
            if index < len(boxes) - 1:
                start_x = box[2] + width * 0.01
                end_x = boxes[index + 1][0] - width * 0.01
                y = height / 2
                draw.line((start_x, y, end_x, y), fill=colors["accent"], width=max(4, int(height * 0.007)))
                draw.polygon([(end_x, y), (end_x - width * 0.012, y - height * 0.018), (end_x - width * 0.012, y + height * 0.018)], fill=colors["accent"])


def render_split(image: Image.Image, draw: ImageDraw.ImageDraw, spec: dict, fonts: dict, colors: dict) -> None:
    width, height = image.size
    margin = width * 0.08
    gap = width * 0.035
    panel_width = (width - 2 * margin - gap) / 2
    top, bottom = height * 0.25, height * 0.75
    left_box = (margin, top, margin + panel_width, bottom)
    right_box = (margin + panel_width + gap, top, width - margin, bottom)
    rounded_node(draw, left_box, str(spec["left"]), fonts["subtitle"], colors)
    rounded_node(draw, right_box, str(spec["right"]), fonts["subtitle"], colors)
    divider_x = width / 2
    draw.line((divider_x, top + height * 0.04, divider_x, bottom - height * 0.04), fill=colors["accent"], width=max(4, int(width * 0.005)))
    title = spec.get("title")
    if title:
        lines = wrap_text(draw, str(title), fonts["small"], width * 0.7)
        draw_centered_lines(draw, lines, width / 2, height * 0.14, fonts["small"], colors["muted"], 6)


def render_timeline(image: Image.Image, draw: ImageDraw.ImageDraw, spec: dict, fonts: dict, colors: dict) -> None:
    width, height = image.size
    items = [str(item) for item in spec["items"]]
    portrait = height >= width
    if portrait:
        x = width * 0.24
        y0, y1 = height * 0.2, height * 0.8
        draw.line((x, y0, x, y1), fill=colors["line"], width=max(4, int(width * 0.005)))
        for index, item in enumerate(items):
            y = y0 + (y1 - y0) * index / max(1, len(items) - 1)
            radius = width * 0.022
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=colors["accent"])
            box = (width * 0.34, y - height * 0.055, width * 0.86, y + height * 0.055)
            rounded_node(draw, box, item, fonts["node"], colors)
    else:
        x0, x1 = width * 0.15, width * 0.85
        y = height * 0.5
        draw.line((x0, y, x1, y), fill=colors["line"], width=max(4, int(height * 0.007)))
        for index, item in enumerate(items):
            x = x0 + (x1 - x0) * index / max(1, len(items) - 1)
            radius = height * 0.035
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=colors["accent"])
            box = (x - width * 0.09, y - height * 0.24, x + width * 0.09, y - height * 0.09)
            rounded_node(draw, box, item, fonts["node"], colors)


def render_graphic(width: int, height: int, spec: dict, style: str, font_path: Path) -> Image.Image:
    colors = palette(style)
    image = Image.new("RGB", (width, height), colors["bg"])
    draw = ImageDraw.Draw(image)
    scale = min(width, height)
    fonts = {
        "title": font(font_path, int(scale * 0.075)),
        "subtitle": font(font_path, int(scale * 0.045)),
        "number": font(font_path, int(scale * 0.17)),
        "node": font(font_path, int(scale * 0.032)),
        "small": font(font_path, int(scale * 0.027)),
    }
    kind = spec["kind"]
    if kind == "statement":
        render_statement(image, draw, spec, fonts, colors)
    elif kind == "number":
        render_number(image, draw, spec, fonts, colors)
    elif kind == "relation":
        render_relation(image, draw, spec, fonts, colors)
    elif kind == "split":
        render_split(image, draw, spec, fonts, colors)
    elif kind == "timeline":
        render_timeline(image, draw, spec, fonts, colors)
    else:
        raise ValueError(f"unsupported graphic kind: {kind}")
    return image


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
    parser.add_argument("--shot", action="append")
    args = parser.parse_args()
    try:
        load_skill_env()
        plan_path = args.plan.expanduser().resolve()
        plan = load_json(plan_path)
        errors = validate_plan(plan, plan_path=plan_path, check_files=False)
        if errors:
            raise ValueError("plan validation failed:\n- " + "\n- ".join(errors))
        requested = set(args.shot) if args.shot else None
        shots = selected_approved_shots(plan, requested)
        assert_execution_gate(plan, shots)
        assets_by_id = indexed(plan.get("assets", []), "asset_id")
        selected: list[dict] = []
        seen: set[str] = set()
        for shot in shots:
            asset = assets_by_id.get(str(shot.get("asset_id")))
            if not asset or asset.get("type") != "DETERMINISTIC_GRAPHIC" or asset.get("asset_id") in seen:
                continue
            seen.add(asset["asset_id"])
            selected.append(asset)
        if not selected:
            print("NO_DETERMINISTIC_GRAPHICS")
            return 0
        summary = [
            {"asset_id": asset["asset_id"], "output_name": asset["output_name"], "graphic_spec": asset["graphic_spec"]}
            for asset in selected
        ]
        if args.dry_run:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0

        font_path = find_font()
        output_dir = args.output_dir.expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        width = int(plan["source"]["width"])
        height = int(plan["source"]["height"])
        style = str(plan.get("profile", {}).get("visual_style", "clean_editorial"))
        for asset in selected:
            destination = output_dir / Path(asset["output_name"]).name
            image = render_graphic(width, height, asset["graphic_spec"], style, font_path)
            image.save(destination, format="PNG")
            asset["status"] = "generated"
            asset["generated_path"] = stored_path(plan_path, destination)
            asset["generated_at"] = now_iso()
            print(f"GRAPHIC_WRITTEN {asset['asset_id']}: {destination}")
        save_json(plan_path, plan)
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
