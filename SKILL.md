---
name: AI剪口播
description: 口播视频转录和口误识别，生成网页审核页，导出剪映主轨草稿 / FCPXML / MP4 / SRT 与 A 模式剪辑正本；导出后冻结文字源。触发词：剪口播、处理视频、识别口误、A 模式剪口播
---

# 剪口播 

> 火山引擎转录 + AI 口误识别 + 网页审核 / 字幕格式化

## 模式

- **模式 A: 剪口播** — 转录 → 口误识别 → 网页审核 → 剪辑
- **模式 B: 转字幕** — 转录 → 格式化字幕文本（markdown，无时间戳）

## 输出目录结构

**模式 A（剪口播）：** 一片一夹约定 — 产物落在源片所在文件夹的 `剪口播/` 下（`<片子文件夹>/剪口播/`）。建议每条视频一个文件夹，源片放在里面。
```
<源片所在文件夹>/剪口播/
├── 1_转录/   audio.mp3 · volcengine_v3_result.json · subtitles_words.json
├── 2_分析/   analysis.txt · sentence_map.json · speech_errors.json · auto_selected.json
└── 3_审核/   review.html · audio.mp3 · data.json · silence_periods.json
                <视频名>_cut.fcpxml   ← 网页点击「导出 FCPXML」后生成在此目录
                                       拖入剪映 / Final Cut Pro 完成最终剪辑
```

**模式 B（转字幕）：**
```
output/YYYY-MM-DD_HH-MM_视频名/剪口播/
├── 1_转录/   audio.mp3 · volcengine_v3_result.json · subtitles_words.json · raw_text.txt
└── 2_纠错/   corrected.txt · uncertain.md（可选）
视频所在目录/
└── subtitles_formatted.md   ← 最终输出
```

## 流程总览

```
-1. 首次引导（仅第一次：环境自检 + 配置火山引擎）
0. 确认视频路径 + 选择模式
1-4. run_transcribe.sh（自动，两模式共用）

模式 A（剪口播）:
  5.1 gen_analysis.js
  5.2 读规则.md + analysis.txt
  5.3 AI 判断整句口误 → speech_errors.json（只填 delete_sentences）
  5.4 auto_filler.js → 自动补充词级口癖 idx（快速预筛）
  5.5 AI 逐句扫剩余词级口癖（B2/B3/B4，脚本覆盖不到的部分）
  5.6 merge_selections.js
  6-7. 生成审核网页 + 启动服务器
  【等待用户确认】→ 网页点击「导出 FCPXML」→ 初剪定稿
       → 导出同时提交 FCPXML + review_log.json + rough-cut-export.receipt.json
       → receipt 绑定两个产物与逐字稿指纹；任一缺失或不匹配都不算初剪完成
       → 交给剪映 / Final Cut Pro 继续加字幕、包装（或接你自己的下游流程）
  8. 自进化学习（用户显式触发「已导出，学一下」）→ diff 抽规则 → 确认 → 写 经验规则.md

模式 B（转字幕）:
  B-1 提取纯文本
  B-2 第一步：纠错（只改词，不断行）→ corrected.txt
  B-3 第二步：断行（只格式化，不改字）→ subtitles_formatted.md
```

## 执行步骤

> **路径约定（重要）**：本 skill 不绑定特定 agent，**不要假设它装在 `~/.claude/skills/`**。
> 下面命令里的 `SKILL_DIR` 一律指**本 skill 的安装目录**（即你加载本 `SKILL.md` 的那个目录，
> 含 `scripts/`、`用户习惯/`）。执行前把它设成你实际加载 skill 的绝对路径即可：
> ```bash
> SKILL_DIR="<本 skill 的安装目录>"   # 例：Claude Code 默认 ~/.claude/skills/AI剪口播
> ```
> API Key 的查找顺序见 [scripts/lib/load_api_key.sh](scripts/lib/load_api_key.sh)：
> 环境变量 `VOLCENGINE_API_KEY` → `$SKILL_DIR/.env` →（兼容旧约定）上一级 `.env`。

### 步骤 -1: 首次引导（只在第一次跑）

