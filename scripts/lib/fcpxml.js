'use strict';
/*
 * FCPXML 1.8 生成（从 review_server.js 抽出，便于单测）。
 *
 * 一句话职责：拿到「删除段 + 静音段 + 视频文件」，算出真正保留的片段（复用
 * compute_keeps.js 这一份切割算法），再渲染成可被剪映 / Final Cut Pro 导入的 FCPXML。
 *
 * 设计约束（改动前必读）：
 *   - FCPXML 1.8 DTD 不支持 fade 元素，淡入淡出留给剪辑软件自己加
 *   - 媒体引用用绝对路径的 file:// URI（百分号编码），剪映和 FCP 都靠它定位源视频
 *   - 时间一律用 FCP ticks（帧号 × fpsDen），不要改成秒——浮点累积会导致 ±1 帧漂移
 */

const path = require('path');
const { execFileSync } = require('child_process');
const { computeFinalKeeps, ENGINE_VERSION } = require('./compute_keeps');

// 把绝对路径编码成 file:// URI（保留路径分隔符与安全字符，其余百分号编码）
function fileUri(absPath) {
  return 'file://' + absPath.split('').map(c => (
    /[a-zA-Z0-9\-_.~/]/.test(c) ? c : encodeURIComponent(c)
  )).join('');
}

// FCP 要求的 UUID 格式
function uuid() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = Math.random() * 16 | 0;
    const v = c === 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
}

function ffprobeJson(videoFile) {
  const args = [
    '-v', 'error',
    '-select_streams', 'v:0',
    '-show_entries', 'format=duration:stream=r_frame_rate,width,height',
    '-of', 'json',
    videoFile,
  ];

  let lastError;
  for (let attempt = 1; attempt <= 2; attempt++) {
    try {
      return JSON.parse(execFileSync('ffprobe', args, {
        encoding: 'utf8',
        stdio: ['ignore', 'pipe', 'pipe'],
      }));
    } catch (err) {
      lastError = err;
    }
  }

  const stderr = lastError && lastError.stderr
    ? String(lastError.stderr).trim()
    : '';
  throw new Error(`ffprobe 无法读取源视频「${videoFile}」${stderr ? `：${stderr}` : ''}`);
}

// 用一次 ffprobe 探测视频元数据：时长、帧率（有理数）、宽高
function probeVideo(videoFile) {
  const metadata = ffprobeJson(videoFile);
  const stream = Array.isArray(metadata.streams) ? metadata.streams[0] : null;
  const duration = Number(metadata.format && metadata.format.duration);
  const fpsRaw = stream && stream.r_frame_rate;
  const fpsParts = typeof fpsRaw === 'string' ? fpsRaw.split('/').map(Number) : [];
  const [fpsNum, fpsDen] = fpsParts.length === 2 ? fpsParts : [fpsParts[0], 1];
  const width = Number(stream && stream.width);
  const height = Number(stream && stream.height);

  if (!Number.isFinite(duration) || duration <= 0) {
    throw new Error(`ffprobe 未返回有效视频时长：${videoFile}`);
  }
  if (!Number.isFinite(fpsNum) || fpsNum <= 0 || !Number.isFinite(fpsDen) || fpsDen <= 0) {
    throw new Error(`ffprobe 未返回有效视频帧率：${videoFile}`);
  }
  if (!Number.isFinite(width) || width <= 0 || !Number.isFinite(height) || height <= 0) {
    throw new Error(`ffprobe 未返回有效视频尺寸：${videoFile}`);
  }

  return { duration, fpsNum, fpsDen, width, height };
}

// 保留段向外取整到源视频真实帧：开头 floor、结尾 ceil。
// 目标是宁可多留不足一帧，也不把句尾最后一个字向内截断。
function quantizeSegmentOutward(seg, fpsNum, fpsDen, duration) {
  const frameRate = fpsNum / fpsDen;
  const maxEndFrame = Math.max(1, Math.ceil(duration * frameRate - 1e-9));
  const startFrame = Math.max(0, Math.min(maxEndFrame, Math.floor(seg.start * frameRate + 1e-9)));
  const endFrame = Math.max(startFrame + 1, Math.min(maxEndFrame, Math.ceil(seg.end * frameRate - 1e-9)));
  if (endFrame <= startFrame) return null;
  return {
    start: startFrame / frameRate,
    end: endFrame / frameRate,
    startFrame,
    endFrame,
  };
}

