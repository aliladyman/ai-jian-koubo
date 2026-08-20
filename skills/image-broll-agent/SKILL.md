---
name: image-broll-agent
description: 给已经剪好气口的知识类口播 MP4 自动规划图片型 B-roll。复用 AI剪口播 Skill 的火山引擎字级转写，按完整语义合并时间单元，在保留真人、真实证据、已有图片、确定性图形和 GPT Image 2 无字图片之间路由；生成 broll-plan.json 与审片单，用户明确批准后才调用付费图片 API，图片 QA 通过后用 FFmpeg 添加运镜并按时间戳回填，始终保留原口播声音。触发词：加B-roll、口播配图、给口播插画面、图片运镜、自动回填B-roll。
---

# Image B-roll Agent

本 Skill 是 `AI剪口播` 的独立子流程，不替换现有模式 A / B。输入必须是已经剪好气口并渲染完成的 MP4；不要直接使用删除前的原始视频，否则转写时间戳会与最终时间轴不一致。

## 能做什么

- 复用父 Skill 的火山引擎转写，不使用本地 Whisper。
- 把标点/停顿原子单元进一步按完整语义合并。
- 判断哪些段落应保留真人，哪些应使用真实证据、已有图片、确定性图形或 GPT Image 2。
- 使用 8 个 P0 信息表达模板。
- 输出结构化 `broll-plan.json` 和 `broll-review.md`。
- 按具体 shot ID 审批，并使用 fingerprint 防止“批准后偷改提示词或时间轴”。
- 只生成明确批准的 GPT Image 2 图片。
- 生成金句、数字、流程、对比和时间线等确定性图片。
- 图片 QA 通过后生成推拉/横移 B-roll MP4，并自动回填原视频。
- 原始口播音轨始终保留，不生成背景音乐或旁白。

## 不做什么

- 不自动伪造论文、报道、Logo、产品 UI、真实数据或历史证据。
- P0 不支持视频素材搜索、透明 Alpha、画中画、人物抠像和多层重叠 B-roll。
- P0 的 `EXISTING_MEDIA` 和 `REAL_EVIDENCE` 只接受静态图片。
- 不在用户明确批准前调用付费图片 API。

## 必读参考

每次规划前读取：

1. `references/semantic-segmentation.md`
2. `references/routing-rules.md`
3. `references/generation-profiles.md`
4. `references/templates.md`
5. `references/plan-schema.md`
6. `references/image-prompt-system.md`
7. `references/video-editing.md`

## 工作流

### 0. 确认输入

输入应为模式 A 剪完并从剪映 / Final Cut Pro 渲染出的干净口播 MP4。若用户给的是原始未剪视频，明确提醒先完成口误/气口剪辑；除非用户明确要求直接给原始视频加 B-roll。

### 1. 运行准备脚本

```bash
SKILL_DIR="<image-broll-agent 安装目录>"
VIDEO_PATH="/absolute/path/clean-cut.mp4"

bash "$SKILL_DIR/scripts/prepare_broll.sh" "$VIDEO_PATH" \
  --profile balanced \
  --style clean_editorial
```

该脚本会：

1. 调用父 Skill `scripts/run_transcribe.sh`，通过火山引擎重新转写 clean-cut MP4。
2. 生成 `transcript-context.json` 和 `transcript-context.md`。
3. 创建待填写的 `broll-plan.json` 模板。

默认输出：

```text
~/Desktop/output/<日期_视频名>/B-roll/
├── 1_转录/
├── 2_B-roll方案/
│   ├── transcript-context.json
│   ├── transcript-context.md
│   └── broll-plan.json
├── 3_B-roll素材/
├── 4_B-roll片段/
└── 5_成片/
```

### 2. 按语义合并原子单元

读取 `references/semantic-segmentation.md` 和 `transcript-context.json`。

只能合并相邻 `unit_id`。不得估算或改写时间戳；段落开始/结束必须直接来自原子单元边界。不要按每个逗号机械创建镜头。

### 3. 进行信息载体路由

每段选择：

- `KEEP_A_ROLL`
- `REAL_EVIDENCE`
- `EXISTING_MEDIA`
- `DETERMINISTIC_GRAPHIC`
- `GENERATED_IMAGE`

先判断是否需要保留真人，再判断是否要求真实证据，再看用户是否已有素材，然后才考虑确定性图形或生成图片。