> **目的**：第一次用本 Skill 的人通常没装依赖、没配火山引擎 key。先做一次自检并手把手引导，配好后写标记文件，**以后永久跳过，不再打扰**。

**闸门**：先看标记文件是否存在（`SKILL_DIR` = 本 skill 安装目录，见上方「路径约定」）。
```bash
SKILL_DIR="<本 skill 的安装目录>"
[ -f "$SKILL_DIR/.setup_done" ] && echo "已配置，跳过引导" || echo "需要引导"
```
- 存在 `.setup_done` → **直接进入步骤 0**，不要跑自检、不要提引导。
- 不存在 → 跑自检脚本（跨平台，Win/macOS/Linux 通用）：

```bash
node "$SKILL_DIR/scripts/doctor.js"
```

`doctor.js` 做三层检查并输出人话报告：① 系统依赖（ffmpeg/node/python3/curl）② `VOLCENGINE_API_KEY`（环境变量或 `.env`，查找顺序见 `scripts/lib/load_api_key.sh`）③ 联网实测 key 与极速版/标准版两个资源是否开通。**全绿时它自己写 `.setup_done` 并退出 0**；有缺项退出 1。

**AI 按报告分情况引导用户**（不要让用户自己看懂报告）：
1. **缺系统依赖** → 把报告里对应平台的安装命令复制给用户（脚本已按 Win/Mac 给好），让其装完。
2. **缺 / 占位 API Key** → 按以下流程引导用户（火山引擎·豆包语音服务，共 40h 免费额度）：
   1. 登录控制台 https://console.volcengine.com/speech/new/overview
   2. 左侧「语音识别」→ 开通「录音文件识别 1.0」，**标准版 + 极速版都开**（各 20h、共 ≈40h，独立抵扣）
   3. 左侧「API Key 管理」→ 复制 API Key
   4. 写入 `$SKILL_DIR/.env`（推荐，跟着 skill 走；也可 `export VOLCENGINE_API_KEY=...`）：
   ```bash
   echo "VOLCENGINE_API_KEY=粘贴你的key" >> "$SKILL_DIR/.env"
   ```
3. **某个资源未开通**（报告会精确指出是极速版还是标准版）→ 引导去控制台开通对应「录音文件识别 1.0」资源；默认 auto 轮流需两个都开（各 20h 免费、共 ≈40h），只想用一个就转录时加 `--flash` / `--v3-standard`。
4. 用户修完 → **重跑 `node "$SKILL_DIR/scripts/doctor.js"`**，直到全绿（自动写 `.setup_done`），再进入步骤 0。

> 全程不要替用户去控制台点按钮或粘贴他的私有 key 到别处；只给清晰可复制的命令和链接。

### 步骤 0: 确认视频路径 + 选择模式

收到视频路径后，**先展示确认**，格式：

```
📹 视频：/path/to/视频.mp4
📁 输出：<源片所在文件夹>/剪口播/   （一片一夹约定：产物落在源片旁边）

请选择模式：
  [A] 剪口播 — 识别口误 → 网页审核 → 导出 FCPXML 给剪映 / FCP
  [B] 转字幕 — 转录 → 格式化字幕文本（markdown，无时间戳）
```

用户确认后再继续，不自动开始。

### 步骤 1-4: 一键转录流水线（无需 AI）

> **硬规则 · 转录引擎（代码层已有守卫）**
>
> 1. **逐字稿只能来自火山引擎**（`run_transcribe.sh`，产物 `volcengine_v3_result.json`）。**禁止**用 whisper 或任何其他 ASR 的结果转成 `subtitles_words.json` 塞进本流水线——格式对不代表来源对。
> 2. **转录失败必须停下报告用户**，说明失败原因（先跑 `node scripts/doctor.js --force` 确认是 key、资源还是网络问题），**不得自行寻找替代引擎继续往下跑**。
> 3. 用户**确认后**可以用替代引擎，但必须由用户认可后在 `1_转录/` 写 `.asr_override.json`（含 `engine` / `reason` / `confirmedAt` 三个字段）显式放行；agent 不得自行创建该文件绕过检查。放行后流水线仍会打印醒目告警，审核页需逐句核对——替代引擎的专名/术语错字率明显更高。
>
> 守卫实现：`scripts/lib/assert_asr_source.js`，由 `gen_analysis.js` 与 `generate_review.js` 在消费逐字稿前调用，缺火山产物即 fail closed。
>
> 为什么这么严：实际发生过——转录被 agent 自行换成本地 whisper，全程无报错，成片里「晨报」被识别成「承报」6 处，直到看成片才发现。

