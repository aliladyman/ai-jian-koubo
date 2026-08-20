# Image B-roll Agent

给已经剪好气口的知识类口播视频自动规划和回填图片型 B-roll。

```text
clean-cut.mp4
→ 火山引擎重新转写
→ coding agent 按语义合并
→ 信息载体路由
→ broll-plan.json / broll-review.md
→ 明确批准
→ GPT Image 2 或确定性图形
→ 图片 QA
→ FFmpeg 运镜
→ 保留原口播声音自动回填
```

## 快速开始

在父仓库中直接运行：

```bash
SKILL_DIR="$(pwd)/skills/image-broll-agent"
cp "$SKILL_DIR/.env.example" "$SKILL_DIR/.env"
# 编辑 .env，填写 OPENAI_API_KEY
python3 -m pip install -r "$SKILL_DIR/requirements.txt"
python3 "$SKILL_DIR/scripts/doctor.py"

bash "$SKILL_DIR/scripts/prepare_broll.sh" \
  /absolute/path/clean-cut.mp4 \
  --profile balanced \
  --style clean_editorial
```

完整工作流见 [`SKILL.md`](SKILL.md)。

## 当前范围

P0 支持：真实截图、已有图片、确定性金句/数字/流程/对比/时间线、GPT Image 2 无字图片、6 种图片运镜、全屏时间戳回填。

暂不支持：视频素材搜索、透明叠加、画中画、人物抠像、重叠多轨和自动视觉 QA。
