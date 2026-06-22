/* ====== 导出 Tab - 字幕预览 + 配置 + 重点词 + 导出 ====== */

let _exportDragState = null;
let _exportSelectedLine = 0;    // 当前选中的字幕行索引
let _exportSubLines = [];       // [{text, keywords, sentIdx, takeIdx}]

function renderExport(project, container) {
  STATE.taskId = project.task_id || project.id;
  STATE.projectId = project.id;

  const s = loadSubtitleSettings();

  // Generate all subtitle lines from confirmed takes
  _exportSubLines = generateSubtitleLines(project, s.maxChars);
  _exportSelectedLine = 0;

  // Get video URL for preview
  const clips = project.clips || [];
  const videoUrl = clips.length > 0
    ? `/api/projects/${project.id}/clips/${clips[0].id}`
    : '';

  // Build subtitle lines HTML
  const linesHtml = renderSubtitleLinesList(_exportSubLines);

  container.innerHTML = `
    <div id="export-area">
      <!-- ──── 字幕预览 + 字幕行 + 样式设置（同一行） ──── -->
      <div class="export-section">
        <h3>字幕预览 <span style="font-weight:400;font-size:12px;color:var(--text-dim)">9:16 竖屏</span></h3>
        <div class="export-preview-layout">
          <!-- 第1栏: 9:16 手机预览 -->
          <div class="export-preview-wrapper" id="export-preview-wrapper">
            <div class="export-preview-container" id="export-preview-container">
              <video id="export-preview-video"
                     src="${videoUrl}"
                     muted
                     preload="auto"
                     class="export-preview-video"></video>
              <canvas id="export-preview-canvas"></canvas>
              <div id="export-preview-draghandle"
                   class="subtitle-drag-handle"
                   title="拖动调整字幕垂直位置"
                   style="top:${(1 + s.positionY) * 100}%; left:50%; transform:translate(-50%, -50%)">
                <span class="drag-handle-icon">⠿</span>
              </div>
            </div>
          </div>

          <!-- 第2栏: 字幕行列表 -->
          <div class="subtitle-lines-panel" id="subtitle-lines-panel">
            <div class="subtitle-lines-header">
              <span>字幕行</span>
              <span class="sub-line-count">${_exportSubLines.length} 行</span>
            </div>
            <div id="subtitle-lines-list">
              ${linesHtml || '<div class="kw-empty">暂未确认片段。请先在编辑页面确认句子，再回到导出页查看字幕。</div>'}
            </div>
          </div>

          <!-- 第3栏: 字幕样式（紧凑侧边栏） -->
          <div class="export-settings-sidebar">
            <h4>字幕样式</h4>
            <div class="subtitle-compact-field">
              <label>字体</label>
              <select id="sub-font">
                <option value="Source Han Sans SC" ${s.font === 'Source Han Sans SC' ? 'selected' : ''}>思源黑体</option>
                <option value="Microsoft YaHei" ${s.font === 'Microsoft YaHei' ? 'selected' : ''}>微软雅黑</option>
                <option value="PingFang SC" ${s.font === 'PingFang SC' ? 'selected' : ''}>苹方</option>
                <option value="SimHei" ${s.font === 'SimHei' ? 'selected' : ''}>黑体</option>
                <option value="KaiTi" ${s.font === 'KaiTi' ? 'selected' : ''}>楷体</option>
                <option value="Arial" ${s.font === 'Arial' ? 'selected' : ''}>Arial</option>
              </select>
            </div>
            <div class="subtitle-compact-field">
              <label>字号比例</label>
              <div class="compact-range-row">
                <input type="range" id="sub-font-size" min="0.04" max="0.16" step="0.01" value="${s.fontSizeRatio}">
                <span id="sub-font-size-val" class="compact-range-val">${s.fontSizeRatio}</span>
              </div>
            </div>
            <div class="subtitle-compact-field">
              <label>文本颜色</label>
              <div class="compact-color-row">
                <input type="color" id="sub-color" value="${s.color}">
                <span id="sub-color-val" class="compact-color-val">${s.color}</span>
              </div>
            </div>
            <div class="subtitle-compact-field">
              <label>描边颜色</label>
              <div class="compact-color-row">
                <input type="color" id="sub-stroke-color" value="${s.strokeColor}">
                <span id="sub-stroke-color-val" class="compact-color-val">${s.strokeColor}</span>
              </div>
            </div>
            <div class="subtitle-compact-field">
              <label>描边宽度</label>
              <input type="range" id="sub-stroke-width" min="0" max="0.12" step="0.01" value="${s.strokeWidth}">
            </div>
            <div class="subtitle-compact-field">
              <label>重点词颜色</label>
              <div class="compact-color-row">
                <input type="color" id="sub-keyword-color" value="${s.keywordColor}">
                <span id="sub-keyword-color-val" class="compact-color-val">${s.keywordColor}</span>
              </div>
            </div>
            <div class="subtitle-compact-field">
              <label>垂直位置</label>
              <div class="compact-range-row">
                <input type="range" id="sub-position-y" min="-0.9" max="-0.1" step="0.01" value="${s.positionY}">
                <span id="sub-position-y-val" class="compact-range-val">${Math.round(Math.abs(s.positionY) * 100)}%</span>
              </div>
            </div>
            <div class="subtitle-compact-field">
              <label>每行最大字数</label>
              <div class="compact-range-row">
                <input type="range" id="sub-max-chars" min="8" max="24" step="1" value="${s.maxChars}">
                <span id="sub-max-chars-val" class="compact-range-val">${s.maxChars} 字</span>
              </div>
            </div>
          </div>
        </div>
        <p class="export-hint">
          拖动 <span class="drag-handle-icon-inline">⠿</span> 手柄调整字幕垂直位置，点击字幕行预览，右侧调整样式
        </p>
      </div>

      <!-- ──── 导出 ──── -->
      <div class="export-section">
        <h3>导出格式</h3>
        <div class="export-actions">
          <button id="btn-export-draft" class="btn-export-primary">剪映草稿 (.zip)</button>
          <button id="btn-export-srt" class="btn-export">SRT 字幕</button>
          <button id="btn-export-text" class="btn-export">剪辑清单</button>
        </div>
        <p class="export-hint">导出时会自动为每句选择最佳 take（A 级优先，跳过废片），字幕按逗号/句号拆分为短行</p>
      </div>
    </div>
  `;

  // ──── Bind subtitle controls ────
  const bindings = [
    { id: 'sub-font', key: 'font', type: 'value' },
    { id: 'sub-font-size', key: 'fontSizeRatio', type: 'value', parse: parseFloat },
    { id: 'sub-color', key: 'color', type: 'value' },
    { id: 'sub-stroke-color', key: 'strokeColor', type: 'value' },
    { id: 'sub-stroke-width', key: 'strokeWidth', type: 'value', parse: parseFloat },
    { id: 'sub-keyword-color', key: 'keywordColor', type: 'value' },
    { id: 'sub-position-y', key: 'positionY', type: 'value', parse: parseFloat },
    { id: 'sub-max-chars', key: 'maxChars', type: 'value', parse: parseInt },
  ];

  bindings.forEach(({ id, key, parse }) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('input', () => {
      let val = el.value;
      if (parse) val = parse(val);
      subtitleSettings[key] = val;
      saveSubtitleSettings(subtitleSettings);
      updateExportValueLabels();
      drawExportPreview();
      updateDragHandlePosition();
      // maxChars changed: regenerate subtitle lines
      if (key === 'maxChars') {
        _exportSubLines = generateSubtitleLines(project, val);
        _exportSelectedLine = Math.min(_exportSelectedLine, _exportSubLines.length - 1);
        refreshSubtitleLinesList();
        drawExportPreview();
      }
    });
  });

  updateExportValueLabels();

  // ──── Video events ────
  const previewVideo = document.getElementById('export-preview-video');
  if (previewVideo) {
    previewVideo.addEventListener('loadedmetadata', () => {
      drawExportPreview();
      updateDragHandlePosition();
    });
    previewVideo.addEventListener('timeupdate', () => {
      // Auto-highlight the line that corresponds to current video time
      autoSelectLineByTime(previewVideo.currentTime);
    });
  }

  // ──── Subtitle lines click ────
  const linesList = document.getElementById('subtitle-lines-list');
  if (linesList) {
    linesList.addEventListener('click', (e) => {
      // Keyword toggle button
      const kwBtn = e.target.closest('.sub-line-kw-btn');
      if (kwBtn) {
        e.stopPropagation();
        const word = kwBtn.dataset.word;
        const sentIdx = parseInt(kwBtn.dataset.sentence);
        const lineIdx = parseInt(kwBtn.dataset.line);
        toggleSubLineKeyword(sentIdx, word, kwBtn, lineIdx);
        return;
      }
      // Select line
      const item = e.target.closest('.subtitle-line-item');
      if (item) {
        const idx = parseInt(item.dataset.lineIndex);
        selectSubtitleLine(idx);
      }
    });
  }

  // ──── Drag handle for subtitle position ────
  initExportDragHandle();

  // ──── Export buttons ────
  document.getElementById('btn-export-draft').addEventListener('click', () => exportProjectDraft());
  document.getElementById('btn-export-srt').addEventListener('click', () => exportProjectSrt());
  document.getElementById('btn-export-text').addEventListener('click', () => exportProjectText());

  // ──── Resize handling ────
  window.addEventListener('resize', () => {
    drawExportPreview();
    updateDragHandlePosition();
  });

  // ──── Initial preview draw ────
  setTimeout(() => {
    drawExportPreview();
    updateDragHandlePosition();
    selectSubtitleLine(0);
  }, 300);
}

