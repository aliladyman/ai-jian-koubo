#!/usr/bin/env python3
"""Generate a self-contained visual review page for an Image B-roll plan."""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

from broll_lib import indexed, load_json, resolve_plan_path, validate_plan


def route_label(route: str) -> str:
    return {
        "REAL_EVIDENCE": "真实证据",
        "EXISTING_MEDIA": "已有素材",
        "DETERMINISTIC_GRAPHIC": "本地图形",
        "GENERATED_IMAGE": "ChatGPT 手工生图",
    }.get(route, route)


def asset_uri(plan_path: Path, asset: dict) -> str | None:
    value = asset.get("generated_path") or asset.get("source_path")
    resolved = resolve_plan_path(plan_path, value)
    return resolved.as_uri() if resolved and resolved.is_file() else None


def build_html(plan: dict, plan_path: Path) -> str:
    project = html.escape(str(plan.get("project", {}).get("name", "B-roll 审核")))
    source_path = Path(plan["source"]["video_path"]).expanduser().resolve()
    source_uri = source_path.as_uri()
    assets = indexed(plan.get("assets", []), "asset_id")
    segments = indexed(plan.get("segments", []), "segment_id")
    budget = plan.get("broll_budget", {})
    cards: list[str] = []
    for shot in plan.get("shots", []):
        segment = segments.get(str(shot.get("segment_id")), {})
        asset = assets.get(str(shot.get("asset_id")), {})
        shot_id = html.escape(str(shot.get("shot_id", "")))
        transcript = html.escape(str(segment.get("transcript_text", "")))
        reason = html.escape(str(segment.get("route_reason", "")))
        description = html.escape(str(asset.get("description", "")))
        route = str(segment.get("route", ""))
        route_text = html.escape(route_label(route))
        start = float(shot.get("start_sec", 0))
        end = float(shot.get("end_sec", 0))
        score = segment.get("broll_score", {})
        score_text = f"{score.get('total', 0)} = {score.get('visual_value', 0)} 视觉 + {score.get('comprehension_gain', 0)} 理解 + {score.get('rhythm_gain', 0)} 节奏 − {score.get('generation_cost', 0)} 成本"
        preview = asset_uri(plan_path, asset)
        preview_html = f'<img class="asset-preview" src="{html.escape(preview)}" alt="{shot_id} 素材预览">' if preview else '<div class="asset-placeholder">素材尚未提供</div>'
        detail = ""
        if asset.get("prompt"):
            detail = f'<details><summary>查看并复制 ChatGPT 生图 Prompt</summary><pre>{html.escape(str(asset["prompt"]))}</pre><button class="copy-prompt" data-prompt="{html.escape(str(asset["prompt"]), quote=True)}">复制 Prompt</button></details>'
        elif asset.get("graphic_spec"):
            detail = f'<details><summary>查看本地图形规格</summary><pre>{html.escape(json.dumps(asset["graphic_spec"], ensure_ascii=False, indent=2))}</pre></details>'
        elif route == "REAL_EVIDENCE":
            detail = '<div class="blocker">审批前必须补充可核验的真实截图，禁止改成 AI 生图。</div>'
        cards.append(f"""
        <article class="shot-card" data-shot-id="{shot_id}">
          <div class="shot-head">
            <label><input class="shot-check" type="checkbox" value="{shot_id}" checked> <strong>{shot_id}</strong></label>
            <span class="route route-{html.escape(route.lower())}">{route_text}</span>
          </div>
          <div class="shot-grid">
            <div>
              <button class="seek" data-start="{start:.3f}" data-end="{end:.3f}">▶ 播放 {start:.1f}–{end:.1f}s</button>
              <p class="transcript">{transcript}</p>
              <dl>
                <dt>为什么需要</dt><dd>{reason}</dd>
                <dt>价值评分</dt><dd>{html.escape(score_text)}</dd>
                <dt>时长与运镜</dt><dd>{end - start:.1f}s · {html.escape(str(shot.get('duration_class', '')))} · {html.escape(str(shot.get('motion_preset', '')))}</dd>
                <dt>素材要求</dt><dd>{description}</dd>
              </dl>
              {detail}
            </div>
            <div>{preview_html}</div>
          </div>
        </article>""")

    embedded_plan = json.dumps(plan, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{project} · B-roll 审核</title>
  <style>
    :root {{ color-scheme: dark; --bg:#0c1017; --card:#151b25; --line:#2a3444; --text:#f4f7fb; --muted:#9ba8ba; --accent:#65d1ff; --warn:#ffbe55; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif; background:var(--bg); color:var(--text); }}
    main {{ max-width:1180px; margin:auto; padding:24px; }} h1 {{ margin:0 0 8px; font-size:28px; }} .summary {{ color:var(--muted); margin-bottom:18px; }}
    .viewer {{ position:sticky; top:0; z-index:3; background:rgba(12,16,23,.96); padding:12px 0 16px; border-bottom:1px solid var(--line); }}
    video {{ width:100%; max-height:46vh; background:#000; border-radius:14px; }}
    .approval-bar {{ display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-top:12px; }} button {{ border:1px solid var(--line); background:#202a38; color:var(--text); border-radius:9px; padding:9px 13px; cursor:pointer; }} button:hover {{ border-color:var(--accent); }}
    #approval-text {{ flex:1; min-width:260px; background:#0a0d12; border:1px solid var(--line); border-radius:9px; padding:10px; color:var(--accent); }}
    .shot-card {{ background:var(--card); border:1px solid var(--line); border-radius:16px; padding:18px; margin:18px 0; }} .shot-card:has(.shot-check:not(:checked)) {{ opacity:.5; }}
    .shot-head {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; }} .route {{ border:1px solid var(--line); border-radius:999px; padding:5px 9px; color:var(--accent); font-size:13px; }}
    .shot-grid {{ display:grid; grid-template-columns:minmax(0,1.4fr) minmax(220px,.6fr); gap:18px; }} .transcript {{ font-size:20px; line-height:1.65; }}
    dl {{ display:grid; grid-template-columns:90px 1fr; gap:8px 14px; }} dt {{ color:var(--muted); }} dd {{ margin:0; line-height:1.55; }}
    pre {{ white-space:pre-wrap; word-break:break-word; background:#0a0d12; border:1px solid var(--line); padding:12px; border-radius:10px; }}
    .asset-preview,.asset-placeholder {{ width:100%; aspect-ratio:9/16; max-height:420px; object-fit:contain; background:#0a0d12; border:1px solid var(--line); border-radius:12px; }} .asset-placeholder {{ display:grid; place-items:center; color:var(--muted); }}
    .blocker {{ margin-top:12px; padding:10px; border:1px solid var(--warn); color:var(--warn); border-radius:9px; }} .empty {{ color:var(--muted); padding:32px 0; }}
    @media(max-width:760px) {{ main {{ padding:14px; }} .shot-grid {{ grid-template-columns:1fr; }} .viewer {{ position:relative; }} dl {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body><main>
  <h1>{project}</h1>
  <div class="summary">{len(plan.get('shots', []))} 个候选镜头 · 最多 {budget.get('max_total_broll', 0)} 个 · ChatGPT 手工生图最多 {budget.get('max_generated_images', 0)} 张</div>
  <section class="viewer">
    <video id="source-video" controls preload="metadata" src="{html.escape(source_uri)}"></video>
    <div class="approval-bar">
      <button id="select-all">全选</button><button id="select-none">全不选</button>
      <input id="approval-text" readonly aria-label="批准文本">
      <button id="copy-approval">复制批准文本</button><button id="download-selection">下载选择结果</button>
    </div>
  </section>
  <section id="shots">{''.join(cards) if cards else '<p class="empty">本次自动规划没有达到门槛的 B-roll，保留全程真人画面。</p>'}</section>
  <script id="plan-data" type="application/json">{embedded_plan}</script>
  <script>
    const video = document.getElementById('source-video'); let stopAt = null;
    const checks = () => [...document.querySelectorAll('.shot-check')];
    const selected = () => checks().filter(x => x.checked).map(x => x.value);
    function refresh() {{ const ids = selected(); document.getElementById('approval-text').value = ids.length ? `批准 ${{ids.join('、')}}` : '不批准任何 B-roll'; }}
    checks().forEach(x => x.addEventListener('change', refresh)); refresh();
    document.querySelectorAll('.seek').forEach(btn => btn.addEventListener('click', async () => {{ video.currentTime = Number(btn.dataset.start); stopAt = Number(btn.dataset.end); await video.play(); }}));
    video.addEventListener('timeupdate', () => {{ if (stopAt !== null && video.currentTime >= stopAt) {{ video.pause(); stopAt = null; }} }});
    document.getElementById('select-all').onclick = () => {{ checks().forEach(x => x.checked = true); refresh(); }};
    document.getElementById('select-none').onclick = () => {{ checks().forEach(x => x.checked = false); refresh(); }};
    document.getElementById('copy-approval').onclick = async () => navigator.clipboard.writeText(document.getElementById('approval-text').value);
    document.querySelectorAll('.copy-prompt').forEach(btn => btn.onclick = async () => navigator.clipboard.writeText(btn.dataset.prompt));
    document.getElementById('download-selection').onclick = () => {{
      const payload = {{confirmation:'CONFIRM_BROLL_PLAN', approved_shots:selected(), exported_at:new Date().toISOString()}};
      const blob = new Blob([JSON.stringify(payload, null, 2)], {{type:'application/json'}}); const a = document.createElement('a');
      a.href = URL.createObjectURL(blob); a.download = 'broll-approval-selection.json'; a.click(); URL.revokeObjectURL(a.href);
    }};
  </script>
</main></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        plan_path = args.plan.expanduser().resolve()
        plan = load_json(plan_path)
        errors = validate_plan(plan, plan_path=plan_path, check_files=False)
        if errors:
            raise ValueError("plan validation failed:\n- " + "\n- ".join(errors))
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(build_html(plan, plan_path), encoding="utf-8")
        print(f"REVIEW_HTML_WRITTEN: {output}")
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
