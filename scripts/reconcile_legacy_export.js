#!/usr/bin/env node
'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { commitRoughCutExportBundle } = require('./lib/export_bundle');

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i++) {
    const match = argv[i].match(/^--([\w-]+)$/);
    if (!match) continue;
    if (match[1] === 'apply') args.apply = true;
    else args[match[1]] = argv[++i];
  }
  return args;
}

function readReplacements(filePath) {
  if (!filePath || !fs.existsSync(filePath)) return {};
  const data = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  if (!data.replacements || typeof data.replacements !== 'object' || Array.isArray(data.replacements)) {
    throw new Error('纠错词典 replacements 格式不合法: ' + filePath);
  }
  return data.replacements;
}

const args = parseArgs(process.argv);
for (const name of ['fcpxml', 'review-log', 'words']) {
  if (!args[name]) {
    throw new Error('用法: node reconcile_legacy_export.js --fcpxml <cut.fcpxml> --review-log <review_log.json> --words <subtitles_words.json> [--global-dict <json>] [--local-dict <json>] [--apply]');
  }
}
const fcpxmlPath = path.resolve(args.fcpxml);
const reviewLogPath = path.resolve(args['review-log']);
const wordsPath = path.resolve(args.words);
for (const filePath of [fcpxmlPath, reviewLogPath, wordsPath]) {
  if (!fs.existsSync(filePath)) throw new Error('文件不存在: ' + filePath);
}
const legacy = JSON.parse(fs.readFileSync(reviewLogPath, 'utf8'));
if (!Array.isArray(legacy.finalSelected)) {
  throw new Error('旧 review_log.json 缺少 finalSelected，无法安全迁入');
}
if (!legacy.finalSelected.every((index) => Number.isInteger(index) && index >= 0)) {
  throw new Error('旧 finalSelected 含非法 idx，无法安全迁入');
}
const migratedAt = new Date().toISOString();
const migrated = {
  ...legacy,
  textAuthority: {
    version: 1,
    kind: 'reconciled-review-export',
    wordsSha256: crypto.createHash('sha256').update(fs.readFileSync(wordsPath)).digest('hex'),
    deletedWordIndices: [...legacy.finalSelected].sort((a, b) => a - b),
    corrections: {
      global: readReplacements(args['global-dict']),
      local: readReplacements(args['local-dict']),
    },
    precedence: ['global', 'local'],
    migration: {
      migratedAt,
      note: '旧导出没有冻结纠错快照；本字段来自迁入时现有词典，不冒充原导出时状态',
    },
  },
};
if (!args.apply) {
  console.log(JSON.stringify({ write: false, reviewLog: migrated }, null, 2));
  process.exit(0);
}
const receipt = commitRoughCutExportBundle({
  fcpxmlPath,
  fcpxmlBytes: fs.readFileSync(fcpxmlPath),
  reviewLogPath,
  reviewLog: migrated,
});
console.log(JSON.stringify({ write: true, receipt }, null, 2));
