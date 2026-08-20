# ChatGPT 手工生图提示词规则

每张图只表达一个核心语义。提示词应明确主体与动作、环境、构图、景深、灯光、材质、有限色彩和裁切安全区。

推荐结尾：

`No readable text, no letters, no numbers, no logos, no watermark, no UI, no charts, no fake evidence. Keep the main subject inside the central 70% safe area for vertical crop.`

不得生成论文、报道、官方截图、真实 UI、品牌 Logo、精确数字、需要逐字准确的中文、未授权真实人物身份或伪纪实证据。Prompt 由 `export_image_prompts.py` 导出，用户复制到 ChatGPT 生图；Skill 不调用图片 API。
