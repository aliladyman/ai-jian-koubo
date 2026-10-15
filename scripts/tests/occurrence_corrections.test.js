'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { validateSpan, validateOccurrences, correctKeptText } = require('../lib/occurrence_corrections');
const words = [...'他问他'].map((text, sourceIndex) => ({ text, sourceIndex }));

test('同字多次出现，只改指定出现处', () => {
  const fixes = validateOccurrences(words, [{ startIdx: 0, endIdx: 0, from: '他', to: '她' }]);
  assert.equal(correctKeptText(words, {}, fixes), '她问他');
  assert.equal(words.map(w => w.text).join(''), '他问他');
});

test('两处相同字可以分别改成不同内容，单处覆盖词典', () => {
  const fixes = validateOccurrences(words, [
    { startIdx: 0, endIdx: 0, from: '他', to: '她' },
    { startIdx: 2, endIdx: 2, from: '他', to: '它' },
  ]);
  assert.equal(correctKeptText(words, { 他: 'TA', 她: '错误' }, fixes), '她问它');
  assert.equal(correctKeptText(words, { 他: 'TA' }, fixes.slice(1)), 'TA问它');
});

test('改为原字可仅在这一处覆盖词典', () => {
  assert.equal(correctKeptText(words, { 他: '她' }, [{ startIdx: 0, endIdx: 0, from: '他', to: '他' }]), '他问她');
});

test('长度不同的修改不扩散，已删除的修改不会复活', () => {
  const fixes = validateOccurrences(words, [{ startIdx: 0, endIdx: 1, from: '他问', to: '小明问' }]);
  assert.equal(correctKeptText(words, {}, fixes), '小明问他');
  assert.equal(correctKeptText(words.slice(2), {}, fixes), '他');
  assert.throws(() => correctKeptText(words.slice(1), {}, fixes), /部分文字已剪掉/);
});

test('拒绝越界、错位、跨静音与重叠修改', () => {
  assert.throws(() => validateSpan(words, { startIdx: 3, endIdx: 3 }, '他'), /位置不合法/);
  assert.throws(() => validateSpan(words, { startIdx: 1, endIdx: 1 }, '他'), /原文不一致/);
  assert.throws(() => validateSpan([{ text: '', isGap: true }], { startIdx: 0, endIdx: 0 }, ''), /原文不一致/);
  assert.throws(() => validateOccurrences(words, [
    { startIdx: 0, endIdx: 1, from: '他问', to: '她问' },
    { startIdx: 1, endIdx: 1, from: '问', to: '答' },
  ]), /位置重叠/);
});
