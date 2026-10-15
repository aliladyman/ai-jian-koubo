/**
 * 切割算法单一来源（前后端共用）
 *
 * 输入「用户明确选中的删除段」，输出「实际保留片段 finalKeeps」。
 * 默认自然安全模式只做区间取反：黄色静音只是候选，不会在红色选区之外
 * 自动吸附或二次切割。旧版静音吸附算法仍可通过
 * preserveNaturalPauses:false 显式启用，供历史工程兼容。
 *
 * UMD：Node 用 require('./lib/compute_keeps')，浏览器用 <script> 后读 window.ComputeKeeps。
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.ComputeKeeps = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const ENGINE_VERSION = 'a-mode-explicit-v1';
  const EPS = 1e-6;

  // 默认使用自然安全模式；其余阈值只在显式兼容模式中生效。
  const DEFAULTS = {
    preserveNaturalPauses: true,
    mergeGap: 0.15,          // 相邻删除段间距 < 此值则合并，吸收词级时间戳天然间隙
    minKeepDur: 0.1,         // 短于此的保留段无意义，丢弃
    lookBack: 0.6,           // 删除点前后多大窗口内寻找静音作为吸附切点
    padFrames: 2 / 30,       // 吸附后给说话者留的喘气余量（秒）
    edgeMargin: 0.05,        // 保留段边缘此范围内的静音不算「内部静音」
    minInternalSilence: 0.2, // 保留段内部 ≥ 此长度的静音会被二次切掉（换气/未识别停顿）
  };

  function validInterval(seg) {
    return seg && Number.isFinite(Number(seg.start)) && Number.isFinite(Number(seg.end));
  }

  function mergeDeleteSegments(deleteList, duration, mergeGap) {
    const maxDuration = Number.isFinite(duration) && duration > 0 ? duration : 0;
    const sorted = (deleteList || [])
      .filter(validInterval)
      .map(seg => ({
        start: Math.max(0, Math.min(maxDuration, Number(seg.start))),
        end: Math.max(0, Math.min(maxDuration, Number(seg.end))),
      }))
      .filter(seg => seg.end > seg.start + EPS)
      .sort((a, b) => a.start - b.start || a.end - b.end);

    const merged = [];
    for (const seg of sorted) {
      const last = merged[merged.length - 1];
      if (!last || seg.start > last.end + mergeGap + EPS) {
        merged.push({ start: seg.start, end: seg.end });
      } else {
        last.end = Math.max(last.end, seg.end);
      }
    }
    return merged;
  }

  // 服务器与浏览器共用：只合并「token 序列中连续被选中」的词/静音。
  // 未选中的 gap 会切断删除段，避免 UI 没标红、导出却把它吞掉。
  function buildDeleteListFromSelection(words, selectedIndices) {
    const selected = new Set((selectedIndices || []).map(Number).filter(Number.isInteger));
    const out = [];
    let cur = null;
    for (let i = 0; i < (words || []).length; i++) {
      const w = words[i];
      const usable = validInterval(w) && Number(w.end) > Number(w.start) + EPS;
      if (selected.has(i) && usable) {
        if (!cur) cur = { start: Number(w.start), end: Number(w.end) };
        else cur.end = Math.max(cur.end, Number(w.end));
      } else if (cur) {
        out.push(cur);
        cur = null;
      }
    }
    if (cur) out.push(cur);
    return out;
  }

  // 在 (rawStart, windowEnd] 内找最近的静音终点（最小 end），用于裁保留段开头
  function findNextSilenceEnd(periods, rawStart, windowEnd) {
    let best = null;
    for (const sp of periods) {
      if (sp.end > rawStart && sp.end <= windowEnd) {
        if (best === null || sp.end < best) best = sp.end;
      }
    }
    return best;
  }

  // 在 [windowStart, rawEnd) 内找最后一个静音起点，用于裁保留段末尾
  function findLastSilenceStart(periods, rawEnd, windowStart) {
    let best = null;
    for (const sp of periods) {
      if (sp.start >= windowStart && sp.start < rawEnd) best = sp.start;
    }
    return best;
  }

  /**
   * @param {{start:number,end:number}[]} deleteList 用户选中的删除段（无需排序）
   * @param {{start:number,end:number}[]} silencePeriods ffmpeg 检测的静音段
   * @param {number} duration 媒体总时长（秒）
   * @param {object} [opts] 覆盖默认阈值
   * @returns {{start:number,end:number}[]} 实际保留片段
   */
  function computeFinalKeeps(deleteList, silencePeriods, duration, opts) {
    const o = Object.assign({}, DEFAULTS, opts || {});
    // 非对称喘气余量：起始(lead-in)与结尾(trail)可分别设置。
    // 未显式给 padStart/padEnd 时退回对称 padFrames，保持旧行为。
    const padStart = (opts && opts.padStart != null) ? opts.padStart : o.padFrames;
    const padEnd = (opts && opts.padEnd != null) ? opts.padEnd : o.padFrames;
    const periods = (silencePeriods || []).slice().sort((a, b) => a.start - b.start);

    // 自然安全模式：删除范围 = 红色明确选区；静音数据不参与实际切点。
    const safeMode = o.preserveNaturalPauses !== false;
    const merged = mergeDeleteSegments(deleteList, duration, safeMode ? 0 : o.mergeGap);
    if (safeMode) {
      const keeps = [];
      let cursor = 0;
      for (const del of merged) {
        if (del.start > cursor + EPS) keeps.push({ start: cursor, end: del.start });
        cursor = Math.max(cursor, del.end);
      }
      if (cursor < duration - EPS) keeps.push({ start: cursor, end: duration });
      return keeps;
    }

    // 兼容模式：保留历史的静音吸附 + 内部静音二次切割行为。
    const keepSegments = [];
    let cursor = 0;
    for (const del of merged) {
      if (del.start > cursor + o.minKeepDur) {
        const silEnd = findNextSilenceEnd(periods, cursor, cursor + o.lookBack);
        const trimmedStart = silEnd !== null ? silEnd - padStart : cursor;

        const silStart = findLastSilenceStart(periods, del.start, del.start - o.lookBack);
        const trimmedEnd = silStart !== null ? silStart + padEnd : del.start;

        if (trimmedEnd > trimmedStart + o.minKeepDur) {
          keepSegments.push({ start: trimmedStart, end: trimmedEnd });
        }
      }
      cursor = del.end;
    }
    if (cursor < duration - o.minKeepDur) {
      const silEnd = findNextSilenceEnd(periods, cursor, cursor + o.lookBack);
      const trimmedStart = silEnd !== null ? silEnd - padStart : cursor;
      keepSegments.push({ start: trimmedStart, end: duration });
    }

    // 3) 保留段内部长静音二次切割
    const finalKeeps = [];
    for (const keep of keepSegments) {
      const internal = periods.filter(sp =>
        sp.start > keep.start + o.edgeMargin &&
        sp.end < keep.end - o.edgeMargin &&
        (sp.end - sp.start) >= o.minInternalSilence
      );
      let cur = keep.start;
      for (const sp of internal) {
        if (sp.start + padEnd > cur + o.minKeepDur) finalKeeps.push({ start: cur, end: sp.start + padEnd });
        cur = sp.end;
      }
      if (keep.end > cur + o.minKeepDur) finalKeeps.push({ start: cur, end: keep.end });
    }

    return finalKeeps;
  }

  // 区间相减：a 减去 b（两侧都已按 start 升序、内部不重叠），丢弃短于 minDur 的碎片。
  // 审核页用它算「算法切了、但用户没选」的误伤段（cuts − deleteSegs）。
  function intervalSubtract(a, b, minDur) {
    const min = minDur == null ? 0.02 : minDur;
    const out = [];
    for (const c of a) {
      let segs = [{ start: c.start, end: c.end }];
      for (const d of b) {
        const next = [];
        for (const s of segs) {
          if (d.end <= s.start || d.start >= s.end) { next.push(s); continue; }
          if (d.start > s.start) next.push({ start: s.start, end: d.start });
          if (d.end < s.end) next.push({ start: d.end, end: s.end });
        }
        segs = next;
      }
      for (const s of segs) if (s.end - s.start > min) out.push(s);
    }
    return out;
  }

  // 保留段取反 → 实际被切掉的区间（含吸附/二次切的「误伤」）
  function keepsToCuts(finalKeeps, duration) {
    const cuts = [];
    let cursor = 0;
    for (const k of finalKeeps) {
      if (k.start > cursor + 1e-6) cuts.push({ start: cursor, end: k.start });
      cursor = Math.max(cursor, k.end);
    }
    if (cursor < duration - 1e-6) cuts.push({ start: cursor, end: duration });
    return cuts;
  }

  // 检查实际切掉的区间是否碰到了任何「未选中真词」。安全模式命中即应阻断导出。
  function findUnselectedWordCutRisks(words, selectedIndices, finalKeeps, duration, tolerance) {
    const selected = new Set((selectedIndices || []).map(Number).filter(Number.isInteger));
    const cuts = keepsToCuts(finalKeeps || [], duration);
    const tol = tolerance == null ? 1e-4 : Math.max(0, Number(tolerance));
    const risks = [];
    for (let i = 0; i < (words || []).length; i++) {
      const w = words[i];
      if (!w || w.isGap || selected.has(i) || !validInterval(w)) continue;
      const ws = Number(w.start), we = Number(w.end);
      for (const cut of cuts) {
        const overlap = Math.min(cut.end, we) - Math.max(cut.start, ws);
        if (overlap > tol) {
          risks.push({
            idx: i,
            text: String(w.text || ''),
            wordStart: ws,
            wordEnd: we,
            cutStart: cut.start,
            cutEnd: cut.end,
            overlap: Number(overlap.toFixed(6)),
          });
          break;
        }
      }
    }
    return risks;
  }

  return {
    computeFinalKeeps,
    keepsToCuts,
    intervalSubtract,
    buildDeleteListFromSelection,
    findUnselectedWordCutRisks,
    DEFAULTS,
    ENGINE_VERSION,
  };
});
