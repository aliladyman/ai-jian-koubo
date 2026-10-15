# 更新日志

本仓库 fork 自 [lcbuaaliu/ai-jian-koubo](https://github.com/lcbuaaliu/ai-jian-koubo)（基线：2026-06-24 提交 `e223b91`）。按 AGPL-3.0 第 5 条，下面列出相对原版的全部修改。代码里标「本地补丁」的注释也是这些改动。

## 增强版 v1 · 2026-10-15

### 新增

- **剪映主轨草稿导出**（`scripts/lib/jianying.js`、`jianying_template.json`，`POST /api/jianying`）：用和 FCPXML 同一组保留段、帧率和句尾检查，生成一份全新的剪映原生草稿，视频在主轨。原因：剪映 11.3.0 导入 FCPXML（即使写了 lane=0）画面仍落在附加轨。每次导出新建草稿，不改已有草稿；默认 macOS 草稿目录，可用 `JIANYING_DRAFT_ROOT` 指定。
- **MP4 导出**（`scripts/lib/render_mp4.js`，`POST /api/mp4`）：按同一组保留段分段编码后拼接，中间音频用 PCM，避免每个切点重复引入 AAC 延迟。
- **SRT 导出**（审核页「导出 SRT」）：时间码对应剪后视频，带上审核页里改过的字。
- **成套导出与回执**（`scripts/lib/export_bundle.js`）：FCPXML、`review_log.json`、`rough-cut-export.receipt.json` 一起写，回执最后写并用 SHA-256 绑定前两者和逐字稿；任一文件写失败或被单独替换，API 不返回成功。
- **双击改字**（`scripts/lib/occurrence_corrections.js`，`POST /api/corrections`）：三种范围——全局词典、本片词典、只改这一处；改字只改显示和词典，不改转录原文；「只改这一处」的修改最后生效，不会被词典再替换，也不会带回已删除的词。
- **字幕断行预览**（`POST /api/captions-preview`，附带 `scripts/captions/`）：按剪后时间轴出逐句文字，再按确定性中文断行规则（`用户习惯/断行prompt.md`）断行。
- **转录来源守卫**（`scripts/lib/assert_asr_source.js`）：分析和生成审核页之前，要求同目录有火山引擎产物 `volcengine_v3_result.json`，缺了就停；换别的引擎必须由用户确认后写 `1_转录/.asr_override.json`。
- **旧工程补导出**（`scripts/reconcile_legacy_export.js`）：给新版之前导出的工程补齐回执。
- **测试**：`scripts/tests/` 下 6 个文件、20 个用例（句尾保护、成套导出、MP4、剪映草稿、改字 API、改字逻辑）。

### 改进

- **默认「只删标红」的安全模式**（`scripts/lib/compute_keeps.js`、`fcpxml.js`）：删除范围等于红色明确选区，静音数据不参与实际切点；切口碰到未选中的字就阻断导出；FCPXML 边界按源视频真实帧率向外取整（开头 floor、结尾 ceil）。旧的静音吸附行为只在显式兼容模式（`preserveNaturalPauses:false`）里保留。
- **审核页**（`scripts/templates/review.html`）：静音阈值一键勾选、句尾保护面板、字幕预览开关、四个导出按钮；改字覆盖层；播放跳段与导出共用同一份实际切点。
- **审核服务**（`scripts/review_server.js`）：新增上述 API；只接受本机请求。
- **剪辑规则**（`用户习惯/规则.md`）：重说（retake）四步判断、删前保后、短句护栏、语境词四个判据、停顿四类先分类再压缩、陈述句复述成反问不算重说。
- **SKILL.md**：转录引擎硬规则、参考稿存活自检（5.7）、A 模式句尾安全规则、停顿四类与置信分层、交付前四检、剪映主轨交付说明。
- **自检**（`scripts/doctor.js`）：不再在终端打印 API Key 的前几位，只显示长度。

### 没有改

- 转录脚本、口误识别的整体流程（步骤 0–8）、模式 B 转字幕、`用户习惯/经验规则.md`（仍是空模板，从你自己的剪辑里学）。

### 已知限制

- 只在 macOS + 剪映专业版 11.3 上验证过；Windows 未实机测试。
- 剪映主轨草稿只覆盖单条口播视频的帧对齐初剪。
- 剪映首页可能不会立刻显示新草稿，需要退出重开。
