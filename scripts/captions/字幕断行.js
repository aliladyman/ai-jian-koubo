#!/usr/bin/env node
/**
 * 字幕断行.js — 确定性中文字幕断行（实现 ai剪口播 断行prompt.md 的全部规则）。
 *
 * 用法:
 *   node 字幕断行.js --json 分镜输入.json [--max-len 12] [--glue "词1,词2"]   # 带时间轴 → JSON 行
 *   node 字幕断行.js --text corrected.txt [--max-len 16] [--glue ...]          # 纯文本 → stdout
 *   node 字幕断行.js --audit-json 字幕行.json [--max-len 12] [--glue ...]       # 全量断行审计 → JSON 报告
 *
 * 规则来源: 本 skill 的 用户习惯/断行prompt.md（逐条对应 R 编号）
 *   R1 只格式化，不改字/删字/加字（冲突加行，绝不删词缩短）
 *   R2 每行 ≤ maxLen；能单行完整就不拆
 *   R3 断点优先级 ①句/从句边界(原标点) ②连词前 ③话题转折前 ④动词前(主语留上行)
 *   R4 绝不拆分单元: 词边界(Segmenter)+glue专名；数量词+名词不拆；英文串不拆；不在"的"前断
 *   R5 形态: 下行更长(梯形)；上行 ≥4 字
 *   R6 标点删除(留英文连字符)，位置记为①级断点   R7 空格规则   R8 分段留人   R9 不转换文字
 * 附加(2026-07-19 用户拍板):
 *   U1 语气词/依附助词不做行首   U2 不留孤字尾行(≥2字)
 *   U3 单字汉字不做行首——分词器会把"知识库"切成"知识|库"，禁止把半词的"库"甩到下行开头
 *   U4 碎句黏合(--json)——上游剪辑点可能把词从中间切成两句(如 i48"知识"/i49"库每天…")，
 *      对 <4 字的碎句，按时间间隙就近黏回相邻句再断行（详见 mergeFragments）
 * 断行改为「先按高优先断点(句界/连词/转折)硬预切，再对超长段按次优点补切」，
 * 保证连词一定断在其前(不再留行尾)；无合法断点的段落进 warnings，绝不硬拆。
 */
'use strict';
const fs = require('fs');
const { createHash } = require('crypto');

const CONJ = new Set(['但是', '所以', '因为', '然后', '而且', '但', '不过', '可是', '而']);   // R3②
const TURN = new Set(['其实', '另外', '不过']);                                              // R3③
const VERB = new Set(['是', '有', '要', '做', '想', '说', '看', '用', '给', '让', '把',      // R3④近似
  '去', '来', '能', '会', '帮', '搭', '剪', '读', '写', '发', '存', '整理', '总结', '解决', '变成']);
