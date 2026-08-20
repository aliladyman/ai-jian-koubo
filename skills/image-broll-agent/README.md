# Image B-roll Agent

给已经剪好气口的知识类口播视频自动规划和回填图片型 B-roll。

```text
clean-cut.mp4
→ 复用/重映射 AI剪口播 的火山逐字稿（独立使用时才重新转写）
→ 本地算法按语义合并、评分和路由
→ 信息载体路由
→ broll-plan.json / broll-review.md / broll-review.html
→ 价值评分与 8/5 预算门
→ 明确批准
→ 导出 Prompt
→ 用户在 ChatGPT 内生图并导入 / 本地确定性图形
→ 图片 QA
→ FFmpeg 运镜
→ 保留原口播声音自动回填
```

## 快速开始

`AI剪口播` A 模式网页导出后，默认直接运行：

```bash
bash "$HOME/.codex/skills/image-broll-agent/scripts/handoff_from_ai_jian_koubo.sh" \
  "/absolute/path/片子/剪口播/3_审核" \
  --profile balanced \
  --open-review
```

脚本会在本地渲染 FCPXML、重映射已有火山逐字稿、自动规划，并打开可视化审核页；不会再次调用 ASR。也可对已有 clean-cut MP4 独立运行：

```bash
SKILL_DIR="$(pwd)/skills/image-broll-agent"
cp "$SKILL_DIR/.env.example" "$SKILL_DIR/.env"
# 独立安装时编辑 .env，填写父 AI剪口播 Skill 路径；无需 OpenAI API Key
python3 -m pip install -r "$SKILL_DIR/requirements.txt"
python3 "$SKILL_DIR/scripts/doctor.py"

bash "$SKILL_DIR/scripts/prepare_broll.sh" \
  /absolute/path/clean-cut.mp4 \
  --profile balanced \
  --style clean_editorial
```

完整工作流见 [`SKILL.md`](SKILL.md)。

## 当前范围

P0 支持：A 模式默认交接、纯本地语义规划、真实截图、已有图片、确定性金句/数字/流程/对比/时间线、ChatGPT 手工无字图片、2–3 分钟默认 8/5 预算、可视化审核、6 种图片运镜和全屏时间戳回填。

暂不支持：视频素材搜索、透明叠加、画中画、人物抠像、重叠多轨和自动视觉 QA。
