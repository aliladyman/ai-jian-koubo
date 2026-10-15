'use strict';

function validateSpan(words, span, from) {
  if (!span || !Number.isInteger(span.startIdx) || !Number.isInteger(span.endIdx) ||
      span.startIdx < 0 || span.endIdx < span.startIdx || span.endIdx >= words.length) {
    throw new Error('纠错位置不合法');
  }
  const tokens = words.slice(span.startIdx, span.endIdx + 1);
  if (tokens.some(w => w.isGap) || tokens.map(w => w.text).join('') !== from) {
    throw new Error('纠错位置与原文不一致，请重新选字');
  }
  return { startIdx: span.startIdx, endIdx: span.endIdx };
}

function validateOccurrences(words, entries = []) {
  if (!Array.isArray(entries)) throw new Error('单处纠错记录格式不合法');
  const result = entries.map(c => {
    if (!c || typeof c.from !== 'string' || !c.from || c.from.length > 80 ||
        typeof c.to !== 'string' || !c.to || c.to.length > 80) {
      throw new Error('单处纠错文字不合法');
    }
    return { ...validateSpan(words, c, c.from), from: c.from, to: c.to };
  }).sort((a, b) => a.startIdx - b.startIdx);
  for (let i = 1; i < result.length; i++) {
    if (result[i].startIdx <= result[i - 1].endIdx) throw new Error('单处纠错位置重叠');
  }
  return result;
}

function applyDictionary(text, replacements) {
  let result = text;
  for (const [from, to] of Object.entries(replacements)
    .filter(([f]) => f).sort((a, b) => b[0].length - a[0].length)) {
    result = result.split(from).join(to);
  }
  return result;
}

function correctKeptText(kept, replacements, occurrences) {
  const indices = new Set(kept.map(w => w.sourceIndex));
  const active = new Map();
  for (const c of occurrences) {
    let count = 0;
    for (let i = c.startIdx; i <= c.endIdx; i++) if (indices.has(i)) count++;
    if (!count) continue;
    if (count !== c.endIdx - c.startIdx + 1) {
      throw new Error('纠错选区有部分文字已剪掉，请重新审核该处');
    }
    active.set(c.startIdx, c);
  }
  let text = '', raw = '';
  const flush = () => { text += applyDictionary(raw, replacements); raw = ''; };
  for (let i = 0; i < kept.length; i++) {
    const c = active.get(kept[i].sourceIndex);
    if (!c) { raw += kept[i].text; continue; }
    flush();
    // 单处修改最后生效，不能再被词典替换，也不能带回已删除的词。
    text += c.to;
    i += c.endIdx - c.startIdx;
  }
  flush();
  return text;
}

module.exports = { validateSpan, validateOccurrences, correctKeptText };
