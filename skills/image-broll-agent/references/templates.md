# P0 模板库

- `I01_STATEMENT_CARD`：金句、结论、反转，确定性文字。
- `I02_CONCEPT_HERO`：核心概念，无字主视觉加可选确定性文字。
- `I03_NUMBER_IMPACT`：已核实数字、比例、排名，数字由 Pillow 绘制。
- `I04_EVIDENCE_FRAME`：论文、文章、官方页面和真实截图，禁止生成证据。
- `I05_RELATION_FLOW`：2–4 步流程、因果或依赖关系。
- `I06_SPLIT_COMPARISON`：新旧、左右、Tool/Agent 双边对比。
- `I07_TIMELINE_TAXONOMY`：时间线、阶段、分类树，最多 5 个节点。
- `I08_CINEMATIC_METAPHOR`：抽象概念、工作环境、物体隐喻和空间氛围。

确定性图形 `graphic_spec.kind` 支持 `statement`、`number`、`relation`、`split` 和 `timeline`。
