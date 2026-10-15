#!/usr/bin/env node
/**
 * build_cut_timeline.js — 把初剪结果换算成「剪后时间轴」的句子清单（分镜输入）。
 *
 * 输入：
 *   --fcpxml <path>  ai剪口播导出的 *_cut.fcpxml（保留片段 = asset-clip 序列）
 *   --words  <path>  词级逐字稿，两种格式自动识别：
 *                    ① ai剪口播 subtitles_words.json：[{text,start,end,isGap}]（秒）
 *                    ② mvp transcript.json：{sources:[{words:[{text,startMs,endMs,kind}]}]}（毫秒）
 *   --review-log <path> 可选；默认读取 fcpxml 同目录 review_log.json，消费 A 模式最终删词与纠错快照
 *   --fixes  <path,...> 可选，显式追加纠错词典；无纠错快照时默认读取全局专名词典和片内字幕纠错.json
 *   --out    <path>  输出 JSON（默认 ./分镜输入.json）
 *
 * 输出：剪后时间轴上的句子清单。被剪掉的句子标 dropped，不参与分镜。
 * 红线：分镜摆位只能用本脚本输出的 startMs/endMs（剪后轴），
 *       绝不能直接用逐字稿里的原始录音轴时间（两轴可能相差十几秒）。
 * 零依赖，Node 18+。
 */
"use strict";
const fs = require("fs");
const os = require("os");
const path = require("path");
const { assertRoughCutExportReceipt } = require("./lib/rough_cut_export_receipt");
const { validateOccurrences, correctKeptText } = require("../lib/occurrence_corrections");

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i++) {
    const m = argv[i].match(/^--([\w-]+)$/);
    if (m) { args[m[1]] = argv[i + 1]; i++; }
  }
  if (!args.fcpxml || !args.words) {
    console.error("用法: node build_cut_timeline.js --fcpxml <..._cut.fcpxml> --words <subtitles_words.json|transcript.json> [--review-log review_log.json] [--fixes 纠错词典.json,...] [--out 分镜输入.json]");
    process.exit(2);
  }
  return args;
}

function splitFixPaths(value) {
  return String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => path.resolve(item));
}

function addUnique(list, value) {
  if (!value) return;
  const resolved = path.resolve(value);
  if (!list.includes(resolved)) list.push(resolved);
}

function discoverCorrectionFiles(args) {
  const files = [];
  const roots = [];

  // 与字幕转 srt 的优先级一致：全局词典先读，片内词典后读并覆盖全局。
  addUnique(files, process.env.AI_JIAN_KOUBO_GLOBAL_DICT || path.join(os.homedir(), ".ai-jian-koubo", "专名词典.json"));

  const addRoot = (root) => {
    if (!root) return;
    const resolved = path.resolve(root);
    if (!roots.includes(resolved)) roots.push(resolved);
  };
  if (args.fcpxml) {
    // <片子>/剪口播/3_审核/*.fcpxml → <片子>
    const reviewDir = path.dirname(path.resolve(args.fcpxml));
    addRoot(path.dirname(path.dirname(reviewDir)));
  }
  if (args.out) {
    // <片子>/分镜/分镜输入.json → <片子>
    addRoot(path.dirname(path.dirname(path.resolve(args.out))));
  }
  if (args.words) {
    // 兼容 <片子>/剪口播/1_转录/subtitles_words.json。
    const wordsDir = path.dirname(path.resolve(args.words));
    addRoot(path.dirname(path.dirname(wordsDir)));
  }
  for (const root of roots) {
    addUnique(files, path.join(root, "分镜", "字幕纠错.json"));
  }

  // 显式词典最后合并，允许一次性覆盖自动发现的词典。
  for (const file of splitFixPaths(args.fixes)) addUnique(files, file);
  return files;
}

function loadReviewAuthority(args) {
  const defaultPath = path.join(path.dirname(path.resolve(args.fcpxml)), "review_log.json");
  const reviewLogPath = args["review-log"] ? path.resolve(args["review-log"]) : defaultPath;
  if (!fs.existsSync(reviewLogPath)) {
    throw new Error(`review_log.json 不存在，禁止在无文字正本时生成分镜: ${reviewLogPath}`);
  }
  const log = JSON.parse(fs.readFileSync(reviewLogPath, "utf8"));
  const authority = log && log.textAuthority;
  if (!authority || !authority.wordsSha256 || !Array.isArray(authority.deletedWordIndices)) {
    throw new Error(`review_log.json 缺少完整 textAuthority: ${reviewLogPath}`);
  }
  assertRoughCutExportReceipt({
    fcpxmlPath: path.resolve(args.fcpxml),
    reviewLogPath,
    wordsPath: path.resolve(args.words),
  });
  const deletedWordIndices = Array.isArray(authority && authority.deletedWordIndices)
    ? authority.deletedWordIndices
    : [];
  if (!deletedWordIndices.every((index) => Number.isInteger(index) && index >= 0)) {
    throw new Error(`review_log.json 的删除 idx 非法: ${reviewLogPath}`);
  }
  if (authority && authority.wordsSha256) {
    const actual = require("crypto").createHash("sha256")
      .update(fs.readFileSync(path.resolve(args.words))).digest("hex");
    if (actual !== authority.wordsSha256) {
      throw new Error("review_log.json 与当前逐字稿指纹不匹配，拒绝混用不同导出的文字正本");
    }
  }
  const corrections = authority && authority.corrections;
  const snapshot = corrections && typeof corrections === "object"
    ? Object.assign({}, corrections.global || {}, corrections.local || {})
    : null;
  return {
    path: reviewLogPath,
    mode: "textAuthority",
    deletedWordIndices: new Set(deletedWordIndices),
    corrections: snapshot,
    occurrences: corrections && corrections.occurrences !== undefined ? corrections.occurrences : [],
  };
}