硬规则：

- 证据、Logo、真实 UI、引用和精确数据不得路由到 `GENERATED_IMAGE`。
- `GENERATED_IMAGE` 的 `text_policy` 必须是 `no_text`。
- 所有 GPT Image 2 asset 必须记录固定模型，例如 `gpt-image-2-2026-04-21`。
- 缺失的真实证据必须标记 `status: missing` 和 `blocks_generation: true`。

### 4. 填写并校验计划

按照 `references/plan-schema.md` 填写：

- `segments`
- `assets`
- `shots`

计划必须包含每个镜头的时间、原文、route、template、素材、运镜和审批状态。

```bash
python3 "$SKILL_DIR/scripts/plan_tool.py" validate \
  "$PLAN_DIR/broll-plan.json"

python3 "$SKILL_DIR/scripts/plan_tool.py" review \
  "$PLAN_DIR/broll-plan.json" \
  --output "$PLAN_DIR/broll-review.md"
```

向用户展示审片单并停止。不得把“继续”“看起来可以”解释为付费生成批准。

### 5. 记录明确批准

用户必须明确批准具体镜头，例如：“批准 B001、B003”。然后运行：

```bash
python3 "$SKILL_DIR/scripts/plan_tool.py" approve \
  "$PLAN_DIR/broll-plan.json" \
  --shots B001,B003 \
  --confirmation CONFIRM_IMAGE_BROLL_COST
```

如果提示词、模型、尺寸、时间戳、route、template、运镜、profile 或源视频变化，先运行 reset 并重新审批：

```bash
python3 "$SKILL_DIR/scripts/plan_tool.py" reset \
  "$PLAN_DIR/broll-plan.json" --shots all
```

### 6. Dry-run

先查看即将发送给 OpenAI 的请求，不联网、不付费：

```bash
python3 "$SKILL_DIR/scripts/generate_image2.py" \
  "$PLAN_DIR/broll-plan.json" \
  --output-dir "$ASSET_DIR" \
  --dry-run
```

### 7. 生成批准的图片和确定性图形

真实付费生成必须带 `--approved`：

```bash
python3 "$SKILL_DIR/scripts/generate_image2.py" \
  "$PLAN_DIR/broll-plan.json" \
  --output-dir "$ASSET_DIR" \
  --approved
```

确定性图形不调用付费 API：

```bash
python3 "$SKILL_DIR/scripts/prepare_assets.py" \
  "$PLAN_DIR/broll-plan.json" \
  --output-dir "$ASSET_DIR"
```

真实证据和已有图片由用户提供，并在计划中写入 `source_path`。

### 8. 图片 QA

逐张检查：

- 是否与原文语义一致
- 是否出现多余文字、Logo、水印或伪 UI
- 是否会被误认为真实证据
- 主体是否适合竖屏/横屏裁切
- 精确图形中的文字、数字和关系是否正确

通过后：

```bash
python3 "$SKILL_DIR/scripts/plan_tool.py" qa \
  "$PLAN_DIR/broll-plan.json" \
  --shots B001,B003 \
  --status accepted
```

不通过则设为 `rejected`，修改计划、reset 并重新审批/生成。

### 9. 渲染图片运镜

```bash
python3 "$SKILL_DIR/scripts/render_broll.py" \
  "$PLAN_DIR/broll-plan.json" \
  --output-dir "$CLIP_DIR"
```

支持：`static_hold`、`slow_push`、`slow_pull`、`pan_left`、`pan_right`、`diagonal_push`。

### 10. 自动回填

```bash
python3 "$SKILL_DIR/scripts/assemble_edit.py" \
  "$PLAN_DIR/broll-plan.json" \
  --output "$FINAL_DIR/final-with-broll.mp4"
```

合成只替换指定时间范围内的视频画面，完整保留源口播音轨，并输出 `broll-edit-manifest.json`。

## 安全门禁

真实 GPT Image 2 请求必须同时满足：

1. 当前对话中用户明确批准具体 shot ID 或全部镜头。
2. plan 和 shot 状态为 approved。
3. fingerprint 与当前计划一致。
4. 命令显式包含 `--approved`。
5. 阻塞素材已提供。
6. API Key 只从环境变量或本 Skill `.env` 读取，绝不写入计划、提示词、manifest 或源码。

## 验证

```bash
bash "$SKILL_DIR/scripts/validate.sh"
```