const MEASURE = new Set([...'篇条个张次年月日天块件位名家台部套支笔场层步项句字词行页分秒万亿只本段份轮遍趟回组批号倍成']);
const NO_HEAD = new Set([...'吧呢吗啊呀嘛哦哈呗喔哟诶嘞咯啦哇欸唉嗯呃额的了着过得地']);       // U1
const PUNCT = /[，。？！、；：""''《》（）,.?!;:"'()\[\]【】…—～~·]/;

const CNNUM = new Set([...'零一二三四五六七八九十两百千万亿']);                              // 中文数字连写不拆
const isCJK = (c) => /[一-鿿]/.test(c);
const isLatin = (t) => /^[A-Za-z0-9][A-Za-z0-9-]*$/.test(t);
const isNum = (t) => /^[0-9]+(\.[0-9]+)?$/.test(t);
const isSingleCJK = (t) => [...t].length === 1 && isCJK(t);                                  // U3

function tokenize(text) {
  const seg = new Intl.Segmenter('zh', { granularity: 'word' });
  const raw = [...seg.segment(text)].map((s) => s.segment).filter((s) => s.trim() !== '' || s === ' ');
  const toks = [];
  let clauseStart = false;
  for (let i = 0; i < raw.length; i++) {
    const t = raw[i];
    if (PUNCT.test(t) && t.length === 1) { clauseStart = true; continue; }                   // R6 删标点
    if (t === ' ') continue;
    if (t === '-' && toks.length && isLatin(toks[toks.length - 1].t) && i + 1 < raw.length && isLatin(raw[i + 1])) {
      toks[toks.length - 1].t += '-' + raw[++i];                                             // R4 GPT-4
      continue;
    }
    toks.push({ t, clauseStart });
    clauseStart = false;
  }
  return toks;
}

function glueTokens(toks, glue) {                                                            // R4 专名粘连
  if (!glue.size) return toks;
  const out = [];
  for (let i = 0; i < toks.length; i++) {
    let merged = false;
    for (const span of [4, 3, 2]) {
      if (i + span <= toks.length) {
        const cand = toks.slice(i, i + span).map((x) => x.t).join('');
        if (glue.has(cand)) { out.push({ t: cand, clauseStart: toks[i].clauseStart }); i += span - 1; merged = true; break; }
      }
    }
    if (!merged) out.push(toks[i]);
  }
  return out;
}

const width = (t) => [...t.t].reduce((n, c) => n + (isCJK(c) ? 1 : 0.6), 0);
const lineWidth = (toks) => toks.reduce((n, x) => n + width(x), 0);

function join(toks) {                                                                        // R7 空格
  let out = '';
  for (let i = 0; i < toks.length; i++) {
    if (i && isLatin(toks[i - 1].t) && isLatin(toks[i].t)) out += ' ';
    out += toks[i].t;
  }
  return out;
}

function legalCut(toks, i, relax) {                                                          // 在 toks[i] 前断是否合法
  const prev = toks[i - 1], cur = toks[i];
  if (!prev || !cur) return false;
  if (cur.t === '的' || NO_HEAD.has(cur.t)) return false;                                     // R4"的" + U1(硬约束)
  if (isNum(prev.t) && MEASURE.has(cur.t)) return false;                                      // R4 数字|量词
  if (i >= 2 && isNum(toks[i - 2].t) && MEASURE.has(prev.t)) return false;                    // R4 量词|名词
  if (isLatin(prev.t) && isLatin(cur.t)) return false;                                        // R4 英文串
  if (CNNUM.has([...prev.t].pop()) && CNNUM.has([...cur.t][0])) return false;                 // 数字连写(七|八年)不拆
  // U3 单字禁行首（软约束，relax 时放开）：动词单字例外(主语留上行/谓语下行)
  if (!relax && isSingleCJK(cur.t) && !cur.clauseStart && !CONJ.has(cur.t) && !TURN.has(cur.t) && !VERB.has(cur.t)) return false;
  return true;
}

function presplit(toks) {                                                                   // R3①②③ 硬预切
  const segs = []; let cur = [];
  for (const t of toks) {
    // 高优先断点前切段，但前段 <4 字不切(避免"现在"这种短行单独成段)
    if (cur.length && lineWidth(cur) >= 4 && (t.clauseStart || CONJ.has(t.t) || TURN.has(t.t))) { segs.push(cur); cur = [t]; }
    else cur.push(t);
  }
  if (cur.length) segs.push(cur);
  const fixed = [];                                                                         // 尾部纯连词段黏回前段(避免"但是"孤悬句尾)
  for (const s of segs) {
    if (fixed.length && s.every((x) => CONJ.has(x.t) || TURN.has(x.t))) fixed[fixed.length - 1] = fixed[fixed.length - 1].concat(s);
    else fixed.push(s);
  }
  return fixed;
}

function scoreLong(toks, i, maxLen) {                                                        // 超长段内次优点评分
  let s = 1;                                                                                 // 词边界兜底
  if (VERB.has(toks[i].t)) s = 3;                                                            // R3④ 动词前
  const L = lineWidth(toks.slice(0, i)), R = lineWidth(toks.slice(i));
  if (L < 4) s -= 4;                                                                         // R5 上行≥4
  if (R < 2) s -= 99;                                                                        // U2 孤字尾行
  if (L > maxLen || R > maxLen) s -= 2;
  s -= Math.abs(L - R) * 0.15;
  if (L <= R) s += 1.2;                                                                      // R5 梯形
  return s;
}

function splitLong(toks, maxLen, warnings, src) {                                            // 段超长→按次优点二分
  if (lineWidth(toks) <= maxLen) return [toks];                                              // R2
  for (const relax of [false, true]) {                                                       // 先严格(守U3)，无点则放宽单字行首
    let best = -1, bestS = -Infinity;
    for (let i = 1; i < toks.length; i++) {
      if (!legalCut(toks, i, relax)) continue;
      const s = scoreLong(toks, i, maxLen);
      if (s > bestS) { bestS = s; best = i; }
    }
    if (best >= 0) return [...splitLong(toks.slice(0, best), maxLen, warnings, src),
                           ...splitLong(toks.slice(best), maxLen, warnings, src)];
  }
  warnings.push(`无合法断点(整段超长,未拆): ${src}`); return [toks];                          // R1 绝不硬拆
}

function breakSentence(text, maxLen, warnings, glue) {
  const toks = glueTokens(tokenize(text), glue);
  if (!toks.length) return [];
  const lines = [];
  for (const seg of presplit(toks)) lines.push(...splitLong(seg, maxLen, warnings, text));
  return lines.map(join).filter(Boolean);
}

// U4 碎句黏合：<4 字碎句黏回相邻句（修上游把词从中间切成两句，如 i48"知识"/i49"库每天…"）
// 方向优先级：① glue 词汇信号(碎句是某专名前缀，碎句+下句以该专名开头 → 向后) ② 时间就近兜底
// —— 词被切开处恰有停顿，时间信号会误导，故词汇信号优先。
function mergeFragments(sents, maxGapMs, glue) {
  const len = (x) => [...x.text].length;
  const isFrag = (x) => len(x) < 4;
  const gap = (a, b) => (b.startMs != null && a.endMs != null) ? b.startMs - a.endMs : Infinity;
  const merge = (a, b) => ({ ...a, text: a.text + b.text, endMs: b.endMs });
  const glueForward = (x, next) => {
    if (!next) return false;
    for (const g of glue) if (g.startsWith(x.text) && (x.text + next.text).startsWith(g)) return true;
    return false;
  };
  const out = [];
  for (let i = 0; i < sents.length; i++) {
    const x = sents[i], next = sents[i + 1], prev = out[out.length - 1];
    if (isFrag(x) && glueForward(x, next)) { out.push(merge(x, next)); i++; }                // ① 词汇信号向后
    else if (isFrag(x) && next && gap(x, next) <= maxGapMs && (!prev || gap(prev, x) >= gap(x, next))) { out.push(merge(x, next)); i++; }
    else if (isFrag(x) && prev && gap(prev, x) <= maxGapMs) { out[out.length - 1] = merge(prev, x); }
    else out.push(x);
  }
  return out;
}

// ---------------- 词级持久断点覆盖（2026-07-21 用户拍板） ----------------
// 覆盖只移动现有词边界，不得改字。所有 anchor 都精确绑定无覆盖基线 cue；
// source/review hash 任一不匹配即失败，禁止把旧覆盖模糊迁移到新内容。
const SHA256_RE = /^sha256:[0-9a-f]{64}$/;

function overrideError(message) {
  return new Error(`字幕断行覆盖无效: ${message}`);
}

function linePayloadHash(lines) {
  return `sha256:${createHash('sha256').update(JSON.stringify(lines)).digest('hex')}`;
}

function assertCue(value, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw overrideError(`${label} 必须是 cue 对象`);
  if (typeof value.text !== 'string' || !value.text) throw overrideError(`${label}.text 不能为空`);
  if (!Number.isInteger(value.startMs) || !Number.isInteger(value.endMs) || value.startMs < 0 || value.endMs <= value.startMs) {
    throw overrideError(`${label} 时间范围不合法`);
  }
  return { text: value.text, startMs: value.startMs, endMs: value.endMs };
}

function findBaselineCue(cues, expected, label) {
  const matches = cues.filter((cue) => cue.line.text === expected.text &&
    cue.line.startMs === expected.startMs && cue.line.endMs === expected.endMs);
  if (matches.length !== 1) throw overrideError(`${label} 未精确命中唯一基线 cue`);
  return matches[0];
}

function buildOverrideModel(lines, glue) {
  const tokens = [];
  const cues = [];
  const boundaries = new Set();                                                   // 在全局 token index 前断开
  for (let cueIndex = 0; cueIndex < lines.length; cueIndex++) {
    const line = lines[cueIndex];
    const cueTokens = glueTokens(tokenize(line.text), glue);
    if (!cueTokens.length || join(cueTokens) !== line.text) {
      throw overrideError(`基线 cue ${cueIndex} 无法按同一分词规则无损还原`);
    }
    const totalCodePoints = [...line.text].length;
    const boundaryTimes = [];
    const offsets = [];
    for (let i = 0; i <= cueTokens.length; i++) {
      const prefix = join(cueTokens.slice(0, i));
      const offset = [...prefix].length;
      offsets.push(offset);
      boundaryTimes.push(i === cueTokens.length
        ? line.endMs
        : Math.round(line.startMs + (line.endMs - line.startMs) * (offset / totalCodePoints)));
    }
    const globalStart = tokens.length;
    for (let i = 0; i < cueTokens.length; i++) {
      tokens.push({ token: cueTokens[i], startMs: boundaryTimes[i], endMs: boundaryTimes[i + 1] });
    }
    const cue = { cueIndex, line, tokens: cueTokens, offsets, globalStart, globalEnd: tokens.length };
    cues.push(cue);
    if (cueIndex > 0) boundaries.add(globalStart);
  }
  return { tokens, cues, boundaries };
}

function validateOverrideEnvelope(raw, baselineLines, maxLen) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw) || raw.version !== 1) {
    throw overrideError('version 必须为 1');
  }
  const source = raw.source;
  if (!source || typeof source !== 'object' || Array.isArray(source) ||
      !SHA256_RE.test(source.baselineSha256 || '') || source.maxLen !== maxLen ||
      source.lineCount !== baselineLines.length) {
    throw overrideError('source 必须精确绑定当前 baseline hash、maxLen 和行数');
  }
  const actualBaselineHash = linePayloadHash(baselineLines);
  if (source.baselineSha256 !== actualBaselineHash) {
    throw overrideError(`基线已变化（期望 ${source.baselineSha256}，当前 ${actualBaselineHash}）`);
  }
  const review = raw.review;
  if (!review || typeof review !== 'object' || Array.isArray(review) || review.status !== 'complete' ||
      !SHA256_RE.test(review.finalLinesSha256 || '') || !Number.isInteger(review.lineCount) ||
      review.lineCount < 1 || review.actor !== 'agent' || typeof review.reviewedAt !== 'string' ||
      !Number.isFinite(Date.parse(review.reviewedAt))) {
    throw overrideError('review 必须包含 agent 的完整复核状态、最终 hash、行数与 ISO 时间');
  }
  if (!Array.isArray(raw.operations)) throw overrideError('operations 必须是数组');
  return raw;
}

