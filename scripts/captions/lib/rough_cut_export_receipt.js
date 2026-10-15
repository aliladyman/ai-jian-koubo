'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

function sha256File(filePath) {
  return crypto.createHash('sha256').update(fs.readFileSync(filePath)).digest('hex');
}

function assertRoughCutExportReceipt({ fcpxmlPath, reviewLogPath, wordsPath }) {
  const receiptPath = path.join(path.dirname(fcpxmlPath), 'rough-cut-export.receipt.json');
  if (!fs.existsSync(receiptPath)) {
    throw new Error('缺少 rough-cut-export.receipt.json，禁止消费未成套提交的初剪结果');
  }
  const receipt = JSON.parse(fs.readFileSync(receiptPath, 'utf8'));
  if (!receipt || receipt.version !== 1 || !receipt.artifacts) {
    throw new Error('rough-cut-export.receipt.json 格式不合法');
  }
  const expected = [
    ['FCPXML', fcpxmlPath, receipt.artifacts.fcpxml],
    ['review_log.json', reviewLogPath, receipt.artifacts.reviewLog],
  ];
  for (const [label, filePath, entry] of expected) {
    if (!fs.existsSync(filePath)) throw new Error(label + ' 不存在');
    if (!entry || entry.file !== path.basename(filePath) || entry.sha256 !== sha256File(filePath)) {
      throw new Error(label + ' 与初剪导出回执不一致');
    }
  }
  const wordsSha256 = sha256File(wordsPath);
  if (receipt.wordsSha256 !== wordsSha256) {
    throw new Error('逐字稿与初剪导出回执不一致');
  }
  return receipt;
}

module.exports = { assertRoughCutExportReceipt };
