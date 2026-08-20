---
name: image-broll-agent
description: 给 2–3 分钟知识类口播规划图片型 B-roll；默认接在 AI剪口播 A 模式导出之后，本地渲染干净口播、重映射已有火山逐字稿并自动完成语义分段、评分、预算和路由，生成可视化审核页。批准后输出 Prompt，由用户使用 ChatGPT 套餐生图，QA 通过再用 FFmpeg 运镜回填，始终保留原口播声音。触发词：加B-roll、口播配图、给口播插画面、图片运镜、自动回填B-roll。
---

# Image B-roll Agent

本 Skill 是 `AI剪口播` A 模式导出后的默认子步骤，不替换现有模式 A / B，也不新增视频总流程 handler。默认读取导出的 FCPXML / review_log / receipt，在本地渲染干净口播并重映射现有火山逐字稿；也保留对独立 clean-cut MP4 的入口。

## 能做什么

- 复用父 Skill 的火山引擎转写，不使用本地 Whisper。
- 用本地确定性算法把标点/停顿原子单元按完整语义合并、评分和路由，不依赖 Agent 手工填 plan。
- 判断哪些段落应保留真人，哪些应使用真实证据、已有图片、确定性图形或 ChatGPT 手工生成的无字图片。
- 对语义段做 B-roll 价值评分，默认 2–3 分钟视频最多 8 个 B-roll，其中手工生图最多 5 张。
- 使用 8 个 P0 信息表达模板。
- 输出结构化 `broll-plan.json`、文字审片单 `broll-review.md` 和可播放逐镜选择的 `broll-review.html`。
- 按具体 shot ID 审批，并使用 fingerprint 防止“批准后偷改提示词或时间轴”。
- 为明确批准的镜头导出可复制 Prompt，并导入用户从 ChatGPT 下载的图片。
- 生成金句、数字、流程、对比和时间线等确定性图片。
- 图片 QA 通过后生成推拉/横移 B-roll MP4，并自动回填原视频。
- 原始口播音轨始终保留，不生成背景音乐或旁白。

## 不做什么

- 不自动伪造论文、报道、Logo、产品 UI、真实数据或历史证据。
- P0 不支持视频素材搜索、透明 Alpha、画中画、人物抠像和多层重叠 B-roll。
- P0 的 `EXISTING_MEDIA` 和 `REAL_EVIDENCE` 只接受静态图片。
- 不调用 OpenAI Image API，不读取 `OPENAI_API_KEY`，不自动消耗 API 余额。

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

### 0. 默认入口：承接 AI剪口播 A 模式导出

A 模式网页导出成功且 `3_审核/` 中已有 `*_cut.fcpxml + review_log.json` 后，默认执行下列交接，不再要求用户先去剪映 / Final Cut 手工渲染：

```bash
SKILL_DIR="<image-broll-agent 安装目录>"
REVIEW_DIR="/absolute/path/片子/剪口播/3_审核"

bash "$SKILL_DIR/scripts/handoff_from_ai_jian_koubo.sh" "$REVIEW_DIR" \
  --profile balanced \
  --style clean_editorial \
  --open-review
```

脚本会验证当前导出回执（旧工程无 receipt 时校验 FCPXML 与 review_log）、本地渲染保留片段、重映射 `1_转录/subtitles_words.json` 到 clean-cut 时间轴，再自动规划。它不再次调用 ASR，也不调用图片 API。

状态写入 `B-roll/broll-handoff-state.json`：先 `clean_cut_rendered`，计划与审核页生成后进入 `awaiting_broll_approval`。此时必须停下等待用户批准具体 shot。

### 1. 独立 clean-cut MP4 入口

仅当用户直接提供已渲染的 clean-cut MP4 时运行：

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
3. 本地自动生成完整的 `broll-plan.json`。
4. 自动校验并生成 `broll-review.md` 与 `broll-review.html`。

默认输出：

```text
~/Desktop/output/<日期_视频名>/B-roll/
├── 1_转录/
├── 2_B-roll方案/
│   ├── transcript-context.json
│   ├── transcript-context.md
│   ├── broll-plan.json
│   ├── broll-review.md
│   └── broll-review.html
├── 3_B-roll素材/
├── 4_B-roll片段/
└── 5_成片/
```

### 2. 复核本地自动语义分段

读取 `references/semantic-segmentation.md` 和 `transcript-context.json`。

`prepare_broll.sh` 已调用 `auto_plan.py` 完成此步。复核时只能合并相邻 `unit_id`，不得估算或改写时间戳；段落开始/结束必须直接来自原子单元边界。不要按每个逗号机械创建镜头。