function applyLineBreakOverrides(baselineLines, rawOverrides, maxLen, glue) {
  const overrides = validateOverrideEnvelope(rawOverrides, baselineLines, maxLen);
  const model = buildOverrideModel(baselineLines, glue);
  const forced = new Set();
  const joined = new Set();
  const ids = new Set();

  for (const operation of overrides.operations) {
    if (!operation || typeof operation !== 'object' || Array.isArray(operation) ||
        typeof operation.id !== 'string' || !operation.id.trim() || ids.has(operation.id)) {
      throw overrideError('每条 operation 必须有唯一非空 id');
    }
    ids.add(operation.id);
    if (!['agent', 'user-review'].includes(operation.origin) ||
        typeof operation.reason !== 'string' || !operation.reason.trim()) {
      throw overrideError(`${operation.id} 缺少合法 origin 或 reason`);
    }
    if (operation.op === 'force-break') {
      const anchor = operation.anchor;
      if (!anchor || typeof anchor !== 'object' || Array.isArray(anchor)) throw overrideError(`${operation.id} 缺少 anchor`);
      const cue = findBaselineCue(model.cues, assertCue(anchor.cue, `${operation.id}.anchor.cue`), operation.id);
      const offset = anchor.beforeCodePointOffset;
      if (!Number.isInteger(offset) || offset <= 0 || offset >= [...cue.line.text].length) {
        throw overrideError(`${operation.id} 的 beforeCodePointOffset 越界`);
      }
      const localIndex = cue.offsets.indexOf(offset);
      if (localIndex <= 0 || localIndex >= cue.tokens.length || !legalCut(cue.tokens, localIndex, true)) {
        throw overrideError(`${operation.id} 不是允许的词边界`);
      }
      if (anchor.leftToken !== cue.tokens[localIndex - 1].t || anchor.rightToken !== cue.tokens[localIndex].t) {
        throw overrideError(`${operation.id} 的相邻词校验失败`);
      }
      const boundary = cue.globalStart + localIndex;
      if (model.boundaries.has(boundary) || forced.has(boundary)) throw overrideError(`${operation.id} 重复指定已有断点`);
      forced.add(boundary);
    } else if (operation.op === 'join-up') {
      const anchor = operation.anchor;
      if (!anchor || typeof anchor !== 'object' || Array.isArray(anchor)) throw overrideError(`${operation.id} 缺少 anchor`);
      const upper = findBaselineCue(model.cues, assertCue(anchor.upper, `${operation.id}.anchor.upper`), `${operation.id}.upper`);
      const lower = findBaselineCue(model.cues, assertCue(anchor.lower, `${operation.id}.anchor.lower`), `${operation.id}.lower`);
      if (lower.cueIndex !== upper.cueIndex + 1 || upper.line.endMs !== lower.line.startMs) {
        throw overrideError(`${operation.id} 只能并回时间连续的相邻 cue`);
      }
      const leftToken = upper.tokens[upper.tokens.length - 1].t;
      const rightToken = lower.tokens[0].t;
      if (anchor.leftToken !== leftToken || anchor.rightToken !== rightToken) {
        throw overrideError(`${operation.id} 的相邻词校验失败`);
      }
      const boundary = lower.globalStart;
      if (!model.boundaries.has(boundary) || joined.has(boundary)) throw overrideError(`${operation.id} 重复移除同一断点`);
      joined.add(boundary);
    } else {
      throw overrideError(`${operation.id} 的 op 只允许 force-break 或 join-up`);
    }
  }

  const finalBoundaries = new Set(model.boundaries);
  for (const boundary of joined) finalBoundaries.delete(boundary);
  for (const boundary of forced) finalBoundaries.add(boundary);
  const groups = [];
  let current = [];
  for (let i = 0; i < model.tokens.length; i++) {
    if (i > 0 && finalBoundaries.has(i)) { groups.push(current); current = []; }
    current.push(model.tokens[i]);
  }
  if (current.length) groups.push(current);

  const finalLines = groups.map((group, index) => {
    const cueTokens = group.map((item) => item.token);
    if (lineWidth(cueTokens) > maxLen) throw overrideError(`应用后第 ${index + 1} 行超过 maxLen=${maxLen}`);
    const startMs = group[0].startMs;
    const endMs = group[group.length - 1].endMs;
    if (!Number.isInteger(startMs) || !Number.isInteger(endMs) || endMs <= startMs) {
      throw overrideError(`应用后第 ${index + 1} 行时间范围不合法`);
    }
    return { text: join(cueTokens), startMs, endMs };
  });
  const finalHash = linePayloadHash(finalLines);
  if (overrides.review.lineCount !== finalLines.length || overrides.review.finalLinesSha256 !== finalHash) {
    throw overrideError(`最终复核签名不匹配（当前 ${finalLines.length} 行，${finalHash}）`);
  }
  return finalLines;
}

