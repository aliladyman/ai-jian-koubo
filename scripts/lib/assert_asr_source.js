/**
 * 转录来源守卫（fail closed）
 *
 * 背景：实际发生过——转录那一步被绕过，agent 自己跑 whisper 出 audio.json，
 * 转成 subtitles_words.json 塞回流水线，下游全程没报错，成片错字暴增
 * （「晨报」→「承报」6 处），直到看成片才发现引擎被换过。
 *
 * 根因不是规则缺失（SKILL.md 一直规定走 run_transcribe.sh），而是没有任何一环
 * 校验「这份逐字稿是谁转的」——下游只认文件格式，绕道不撞墙。
 *
 * 本守卫：消费 subtitles_words.json 之前，要求同目录存在火山产物
 * volcengine_v3_result.json；缺失即停止并说明怎么办。
 * 用户确认后确需换引擎时，写 .asr_override.json 显式放行（见下方格式），
 * 放行时仍会打印醒目告警，不静默。
 */

const fs = require('fs');
const path = require('path');

const VOLC_RESULT = 'volcengine_v3_result.json';
const OVERRIDE_FILE = '.asr_override.json';

/**
 * @param {string} subtitlesWordsPath  subtitles_words.json 的路径
 * @param {string} caller              调用方脚本名，用于报错信息
 */
function assertAsrSource(subtitlesWordsPath, caller) {
  const dir = path.dirname(path.resolve(subtitlesWordsPath));
  const volcPath = path.join(dir, VOLC_RESULT);
  if (fs.existsSync(volcPath)) return;   // 正常路径：火山产物在，放行

  const overridePath = path.join(dir, OVERRIDE_FILE);
  if (fs.existsSync(overridePath)) {
    let ov = null;
    try {
      ov = JSON.parse(fs.readFileSync(overridePath, 'utf8'));
    } catch (e) {
      console.error('❌ ' + OVERRIDE_FILE + ' 不是合法 JSON：' + e.message);
      process.exit(1);
    }
    // 三个字段都要有，防止随手 echo '{}' 就放行
    const missing = ['engine', 'reason', 'confirmedAt'].filter(k => !ov || !ov[k]);
    if (missing.length) {
      console.error('❌ ' + OVERRIDE_FILE + ' 缺字段: ' + missing.join(', ') +
                    '\n   必须含 engine（实际用的引擎）、reason（为什么不用火山）、confirmedAt（用户确认时间）。');
      process.exit(1);
    }
    console.error('');
    console.error('⚠️  ══════════ 本片未使用火山引擎转录 ══════════');
    console.error('⚠️  引擎: ' + ov.engine);
    console.error('⚠️  原因: ' + ov.reason);
    console.error('⚠️  用户确认于: ' + ov.confirmedAt);
    console.error('⚠️  替代引擎中文识别通常弱于火山大模型版，专名/术语错字会明显增多，');
    console.error('⚠️  审核页请逐句核对，不要只扫一遍。');
    console.error('⚠️  ═══════════════════════════════════════════');
    console.error('');
    return;
  }

  console.error('');
  console.error('❌ 转录来源校验失败（' + caller + '）');
  console.error('   目录: ' + dir);
  console.error('   缺少火山转录产物: ' + VOLC_RESULT);
  console.error('');
  console.error('   本 skill 的逐字稿必须来自火山引擎（run_transcribe.sh）。检测到 ' +
                'subtitles_words.json 存在但火山产物缺失，说明转录这一步被替换或跳过了。');
  console.error('');
  console.error('   正确做法：重跑转录');
  console.error('     bash <skill>/scripts/run_transcribe.sh <视频路径> <片夹>/剪口播');
  console.error('');
  console.error('   若火山确实不可用（先跑 node scripts/doctor.js --force 确认），');
  console.error('   必须先把情况报告用户、取得确认，再由用户认可后写入：');
  console.error('     ' + path.join(dir, OVERRIDE_FILE));
  console.error('     {"engine":"whisper-large-v3","reason":"火山资源未开通","confirmedAt":"2026-07-21T21:00+08:00"}');
  console.error('   agent 不得自行创建该文件绕过本检查。');
  console.error('');
  process.exit(1);
}

module.exports = { assertAsrSource };