```bash
SKILL_DIR="<本 skill 的安装目录>"   # 见上方「路径约定」
VIDEO_PATH="/path/to/视频.mp4"
# 一片一夹约定：产物落在源片所在文件夹的 剪口播/ 下，
# 便于「源片+产物」同处、源片不挪窝、批量按文件夹扫。
BASE_DIR="$(dirname "$VIDEO_PATH")/剪口播"
# 兜底：若源片没有放在自己的片子文件夹里（如临时放在 Downloads），
# 产物会落在源片旁边；建议先给每条视频建一个文件夹再跑。

bash "$SKILL_DIR/scripts/run_transcribe.sh" "$VIDEO_PATH" "$BASE_DIR"
# 输出: BASE_DIR/1_转录/{audio.mp3, volcengine_v3_result.json, subtitles_words.json}
#
# 默认引擎: auto 轮流（flash 极速版 auc_turbo ↔ 标准版 auc 交替）
#   - 每次转录自动切换引擎，分摊两份各 20h 免费额度 ≈ 共 40h
#   - 单 X-Api-Key 认证，base64 直传，不依赖外部图床
#   - 需在控制台同时开通极速版(auc_turbo)与标准版(auc)两个资源
#   - 限制: 音频 ≤ 2h、≤ 100MB
# 可选引擎（只开了一个资源、或想固定用某个时加）:
#   --flash        只用极速版（一次直出、最快）
#   --v3-standard  只用标准版（异步 submit/query 轮询）
```

### 步骤 5: 生成分析文件 + 口误识别

#### 5.1 生成分析文件

```bash
node "$SKILL_DIR/scripts/gen_analysis.js" \
  "$BASE_DIR/1_转录/subtitles_words.json" \
  "$BASE_DIR/2_分析"
# 输出: analysis.txt + sentence_map.json + auto_selected.json
```

#### 5.2 读取规则 + 分析文件

读 `用户习惯/规则.md`、`用户习惯/经验规则.md`（自进化沉淀的个人偏好，见步骤 8）和 `analysis.txt`。
两份规则都要遵守；冲突时以更具体、更新的为准。

`analysis.txt` 格式（每行一句，序号: 文本）：
```
0: 直接开始了啊
1: 这是深圳腾讯总部楼下
2: 就为了安装一只
```

#### 5.3 AI 判断整句口误（只填 delete_sentences）

> ⚠️ 由你直接阅读 `analysis.txt` 并判断哪些**整句**是口误。
> **本步只填 `delete_sentences`**，`delete_idx` 留空数组。词级口癖留到 5.4（脚本）+ 5.5（AI 补漏）。

按 `规则.md` 的 **A 节（整句删除）** 判断：重复重说、残句、句内卡顿、只含语气词的整句等。

**输出格式**（写入 `$BASE_DIR/2_分析/speech_errors.json`）：
```json
{
  "delete_sentences": [2, 3, 8, 10],
  "delete_idx": []
}
```

#### 5.4 脚本自动识别词级口癖（无需 AI）

```bash
node "$SKILL_DIR/scripts/auto_filler.js" \
  "$BASE_DIR/2_分析/sentence_map.json" \
  "$BASE_DIR/1_转录/subtitles_words.json" \
  "$BASE_DIR/2_分析/speech_errors.json"
```

脚本会**就地修改** `speech_errors.json`，把识别到的口癖 idx 合并进 `delete_idx`：

- 任意位置：`呃 / 嗯 / 额 / 诶 / 欸 / 唉 / 噢`（已排除"额外/金额"等真词）
- 任意位置的：`然后`（用户偏好：宁可手动加回）
- 句首过渡词：`然后 / 那么 / 好的 / 啊 / 哦 / 哎 / 呀 / 对 / 呢 / 那`（"那"会避开"那个/那么/那里"等）
- 句尾废词：`对 / 呢 / 啊 / 哦`
- 跳过已整句删除的句子；保护剩余字数 ≤3-4 的短句不被掏空