/* ──── 生成字幕行 ──── */

function generateSubtitleLines(project, maxChars) {
  const sentences = project.sentences || [];
  const lines = [];

  for (const sent of sentences) {
    const takeIdx = sent.confirmed_take_index >= 0 ? sent.confirmed_take_index : 0;
    if (!sent.takes || !sent.takes[takeIdx]) continue;
    const take = sent.takes[takeIdx];

    // Split take text into short subtitle lines (simulating backend _split_to_short_lines)
    const shortLines = splitSubtitlesForDisplay(take.text, maxChars || 12);

    for (const lineText of shortLines) {
      // Detect keywords in this line
      const tokens = typeof getKeywordTokens === 'function'
        ? getKeywordTokens(lineText, '#FFD700', '#FF6B6B')
        : [];

      const keywords = tokens
        .filter(t => t.isKeyword)
        .map(t => ({ word: t.word, type: t.type, color: t.color }));

      lines.push({
        text: lineText,
        keywords,
        sentIdx: sent.index,
        takeIdx,
        startTime: take.start,
        endTime: take.end,
      });
    }
  }

  return lines;
}

/* ──── 前端字幕拆分（模拟后端 _split_to_short_lines） ──── */

function splitSubtitlesForDisplay(text, maxChars) {
  if (!text || !text.trim()) return [text || ''];

  // Step 1: split at sentence-final punctuation
  const sentenceBreaks = /([。！？!?\n])/;
  const segments = text.split(sentenceBreaks);

  let rawSentences = [];
  let buf = '';
  for (const seg of segments) {
    if (/^[。！？!?\n]+$/.test(seg)) {
      buf += seg;
      rawSentences.push(buf);
      buf = '';
    } else {
      if (buf) rawSentences.push(buf);
      buf = seg;
    }
  }
  if (buf) rawSentences.push(buf);

  // Step 2: split at commas / minor breaks
  const minorBreaks = /([，、；：,;:])/;
  const effectiveMax = Math.max(6, maxChars);
  const lines = [];

  for (const sentence of rawSentences) {
    const s = sentence.trim();
    if (!s) continue;

    if (s.length <= effectiveMax) {
      lines.push(s);
      continue;
    }

    const parts = s.split(minorBreaks);
    let current = '';
    for (const part of parts) {
      if (/^[，、；：,;:]+$/.test(part)) {
        if (current && current.length + part.length <= effectiveMax) {
          current += part;
        } else {
          if (current) lines.push(current);
          current = part.replace(/^[，、；：,;:]+/, '');
        }
      } else {
        const combined = current + part;
        if (combined.length <= effectiveMax) {
          current = combined;
        } else {
          if (current) lines.push(current);
          let remaining = part;
          while (remaining.length > effectiveMax) {
            lines.push(remaining.substring(0, effectiveMax));
            remaining = remaining.substring(effectiveMax);
          }
          current = remaining;
        }
      }
    }
    if (current) lines.push(current);
  }

  // If only one long line, split evenly
  if (lines.length === 1 && lines[0].length > effectiveMax) {
    const t = lines[0];
    const n = Math.ceil(t.length / effectiveMax);
    const chunkSize = Math.ceil(t.length / n);
    const result = [];
    for (let i = 0; i < t.length; i += chunkSize) {
      result.push(t.substring(i, i + chunkSize));
    }
    return result;
  }

  // Filter empty/pure-punctuation lines
  return lines.filter(l => l.trim() && !/^[，。！？、；：,\.!\?;:\s]+$/.test(l.trim()));
}

