#!/usr/bin/env node
/**
 * 审核服务器
 *
 * 功能：
 * 1. 提供静态文件服务（review.html, audio.mp3）
 * 2. POST /api/fcpxml - 接收删除列表，导出 FCPXML 工程文件（可导入剪映 / Final Cut Pro）
 *
 * 本地补丁 2026-07-20（经用户拍板破例修改，说明见 remotion-video/docs/ai-jian-koubo-local-patch.md）：
 * 3. POST /api/corrections      - 审查页双击改字 → 写 <片>/分镜/字幕纠错.json（或全局专名词典）
 * 4. POST /api/captions-preview - 字幕断行预览：临时 fcpxml → build_cut_timeline.js → 字幕断行.js
 *                                 → 逐行套两级纠错词典（与合成同引擎同脚本同参数）
 *
 * 用法: node review_server.js [port] [video_file]
 * 必须: video_file（无默认值，会检查文件是否存在）
 */

const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');
const crypto = require('crypto');
const { execFile } = require('child_process');
const { buildFcpxml } = require('./lib/fcpxml');
const { saveJianying } = require('./lib/jianying');
const { commitRoughCutExportBundle } = require('./lib/export_bundle');
const { validateSpan, validateOccurrences, correctKeptText } = require('./lib/occurrence_corrections');
const {
  buildDeleteListFromSelection,
  findUnselectedWordCutRisks,
  DEFAULTS: CUT_DEFAULTS,
} = require('./lib/compute_keeps');

const { renderMp4 } = require('./lib/render_mp4');
let mp4Busy = false;

const PORT = process.argv[2] || 8899;
const VIDEO_FILE = process.argv[3];

if (!VIDEO_FILE) {
  console.error('❌ 错误: 必须指定视频文件路径');
  console.error('用法: node review_server.js [port] [video_file]');
  process.exit(1);
}

if (!fs.existsSync(VIDEO_FILE)) {
  console.error(`❌ 错误: 视频文件不存在: ${VIDEO_FILE}`);
  process.exit(1);
}

// ── 本地补丁：路径推导（一片一夹约定：源片所在文件夹 = 片根，见 SKILL.md BASE_DIR）──
// 不用 cwd ../../：手动裸启时 cwd 不可靠，视频绝对路径是更稳的锚点。
const PIECE_ROOT = path.dirname(path.resolve(VIDEO_FILE));
const LOCAL_DICT = path.join(PIECE_ROOT, '分镜', '字幕纠错.json');
// 全局专名词典：所有片子共用；可用环境变量 AI_JIAN_KOUBO_GLOBAL_DICT 指定其他位置
const GLOBAL_DICT = process.env.AI_JIAN_KOUBO_GLOBAL_DICT ||
  path.join(os.homedir(), '.ai-jian-koubo', '专名词典.json');
const CORR_LOG = path.resolve('corrections.json'); // 3_审核/ 留痕，页面刷新后回放覆盖层
const SUBTITLES_WORDS = path.join(PIECE_ROOT, '剪口播', '1_转录', 'subtitles_words.json');
// 字幕断行脚本：随本 skill 附带在 scripts/captions/；env KOUBO_FENJING_SCRIPTS 可覆盖
const FENJING_SCRIPTS = process.env.KOUBO_FENJING_SCRIPTS ||
  path.join(__dirname, 'captions');
const BUILD_CUT_JS = path.join(FENJING_SCRIPTS, 'build_cut_timeline.js');
const BREAK_JS = path.join(FENJING_SCRIPTS, '字幕断行.js');

// 静音边界，由 generate_review.js 预计算（对 audio.mp3 跑 silencedetect，自适应阈值 = 峰值 - 35dB）
// 切割算法本身在 lib/compute_keeps.js（前后端共用，单一来源）
let silencePeriods = [];
try {
  silencePeriods = JSON.parse(fs.readFileSync('silence_periods.json', 'utf8'));
  silencePeriods.sort((a, b) => a.start - b.start); // 确保按时间升序
  console.log('🔕 读取到 ' + silencePeriods.length + ' 个静音段');
} catch (e) {
  console.warn('⚠️ 读取 silence_periods.json 失败，末尾裁剪已跳过');
}

