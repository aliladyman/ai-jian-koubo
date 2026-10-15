'use strict';
// FCPXML imports in Jianying 11.3.0 create an auxiliary track even with lane=0.
// Use the same frame-aligned keeps in a separate native draft; never patch live drafts.
const fs = require('fs');
const path = require('path');
const os = require('os');
const crypto = require('crypto');
const template = require('./jianying_template.json');
const clone = value => JSON.parse(JSON.stringify(value));
const uuid = () => crypto.randomUUID().toUpperCase();
function buildJianying({ videoFile, finalKeeps, mediaMeta, name }) {
  const { fpsNum, fpsDen, width, height, duration } = mediaMeta;
  if (![fpsNum, fpsDen, width, height, duration].every(n => Number.isFinite(n) && n > 0)) throw new Error('剪映导出缺少有效媒体信息');
  if (!Array.isArray(finalKeeps) || !finalKeeps.length) throw new Error('剪映主轨没有保留片段');
  const us = frames => Math.round(frames * fpsDen * 1000000 / fpsNum);
  const draft = clone(template.draft), video = clone(template.video);
  Object.assign(video, { id: uuid(), path: path.resolve(videoFile), material_name: path.basename(videoFile), width, height, duration: Math.ceil(duration * 1000000) });
  let frames = 0, previousEnd = -1;
  const segments = finalKeeps.map(({ startFrame, endFrame }) => {
    if (!Number.isSafeInteger(startFrame) || !Number.isSafeInteger(endFrame) || startFrame < 0 || endFrame <= startFrame || startFrame < previousEnd || endFrame > Math.ceil(duration * fpsNum / fpsDen - 1e-9)) throw new Error('剪映主轨剪点非法或越界');
    previousEnd = endFrame;
    const segment = clone(template.segment);
    const start = us(frames); frames += endFrame - startFrame;
    Object.assign(segment, { id: uuid(), material_id: video.id, source_timerange: { start: us(startFrame), duration: us(endFrame) - us(startFrame) }, target_timerange: { start, duration: us(frames) - start }, visible: true });
    return segment;
  });
  Object.assign(draft, { id: uuid(), name, fps: fpsNum / fpsDen, duration: us(frames), canvas_config: { width, height, ratio: 'original' }, tracks: [{ id: uuid(), type: 'video', flag: 0, attribute: 0, is_default_name: true, name: '', segments }] });
  draft.materials.videos = [video];
  return draft;
}
function saveJianying({ videoFile, finalKeeps, mediaMeta, draftRoot, exportDir = process.cwd() }) {
  if (!draftRoot) {
    if (process.platform !== 'darwin') throw new Error('请设置 JIANYING_DRAFT_ROOT 为剪映本地草稿目录');
    draftRoot = path.join(os.homedir(), 'Movies', 'JianyingPro', 'User Data', 'Projects', 'com.lveditor.draft');
  }
  if (!fs.existsSync(draftRoot) || !fs.statSync(draftRoot).isDirectory()) throw new Error('剪映草稿目录不存在，请先打开剪映或设置 JIANYING_DRAFT_ROOT');
  if (!fs.existsSync(videoFile) || !fs.statSync(videoFile).isFile()) throw new Error('源视频不存在');
  const suffix = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d+Z$/, '') + '-' + crypto.randomUUID().slice(0, 8);
  const name = path.basename(videoFile, path.extname(videoFile)) + '_主轨_' + suffix;
  const draft = buildJianying({ videoFile, finalKeeps, mediaMeta, name });
  const dest = path.join(draftRoot, name);
  // New unique directory only; existing user drafts are never overwritten.
  fs.mkdirSync(dest);
  const bytes = JSON.stringify(draft);
  fs.writeFileSync(path.join(dest, 'draft_info.json'), bytes, { flag: 'wx' });
  fs.writeFileSync(path.join(dest, 'draft_content.json'), bytes, { flag: 'wx' });
  const now = Date.now() * 1000;
  const meta = { draft_id: draft.id, draft_name: name, draft_fold_path: dest, draft_root_path: draftRoot, draft_cover: '', draft_materials: [], tm_draft_create: now, tm_draft_modified: now, tm_duration: draft.duration };
  fs.writeFileSync(path.join(dest, 'draft_meta_info.json'), JSON.stringify(meta), { flag: 'wx' });
  for (const file of ['draft_info.json', 'draft_content.json']) {
    if (fs.readFileSync(path.join(dest, file), 'utf8') !== bytes) throw new Error('剪映草稿写入校验失败');
  }
  const receipt = { schemaVersion: 1, exporter: 'jianying-maintrack-v1', draftName: name, draftPath: dest, segments: finalKeeps.length, durationUs: draft.duration, trackFlag: 0, draftSha256: crypto.createHash('sha256').update(bytes).digest('hex'), guiVerified: false };
  const receiptPath = path.join(exportDir, name + '.receipt.json');
  fs.writeFileSync(receiptPath, JSON.stringify(receipt, null, 2), { flag: 'wx' });
  return { ...receipt, receiptPath };
}
module.exports = { buildJianying, saveJianying };
