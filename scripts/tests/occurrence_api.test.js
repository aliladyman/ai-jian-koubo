'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const { spawn, execFileSync } = require('node:child_process');
const { once } = require('node:events');

test('单处纠错 API、刷新回读、字幕预览和导出使用同一位置', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'occurrence-api-'));
  const review = path.join(root, '剪口播', '3_审核');
  const transcript = path.join(root, '剪口播', '1_转录', 'subtitles_words.json');
  const dictPath = path.join(root, '分镜', '字幕纠错.json');
  fs.mkdirSync(review, { recursive: true });
  fs.mkdirSync(path.dirname(transcript), { recursive: true });
  const words = [...'他问他问他'].map((text, i) => ({ text, start: i, end: i + .9, isGap: false }));
  const original = JSON.stringify(words);
  fs.writeFileSync(transcript, original);
  fs.writeFileSync(path.join(review, 'data.json'), JSON.stringify({ words, autoSelected: [] }));
  fs.writeFileSync(path.join(review, 'silence_periods.json'), '[]');
  const video = path.join(root, 'fixture.mp4');
  execFileSync('ffmpeg', ['-v', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=160x90:r=25', '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=mono', '-t', '5', '-c:v', 'libx264', '-threads', '1', '-c:a', 'aac', video]);
  const probe = net.createServer();
  probe.listen(0, '127.0.0.1');
  await once(probe, 'listening');
  const port = probe.address().port;
  await new Promise(resolve => probe.close(resolve));
  const fenjing = path.resolve(__dirname, '../captions');
  const child = spawn(process.execPath, [path.resolve(__dirname, '../review_server.js'), String(port), video], {
    cwd: review, env: { ...process.env, KOUBO_FENJING_SCRIPTS: fenjing, AI_JIAN_KOUBO_GLOBAL_DICT: path.join(root, 'global-dict.json') }, stdio: ['ignore', 'pipe', 'pipe'],
  });
  let logs = '';
  child.stdout.on('data', b => { logs += b; });
  child.stderr.on('data', b => { logs += b; });
  const post = async (endpoint, body) => {
    const r = await fetch(`http://127.0.0.1:${port}${endpoint}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    return r.json();
  };
  const correction = body => post('/api/corrections', body);
  const set = (idx, to) => correction({ action: 'set', scope: 'occurrence', from: '他', to, span: { startIdx: idx, endIdx: idx } });
  try {
    for (let i = 0; !logs.includes('READY_PORT=') && i < 100; i++) await new Promise(r => setTimeout(r, 30));
    assert.match(logs, /READY_PORT=/);
    assert.equal((await set(0, '她')).success, true);
    assert.equal((await set(4, '它')).success, true);
    let saved = await correction({ action: 'list' });
    assert.deepEqual(saved.occurrences.map(c => [c.startIdx, c.to]), [[0, '她'], [4, '它']]);
    assert.deepEqual(saved.local, {});
    assert.equal(fs.readFileSync(transcript, 'utf8'), original);
    const beforeBadRequest = fs.readFileSync(dictPath, 'utf8');
    assert.equal((await set(1, '她')).success, false);
    assert.equal(fs.readFileSync(dictPath, 'utf8'), beforeBadRequest);
    assert.equal((await correction({ action: 'remove', scope: 'occurrence', from: '他', span: { startIdx: 0, endIdx: 0 } })).success, true);
    saved = await correction({ action: 'list' });
    assert.deepEqual(saved.occurrences.map(c => c.startIdx), [4]);
    assert.equal((await set(0, '她')).success, true);

    const preview = await post('/api/captions-preview', { deleteList: [], finalSelected: [], opts: { preserveNaturalPauses: true } });
    assert.equal(preview.success, true, preview.error);
    assert.equal(preview.lines.map(l => l.text).join(''), '她问他问它');
    const exported = await post('/api/fcpxml', { deleteList: [], finalSelected: [], opts: { preserveNaturalPauses: true } });
    assert.equal(exported.success, true, exported.error);
    const log = JSON.parse(fs.readFileSync(path.join(review, 'review_log.json')));
    assert.equal(log.textAuthority.corrections.occurrences.length, 2);
    assert.equal((await set(0, '姐姐')).success, true);
    const output = path.join(root, 'timeline.json');
    execFileSync(process.execPath, [path.join(fenjing, 'build_cut_timeline.js'), '--fcpxml', path.join(review, 'fixture_cut.fcpxml'), '--words', transcript, '--out', output]);
    assert.equal(JSON.parse(fs.readFileSync(output)).sentences[0].text, '她问他问它');

    fs.writeFileSync(transcript, original + '\n');
    assert.equal((await correction({ action: 'list' })).success, false);
    fs.writeFileSync(transcript, original);
    fs.writeFileSync(dictPath, '{broken');
    assert.equal((await set(0, '她')).success, false);
    assert.equal(fs.readFileSync(dictPath, 'utf8'), '{broken');
  } finally {
    child.kill('SIGTERM');
    await once(child, 'exit');
    fs.rmSync(root, { recursive: true, force: true });
  }
});