// 自进化学习需要的原料：词级文本（重建上下文）+ AI 初选 idx（diff 基线）。
// 都在 data.json（generate_review.js 生成，与本进程同在 3_审核/）里，启动时读一次。
let reviewWords = [];
let aiSelectedIdx = [];
try {
  const d = JSON.parse(fs.readFileSync('data.json', 'utf8'));
  reviewWords = Array.isArray(d.words) ? d.words : [];
  aiSelectedIdx = Array.isArray(d.autoSelected) ? d.autoSelected : [];
} catch (e) {
  console.warn('⚠️ 读取 data.json 失败，导出时将无法生成 review_log.json（自进化学习日志）');
}

const MIME_TYPES = {
  '.html': 'text/html',
  '.js': 'application/javascript',
  '.css': 'text/css',
  '.json': 'application/json',
  '.mp3': 'audio/mpeg',
  '.mp4': 'video/mp4',
};

// ── 本地补丁：新端点的公共工具 ──────────────────────────────────────────
// 写盘端点只信本机来源。三重校验：
//   remoteAddress（TCP 层，不可伪造）挡局域网直连；Host/Origin 挡浏览器跨源（CORS 是 *）。
// 不改 listen 绑定：原版全接口监听，局域网开审核页浏览是既有用法，只把写盘/预览限制在本机。
function isLocalRequest(req) {
  const ra = String((req.socket && req.socket.remoteAddress) || '');
  const raOk = ra === '127.0.0.1' || ra === '::1' || ra === '::ffff:127.0.0.1';
  const host = String(req.headers.host || '');
  const hostOk = /^(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$/.test(host);
  const origin = req.headers.origin;
  const originOk = !origin || /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$/.test(origin);
  return raOk && hostOk && originOk;
}
// 异步跑 node 子脚本（不用 spawnSync：同步会阻塞事件循环，卡住 /video 流和所有请求）
function runNode(args, timeoutMs) {
  return new Promise((resolve, reject) => {
    execFile(process.execPath, args,
      { timeout: timeoutMs, maxBuffer: 16 * 1024 * 1024, encoding: 'utf8' },
      (err, stdout, stderr) => {
        if (err) reject(new Error(String(stderr || err.message || '子进程失败').slice(0, 400)));
        else resolve(stdout);
      });
  });
}
function readBody(req, res, limit = 1024 * 1024) {
  return new Promise((resolve) => {
    let body = '', over = false;
    req.on('data', chunk => {
      if (over) return;
      body += chunk;
      if (body.length > limit) {
        over = true;
        res.writeHead(413, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ success: false, error: '请求体过大' }));
        req.destroy();
        resolve(null);
      }
    });
    req.on('end', () => { if (!over) resolve(body); });
    req.on('error', () => resolve(null));
  });
}
function readJsonSafe(p) {
  if (!fs.existsSync(p)) return { exists: false, data: null, error: null };
  try {
    return { exists: true, data: JSON.parse(fs.readFileSync(p, 'utf8')), error: null };
  } catch (e) {
    return { exists: true, data: null, error: e.message };
  }
}
// 原子写 + 回读验证：临时文件同目录 rename，绝不留半截 JSON
function atomicWriteJson(p, obj) {
  const tmp = path.join(path.dirname(p), '.' + path.basename(p) + '.tmp-' + process.pid);
  fs.writeFileSync(tmp, JSON.stringify(obj, null, 2) + '\n', 'utf8');
  fs.renameSync(tmp, p);
  JSON.parse(fs.readFileSync(p, 'utf8')); // 回读验证，解析失败会抛
}
function sendJson(res, code, obj) {
  res.writeHead(code, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(obj));
}
function segmentsEqual(a, b, tolerance = 1e-4) {
  if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
  return a.every((seg, i) =>
    Math.abs(Number(seg.start) - Number(b[i].start)) <= tolerance &&
    Math.abs(Number(seg.end) - Number(b[i].end)) <= tolerance
  );
}
function sourceFingerprint(videoFile) {
  const resolved = fs.realpathSync(videoFile);
  const stat = fs.statSync(resolved);
  const fingerprint = crypto.createHash('sha256')
    .update([resolved, stat.size, stat.mtimeMs].join('\0'))
    .digest('hex');
  return { path: resolved, size: stat.size, mtimeMs: stat.mtimeMs, fingerprint };
}

