'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { buildJianying, saveJianying } = require('../lib/jianying');
const mediaMeta = { fpsNum: 30000, fpsDen: 1001, width: 1920, height: 1080, duration: 20 };
const finalKeeps = [{ startFrame: 1, endFrame: 17 }, { startFrame: 25, endFrame: 56 }, { startFrame: 400, endFrame: 500 }];
const args = { videoFile: '/fixture.mov', name: '测试', mediaMeta, finalKeeps };
test('fractional-fps cuts bind only to main track without losing frames', () => {
  const d = buildJianying(args);
  assert.equal(d.tracks.length, 1); assert.equal(d.tracks[0].flag, 0);
  let end = 0;
  d.tracks[0].segments.forEach((s, i) => {
    assert.equal(s.target_timerange.start, end); end += s.target_timerange.duration;
    assert.equal(s.source_timerange.start, Math.round(finalKeeps[i].startFrame * 1001e6 / 30000));
    assert.equal(s.visible, true); assert.equal(s.material_id, d.materials.videos[0].id);
  });
  assert.equal(end, Math.round(147 * 1001e6 / 30000)); assert.equal(end, d.duration);
});
test('empty, overlapping and out-of-range cuts fail closed', () => {
  for (const keeps of [[], [{startFrame:0,endFrame:700}], [{startFrame:2,endFrame:5},{startFrame:4,endFrame:6}]]) assert.throws(() => buildJianying({...args,finalKeeps:keeps}));
});
test('repeated exports create separate drafts and preserve existing edits', () => {
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'jianying-test-'));
  const videoFile=path.join(root,'source.mov'); fs.writeFileSync(videoFile,'fixture');
  const a=saveJianying({...args,videoFile,draftRoot:root,exportDir:root});
  fs.writeFileSync(path.join(a.draftPath,'user-edit'),'keep');
  const b=saveJianying({...args,videoFile,draftRoot:root,exportDir:root});
  assert.notEqual(a.draftPath,b.draftPath); assert.equal(fs.readFileSync(path.join(a.draftPath,'user-edit'),'utf8'),'keep');
  assert.equal(JSON.parse(fs.readFileSync(b.receiptPath)).trackFlag,0);
  assert.throws(()=>saveJianying({...args,videoFile:'/missing',draftRoot:root,exportDir:root}));
});
test('HTTP native export rejects remote requests and matches the canonical FCPXML', { timeout: 30000 }, async () => {
  const {spawn,execFileSync}=require('child_process');
  const {once}=require('events');
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'jianying-http-'));
  const review=path.join(root,'剪口播','3_审核'), transcript=path.join(root,'剪口播','1_转录'), draftRoot=path.join(root,'drafts');
  for(const p of [review,transcript,draftRoot])fs.mkdirSync(p,{recursive:true});
  const source=path.join(root,'source.mp4');
  execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','color=blue:s=160x240:r=30:d=3','-f','lavfi','-i','sine=duration=3','-c:v','libx264','-c:a','aac',source]);
  const words=[{text:'头',start:0,end:1},{text:'删',start:1,end:2},{text:'尾',start:2,end:3}];
  fs.writeFileSync(path.join(review,'data.json'),JSON.stringify({words,autoSelected:[1]}));
  fs.writeFileSync(path.join(transcript,'subtitles_words.json'),JSON.stringify(words));
  const port=20000+Math.floor(Math.random()*30000);
  const child=spawn(process.execPath,[path.resolve(__dirname,'../review_server.js'),String(port),source],{cwd:review,env:{...process.env,JIANYING_DRAFT_ROOT:draftRoot},stdio:['ignore','pipe','pipe']});
  try {
    await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('startup timeout')),10000);child.stdout.on('data',b=>{if(String(b).includes('READY_PORT=')){clearTimeout(timer);resolve();}});child.once('exit',()=>{clearTimeout(timer);reject(Error('server exited'));});});
    const post=(finalSelected,headers={})=>fetch(`http://localhost:${port}/api/jianying`,{method:'POST',headers:{'Content-Type':'application/json',...headers},body:JSON.stringify({finalSelected,opts:{preserveNaturalPauses:true}})});
    assert.equal((await post([1],{Origin:'https://example.com'})).status,403);
    assert.equal((await post([999])).status,500);
    const response=await post([1]);const result=await response.json();assert.equal(response.status,200,JSON.stringify(result));
    const d=JSON.parse(fs.readFileSync(path.join(result.jianying.draftPath,'draft_info.json')));
    assert.equal(d.duration,2000000);assert.equal(d.tracks[0].flag,0);assert.equal(d.tracks[0].segments.length,2);assert.equal(d.tracks[0].segments[1].source_timerange.start,2000000);
    require('../lib/export_bundle').assertExportReceiptCurrent({fcpxmlPath:result.output,reviewLogPath:path.join(review,'review_log.json')});
    assert.equal((await post([0,1,2])).status,500);
  } finally {if(child.exitCode===null){child.kill();await once(child,'exit');}}
});