跑完后，用户已手工填的 idx 也会被保留（合并去重）。

#### 5.5 AI 逐句扫剩余词级口癖（脚本覆盖不到的部分）

脚本只处理"无需上下文判断"的安全口癖。AI 在此扫 `analysis.txt`，找出脚本覆盖不到的：

- **B4 句中重说**（优先级最高）：前半段说错、后半段纠正 → 删前半段，保留后半段
- **B3 冗余引导短语**：大家可以看到、你看、给大家看一下、比如说你看一下、我可以告诉你、你明白吗
- **B2 句中填充词**（**慎用**，需明确判断为口癖才删）：其实、就、也、大概、这个、那个、就是
- **B5 脚本未覆盖的句尾拖音**

**工作方式（避免 token 爆炸 + 过删）：**
1. 顺序扫 `analysis.txt`，只标"明显有问题"的句子。没明显问题的句子直接跳过，不要为了"也许能再删一点"硬挑刺。
2. 把候选句号攒成一批（建议 20-30 句一组），**一次** `gen_word_detail.js` 调用拿到词级 idx。
3. 把新增 idx **合并**写回 `speech_errors.json` 的 `delete_idx`（与 5.4 结果取并集，不要覆盖）。

```bash
# 一次传多个句号，减少往返
node "$SKILL_DIR/scripts/gen_word_detail.js" \
  "$BASE_DIR/2_分析/sentence_map.json" \
  "$BASE_DIR/1_转录/subtitles_words.json" \
  5 8 12 24 25 44 ...
```

**判断尺度**：句子已经能读通就不要再动。剪口播的容错来自审核网页（用户能取消勾选），但**误删比漏删难恢复**——用户得手动取消勾选才能找回。所以**漏删优于过删**。追加删除语境依赖词（就是 / 那个 / 对 / 所以 / 其实等；"然后"已被 5.4 脚本全删，无需再扫）时，必须过 `规则.md` C 节的四判据——只有判成无功能垫话才删。

#### 5.6 合并到 auto_selected（代码自动映射句号→idx）

```bash
node "$SKILL_DIR/scripts/merge_selections.js" \
  "$BASE_DIR/2_分析/sentence_map.json" \
  "$BASE_DIR/2_分析/speech_errors.json" \
  "$BASE_DIR/2_分析/auto_selected.json"
```

#### 5.7 参考稿存活自检（可选——用户主动提供了参考稿才做，没提供不问、不设门，直接跳过）

> 有参考稿时（如提词器里的逐字稿），把稿子当 ground truth 做一次防过剪自检。稿子是"应该说的话"，实录会有即兴改词——按语义对应核对，不逐字比对。

1. 参考稿存 `2_分析/script.txt`
2. 对照删除结果核对：**参考稿的每一句，在保留内容里应恰好存活一次**
3. 稿中某句在保留内容里消失 → 疑似过剪（常见于修辞性复述被误判 retake，见 规则.md A1），从 `delete_sentences` 移除对应句
4. 稿中某句存活两次以上 → 疑似漏删的重复 retake，按 A1 四步验证后再决定是否补删
5. 本步只修正 AI 初选；最终裁决仍在步骤 6-7 网页审核。拿不准的保留（漏删优于过删）

### 步骤 6-7: 生成审核数据并启动服务器

```bash
# 6. 生成 data.json + review.html（从 templates/review.html 复制）
#    前端模板在 scripts/templates/review.html，改样式直接改那里
node "$SKILL_DIR/scripts/generate_review.js" \
  "$BASE_DIR/1_转录/subtitles_words.json" \
  "$BASE_DIR/2_分析/auto_selected.json" \
  "$BASE_DIR/1_转录/audio.mp3" \
  "$BASE_DIR/3_审核"

# 7. 启动审核服务器
#    serve_review.sh 会自动选端口、在【一个独立的 OS 终端窗口】里前台运行服务器、
#    健康检查、打开浏览器；若环境禁止开新窗口，会打印一条手动命令兜底。
#    （不要再用 `&` / nohup 在 agent 后台挂服务——见下方「为什么」。）
bash "$SKILL_DIR/scripts/serve_review.sh" \
  "$BASE_DIR/3_审核" "$VIDEO_PATH" "$SKILL_DIR/scripts/review_server.js"
```