/* ──── 渲染字幕行列表 ──── */

function renderSubtitleLinesList(lines) {
  if (!lines.length) return '';

  return lines.map((line, i) => {
    const lineKwKey = `${line.sentIdx}:${i}`;
    const kwTogglesHtml = line.keywords.length > 0
      ? `<div class="sub-line-kw-toggles">` +
        line.keywords.map(kw => {
          const overrideKey = `${line.sentIdx}:${kw.word}`;
          const enabled = window._keywordOverrides.hasOwnProperty(overrideKey)
            ? window._keywordOverrides[overrideKey] !== false
            : true;
          const cls = enabled ? 'kw-on' : 'kw-off';
          const typeLabel = kw.type && KEYWORD_TYPES && KEYWORD_TYPES[kw.type]
            ? KEYWORD_TYPES[kw.type].label : (kw.type || '');
          return `<button class="sub-line-kw-btn ${cls}"
                  data-word="${escapeHtml(kw.word)}"
                  data-sentence="${line.sentIdx}"
                  data-line="${i}"
                  title="${typeLabel}: 点击切换">
            <span class="sub-line-kw-dot" style="background:${kw.color || '#FFD700'}"></span>
            ${escapeHtml(kw.word)}
          </button>`;
        }).join('') +
        `</div>`
      : `<div class="sub-line-no-kw">无重点词</div>`;

    return `<div class="subtitle-line-item" data-line-index="${i}" data-sentence="${line.sentIdx}">
      <span class="sub-line-idx">#${i + 1}</span>
      <div>
        <div class="sub-line-text">${escapeHtml(line.text)}</div>
        ${kwTogglesHtml}
      </div>
    </div>`;
  }).join('');
}

