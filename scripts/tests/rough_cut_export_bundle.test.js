'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const {
  assertExportReceiptCurrent,
  commitRoughCutExportBundle,
} = require('../lib/export_bundle');

test('FCPXML 与 review_log 由 receipt-last 成套提交', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'rough-cut-export-'));
  try {
    const fcpxmlPath = path.join(root, 'clip_cut.fcpxml');
    const reviewLogPath = path.join(root, 'review_log.json');
    commitRoughCutExportBundle({
      fcpxmlPath,
      fcpxmlBytes: '<fcpxml/>',
      reviewLogPath,
      reviewLog: {
        video: 'clip',
        engineVersion: 'test',
        textAuthority: { wordsSha256: 'a'.repeat(64) },
      },
    });
    assert.doesNotThrow(() =>
      assertExportReceiptCurrent({ fcpxmlPath, reviewLogPath }),
    );
    fs.writeFileSync(fcpxmlPath, '<fcpxml changed="1"/>');
    assert.throws(
      () => assertExportReceiptCurrent({ fcpxmlPath, reviewLogPath }),
      /指纹不一致/,
    );
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('缺少 textAuthority 时拒绝提交且不写正式文件', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'rough-cut-export-'));
  try {
    const fcpxmlPath = path.join(root, 'clip_cut.fcpxml');
    const reviewLogPath = path.join(root, 'review_log.json');
    assert.throws(
      () =>
        commitRoughCutExportBundle({
          fcpxmlPath,
          fcpxmlBytes: '<fcpxml/>',
          reviewLogPath,
          reviewLog: { video: 'clip' },
        }),
      /textAuthority/,
    );
    assert.equal(fs.existsSync(fcpxmlPath), false);
    assert.equal(fs.existsSync(reviewLogPath), false);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});