function readOccurrenceCorrections(dict) {
  if (dict.occurrences === undefined) return [];
  const hash = crypto.createHash('sha256').update(fs.readFileSync(SUBTITLES_WORDS)).digest('hex');
  if (dict.wordsSha256 !== hash) throw new Error('单处纠错与逐字稿指纹不匹配，请重新审核');
  return validateOccurrences(reviewWords, dict.occurrences);
}

function buildReviewLogOrThrow({
  finalSelected,
  baseName,
  engineVersion,
  safeMode,
  effectiveOpts,
  mediaMeta,
  finalKeeps,
  requestedKeeps,
  selectionMatched,
  tailRisks,
}) {
  if (!Array.isArray(finalSelected)) {
    throw new Error('请求缺少 finalSelected，已阻止无文字正本的导出');
  }
  if (!reviewWords.length) {
    throw new Error('data.json 缺少审核词级数据，无法生成文字正本');
  }
  if (!fs.existsSync(SUBTITLES_WORDS)) {
    throw new Error('缺少 subtitles_words.json，无法绑定逐字稿指纹');
  }
  const isWord = (i) => reviewWords[i] && !reviewWords[i].isGap;
  const contextFor = (idx) => {
    let l = idx, r = idx;
    for (let k = 0; k < 12 && l - 1 >= 0 && reviewWords[l - 1] && !reviewWords[l - 1].isGap; k++) l--;
    for (let k = 0; k < 12 && r + 1 < reviewWords.length && reviewWords[r + 1] && !reviewWords[r + 1].isGap; k++) r++;
    let s = '';
    for (let i = l; i <= r; i++) {
      if (reviewWords[i].isGap) continue;
      s += (i === idx) ? '【' + reviewWords[i].text + '】' : reviewWords[i].text;
    }
    return s;
  };
  const entry = (i) => ({
    idx: i,
    text: reviewWords[i] ? reviewWords[i].text : '',
    start: reviewWords[i] ? reviewWords[i].start : null,
    end: reviewWords[i] ? reviewWords[i].end : null,
    context: contextFor(i),
  });
  const aiSet = new Set(aiSelectedIdx);
  const finalSet = new Set(finalSelected);
  const aiOnly = aiSelectedIdx.filter(i => !finalSet.has(i) && isWord(i)).sort((a, b) => a - b);
  const userOnly = finalSelected.filter(i => !aiSet.has(i) && isWord(i)).sort((a, b) => a - b);
  const globalCorrections = readJsonSafe(GLOBAL_DICT).data || {};
  const localRead = readJsonSafe(LOCAL_DICT);
  if (localRead.error) throw new Error('本片纠错文件损坏，拒绝导出');
  const localCorrections = localRead.data || {};
  const occurrences = readOccurrenceCorrections(localCorrections);
  correctKeptText(reviewWords.map((w, sourceIndex) => ({ ...w, sourceIndex }))
    .filter(w => !w.isGap && !finalSet.has(w.sourceIndex)), {}, occurrences);
  const wordsSha256 = crypto.createHash('sha256').update(fs.readFileSync(SUBTITLES_WORDS)).digest('hex');
  return {
    video: baseName,
    exportedAt: new Date().toISOString(),
    engineVersion,
    mode: safeMode ? 'explicit-selection-safe' : 'legacy-silence-snap',
    opts: effectiveOpts,
    source: Object.assign(sourceFingerprint(VIDEO_FILE), mediaMeta),
    aiSelected: aiSelectedIdx,
    finalSelected,
    segments: finalKeeps.length,
    requestedKeeps,
    finalKeeps,
    integrity: {
      deleteListSource: safeMode ? 'server-rebuilt-from-finalSelected' : 'client-request',
      clientDeleteListMatchedCanonical: selectionMatched,
      unselectedWordCutRiskCount: tailRisks.length,
      unselectedWordCutRisks: tailRisks,
    },
    textAuthority: {
      version: 1,
      kind: 'review-export',
      wordsSha256,
      deletedWordIndices: finalSelected.filter(isWord).sort((a, b) => a - b),
      corrections: {
        global: (globalCorrections && globalCorrections.replacements) || {},
        local: (localCorrections && localCorrections.replacements) || {},
        occurrences,
      },
      precedence: ['global', 'local', 'occurrence'],
    },
    diff: {
      说明: 'aiOnly=AI想删但你保留了(可能AI过删，该收敛规则)；userOnly=你删了但AI没想到(可能AI漏删，该补规则)',
      aiOnly: aiOnly.map(entry),
      userOnly: userOnly.map(entry),
    },
  };
}