> **⚠️ 为什么必须用 `serve_review.sh`，不能直接后台 `&`/nohup 挂服务（重要，否则用户会「拒绝连接」）：**
> 审核网页要这个本地服务**一直监听端口**。但各 agent 对后台进程的处理不同：
> - **Claude Code** 有常驻进程管理器，会在整个会话期间替你保活后台进程 → 直接 `&` 也没事；
> - **某些 agent（如 Codex）** 把每条命令放在临时子进程/沙箱里，命令一返回就**回收整棵进程树**
>   （连 `nohup`/`disown` 的子进程也杀）→ 端口失联，浏览器报「localhost 拒绝了连接请求」。
>
> 所以**不要依赖 agent 替你保活**。`serve_review.sh` 改在 OS 层另起一个真正的终端窗口前台运行
> （macOS 写可双击的 `.command` 并 `open`；Linux/Windows 起对应终端），它由系统拥有、不随 agent
> 命令回收。脚本最后还会打印一条 `bash "<3_审核>/启动审核服务.command"` 的手动命令——
> 万一连开窗口都被禁，让用户在自己的终端里跑这一条、**保持窗口开着**即可。
>
> 服务器启动时会把地址写进 `3_审核/server_url.txt`、进程号写进 `.review_server.pid`，方便排障。

用户在网页中：播放片段确认 → 勾选/取消 → 点击「导出 FCPXML」→ 生成 `*_cut.fcpxml`（初剪定稿）。

> **A 模式句尾安全规则（默认且不可静默降级）**：审核页采用「只删红色明确选区」。
> 黄色静音只是候选；顶栏静音阈值只负责批量勾成红色，未标红的字、gap 和自然停顿不得被
> 静音吸附或内部静音算法自动切掉。服务端必须按 `finalSelected` 重建删除段，并检查实际切口
> 是否碰到未选中的真词；命中即阻止导出。FCPXML 边界按源视频真实 fps 向外取整（开头 floor、
> 结尾 ceil），宁可多留不足一帧，不向内截断尾字。`preserveNaturalPauses:false` 只用于显式
> 兼容旧工程，不得作为 A 模式默认值。已有 `3_审核/review.html` 是生成时快照；要看到新说明需
> 重跑步骤 6，不能手改快照代替模板更新。

> **停顿四类判据**：每个 gap 先标 `natural-boundary / thinking-hesitation /
> retake-boundary / abnormal-silence`，再决定保留或压缩。自然断句保留 0.3–0.5s；思考停顿
> 只有在不改变语气、情绪与句法时才压缩；重录边界随失败版本删除；异常长静音压到约 0.3s。
> 所有类别都只能使用源片真实存在的静音，不得制造不存在的停顿。
>
> **置信分层**：`auto-safe` 仅限规则命中且切点不碰真词；`review-required` 包含语义依赖、
> 句首起音接近切点、短句重复、跨意图候选；`must-keep` 包含独有铺垫、修辞反问、引用/举例
> 中的口癖词与任何拿不准项。人工批准另记，不覆盖算法 confidence。
>
> **切点可解释性**：审核页和 `review_log.json` 对每个建议删除段记录来源规则、停顿类别、
> 删除前后时长、相邻保留词 id 与实际源帧边界。导出继续执行句尾保护，并增加“首音未被削掉”
> 检查：切点不得进入相邻保留词 `[startMs,endMs]`；命中即阻断，不靠听感猜测放行。
>
> **交付前四检**：① 无保留词被切口覆盖；② 连续听 3–5 个真实拼接点，句首辅音/爆破音完整；
> ③ 重录失败版未残留、不同意图未拼接；④ 长停顿已按四类处理且没有被清零。检查结果写入
> `review_log.json.acceptance`；缺项时不得把 FCPXML 报告为初剪定稿。

