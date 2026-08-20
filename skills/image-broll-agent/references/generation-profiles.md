# B-roll 密度配置

`profile.name` 控制插入密度和运镜复杂度，`profile.visual_style` 控制美术风格。

| Profile | 建议每分钟镜头 | 建议覆盖率 | 单镜时长 |
|---|---:|---:|---:|
| `simple` | 4 | 15%–25% | 3–5 秒 |
| `balanced` | 7 | 25%–35% | 2.5–4 秒 |
| `rich` | 10 | 35%–50% | 1.8–3.5 秒 |

Schema v0.2 在 profile 上限之外增加 2–3 分钟口播硬预算：`max_total_broll <= 8`、`max_generated_images <= 5`。profile 只会进一步收紧密度与覆盖率，不能突破 8/5 上限。

更换 profile、visual style、预算、提示词、目标比例、时间戳、模板或素材后，原审批 fingerprint 自动失效。
