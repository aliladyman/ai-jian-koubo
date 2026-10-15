# Image B-roll Agent

本仓库新增一个独立的图片型 B-roll 子 Skill：`skills/image-broll-agent/`。

它接收已经剪好气口的口播 MP4，复用父 Skill 的火山引擎转写能力获取字级时间戳，再由 coding agent 按语义合并为完整表达单元，并在以下路线之间选择：

- 保留真人口播
- 真实证据截图
- 用户已有图片素材
- 确定性文字、数字、流程图
- GPT Image 2 无字图片

用户明确批准分镜后，Skill 才允许调用图片 API；图片通过人工 QA 后，再由 FFmpeg 添加轻微运镜并按时间戳回填，原始口播音轨始终保留。

现有模式 A / B 不做破坏性修改。建议在模式 A 导出并渲染干净口播视频后，再调用本子 Skill。