function refreshSubtitleLinesList() {
  const list = document.getElementById('subtitle-lines-list');
  if (!list) return;
  list.innerHTML = renderSubtitleLinesList(_exportSubLines) || '<div class="kw-empty">暂未确认片段</div>';
  selectSubtitleLine(_exportSelectedLine);
}

/* ──── 选择字幕行 ──── */

function selectSubtitleLine(index) {
  if (index < 0 || index >= _exportSubLines.length) return;
  _exportSelectedLine = index;

  // Update selection styling
  const items = document.querySelectorAll('.subtitle-line-item');
  items.forEach((item, i) => {
    item.classList.toggle('selected', i === index);
  });

  // Scroll into view
  const selected = document.querySelector('.subtitle-line-item.selected');
  if (selected) {
    selected.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  // Seek video to the line's take start time
  const line = _exportSubLines[index];
  if (line && line.startTime != null) {
    const video = document.getElementById('export-preview-video');
    if (video && video.readyState >= 1) {
      video.currentTime = line.startTime;
    }
  }

  drawExportPreview();
}

function autoSelectLineByTime(currentTime) {
  // Find the line whose startTime is closest to currentTime
  let bestIdx = -1;
  let bestDist = Infinity;
  for (let i = 0; i < _exportSubLines.length; i++) {
    const line = _exportSubLines[i];
    if (line.startTime != null && currentTime >= line.startTime - 0.1) {
      const dist = Math.abs(currentTime - line.startTime);
      if (dist < bestDist) {
        bestDist = dist;
        bestIdx = i;
      }
    }
  }
  if (bestIdx >= 0 && bestIdx !== _exportSelectedLine) {
    _exportSelectedLine = bestIdx;
    const items = document.querySelectorAll('.subtitle-line-item');
    items.forEach((item, i) => {
      item.classList.toggle('selected', i === bestIdx);
    });
    // Don't scroll during auto-follow — only scroll on manual click
    drawExportPreview();
  }
}

/* ──── 关键词切换（字幕行级别） ──── */

function toggleSubLineKeyword(sentIdx, word, btn, lineIdx) {
  const key = `${sentIdx}:${word}`;
  const overrides = window._keywordOverrides;
  if (overrides[key] === undefined) {
    overrides[key] = false;
  } else if (overrides[key] === false) {
    overrides[key] = true;
  } else {
    overrides[key] = false;
  }
  saveKeywordOverridesGlobal();

  // Update button state
  const enabled = overrides[key] !== false;
  btn.classList.toggle('kw-on', enabled);
  btn.classList.toggle('kw-off', !enabled);

  // Update all instances of this keyword across all lines
  document.querySelectorAll(`.sub-line-kw-btn[data-word="${escapeHtml(word)}"][data-sentence="${sentIdx}"]`).forEach(b => {
    b.classList.toggle('kw-on', enabled);
    b.classList.toggle('kw-off', !enabled);
  });

  drawExportPreview();
}

/* ──── 预览渲染 ──── */

function drawExportPreview() {
  const canvas = document.getElementById('export-preview-canvas');
  const wrapper = document.getElementById('export-preview-wrapper');
  if (!canvas || !wrapper) return;

  // Sync canvas size to the wrapper
  const rect = wrapper.getBoundingClientRect();
  canvas.width = rect.width;
  canvas.height = rect.height;

  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  // Get the currently selected subtitle line text
  const line = _exportSubLines[_exportSelectedLine];
  const text = line ? line.text : '';
  const sentIdx = line ? line.sentIdx : 0;

  if (!text) {
    ctx.fillStyle = 'rgba(255,255,255,0.3)';
    ctx.font = '14px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('确认片段后，字幕行将出现在此处', canvas.width / 2, canvas.height / 2);
    ctx.textAlign = 'start';
    return;
  }

  const s = subtitleSettings;
  // Use a slightly larger font for the 9:16 preview (phone screen = smaller canvas width)
  const fontSize = Math.max(16, canvas.height * s.fontSizeRatio);
  const yPos = canvas.height * (1 + s.positionY);

  let tokens = typeof getKeywordTokens === 'function'
    ? getKeywordTokens(text, s.keywordColor, s.keywordColor)
    : [{ word: text, isKeyword: false, type: null, color: null }];

  // Apply keyword overrides
  tokens = tokens.map(t => {
    if (!t.isKeyword) return t;
    const overrideKey = `${sentIdx}:${t.word}`;
    if (window._keywordOverrides.hasOwnProperty(overrideKey) && window._keywordOverrides[overrideKey] === false) {
      return { ...t, isKeyword: false, type: null, color: null };
    }
    return t;
  });

  const fontFamily = `"${s.font}", "Microsoft YaHei", "PingFang SC", sans-serif`;

  // Measure total width
  let totalWidth = 0;
  const measured = tokens.map(t => {
    ctx.font = `${fontSize}px ${t.isKeyword ? 'bold ' : ''}${fontFamily}`;
    const w = ctx.measureText(t.word).width;
    totalWidth += w;
    return { ...t, width: w };
  });

  let x = Math.max(8, (canvas.width - totalWidth) / 2);

  for (const token of measured) {
    ctx.font = `${fontSize}px ${token.isKeyword ? 'bold ' : ''}${fontFamily}`;

    ctx.strokeStyle = s.strokeColor;
    ctx.lineWidth = fontSize * s.strokeWidth * 2;
    ctx.lineJoin = 'round';
    ctx.strokeText(token.word, x, yPos);
    ctx.fillStyle = token.isKeyword ? s.keywordColor : s.color;
    ctx.fillText(token.word, x, yPos);

    x += token.width;
  }
  ctx.textAlign = 'start';
}

/* ──── 拖动手柄 ──── */

function initExportDragHandle() {
  const handle = document.getElementById('export-preview-draghandle');
  const wrapper = document.getElementById('export-preview-wrapper');
  if (!handle || !wrapper) return;

  handle.addEventListener('mousedown', (e) => {
    e.preventDefault();
    _exportDragState = {
      wrapper,
      handle,
      startY: e.clientY,
      startTop: handle.offsetTop,
      wrapperHeight: wrapper.getBoundingClientRect().height,
    };
    handle.classList.add('dragging');
  });

  document.addEventListener('mousemove', (e) => {
    if (!_exportDragState) return;
    const { wrapper, handle, startY, startTop, wrapperHeight } = _exportDragState;
    const dy = e.clientY - startY;
    let newTop = startTop + dy;
    newTop = Math.max(10, Math.min(wrapperHeight - 10, newTop));
    handle.style.top = newTop + 'px';

    const ratio = newTop / wrapperHeight;
    const positionY = ratio - 1;
    const clamped = Math.round(Math.max(-0.9, Math.min(-0.1, positionY)) * 100) / 100;
    subtitleSettings.positionY = clamped;
    saveSubtitleSettings(subtitleSettings);

    const slider = document.getElementById('sub-position-y');
    if (slider) slider.value = clamped;
    const valEl = document.getElementById('sub-position-y-val');
    if (valEl) valEl.textContent = Math.round(Math.abs(clamped) * 100) + '%';

    drawExportPreview();
  });

  document.addEventListener('mouseup', () => {
    if (_exportDragState) {
      _exportDragState.handle.classList.remove('dragging');
      _exportDragState = null;
    }
  });
}

function updateDragHandlePosition() {
  const handle = document.getElementById('export-preview-draghandle');
  const wrapper = document.getElementById('export-preview-wrapper');
  if (!handle || !wrapper) return;
  const h = wrapper.getBoundingClientRect().height;
  const s = subtitleSettings;
  const topPx = (1 + s.positionY) * h;
  handle.style.top = Math.max(10, Math.min(h - 10, topPx)) + 'px';
}

/* ──── 值标签更新 ──── */

function updateExportValueLabels() {
  const s = subtitleSettings;
  const elColor = document.getElementById('sub-color-val');
  const elStroke = document.getElementById('sub-stroke-color-val');
  const elKw = document.getElementById('sub-keyword-color-val');
  const elChars = document.getElementById('sub-max-chars-val');
  const elSize = document.getElementById('sub-font-size-val');
  const elPos = document.getElementById('sub-position-y-val');
  if (elColor) elColor.textContent = s.color;
  if (elStroke) elStroke.textContent = s.strokeColor;
  if (elKw) elKw.textContent = s.keywordColor;
  if (elChars) elChars.textContent = `${s.maxChars} 字`;
  if (elSize) elSize.textContent = s.fontSizeRatio;
  if (elPos) elPos.textContent = Math.round(Math.abs(s.positionY) * 100) + '%';
}

/* ──── 导出 ──── */

function exportProjectDraft() {
  const s = subtitleSettings;
  const params = new URLSearchParams({
    font: s.font,
    fontSizeRatio: s.fontSizeRatio,
    color: s.color.replace('#', ''),
    strokeColor: s.strokeColor.replace('#', ''),
    strokeWidth: s.strokeWidth,
    positionY: s.positionY,
    keywordColor: s.keywordColor.replace('#', ''),
    maxChars: s.maxChars,
  });
  window.open(`/api/projects/${_currentProjectId}/export/draft?${params}`, '_blank');
}

function exportProjectSrt() {
  window.open(`/api/projects/${_currentProjectId}/export/srt`, '_blank');
}

function exportProjectText() {
  window.open(`/api/projects/${_currentProjectId}/export/text`, '_blank');
}
