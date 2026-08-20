# 语义分段规则

读取 `1_转录/transcript-context.json`。其中 `units` 是根据标点、停顿和最大时长得到的原子单元，不是最终 B-roll 段落。

把相邻原子单元合并为完整 semantic beats。每段只表达一个完整意思，例如问题、结论、对比、因果、流程、例子、数字、情绪转折或行动建议。

硬规则：

1. 只能合并相邻 `unit_id`，不能重排。
2. `start_sec` 取第一个单元开始；`end_sec` 取最后一个单元结束。
3. `transcript_text` 按顺序拼接，不得改写、删减或补充。
4. 默认 2.5–8 秒；拆开会破坏语义时允许更长。
5. 数字与解释、引用与来源、问题与限定条件不要拆开。
6. 因果、转折、举例、角色变化和结论落点优先作为边界。
7. 不要为了增加 B-roll 数量制造过细段落。

每段填写 `semantic_role`、`broll_need`（0–3）、`speaker_dependency` 和 `evidence_required`。只有 `broll_need >= 2` 才创建 shot。