function loadCorrections(args, reviewAuthority) {
  const explicit = new Set(splitFixPaths(args.fixes));
  const hasSnapshot = reviewAuthority && reviewAuthority.corrections;
  const replacements = Object.assign({}, hasSnapshot ? reviewAuthority.corrections : {});
  const loadedFiles = hasSnapshot ? [`${reviewAuthority.path}#textAuthority.corrections`] : [];
  const files = hasSnapshot ? splitFixPaths(args.fixes) : discoverCorrectionFiles(args);
  for (const file of files) {
    if (!fs.existsSync(file)) {
      if (explicit.has(file)) throw new Error(`显式指定的纠错词典不存在: ${file}`);
      continue;
    }
    let data;
    try {
      data = JSON.parse(fs.readFileSync(file, "utf8"));
    } catch (err) {
      throw new Error(`纠错词典不是有效 JSON: ${file}（${err.message}）`);
    }
    const map = data && data.replacements;
    if (map !== undefined && (typeof map !== "object" || Array.isArray(map) || map === null)) {
      throw new Error(`纠错词典 replacements 必须是对象: ${file}`);
    }
    for (const [from, to] of Object.entries(map || {})) {
      if (typeof from !== "string" || typeof to !== "string") {
        throw new Error(`纠错词典存在非字符串替换项: ${file}`);
      }
      replacements[from] = to;
    }
    loadedFiles.push(file);
  }
  return { replacements, loadedFiles };
}

function applyTextCorrections(text, replacements) {
  let result = text;
  const entries = Object.entries(replacements)
    .filter(([from]) => from.length > 0)
    .sort((a, b) => b[0].length - a[0].length);
  for (const [from, to] of entries) result = result.split(from).join(to);
  return result;
}

// "107/30s" | "0s" | "-5/30s" → 毫秒
function fcpTimeToMs(v) {
  const m = String(v).trim().match(/^(-?\d+)(?:\/(\d+))?s$/);
  if (!m) throw new Error(`无法解析 fcpxml 时间值: ${v}`);
  return (Number(m[1]) / (m[2] ? Number(m[2]) : 1)) * 1000;
}

function parseFcpxmlClips(xml) {
  const clips = [];
  const re = /<asset-clip\b[^>]*>/g;
  let m;
  while ((m = re.exec(xml)) !== null) {
    const tag = m[0];
    const attr = (name) => {
      const a = tag.match(new RegExp(`\\b${name}="([^"]+)"`));
      return a ? a[1] : null;
    };
    const offset = attr("offset");
    const start = attr("start");
    const duration = attr("duration");
    if (offset === null || duration === null) continue;
    clips.push({
      tlStartMs: fcpTimeToMs(offset),
      srcStartMs: start === null ? 0 : fcpTimeToMs(start),
      durMs: fcpTimeToMs(duration),
    });
  }
  clips.sort((a, b) => a.tlStartMs - b.tlStartMs);
  return clips;
}

// 两种逐字稿格式 → 统一 token: {text, startMs, endMs, isGap}
function loadWords(file) {
  const data = JSON.parse(fs.readFileSync(file, "utf8"));
  if (Array.isArray(data)) {
    // ai剪口播 subtitles_words.json（秒）
    return {
      format: "subtitles_words",
      tokens: data.map((w) => ({
        text: w.text ?? "",
        startMs: Math.round((w.start ?? 0) * 1000),
        endMs: Math.round((w.end ?? 0) * 1000),
        isGap: Boolean(w.isGap),
      })),
    };
  }
  if (data && Array.isArray(data.sources)) {
    // mvp transcript.json（毫秒）
    const tokens = [];
    for (const src of data.sources) {
      for (const w of src.words || []) {
        tokens.push({
          text: w.text ?? "",
          startMs: w.startMs,
          endMs: w.endMs,
          isGap: w.kind === "spacing",
        });
      }
    }
    return { format: "transcript", tokens };
  }
  throw new Error("无法识别逐字稿格式：既不是数组（subtitles_words），也没有 sources（transcript）");
}

