'use strict';
const fs = require('fs');
const path = require('path');
const { execFile } = require('child_process');
function run(bin, args) {
  return new Promise((resolve, reject) => execFile(bin, args,
    { timeout: 2 * 60 * 60 * 1000, maxBuffer: 4 * 1024 * 1024 },
    (err, stdout, stderr) => err ? reject(new Error(`${bin}: ${String(stderr || err.message).slice(-1000)}`)) : resolve(String(stdout))));
}
async function renderMp4({ videoFile, keeps, mediaMeta, outputPath }) {
  if (!keeps.length || keeps.some(s => !Number.isFinite(s.start) || !Number.isFinite(s.end) || s.start < 0 || s.end <= s.start)) {
    throw new Error('没有有效保留片段，无法导出 MP4');
  }
  const metadata = JSON.parse(await run('ffprobe', ['-v', 'error', '-show_streams', '-of', 'json', videoFile]));
  const hasAudio = metadata.streams.some(s => s.codec_type === 'audio');
  const tmp = fs.mkdtempSync(path.join(path.dirname(outputPath), '.mp4-export-'));
  try {
    // 分段顺序编码，限制内存；中间音频用 PCM，避免每个切点重复引入 AAC 编码延迟。
    const files = [];
    for (let i = 0; i < keeps.length; i++) {
      const s = keeps[i];
      const name = `${i}.mov`;
      files.push(`file '${name}'`);
      await run('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
        '-ss', String(s.start), '-i', videoFile, '-t', String(s.end - s.start),
        '-map', '0:v:0', ...(hasAudio ? ['-map', '0:a:0'] : []),
        '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2', '-r', `${mediaMeta.fpsNum}/${mediaMeta.fpsDen}`,
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p',
        ...(hasAudio ? ['-af', 'apad', '-c:a', 'pcm_s16le', '-ar', '48000'] : ['-an']),
        '-map_metadata', '-1', path.join(tmp, name)]);
    }
    fs.writeFileSync(path.join(tmp, 'concat.txt'), files.join('\n'));
    const rendered = path.join(tmp, 'result.mp4');
    await run('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
      '-f', 'concat', '-safe', '1', '-i', path.join(tmp, 'concat.txt'),
      '-c:v', 'copy', ...(hasAudio ? ['-c:a', 'aac', '-b:a', '192k'] : ['-an']),
      '-movflags', '+faststart', rendered]);
    const result = JSON.parse(await run('ffprobe', ['-v', 'error', '-show_streams', '-show_format', '-of', 'json', rendered]));
    const expected = keeps.reduce((n, s) => n + s.end - s.start, 0);
    if (!result.streams.some(s => s.codec_type === 'video') ||
        (hasAudio && !result.streams.some(s => s.codec_type === 'audio')) ||
        !Number.isFinite(Number(result.format.duration)) ||
        Math.abs(Number(result.format.duration) - expected) > Math.max(0.15, 2 / mediaMeta.fps)) {
      throw new Error('MP4 时长或音视频轨验证失败');
    }
    fs.renameSync(rendered, outputPath);
    return outputPath;
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
}
module.exports = { renderMp4 };
