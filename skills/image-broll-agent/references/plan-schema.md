# `broll-plan.json` 关键字段

Schema 版本：`0.2`，机器可读文件为 `schemas/broll-plan.schema.json`。顶层字段为 `schema_version`、`project`、`source`、`profile`、`broll_budget`、`segments`、`assets`、`shots`、`approval` 和 `edit`。

Route 与 Asset Type 一一对应：`REAL_EVIDENCE`、`EXISTING_MEDIA`、`DETERMINISTIC_GRAPHIC`、`GENERATED_IMAGE`；`KEEP_A_ROLL` 不创建 shot。

`broll_budget` 默认针对 120–180 秒口播：总 B-roll 最多 8 个，ChatGPT 手工生图最多 5 张，候选最低总分 12。`broll_score.total = visual_value + comprehension_gain + rhythm_gain - generation_cost`，每项 0–10。

`GENERATED_IMAGE` 不含模型、尺寸、质量或 API provider；固定使用 `image_provider: manual_chatgpt`、`generation_mode: manual_chatgpt` 和 `target_aspect_ratio`。状态流是 `planned → prompt_ready → waiting_user_generation → user_generated → qa_passed → inserted`。

每个 shot 还必须声明 `duration_class`：观点 2–4 秒、概念解释 5–8 秒、流程说明 8–12 秒、章节转场约 3 秒。执行前必须满足具体 shot 已批准、fingerprint 完整、图片已由用户导入、QA 已通过且阻塞素材已提供。

默认交接另写 `broll-handoff-state.json`：`clean_cut_rendered → awaiting_broll_approval`。批准之后的细粒度进度仍以 plan 内 shot/asset 状态为准：`planned → waiting_user_generation → user_generated → qa_passed → inserted`。