> **导出后**：先验证导出 receipt 与文字正本，再交给剪辑软件或你自己的下游流程。需要按剪后时间轴拿到逐句文字时，用附带的 `scripts/captions/build_cut_timeline.js`（读 `*_cut.fcpxml + review_log.json`）。

> **导出时服务器成套提交 `*_cut.fcpxml + review_log.json + rough-cut-export.receipt.json`**：receipt 最后写入，绑定 FCPXML、文字正本与逐字稿 SHA-256；任何一个文件写失败、被单独替换或缺失时，API 不返回成功，下游也必须 fail closed。`review_log.json` 记录
> AI 初选 idx、用户最终 idx、有效切割参数、源 fps、实际保留段、句尾保护检查，以及二者
> **词级 diff**（带文字+句子上下文）。
> 这是步骤 8「自进化学习」的唯一原料，**不读 `.fcpxml`**（那是算完的时间线，丢失了词级选择）。
> 同一文件的 `textAuthority` 还要冻结：逐字稿 SHA-256、最终删除的词级 idx、导出当时的全局/片内纠错词典。下游字幕、敏感词检测与分镜文字必须同时消费 `*_cut.fcpxml + review_log.json`；FCPXML 的向外取整只保护声音，不能让已经删除的词在字幕里复活。

### 页面导出 MP4（初剪视频）

审核页点击「导出 MP4」，按点击时的红色选区在本机生成 H.264/AAC MP4；保留原画幅和原声，不烧录字幕、不添加 B-roll。页面显示生成状态，完成后提供下载链接；本地文件保存在 `3_审核/`，文件名含唯一标识，避免覆盖以前的视频。无删除选区时导出完整视频，全删时拒绝导出。

MP4 使用服务端 `buildFcpxml` 的 `finalKeeps` 与同一尾字保护检查；成功后仍成套提交 FCPXML、文字正本和导出回执。MP4 是初剪交付，不代表完成分镜或正式成片验收。需要本机已有 ffmpeg/ffprobe，渲染失败在页面显示错误，可重试。模板更新后，旧审核页需要重新生成，并重新启动审核服务才生效。

### 步骤 8: 自进化学习（用户显式触发）

> **不自动跑。** 用户导出后，在**任意会话**说「<项目> 已导出，学一下」之类，才执行本步。
> 本步只读文件、不依赖对话上下文还在，所以冷会话也能跑。

1. **定位日志**：单个项目读 `<片子文件夹>/剪口播/3_审核/review_log.json`；
   批量重学则 glob `<你的视频根目录>/*/剪口播/3_审核/review_log.json`，逐个汇总。
   （日志只存在片子文件夹里，删片子文件夹会丢语料。）
2. **读现有规则**：先读 `用户习惯/经验规则.md` **全文** + `用户习惯/规则.md`，避免重复提已有规则。
3. **看 diff 抽规则**：对每条 `diff.aiOnly`（AI 想删你留回，可能过删）和 `diff.userOnly`
   （你删了 AI 没想到，可能漏删），对比「AI 为何这么剪 vs 你为何这么剪」，
   抽象出**能泛化到下一条视频**的通用偏好。**严禁**把单条口误/语境例外固化成规则。
4. **违例提醒**：若 diff 显示用户违反了某条已有规则，**逐条提醒**用户，让其判断
   是「正当例外（规则不动）」还是「该改松/加例外条件」。
5. **列给用户确认**：把候选的【新增 / 细化已有 / 合并重复 / 改某条】列出来，**等用户确认**。
6. **写入**：确认后才改 `用户习惯/经验规则.md`，每条带出处标签 `（学于 <视频名> YYYY-MM-DD；已确认）`。
   下次步骤 5.2 即生效。

### 模式 B: 转字幕

> 步骤 1-4 完成后，如果用户选了模式 B，执行以下步骤。
> **两步拆分**：先纠错，再断行。两步必须分开进行，不要混为一步。

#### B-1 提取纯文本（脚本执行）

```bash
node "$SKILL_DIR/scripts/extract_text.js" \
  "$BASE_DIR/1_转录/subtitles_words.json" \
  "$BASE_DIR/1_转录"
# 输出: $BASE_DIR/1_转录/raw_text.txt
```