// 两段向外取整后若重叠/相接，直接连成一段。短到不足一帧的删除宁可放弃，
// 也不制造重复帧、卡音或半个尾字。
function mergeQuantizedKeeps(segments) {
  const out = [];
  for (const seg of segments) {
    if (!seg) continue;
    const last = out[out.length - 1];
    if (!last || seg.startFrame > last.endFrame) {
      out.push({ ...seg });
    } else {
      last.endFrame = Math.max(last.endFrame, seg.endFrame);
      last.end = Math.max(last.end, seg.end);
    }
  }
  return out;
}

/**
 * 生成 FCPXML。
 * @param {object} o
 * @param {string} o.videoFile        源视频路径
 * @param {number[]} o.deleteList      删除段（秒区间，见 compute_keeps）
 * @param {Array} o.silencePeriods     预计算静音段
 * @param {object} [o.cutOpts]         切割参数（padStart/padEnd 等）
 * @returns {{ xml:string, outputPath:string, finalKeeps:Array, baseName:string }}
 */
function buildFcpxml({ videoFile, deleteList, silencePeriods, cutOpts }) {
  const { duration, fpsNum, fpsDen, width, height } = probeVideo(videoFile);

  // ticks = 帧号 × fpsDen，分母为 fpsNum：对 14.985/29.97/30/24 等帧率都成立
  const frameDuration = `${fpsDen}/${fpsNum}s`;

  // 先按选择得到保留段，再向外取到真实源帧。任何不足一帧的删除会被安全合并为保留。
  const requestedKeeps = computeFinalKeeps(deleteList, silencePeriods, duration, cutOpts);
  const finalKeeps = mergeQuantizedKeeps(
    requestedKeeps.map(seg => quantizeSegmentOutward(seg, fpsNum, fpsDen, duration))
  );

  const baseName = path.basename(videoFile, path.extname(videoFile));
  const outputPath = path.resolve(`${baseName}_cut.fcpxml`);

  const videoSrc = fileUri(path.resolve(videoFile));

  // asset 时长也向上取到完整源帧，避免最后一帧的 clip 超出声明时长。
  const assetDurationTicks = Math.ceil(duration * fpsNum / fpsDen - 1e-9) * fpsDen;

  // 每个保留片段一个 asset-clip，引用同一个 asset r1；
  // offset 在 tick 空间累加，避免浮点秒累积误差导致 ±1 帧偏移
  let timelineOffsetTicks = 0;
  const clips = finalKeeps.map((seg) => {
    const startTicks = seg.startFrame * fpsDen;
    const durTicks = (seg.endFrame - seg.startFrame) * fpsDen;
    const offsetTicks = timelineOffsetTicks;
    timelineOffsetTicks += durTicks;
    return `            <asset-clip name="${baseName}" offset="${offsetTicks}/${fpsNum}s" ref="r1" start="${startTicks}/${fpsNum}s" duration="${durTicks}/${fpsNum}s" audioRole="dialogue" format="r2" tcFormat="NDF" />`;
  }).join('\n');

  const totalTicks = timelineOffsetTicks;

  // 不写 library@location：审核页会把服务器生成的 XML 下载到浏览器下载目录，
  // 原绝对路径会随复制/下载立即失效，并可能误导剪映等第三方导入器。
  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<fcpxml version="1.8">
  <resources>
    <format id="r2" frameDuration="${frameDuration}" width="${width}" height="${height}" colorSpace="1-1-1 (Rec. 709)" />
    <asset id="r1" name="${baseName}" src="${videoSrc}" start="0/1s" duration="${assetDurationTicks}/${fpsNum}s" format="r2" hasAudio="1" hasVideo="1" audioSources="1" audioChannels="2" audioRate="48k" />
  </resources>
  <library>
    <event name="${baseName}_剪辑" uid="${uuid()}">
      <project name="${baseName}_cut" uid="${uuid()}">
        <sequence duration="${totalTicks}/${fpsNum}s" format="r2" tcStart="0/1s" tcFormat="NDF" audioLayout="stereo" audioRate="48k">
          <spine>
${clips}
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>`;

  return {
    xml,
    outputPath,
    requestedKeeps,
    finalKeeps,
    baseName,
    engineVersion: ENGINE_VERSION,
    mediaMeta: {
      duration,
      fpsNum,
      fpsDen,
      fps: fpsNum / fpsDen,
      width,
      height,
      frameAlignedDuration: assetDurationTicks / fpsNum,
    },
  };
}

module.exports = {
  buildFcpxml,
  probeVideo,
  quantizeSegmentOutward,
  mergeQuantizedKeeps,
};
