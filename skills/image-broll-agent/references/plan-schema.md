# `broll-plan.json` 关键字段

Schema 版本：`0.1`。顶层字段为 `schema_version`、`project`、`source`、`profile`、`segments`、`assets`、`shots`、`approval` 和 `edit`。

Route 与 Asset Type 一一对应：`REAL_EVIDENCE`、`EXISTING_MEDIA`、`DETERMINISTIC_GRAPHIC`、`GENERATED_IMAGE`；`KEEP_A_ROLL` 不创建 shot。

真实执行前必须同时满足：用户明确批准具体 shot；plan 和 shot 为 approved；`approval_fingerprint` 与当前计划一致；付费命令含 `--approved`；所有阻塞素材已提供。任何时间、提示词、模型、尺寸、route、模板、运镜或 profile 变化都会使 fingerprint 失效。
