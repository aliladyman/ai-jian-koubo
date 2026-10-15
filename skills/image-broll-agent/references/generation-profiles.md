# B-roll 密度配置

`profile.name` 控制插入密度和运镜复杂度，`profile.visual_style` 控制美术风格。

| Profile | 建议每分钟镜头 | 建议覆盖率 | 单镜时长 |
|---|---:|---:|---:|
| `simple` | 4 | 15%–25% | 3–5 秒 |
| `balanced` | 7 | 25%–35% | 2.5–4 秒 |
| `rich` | 10 | 35%–50% | 1.8–3.5 秒 |

Schema 硬上限：simple 为 5 镜/分钟、覆盖率 0.30；balanced 为 8 镜/分钟、0.42；rich 为 12 镜/分钟、0.58。

更换 profile、visual style、模型、提示词、时间戳、模板或素材后，原审批 fingerprint 自动失效。