// 词（原始轴）→ 剪后轴。取与词时间重叠最大的保留片段；完全无重叠（词落在删除区内）返回 null。
// 用「重叠」而非「中点」判断：句边界的词常紧贴初剪切割点，中点易落在保留段外被误丢，
// 导致每句边界丢 1-2 字（2026-07-22 修）。被删除口误词的语音完全在删除区、零重叠，仍正确丢弃。
function mapWordToTimeline(word, clips) {
  let best = null, bestOverlap = 0;
  for (const c of clips) {
    const srcEndMs = c.srcStartMs + c.durMs;
    const overlap = Math.min(word.endMs, srcEndMs) - Math.max(word.startMs, c.srcStartMs);
    if (overlap > bestOverlap) {
      bestOverlap = overlap;
      best = {
        startMs: Math.round(c.tlStartMs + Math.max(0, word.startMs - c.srcStartMs)),
        endMs: Math.round(c.tlStartMs + Math.min(c.durMs, word.endMs - c.srcStartMs)),
      };
    }
  }
  return best;
}

function main() {
  const args = parseArgs(process.argv);
  const xml = fs.readFileSync(args.fcpxml, "utf8");
  const clips = parseFcpxmlClips(xml);
  if (clips.length === 0) throw new Error("fcpxml 里没有找到 asset-clip 保留片段");
  const { format, tokens } = loadWords(args.words);
  const reviewAuthority = loadReviewAuthority(args);
  const { replacements, loadedFiles } = loadCorrections(args, reviewAuthority);
  const occurrences = validateOccurrences(tokens, reviewAuthority.occurrences);

  // 按静音间隙聚句：gap token 是分隔符
  const sentences = [];
  let cur = [];
  const flush = () => {
    if (cur.length === 0) return;
    const kept = [];
    for (const w of cur) {
      if (reviewAuthority && reviewAuthority.deletedWordIndices.has(w.sourceIndex)) continue;
      const tl = mapWordToTimeline(w, clips);
      if (tl) kept.push({ ...tl, text: w.text, sourceIndex: w.sourceIndex });
    }
    sentences.push({
      i: sentences.length,
      // 只修正展示文本；词的 start/end 和原始 ASR 文件保持不变。
      text: correctKeptText(kept, replacements, occurrences),
      srcStartMs: cur[0].startMs,
      srcEndMs: cur[cur.length - 1].endMs,
      startMs: kept.length ? kept[0].startMs : null,
      endMs: kept.length ? kept[kept.length - 1].endMs : null,
      dropped: kept.length === 0,
      keptRatio: cur.length ? Number((kept.length / cur.length).toFixed(2)) : 0,
    });
    cur = [];
  };
  tokens.forEach((t, sourceIndex) => {
    if (t.isGap) flush();
    else cur.push({ ...t, sourceIndex });
  });
  flush();

  const timelineDurationMs = Math.round(Math.max(...clips.map((c) => c.tlStartMs + c.durMs)));
  const keptCount = sentences.filter((s) => !s.dropped).length;
  const out = {
    meta: {
      fcpxml: path.resolve(args.fcpxml),
      wordsFile: path.resolve(args.words),
      wordsFormat: format,
      clipCount: clips.length,
      timelineDurationMs,
      sourceDurationMs: tokens.length ? tokens[tokens.length - 1].endMs : 0,
      sentences: sentences.length,
      kept: keptCount,
      dropped: sentences.length - keptCount,
      axis: "本文件 startMs/endMs 为剪后时间轴；分镜摆位只许用这两个字段",
      correctionFiles: loadedFiles,
      // 不把旧词写回产物 meta，避免扫描整份 JSON 时把词典键误当成正文。
      appliedFixes: Object.keys(replacements).length,
      occurrenceFixes: occurrences.length,
      correctionMode: "展示文本应用纠错词典和单处修改；时间码和原始 ASR 不改",
      reviewLog: reviewAuthority ? reviewAuthority.path : null,
      textAuthorityMode: reviewAuthority ? reviewAuthority.mode : "missing",
      deletedWordIndices: reviewAuthority ? reviewAuthority.deletedWordIndices.size : 0,
    },
    sentences,
  };
  const outPath = args.out || "分镜输入.json";
  fs.writeFileSync(outPath, JSON.stringify(out, null, 2), "utf8");

  const fmt = (ms) => `${String(Math.floor(ms / 60000)).padStart(2, "0")}:${String(Math.floor((ms % 60000) / 1000)).padStart(2, "0")}`;
  console.log(`剪后总时长 ${fmt(timelineDurationMs)}（${timelineDurationMs}ms），保留片段 ${clips.length} 段`);
  console.log(`句子 ${sentences.length} 句：保留 ${keptCount}，剪掉 ${sentences.length - keptCount}`);
  console.log(`已应用纠错词典 ${loadedFiles.length} 个，替换项 ${Object.keys(replacements).length} 个`);
  for (const file of loadedFiles) console.log(`  纠错词典：${file}`);
  console.log(`已写出 ${path.resolve(outPath)}`);
  for (const s of sentences.filter((x) => !x.dropped).slice(0, 3)) {
    console.log(`  [${fmt(s.startMs)}–${fmt(s.endMs)}] ${s.text.slice(0, 30)}`);
  }
}

if (require.main === module) main();

module.exports = {
  applyTextCorrections,
  loadReviewAuthority,
  mapWordToTimeline,
  parseFcpxmlClips,
};