// ---------------- 全量字幕断行审计 ----------------
// 审计只报告，不改文字、不重断。它既检查显式换行，也检查没有换行的单行 cue，
// 并对相邻 cue 的边界做保护词检查，避免上游时码把一个词从中间切开。
function auditCaptionLines(raw, maxLen, glue) {
  const sourceLines = Array.isArray(raw)
    ? raw
    : Array.isArray(raw?.lines)
      ? raw.lines
      : Array.isArray(raw?.captions)
        ? raw.captions
        : null;
  if (!sourceLines) throw new Error('字幕审计输入必须是数组，或包含 lines/captions 数组');

  const violations = [];
  const warnings = [];
  const add = (kind, index, detail) => violations.push({ kind, index, ...detail });
  const normalizedText = (text) => text.replace(/[\s]/gu, '');
  const segmentAudit = (text, cueIndex, lineIndex, segmentIndex) => {
    const normalized = normalizedText(text);
    if (!normalized) {
      add('empty-line', cueIndex, { lineIndex, segmentIndex, text });
      return;
    }
    const toks = glueTokens(tokenize(normalized), glue);
    if (join(toks) !== normalized) {
      warnings.push({ kind: 'normalization-mismatch', index: cueIndex, lineIndex, segmentIndex, text });
    }
    const measured = lineWidth(toks);
    if (measured > maxLen) {
      add('max-width', cueIndex, { lineIndex, segmentIndex, text, width: measured, maxLen });
    }
    if ([...normalized].length < 2) {
      add('orphan-line', cueIndex, { lineIndex, segmentIndex, text });
    }
    if (toks[0] && NO_HEAD.has(toks[0].t)) {
      add('function-word-head', cueIndex, { lineIndex, segmentIndex, text, token: toks[0].t });
    }
    if (segmentIndex > 0 && toks[0] && isSingleCJK(toks[0].t) && toks.length > 1 &&
        !CONJ.has(toks[0].t) && !TURN.has(toks[0].t) && !VERB.has(toks[0].t)) {
      add('single-cjk-head', cueIndex, { lineIndex, segmentIndex, text, token: toks[0].t });
    }
    return { text: normalized, toks };
  };

  const lines = sourceLines.map((line, index) => {
    if (!line || typeof line !== 'object' || typeof line.text !== 'string') {
      add('invalid-cue', index, { text: line?.text ?? null });
      return { text: '', startMs: null, endMs: null };
    }
    if (!Number.isInteger(line.startMs) || !Number.isInteger(line.endMs) || line.startMs < 0 || line.endMs <= line.startMs) {
      add('invalid-time', index, { text: line.text, startMs: line.startMs, endMs: line.endMs });
    }
    const segments = line.text.split(/\r?\n/u);
    if (segments.length > 1) {
      warnings.push({ kind: 'explicit-line-break', index, segments: segments.length, text: line.text });
    }
    const audited = segments.map((segment, segmentIndex) => segmentAudit(segment, index, index, segmentIndex));
    for (let i = 1; i < audited.length; i++) {
      const previous = audited[i - 1];
      const current = audited[i];
      if (!previous?.text || !current?.text) continue;
      const combined = previous.text + current.text;
      const combinedTokens = glueTokens(tokenize(combined), glue);
      const offset = [...previous.text].length;
      let cursor = 0;
      let boundaryIndex = -1;
      for (let tokenIndex = 0; tokenIndex < combinedTokens.length; tokenIndex++) {
        cursor += [...combinedTokens[tokenIndex].t].length;
        if (cursor === offset) { boundaryIndex = tokenIndex + 1; break; }
      }
      const latinBoundary = /^[A-Za-z0-9]$/u.test([...previous.text].at(-1) ?? '') &&
        /^[A-Za-z0-9]$/u.test([...current.text][0] ?? '');
      if (!latinBoundary && (boundaryIndex < 0 || !legalCut(combinedTokens, boundaryIndex, true))) {
        add('protected-break', index, {
          lineIndex: index,
          segmentIndex: i,
          text: line.text,
          left: previous.text,
          right: current.text,
        });
      }
    }
    return { text: normalizedText(line.text), startMs: line.startMs, endMs: line.endMs };
  });

  for (let i = 1; i < lines.length; i++) {
    const left = lines[i - 1];
    const right = lines[i];
    if (!left.text || !right.text) continue;
    const gapMs = right.startMs - left.endMs;
    if (gapMs > 350) continue;
    const combined = left.text + right.text;
    const combinedTokens = glueTokens(tokenize(combined), glue);
    const offset = [...left.text].length;
    let cursor = 0;
    let boundaryIndex = -1;
    for (let tokenIndex = 0; tokenIndex < combinedTokens.length; tokenIndex++) {
      cursor += [...combinedTokens[tokenIndex].t].length;
      if (cursor === offset) { boundaryIndex = tokenIndex + 1; break; }
    }
    const latinBoundary = /^[A-Za-z0-9]$/u.test([...left.text].at(-1) ?? '') &&
      /^[A-Za-z0-9]$/u.test([...right.text][0] ?? '');
    if (!latinBoundary && (boundaryIndex < 0 || !legalCut(combinedTokens, boundaryIndex, true))) {
      add('adjacent-protected-break', i, {
        previousIndex: i - 1,
        index: i,
        gapMs,
        left: left.text,
        right: right.text,
      });
    }
  }

  return {
    version: 1,
    maxLen,
    lineCount: sourceLines.length,
    violationCount: violations.length,
    warningCount: warnings.length,
    passed: violations.length === 0,
    violations,
    warnings,
  };
}

