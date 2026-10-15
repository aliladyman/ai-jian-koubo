'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {
  computeFinalKeeps,
  buildDeleteListFromSelection,
  findUnselectedWordCutRisks,
} = require('../lib/compute_keeps');
const {
  quantizeSegmentOutward,
  mergeQuantizedKeeps,
} = require('../lib/fcpxml');

test('安全模式只删除明确选区，不吸附误判静音', () => {
  const keeps = computeFinalKeeps(
    [{ start: 2, end: 2.4 }],
    [{ start: 1.55, end: 1.92 }, { start: 2.45, end: 2.8 }],
    4,
    { preserveNaturalPauses: true }
  );
  assert.deepEqual(keeps, [
    { start: 0, end: 2 },
    { start: 2.4, end: 4 },
  ]);
});

test('旧版静音吸附只在显式兼容开关下运行', () => {
  const keeps = computeFinalKeeps(
    [],
    [{ start: 1.2, end: 1.6 }],
    3,
    { preserveNaturalPauses: false, minInternalSilence: 0.2 }
  );
  assert.equal(keeps.length, 2);
});

test('未选中的 gap 会切断删除段，不被两侧红词暗中吞掉', () => {
  const words = [
    { text: '删', start: 0, end: 0.2 },
    { text: '', start: 0.2, end: 0.65, isGap: true },
    { text: '删', start: 0.65, end: 0.9 },
  ];
  assert.deepEqual(buildDeleteListFromSelection(words, [0, 2]), [
    { start: 0, end: 0.2 },
    { start: 0.65, end: 0.9 },
  ]);
});

test('尾字保护检查能拦住切口穿过未选中文字', () => {
  const words = [
    { text: '最', start: 1.2, end: 1.4 },
    { text: '后', start: 1.4, end: 1.68 },
    { text: '删', start: 2, end: 2.3 },
  ];
  const risks = findUnselectedWordCutRisks(
    words,
    [2],
    [{ start: 0, end: 1.5 }, { start: 2.3, end: 3 }],
    3
  );
  assert.equal(risks.length, 1);
  assert.equal(risks[0].text, '后');
  assert.ok(risks[0].overlap >= 0.17);
});

test('14.985fps 边界向外取整，不向内截断', () => {
  const fpsNum = 15000;
  const fpsDen = 1001;
  const raw = { start: 1.021, end: 1.487 };
  const q = quantizeSegmentOutward(raw, fpsNum, fpsDen, 4);
  assert.ok(q.start <= raw.start);
  assert.ok(q.end >= raw.end);
  assert.equal(Number.isInteger(q.startFrame), true);
  assert.equal(Number.isInteger(q.endFrame), true);
});

test('短到不足一帧的删除被安全保留，不生成重叠卡音', () => {
  const fpsNum = 15000;
  const fpsDen = 1001;
  const quantized = [
    quantizeSegmentOutward({ start: 0, end: 1 }, fpsNum, fpsDen, 3),
    quantizeSegmentOutward({ start: 1.01, end: 3 }, fpsNum, fpsDen, 3),
  ];
  const merged = mergeQuantizedKeeps(quantized);
  assert.equal(merged.length, 1);
  assert.equal(merged[0].startFrame, 0);
});
