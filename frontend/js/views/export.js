/* ====== 导出 Tab - 字幕配置 + 预览 + 导出 ====== */

function renderExport(project, container) {
  // Ensure STATE is populated
  STATE.taskId = project.task_id || project.id;
  STATE.projectId = project.id;

  // Load subtitle settings
  const s = loadSubtitleSettings();

  container.innerHTML = `
    <div id="export-area">
      <div class="export-section">
        <h3>字幕样式</h3>
        <div class="subtitle-panel-body export-subtitle-grid">
          <div class="subtitle-field">
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
          <div class="subtitle-field">
            <label>字号比例</label>
            <div class="range-row">
              <input type="range" id="sub-font-size" min="0.04" max="0.16" step="0.01" value="${s.fontSizeRatio}">
              <span id="sub-font-size-val" class="range-value">${s.fontSizeRatio}</span>
            </div>
          </div>
          <div class="subtitle-field">
            <label>文本颜色</label>
            <div class="sub-color-row">
              <input type="color" id="sub-color" value="${s.color}">
              <span id="sub-color-val">${s.color}</span>
            </div>
          </div>
          <div class="subtitle-field">
            <label>描边颜色</label>
            <div class="sub-color-row">
              <input type="color" id="sub-stroke-color" value="${s.strokeColor}">
              <span id="sub-stroke-color-val">${s.strokeColor}</span>
            </div>
          </div>
          <div class="subtitle-field">
            <label>描边宽度</label>
            <input type="range" id="sub-stroke-width" min="0" max="0.12" step="0.01" value="${s.strokeWidth}">
          </div>
          <div class="subtitle-field">
            <label>重点词颜色</label>
            <div class="sub-color-row">
              <input type="color" id="sub-keyword-color" value="${s.keywordColor}">
              <span id="sub-keyword-color-val">${s.keywordColor}</span>
            </div>
          </div>
          <div class="subtitle-field">
            <label>垂直位置</label>
            <input type="range" id="sub-position-y" min="-0.9" max="-0.1" step="0.05" value="${s.positionY}">
          </div>
          <div class="subtitle-field">
            <label>每行最大字数</label>
            <div class="range-row">
              <input type="range" id="sub-max-chars" min="8" max="24" step="1" value="${s.maxChars}">
              <span id="sub-max-chars-val" class="range-value">${s.maxChars} 字</span>
            </div>
          </div>
        </div>
      </div>

      <div class="export-section">
        <h3>导出格式</h3>
        <div class="export-actions">
          <button id="btn-export-draft" class="btn-export-primary">剪映草稿 (.zip)</button>
          <button id="btn-export-srt" class="btn-export">SRT 字幕</button>
          <button id="btn-export-text" class="btn-export">剪辑清单</button>
        </div>
        <p class="export-hint">导出时会自动为每句选择最佳 take（A 级优先，跳过废片）</p>
      </div>
    </div>
  `;

  // Bind subtitle controls
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
    });
  });

  updateExportValueLabels();

  // Export buttons
  document.getElementById('btn-export-draft').addEventListener('click', () => exportProjectDraft());
  document.getElementById('btn-export-srt').addEventListener('click', () => exportProjectSrt());
  document.getElementById('btn-export-text').addEventListener('click', () => exportProjectText());
}

function updateExportValueLabels() {
  const s = subtitleSettings;
  const elColor = document.getElementById('sub-color-val');
  const elStroke = document.getElementById('sub-stroke-color-val');
  const elKw = document.getElementById('sub-keyword-color-val');
  const elChars = document.getElementById('sub-max-chars-val');
  const elSize = document.getElementById('sub-font-size-val');
  if (elColor) elColor.textContent = s.color;
  if (elStroke) elStroke.textContent = s.strokeColor;
  if (elKw) elKw.textContent = s.keywordColor;
  if (elChars) elChars.textContent = `${s.maxChars} 字`;
  if (elSize) elSize.textContent = s.fontSizeRatio;
}

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