// ---------------- CLI ----------------
const args = process.argv.slice(2);
const get = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };
// --json 默认 12 与正本一致（:357 的 --overrides 闸门、caption-lines.ts 的 z.literal(12)、
// caption-review-production 的逐行宽度复核都按 12）。原先默认 14 会让照抄 usage 手敲的人
// 生成 14 宽基线，人审完 apply 时被 baselineSha256 拦下报「基线已变化」，整轮复核白做。
const maxLen = Number(get('--max-len', get('--json', null) || get('--audit-json', null) ? 12 : 16));
const maxGap = Number(get('--merge-gap', 350));
const glue = new Set((get('--glue', '') || '').split(',').map((s) => s.trim()).filter(Boolean));
const overridesPath = get('--overrides', null);
const warnings = [];

if (get('--audit-json', null)) {
  const data = JSON.parse(fs.readFileSync(get('--audit-json'), 'utf8'));
  const report = auditCaptionLines(data, maxLen, glue);
  process.stdout.write(JSON.stringify(report, null, 2));
  if (report.violationCount) process.exitCode = 2;
} else if (get('--json', null)) {
  if (overridesPath && maxLen !== 12) {
    throw overrideError('--overrides 必须显式使用 --max-len 12');
  }
  const data = JSON.parse(fs.readFileSync(get('--json'), 'utf8'));
  let sents = (data.sentences || data).filter((x) => !x.dropped);
  sents = mergeFragments(sents, maxGap, glue);                                               // U4
  const out = [];
  for (const x of sents) {
    const parts = breakSentence(x.text, maxLen, warnings, glue);
    const total = parts.reduce((n, p) => n + [...p].length, 0) || 1;
    let cur = x.startMs;
    for (const p of parts) {
      const dur = (x.endMs - x.startMs) * ([...p].length / total);
      out.push({ text: p, startMs: Math.round(cur), endMs: Math.round(cur + dur) });
      cur += dur;
    }
  }
  if (overridesPath) {
    const rawOverrides = JSON.parse(fs.readFileSync(overridesPath, 'utf8'));
    const applied = applyLineBreakOverrides(out, rawOverrides, maxLen, glue);
    out.splice(0, out.length, ...applied);
  }
  process.stdout.write(JSON.stringify({ maxLen, lines: out, warnings }, null, 1));
  if (warnings.length) process.stderr.write('待复核:\n' + warnings.join('\n') + '\n');
} else if (get('--text', null)) {
  if (overridesPath) throw overrideError('--overrides v1 只支持 --json 视频链');
  const src = fs.readFileSync(get('--text'), 'utf8').split('\n');
  const out = [];
  for (const line of src) {
    if (!line.trim()) { out.push(''); continue; }                                            // R8 留空行
    out.push(...breakSentence(line.trim(), maxLen, warnings, glue));
  }
  process.stdout.write(out.join('\n') + '\n');
  if (warnings.length) process.stderr.write('待复核:\n' + warnings.join('\n') + '\n');
} else {
  console.error('用法: node 字幕断行.js --json <分镜输入.json> [--overrides <字幕断行覆盖.json>] | --text <corrected.txt> [--max-len N] [--glue "词,词"] | --audit-json <字幕行.json> [--max-len N] [--glue "词,词"]');
  process.exit(1);
}
