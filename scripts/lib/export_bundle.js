'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

let tempCounter = 0;

function sha256Bytes(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

function sha256File(filePath) {
  return sha256Bytes(fs.readFileSync(filePath));
}

function tempPathFor(filePath) {
  tempCounter += 1;
  return path.join(
    path.dirname(filePath),
    '.' + path.basename(filePath) + '.tmp-' + process.pid + '-' + tempCounter,
  );
}

function atomicWrite(filePath, bytes) {
  const tmp = tempPathFor(filePath);
  fs.writeFileSync(tmp, bytes);
  fs.renameSync(tmp, filePath);
}

function receiptPathFor(fcpxmlPath) {
  return path.join(path.dirname(fcpxmlPath), 'rough-cut-export.receipt.json');
}

function assertExportReceiptCurrent({ fcpxmlPath, reviewLogPath, receiptPath }) {
  const resolvedReceiptPath = receiptPath || receiptPathFor(fcpxmlPath);
  if (!fs.existsSync(resolvedReceiptPath)) {
    throw new Error('缺少 rough-cut-export.receipt.json，初剪导出未完成提交');
  }
  const receipt = JSON.parse(fs.readFileSync(resolvedReceiptPath, 'utf8'));
  if (!receipt || receipt.version !== 1 || !receipt.artifacts) {
    throw new Error('rough-cut-export.receipt.json 格式不合法');
  }
  const checks = [
    ['FCPXML', fcpxmlPath, receipt.artifacts.fcpxml],
    ['review_log.json', reviewLogPath, receipt.artifacts.reviewLog],
  ];
  for (const [label, filePath, entry] of checks) {
    if (!fs.existsSync(filePath)) throw new Error(label + ' 不存在');
    if (!entry || entry.file !== path.basename(filePath)) {
      throw new Error(label + ' 与导出回执文件名不一致');
    }
    if (sha256File(filePath) !== entry.sha256) {
      throw new Error(label + ' 与导出回执指纹不一致，禁止混用不同导出');
    }
  }
  const log = JSON.parse(fs.readFileSync(reviewLogPath, 'utf8'));
  if (!log.textAuthority || !log.textAuthority.wordsSha256) {
    throw new Error('review_log.json 缺少 textAuthority.wordsSha256');
  }
  if (receipt.wordsSha256 !== log.textAuthority.wordsSha256) {
    throw new Error('导出回执与 review_log.json 的逐字稿指纹不一致');
  }
  return receipt;
}

function commitRoughCutExportBundle({
  fcpxmlPath,
  fcpxmlBytes,
  reviewLogPath,
  reviewLog,
}) {
  if (!reviewLog || !reviewLog.textAuthority || !reviewLog.textAuthority.wordsSha256) {
    throw new Error('缺少 textAuthority.wordsSha256，禁止提交初剪导出');
  }
  fs.mkdirSync(path.dirname(fcpxmlPath), { recursive: true });
  fs.mkdirSync(path.dirname(reviewLogPath), { recursive: true });
  const fcpxmlBuffer = Buffer.isBuffer(fcpxmlBytes)
    ? fcpxmlBytes
    : Buffer.from(String(fcpxmlBytes));
  const reviewLogBuffer = Buffer.from(JSON.stringify(reviewLog, null, 2) + '\n');
  const fcpxmlTmp = tempPathFor(fcpxmlPath);
  const reviewLogTmp = tempPathFor(reviewLogPath);
  try {
    fs.writeFileSync(fcpxmlTmp, fcpxmlBuffer);
    fs.writeFileSync(reviewLogTmp, reviewLogBuffer);
    // receipt 是提交标志：任一 rename 失败，旧 receipt 都会因 hash 不匹配而使下游 fail closed。
    fs.renameSync(reviewLogTmp, reviewLogPath);
    fs.renameSync(fcpxmlTmp, fcpxmlPath);
    const receipt = {
      version: 1,
      committedAt: new Date().toISOString(),
      video: reviewLog.video,
      engineVersion: reviewLog.engineVersion,
      wordsSha256: reviewLog.textAuthority.wordsSha256,
      artifacts: {
        fcpxml: {
          file: path.basename(fcpxmlPath),
          sha256: sha256Bytes(fcpxmlBuffer),
        },
        reviewLog: {
          file: path.basename(reviewLogPath),
          sha256: sha256Bytes(reviewLogBuffer),
        },
      },
    };
    const receiptPath = receiptPathFor(fcpxmlPath);
    atomicWrite(receiptPath, JSON.stringify(receipt, null, 2) + '\n');
    return assertExportReceiptCurrent({
      fcpxmlPath,
      reviewLogPath,
      receiptPath,
    });
  } finally {
    for (const tmp of [fcpxmlTmp, reviewLogTmp]) {
      try { fs.rmSync(tmp, { force: true }); } catch (_) {}
    }
  }
}

module.exports = {
  assertExportReceiptCurrent,
  commitRoughCutExportBundle,
  receiptPathFor,
  sha256File,
};
