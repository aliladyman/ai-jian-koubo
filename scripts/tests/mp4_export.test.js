'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync, spawn } = require('child_process');
const { once } = require('events');
const { renderMp4 } = require('../lib/render_mp4');
const { assertExportReceiptCurrent } = require('../lib/export_bundle');
const meta = { fpsNum: 30, fpsDen: 1, fps: 30 };
const run = (cmd, args) => execFileSync(cmd, args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
test('MP4 HTTP 导出：删除中间段、原声、帧内容、下载、空选区、全删及并发保护', { timeout: 120000 }, async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'mp4-api-test-'));
  let child;
  try {
    const review = path.join(root, '剪口播', '3_审核');
    const transcript = path.join(root, '剪口播', '1_转录');
    fs.mkdirSync(review, { recursive: true }); fs.mkdirSync(transcript, { recursive: true });
    const source = path.join(root, '中文 source.mp4');
    run('ffmpeg', ['-v', 'error', '-f', 'lavfi', '-i', 'color=red:s=160x240:r=30:d=1',
      '-f', 'lavfi', '-i', 'color=blue:s=160x240:r=30:d=1', '-f', 'lavfi', '-i', 'color=green:s=160x240:r=30:d=1',
      '-f', 'lavfi', '-i', 'sine=frequency=440:duration=3', '-filter_complex', '[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]',
      '-map', '[v]', '-map', '3:a', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', source]);
    const words = [{text:'头',start:0,end:1},{text:'删',start:1,end:2},{text:'尾',start:2,end:3}];
    fs.writeFileSync(path.join(review, 'data.json'), JSON.stringify({words,autoSelected:[1]}));
    fs.writeFileSync(path.join(transcript, 'subtitles_words.json'), JSON.stringify(words));
    fs.writeFileSync(path.join(review, 'silence_periods.json'), '[]');
    // 随机端口；服务启动失败会直接令测试失败。
    const port = 20000 + Math.floor(Math.random() * 30000);
    child = spawn(process.execPath, [path.resolve(__dirname, '../review_server.js'), String(port), source], { cwd: review, stdio: ['ignore','pipe','pipe'] });
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('server startup timeout')), 10000);
      child.stdout.on('data', d => { if (String(d).includes('READY_PORT=')) { clearTimeout(timer); resolve(); } });
      child.once('exit', () => { clearTimeout(timer); reject(new Error('server exited')); });
    });
    const base = `http://localhost:${port}`;
    const post = (finalSelected, headers={}) => fetch(base+'/api/mp4', {method:'POST', headers:{'Content-Type':'application/json',...headers}, body:JSON.stringify({finalSelected,opts:{preserveNaturalPauses:true}})});
    assert.equal((await post([1], {Origin:'https://example.com'})).status, 403);
    const pending = post([1]);
    await new Promise(resolve => setTimeout(resolve, 100));
    assert.equal((await post([1])).status, 409);
    const response = await pending;
    const data = await response.json();
    assert.equal(response.status, 200, JSON.stringify(data));
    assert.equal(data.segments, 2);
    const probe = JSON.parse(run('ffprobe',['-v','error','-show_streams','-show_format','-of','json',data.output]));
    assert.ok(Math.abs(Number(probe.format.duration)-2)<0.15);
    assert.ok(probe.streams.some(s=>s.codec_type==='audio'));
    assert.equal(probe.streams[0].width,160); assert.equal(probe.streams[0].height,240);
    // 剪后后半段必须是绿色，证明不是仅改容器时长或误用源视频。
    const pixel = execFileSync('ffmpeg',['-v','error','-ss','1.5','-i',data.output,'-frames:v','1','-vf','scale=1:1','-f','rawvideo','-pix_fmt','rgb24','pipe:1']);
    assert.ok(pixel[1]>pixel[0]+40 && pixel[1]>pixel[2]+40);
    run('ffmpeg',['-v','error','-i',data.output,'-f','null','-']);
    const download = await fetch(base+'/api/download/'+encodeURIComponent(data.output));
    assert.equal(download.status,200);
    assert.equal((await download.arrayBuffer()).byteLength,fs.statSync(data.output).size);
    assertExportReceiptCurrent({fcpxmlPath:path.join(review,'中文 source_cut.fcpxml'),reviewLogPath:path.join(review,'review_log.json')});
    assert.equal((await post([0,1,2])).status,500);
    assert.equal((await post([999])).status,500);
    const full = await (await post([])).json(); assert.equal(full.success,true,JSON.stringify(full));
    assert.ok(fs.existsSync(data.output)); assert.notEqual(full.output,data.output);
  } finally {
    if(child && child.exitCode===null) { child.kill(); await once(child,'exit'); }
    fs.rmSync(root,{recursive:true,force:true});
  }
});
test('无音轨和渲染失败可恢复', {timeout:60000}, async()=>{
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'mp4-silent-test-'));
  try {
    const source=path.join(root,'silent.mp4');
    run('ffmpeg',['-v','error','-f','lavfi','-i','color=red:s=160x240:r=30:d=1','-c:v','libx264',source]);
    await renderMp4({videoFile:source,keeps:[{start:0,end:1}],mediaMeta:meta,outputPath:path.join(root,'out.mp4')});
    await assert.rejects(renderMp4({videoFile:source,keeps:[],mediaMeta:meta,outputPath:path.join(root,'empty.mp4')}));
    await assert.rejects(renderMp4({videoFile:path.join(root,'missing.mp4'),keeps:[{start:0,end:1}],mediaMeta:meta,outputPath:path.join(root,'bad.mp4')}));
    assert.equal(fs.existsSync(path.join(root,'bad.mp4')),false);
  } finally { fs.rmSync(root,{recursive:true,force:true}); }
});