#### B-2 第一步：纠错（AI 处理）

1. 读取 `$BASE_DIR/1_转录/raw_text.txt`
2. 读取 `$SKILL_DIR/用户习惯/纠错prompt.md` 规则
3. **只做纠错**，不断行、不去标点、不改格式
4. 输出到 `$BASE_DIR/2_纠错/corrected.txt`（每行一句，与输入 1:1 对应）
5. 如有「不确定清单」，输出到 `$BASE_DIR/2_纠错/uncertain.md` 并在对话中列出给用户

#### B-3 第二步：断行（AI 处理）

1. 读取 `$BASE_DIR/2_纠错/corrected.txt`
2. 读取 `$SKILL_DIR/用户习惯/断行prompt.md` 规则
3. **只做格式化**，不改字、不删字、不加字
4. 输出到**视频所在目录**：`$(dirname "$VIDEO_PATH")/subtitles_formatted.md`
5. 告知用户文件路径，流程结束

---

## 配置

火山引擎 API Key 通过 `VOLCENGINE_API_KEY` 提供，查找顺序见 [scripts/lib/load_api_key.sh](scripts/lib/load_api_key.sh)：
环境变量 → `$VOLCENGINE_ENV_FILE` → `$SKILL_DIR/.env` →（兼容旧约定）skill 上一级的 `.env`。推荐写在 `$SKILL_DIR/.env`：
```
VOLCENGINE_API_KEY=your_api_key_here
```

去[新版控制台](https://console.volcengine.com/speech/new/overview)生成 **一个** API Key 即可——所有引擎共用这同一个 `VOLCENGINE_API_KEY`（均为新版控制台单 `X-Api-Key` 认证）。

默认 `auto` 轮流模式会交替用极速版和标准版，**需同时开通两个资源**：「录音文件识别 - 极速版」（`volc.bigasr.auc_turbo`）+「录音文件识别 - 标准版」（`volc.bigasr.auc`）。两者各有 20h 免费额度、各自独立抵扣，轮流即可吃满 ≈40h。若只想/只开通了其中一个资源，加 `--flash` 或 `--v3-standard` 固定使用。



---

## 推荐下一步

| 当发现… | 推荐 | 话术 |
|--------|------|------|
| 已在审核网页导出剪映主轨草稿 | 剪映 | "初剪已锁，在剪映首页打开新草稿，接着加字幕和包装。" |
| 用 Final Cut Pro 或其他剪辑软件 | 导出 FCPXML（通用） | "把 fcpxml 拖入剪辑软件继续。" |
| 审查时发现是稿子本身的结构问题 | 改稿重录 | "这不是剪辑能救的，建议改稿再重录。" |


## 剪映主轨交付

剪映 11.3.0 实测：FCPXML 的 asset-clip（含显式 lane=0）、clip/video 导入后仍落在附加轨。画面可播放不代表主轨识别成功；删除 library@location 不是主轨修复。

- 用户要在剪映继续加工时，审核页优先点「导出剪映主轨」。服务端 POST /api/jianying 复用同一次 finalKeeps、帧率和句尾检查，写入一个全新本地原生草稿，视频轨 flag=0。FCPXML、文字正本和原有回执仍一起生成。
- 默认 macOS 草稿目录通过 os.homedir() 推导；其他目录使用 JIANYING_DRAFT_ROOT。目录不存在时明确失败，不静默回退为已知会落附加轨的 FCPXML。
- 剪映首页打开返回的草稿名；列表未刷新时正常退出并重开剪映。不要再把配套 FCPXML 导入剪映作为主轨交付。
- 每次导出创建新草稿，不改已打开或已编辑草稿。每次落盘生成独立 receipt，guiVerified=false；实际打开后检查主轨位置、开中尾画面和总时长，不能把写入成功当 GUI 验收。
- 原生草稿只覆盖单条口播视频的帧对齐初剪。通用 FCPXML 仍可导出，但不能承诺所有剪映版本的主轨兼容。
- 不单独按 V（会停用片段）；不自动触发智能包装上传或付费处理。
- 回归：node --test scripts/tests/jianying.test.js scripts/tests/a_mode_tail_guard.test.js