### 3. 复核本地自动信息载体路由

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
- `GENERATED_IMAGE` 必须使用 `image_provider: manual_chatgpt` 和 `generation_mode: manual_chatgpt`；不得出现 `provider/model/size/quality` 等 API 字段。
- 缺失的真实证据必须标记 `status: missing` 和 `blocks_generation: true`。

每段填写 `broll_score`：`视觉价值 + 理解提升 + 节奏改善 - 生成成本`。只有达到 `broll_budget.min_broll_score` 的段落才能创建 B-roll。默认预算是 `max_total_broll: 8`、`max_generated_images: 5`。

### 4. 校验计划并打开可视化审核

自动计划已按 `references/plan-schema.md` 填写：

- `segments`
- `assets`
- `shots`

计划必须符合 `schemas/broll-plan.schema.json`，并包含每个镜头的时间、原文、评分、route、template、素材、语义时长类型、运镜和审批状态。

时长按语义决定，不使用固定 6 秒：`short_point` 2–4 秒，`concept_explanation` 5–8 秒，`process_explanation` 8–12 秒，`chapter_transition` 约 3 秒。

```bash
python3 "$SKILL_DIR/scripts/plan_tool.py" validate \
  "$PLAN_DIR/broll-plan.json"

python3 "$SKILL_DIR/scripts/plan_tool.py" review \
  "$PLAN_DIR/broll-plan.json" \
  --output "$PLAN_DIR/broll-review.md"

python3 "$SKILL_DIR/scripts/generate_review_html.py" \
  "$PLAN_DIR/broll-plan.json" \
  --output "$PLAN_DIR/broll-review.html"
```

打开 `broll-review.html`：用户可播放每个时间段、勾选镜头、复制批准文本或下载选择 JSON。展示后停止；用户确认具体镜头后再导出对应 Prompt，避免为低价值镜头浪费生图额度和审核时间。

### 5. 记录明确批准

用户必须明确批准具体镜头，例如：“批准 B001、B003”。然后运行：

```bash
python3 "$SKILL_DIR/scripts/plan_tool.py" approve \
  "$PLAN_DIR/broll-plan.json" \
  --shots B001,B003 \
  --confirmation CONFIRM_BROLL_PLAN
```

如果提示词、目标比例、时间戳、route、template、运镜、预算、profile 或源视频变化，先运行 reset 并重新审批：

```bash
python3 "$SKILL_DIR/scripts/plan_tool.py" reset \
  "$PLAN_DIR/broll-plan.json" --shots all
```

### 6. 导出 ChatGPT 生图 Prompt

脚本只写本地任务文件，不联网，也不会调用图片 API：

```bash
python3 "$SKILL_DIR/scripts/export_image_prompts.py" \
  "$PLAN_DIR/broll-plan.json" \
  --output "$PLAN_DIR/image-prompts.json" \
  --markdown "$PLAN_DIR/image-prompts.md"
```

状态从 `planned` 进入 `waiting_user_generation`。逐条复制 Prompt 到 ChatGPT 生图，并按任务给出的文件名下载到同一目录。

### 7. 导入用户生成图片和生成确定性图形

把 ChatGPT 下载图片导入素材目录：

```bash
python3 "$SKILL_DIR/scripts/import_generated_assets.py" \
  "$PLAN_DIR/broll-plan.json" \
  --input-dir "$DOWNLOAD_DIR" \
  --output-dir "$ASSET_DIR"
```

脚本校验文件名、图片完整性和目标比例，然后把状态推进到 `user_generated`。不会移动或删除下载原图；目标文件已存在且内容不同时会拒绝覆盖，除非显式使用 `--replace`。

确定性图形继续由本地代码生成：

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

通过后手工生图状态进入 `qa_passed`。不通过则设为 `rejected`，修改计划、reset 并重新审批、导出 Prompt 和生图。

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

合成只替换指定时间范围内的视频画面，完整保留源口播音轨，并输出 `broll-edit-manifest.json`。成功后手工生图状态进入 `inserted`。

## 安全门禁

手工生图与回填必须同时满足：

1. 当前对话中用户明确批准具体 shot ID 或全部镜头。
2. plan 和 shot 状态为 approved。
3. fingerprint 与当前计划一致。
4. 计划没有超出 8 个总 B-roll / 5 张手工生图的预算。
5. 每个 B-roll 的价值评分达到门槛，时长符合语义时长类型。
6. Prompt 已导出、用户图片已导入且通过 QA；阻塞素材已提供。

交接状态：`rough_cut_exported → clean_cut_rendered → awaiting_broll_approval`。素材状态：`planned → prompt_ready → waiting_user_generation → user_generated → qa_passed → inserted`。`prompt_ready` 是导出脚本内部的原子过渡；导出完成后落盘为 `waiting_user_generation`。任何一步失败都不得跳到后续状态。

## 验证

```bash
bash "$SKILL_DIR/scripts/validate.sh"
```
