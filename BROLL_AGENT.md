# Image B-roll Agent

本仓库新增一个独立的图片型 B-roll 子 Skill：`skills/image-broll-agent/`。

它默认接在 `AI剪口播` A 模式导出之后：直接读取 FCPXML / review_log / receipt，在本地渲染已批准的干净口播，并把现有火山字级时间戳重映射到新时间轴。随后由本地确定性算法合并语义、评分并在以下路线之间选择：

- 保留真人口播
- 真实证据截图
- 用户已有图片素材
- 确定性文字、数字、流程图
- ChatGPT 手工生成的无字图片

2–3 分钟口播默认最多选择 8 个 B-roll，其中手工生图最多 5 张。计划同时输出 Markdown 和可播放原视频、逐镜选择、复制批准文本的 HTML 审核页。用户明确批准分镜后，Skill 导出 Prompt，由用户使用 ChatGPT 套餐生图并导入；代码不调用图片 API。图片通过人工 QA 后，再由 FFmpeg 添加轻微运镜并按时间戳回填，原始口播音轨始终保留。

现有模式 A / B 不做破坏性修改；B-roll 是 A 模式导出后的默认子步骤，仍保留单独输入 clean-cut MP4 的独立入口。