const server = http.createServer((req, res) => {
  // CORS
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    res.writeHead(200);
    res.end();
    return;
  }

  // 共享切割算法模块：从 scripts/lib 单一来源直供前端，避免拷贝漂移
  if (req.method === 'GET' && req.url.split('?')[0] === '/lib/compute_keeps.js') {
    const libPath = path.join(__dirname, 'lib', 'compute_keeps.js');
    if (fs.existsSync(libPath)) {
      res.writeHead(200, { 'Content-Type': 'application/javascript' });
      fs.createReadStream(libPath).pipe(res);
    } else {
      res.writeHead(404);
      res.end('Not Found');
    }
    return;
  }

  // 视频文件代理（原始视频不在当前目录时使用）
  if (req.method === 'GET' && req.url.startsWith('/video')) {
    if (!VIDEO_FILE || !fs.existsSync(VIDEO_FILE)) {
      res.writeHead(404);
      res.end('Video not found');
      return;
    }
    const stat = fs.statSync(VIDEO_FILE);
    const ext = path.extname(VIDEO_FILE).toLowerCase();
    const contentType = ext === '.mp4' ? 'video/mp4' : ext === '.mov' ? 'video/quicktime' : 'video/mp4';

    if (req.headers.range) {
      const range = req.headers.range.replace('bytes=', '').split('-');
      const start = parseInt(range[0], 10);
      const end = range[1] ? parseInt(range[1], 10) : stat.size - 1;
      res.writeHead(206, {
        'Content-Type': contentType,
        'Content-Range': `bytes ${start}-${end}/${stat.size}`,
        'Accept-Ranges': 'bytes',
        'Content-Length': end - start + 1,
      });
      fs.createReadStream(VIDEO_FILE, { start, end }).pipe(res);
    } else {
      res.writeHead(200, {
        'Content-Type': contentType,
        'Content-Length': stat.size,
        'Accept-Ranges': 'bytes',
      });
      fs.createReadStream(VIDEO_FILE).pipe(res);
    }
    return;
  }

  // ── 本地补丁 API: 双击改字 → 纠错词典 ──────────────────────────────
  // body: { action:'set'|'remove', from, to?, scope:'occurrence'|'local'|'global', span:{startIdx,endIdx} }
  // 落点：local → <片>/分镜/字幕纠错.json；global → GLOBAL_DICT（默认 ~/.ai-jian-koubo/专名词典.json）。
  // 只动词典与 3_审核/corrections.json 留痕；data.json / subtitles_words.json 保持 ASR 原文
  // （字级 token 无法映射不等长纠错，且它们是 review_log 学习信号的基线）。
  if (req.method === 'POST' && req.url.split('?')[0] === '/api/corrections') {
    if (!isLocalRequest(req)) { sendJson(res, 403, { success: false, error: '仅接受本机请求' }); return; }
    readBody(req, res).then(body => {
      if (body == null) return;
      try {
        const p = JSON.parse(body);
        // list：页面加载时拉真实词典（片内 + 全局），让覆盖层显示 = 烧字幕结果
        if (p.action === 'list') {
          const g = readJsonSafe(GLOBAL_DICT), l = readJsonSafe(LOCAL_DICT);
          if (l.error) throw new Error('本片纠错文件损坏，拒绝忽略已保存的修改');
          sendJson(res, 200, {
            success: true,
            global: (g.data && typeof g.data.replacements === 'object' && g.data.replacements) || {},
            local: (l.data && typeof l.data.replacements === 'object' && l.data.replacements) || {},
            occurrences: readOccurrenceCorrections(l.data || {}),
            localPath: LOCAL_DICT,
          });
          return;
        }
        const action = p.action === 'remove' ? 'remove' : (p.action === 'set' ? 'set' : null);
        const from = typeof p.from === 'string' ? p.from.trim() : '';
        const to = typeof p.to === 'string' ? p.to.trim() : '';
        const scope = p.scope === undefined ? 'local' : p.scope;
        if (!['occurrence', 'local', 'global'].includes(scope)) throw new Error('纠错范围不合法');
        const span = p.span && Number.isInteger(p.span.startIdx) && Number.isInteger(p.span.endIdx)
              && p.span.startIdx >= 0 && p.span.endIdx >= p.span.startIdx
          ? { startIdx: p.span.startIdx, endIdx: p.span.endIdx } : null;
        if (!action || !from || from.length > 80 || !span) throw new Error('参数不合法');
        if (action === 'set' && (!to || to.length > 80 || (to === from && scope !== 'occurrence'))) throw new Error('正词不合法');
        if (action === 'set' || scope === 'occurrence') validateSpan(reviewWords, span, from);
        // 片根守卫：视频不在片根启动时（PIECE_ROOT 推导失效），拒绝把片内词典静默写到错误位置
        if (scope !== 'global' && !fs.existsSync(SUBTITLES_WORDS)) {
          throw new Error(`片根推导异常：按视频位置推导为 ${PIECE_ROOT}，但找不到 剪口播/1_转录/subtitles_words.json。请用片根里的原视频启动审核服务`);
        }

        const dictPath = scope === 'global' ? GLOBAL_DICT : LOCAL_DICT;
        fs.mkdirSync(path.dirname(dictPath), { recursive: true });
        const cur = readJsonSafe(dictPath);
        if (cur.error) throw new Error(`词典文件损坏，拒绝覆盖: ${dictPath} (${cur.error})`);
        const dict = cur.data || {
          _说明: scope === 'global'
            ? '全局专名词典：{"错词":"正词"} 整词替换，各片烧字幕时生效。'
            : '本片字幕纠错词典：{"错词":"正词"} 整词替换，烧字幕时生效（片内优先于全局专名词典）。审查页双击改字自动写入。',
          replacements: {},
        };
        if (typeof dict.replacements !== 'object' || dict.replacements === null) dict.replacements = {};
        if (scope === 'occurrence') {
          const entries = readOccurrenceCorrections(dict);
          dict.occurrences = entries.filter(c => action === 'remove'
            ? !(c.startIdx === span.startIdx && c.endIdx === span.endIdx)
            : c.endIdx < span.startIdx || c.startIdx > span.endIdx);
          if (action === 'set') dict.occurrences.push({ ...span, from, to });
          dict.occurrences = validateOccurrences(reviewWords, dict.occurrences);
          dict.wordsSha256 = crypto.createHash('sha256').update(fs.readFileSync(SUBTITLES_WORDS)).digest('hex');
        } else if (action === 'set') dict.replacements[from] = to;
        else delete dict.replacements[from];
        dict.updatedAt = new Date().toISOString().slice(0, 10);
        atomicWriteJson(dictPath, dict);

        // 留痕（页面刷新回放覆盖层）；失败不影响词典写入
        try {
          const logCur = readJsonSafe(CORR_LOG);
          const log = (logCur.data && Array.isArray(logCur.data.entries)) ? logCur.data : { entries: [] };
          log.entries = log.entries.filter(en => !(en && en.span &&
            en.span.startIdx <= span.endIdx && span.startIdx <= en.span.endIdx));
          if (action === 'set') log.entries.push({ span, from, to, scope, at: new Date().toISOString() });
          log.updatedAt = new Date().toISOString();
          atomicWriteJson(CORR_LOG, log);
        } catch (logErr) {
          console.warn('⚠️ corrections.json 留痕失败（词典已写入）: ' + logErr.message);
        }

        console.log(`✏️ 纠错${action === 'set' ? '写入' : '删除'} [${scope}] 「${from}」${action === 'set' ? ' → 「' + to + '」' : ''} → ${dictPath}`);
        sendJson(res, 200, { success: true, dictPath });
      } catch (err) {
        console.error('❌ /api/corrections 失败:', err.message);
        sendJson(res, 500, { success: false, error: err.message });
      }
    });
    return;
  }

  // ── 本地补丁 API: 字幕断行预览 ─────────────────────────────────────
  // 使用与导出一致的选区、纠错快照及临时回执，按位置应用纠错后再断行。
  if (req.method === 'POST' && req.url.split('?')[0] === '/api/captions-preview') {
    if (!isLocalRequest(req)) { sendJson(res, 403, { success: false, error: '仅接受本机请求' }); return; }
    readBody(req, res).then(async body => {
      if (body == null) return;
      if (!fs.existsSync(BUILD_CUT_JS) || !fs.existsSync(BREAK_JS)) {
        sendJson(res, 501, {
          success: false,
          error: `找不到字幕断行脚本（${FENJING_SCRIPTS}）。确认 scripts/captions/ 完整，或用环境变量 KOUBO_FENJING_SCRIPTS 指定目录。`,
        });
        return;
      }
      if (!fs.existsSync(SUBTITLES_WORDS)) {
        sendJson(res, 501, {
          success: false,
          error: `找不到词级逐字稿: ${SUBTITLES_WORDS}（片根按视频文件位置推导，一片一夹结构下应为 <片>/剪口播/1_转录/）`,
        });
        return;
      }
      let tmpDir = null;
      try {
        const p = JSON.parse(body || '{}');
        const deleteList = Array.isArray(p.deleteList) ? p.deleteList : [];

        tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'cap-preview-'));
        const fcpPath = path.join(tmpDir, 'preview.fcpxml');
        const sentPath = path.join(tmpDir, '分镜输入.json');

        // 预览消费与正式导出同一文字正本；临时回执只写临时目录。
        const finalSelected = p.finalSelected;
        if (!Array.isArray(finalSelected) || finalSelected.some(i => !Number.isInteger(i) || i < 0 || i >= reviewWords.length)) {
          throw new Error('字幕预览缺少有效选区，请刷新审核页');
        }
        const canonicalDeleteList = buildDeleteListFromSelection(reviewWords, finalSelected);
        const built = buildFcpxml({ videoFile: VIDEO_FILE, deleteList: canonicalDeleteList,
          silencePeriods, cutOpts: { preserveNaturalPauses: true } });
        const tailRisks = findUnselectedWordCutRisks(reviewWords, finalSelected, built.finalKeeps, built.mediaMeta.duration);
        if (tailRisks.length) throw new Error('字幕预览切点覆盖了保留词');
        const reviewLog = buildReviewLogOrThrow({ ...built, finalSelected, safeMode: true,
          effectiveOpts: { preserveNaturalPauses: true }, tailRisks,
          selectionMatched: segmentsEqual(deleteList, canonicalDeleteList) });
        commitRoughCutExportBundle({ fcpxmlPath: fcpPath, fcpxmlBytes: built.xml,
          reviewLogPath: path.join(tmpDir, 'review_log.json'), reviewLog });
        await runNode([BUILD_CUT_JS, '--fcpxml', fcpPath, '--words', SUBTITLES_WORDS, '--out', sentPath], 30000);

        const gRep = reviewLog.textAuthority.corrections.global;
        const lRep = reviewLog.textAuthority.corrections.local;
        const glue = [...new Set(Object.values(gRep).filter(v => typeof v === 'string' && v.trim() && !v.includes(',')))];
        const args = [BREAK_JS, '--json', sentPath, '--max-len', '12'];
        if (glue.length) args.push('--glue', glue.join(','));
        const parsed = JSON.parse(await runNode(args, 30000));
        // 纠错已在断行前按位置应用，不能再按词面批量替换单处修改。
        const lines = (parsed.lines || []).map(l => ({ startMs: l.startMs, endMs: l.endMs, text: String(l.text) }));
        const failures = [];

        sendJson(res, 200, {
          success: true,
          maxLen: parsed.maxLen || 12,
          lines,
          warnings: parsed.warnings || [],
          failures,
          glue,
          dictCounts: { global: Object.keys(gRep).length, local: Object.keys(lRep).length },
        });
      } catch (err) {
        console.error('❌ /api/captions-preview 失败:', err.message);
        sendJson(res, 500, { success: false, error: err.message });
      } finally {
        if (tmpDir) { try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (e) {} }
      }
    });
    return;
  }

  // API: 导出 FCPXML
  if (req.method === 'POST' && ['/api/fcpxml', '/api/mp4', '/api/jianying'].includes(req.url)) {
    const isMp4 = req.url === '/api/mp4';
    const isJianying = req.url === '/api/jianying';
    if (!isLocalRequest(req)) { sendJson(res, 403, { success: false, error: '仅接受本机请求' }); return; }
    if (mp4Busy) { sendJson(res, 409, { success: false, error: 'MP4 正在生成，请等待完成后再导出' }); return; }
    if (isMp4) mp4Busy = true;
    readBody(req, res).then(async body => {
      if (body == null) { if (isMp4) mp4Busy = false; return; }
      try {
        // 兼容两种请求体：旧版直接传删除段数组；新版传 { deleteList, opts }
        const parsed = JSON.parse(body);
        const deleteList = Array.isArray(parsed) ? parsed : (parsed.deleteList || []);
        const cutOpts = (parsed && !Array.isArray(parsed) && parsed.opts) ? parsed.opts : undefined;
        const finalSelected = (parsed && !Array.isArray(parsed) && Array.isArray(parsed.finalSelected)) ? parsed.finalSelected : null;
        if ((isMp4 || isJianying) && (!finalSelected || finalSelected.some(i => !Number.isInteger(i) || i < 0 || i >= reviewWords.length))) throw new Error('无效的最终选区');
        if ((isMp4 || isJianying) && cutOpts && cutOpts.preserveNaturalPauses === false) throw new Error('MP4 导出要求句尾安全模式');
        const requestedOpts = Object.assign({}, CUT_DEFAULTS, cutOpts || {});
        const safeMode = requestedOpts.preserveNaturalPauses !== false;
        // 安全模式只有一个有效参数；旧页面残留的 30fps pad 值不再伪装成「有效配置」。
        const effectiveOpts = safeMode
          ? { preserveNaturalPauses: true }
          : requestedOpts;

        // 安全模式不信浏览器算出的区间：按最终红色 token 在服务端重建删除段，防止前后端漂移。
        if (safeMode && (!finalSelected || !reviewWords.length)) {
          throw new Error('句尾安全模式缺少 finalSelected 或 data.json，已阻止导出。请重新生成审核页后再试');
        }
        const canonicalDeleteList = safeMode
          ? buildDeleteListFromSelection(reviewWords, finalSelected)
          : deleteList;
        const selectionMatched = segmentsEqual(deleteList, canonicalDeleteList);

        // FCPXML 生成：只删明确选区，并按源视频真实 fps 向外取整。
        const {
          xml,
          outputPath: outputFcpxml,
          requestedKeeps,
          finalKeeps,
          baseName,
          engineVersion,
          mediaMeta,
        } = buildFcpxml({
          videoFile: VIDEO_FILE,
          deleteList: canonicalDeleteList,
          silencePeriods,
          cutOpts: effectiveOpts,
        });

        const tailRisks = finalSelected
          ? findUnselectedWordCutRisks(reviewWords, finalSelected, finalKeeps, mediaMeta.duration)
          : [];
        if (safeMode && tailRisks.length) {
          const first = tailRisks[0];
          throw new Error(`句尾保护检查失败：未选中的「${first.text}」仍与切口重叠 ${Math.round(first.overlap * 1000)}ms，已阻止导出`);
        }

        const log = buildReviewLogOrThrow({
          finalSelected,
          baseName,
          engineVersion,
          safeMode,
          effectiveOpts,
          mediaMeta,
          finalKeeps,
          requestedKeeps,
          selectionMatched,
          tailRisks,
        });
        let mp4Output = null;
        if (isMp4) {
          mp4Output = path.resolve(`${baseName}_cut_${crypto.randomUUID()}.mp4`);
          await renderMp4({ videoFile: VIDEO_FILE, keeps: finalKeeps, mediaMeta, outputPath: mp4Output });
        }
        const logPath = path.resolve('review_log.json');
        const receipt = commitRoughCutExportBundle({
          fcpxmlPath: outputFcpxml,
          fcpxmlBytes: xml,
          reviewLogPath: logPath,
          reviewLog: log,
        });
        console.log(`✅ 导出 FCPXML + 文字正本: ${outputFcpxml} (${finalKeeps.length} 片段，${mediaMeta.fps.toFixed(3)}fps，句尾风险 ${tailRisks.length})`);
        console.log(`🧾 初剪导出回执: rough-cut-export.receipt.json (${receipt.artifacts.fcpxml.sha256.slice(0, 12)}…)`);

        const jianying = isJianying ? saveJianying({ videoFile: VIDEO_FILE, finalKeeps, mediaMeta, draftRoot: process.env.JIANYING_DRAFT_ROOT }) : null;
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({
          success: true,
          jianying,
          output: mp4Output || outputFcpxml,
          segments: finalKeeps.length,
          fps: mediaMeta.fps,
          mode: safeMode ? '句尾安全模式' : '旧版静音吸附模式',
          tailRiskCount: tailRisks.length,
          receipt: 'rough-cut-export.receipt.json',
        }));
      } catch (err) {
        console.error('❌ FCPXML 导出失败:', err.message);
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ success: false, error: err.message }));
      } finally {
        if (isMp4) mp4Busy = false;
      }
    });
    return;
  }

  // API: 下载文件
  if (req.method === 'GET' && req.url.startsWith('/api/download/')) {
    const encodedFileName = req.url.replace('/api/download/', '');
    const fileName = decodeURIComponent(encodedFileName);
    const filePath = path.resolve(fileName);
    if (!fs.existsSync(filePath)) {
      res.writeHead(404);
      res.end('Not Found');
      return;
    }
    const stat = fs.statSync(filePath);
    // RFC 5987 编码（非 ASCII 字符必须编码）
    const rawName = path.basename(filePath);
    const encodedName = encodeURIComponent(rawName);
    const displayName = /[^\x00-\x7F]/.test(rawName)
      ? `UTF-8''${encodedName}`  // RFC 5987 格式
      : `"${rawName}"`;

    res.writeHead(200, {
      'Content-Type': 'application/octet-stream',
      'Content-Disposition': `attachment; filename*=UTF-8''${encodedName}`,
      'Content-Length': stat.size,
    });
    fs.createReadStream(filePath).pipe(res);
    return;
  }

  // 静态文件服务（从当前目录读取）
  let filePath = req.url === '/' ? '/review.html' : req.url;
  filePath = '.' + filePath;

  const ext = path.extname(filePath);
  const contentType = MIME_TYPES[ext] || 'application/octet-stream';

  // 检查文件是否存在
  if (!fs.existsSync(filePath)) {
    res.writeHead(404);
    res.end('Not Found');
    return;
  }

  const stat = fs.statSync(filePath);

  // 支持 Range 请求（音频/视频拖动）
  if (req.headers.range && (ext === '.mp3' || ext === '.mp4')) {
    const range = req.headers.range.replace('bytes=', '').split('-');
    const start = parseInt(range[0], 10);
    const end = range[1] ? parseInt(range[1], 10) : stat.size - 1;

    res.writeHead(206, {
      'Content-Type': contentType,
      'Content-Range': `bytes ${start}-${end}/${stat.size}`,
      'Accept-Ranges': 'bytes',
      'Content-Length': end - start + 1,
    });

    fs.createReadStream(filePath, { start, end }).pipe(res);
    return;
  }

  // 普通请求
  res.writeHead(200, {
    'Content-Type': contentType,
    'Content-Length': stat.size,
    'Accept-Ranges': 'bytes'
  });
  fs.createReadStream(filePath).pipe(res);
});

server.listen(PORT, () => {
  // 落地两个文件到当前目录（3_审核/），让 agent / 用户随时能找到地址并重启：
  //   server_url.txt      — 浏览器要打开的地址
  //   .review_server.pid  — 进程号，用于停止/排障（kill $(cat .review_server.pid)）
  const url = `http://localhost:${PORT}`;
  try {
    fs.writeFileSync('server_url.txt', url + '\n');
    fs.writeFileSync('.review_server.pid', String(process.pid) + '\n');
  } catch (e) { /* 写不进不致命，地址下面也会打印 */ }

  // 输出机器可读的端口号，供 shell 捕获
  console.log('READY_PORT=' + PORT);
  console.log(`
🎬 审核服务器已启动
📍 地址: http://localhost:${PORT}
📹 视频: ${VIDEO_FILE}

操作说明:
1. 在网页中审核 AI 预选的删除片段
2. 点击「导出 FCPXML」按钮
3. 把生成的 .fcpxml 文件拖入剪映 / Final Cut Pro
  `);
});
