/* ====== AutoCut - 主逻辑 ====== */

const API = '/api';
const STATE = {
  taskId: null,
  status: 'idle',         // idle | uploading | processing | editing
  videoDuration: 0,

  sentences: [],          // [{index, text, takes, confirmed_take_index, is_unmatched}]
  unmatched: [],          // [{text, start, end, confidence}]
  currentSentence: 0,     // 当前选中的句子索引
  selectedTake: {},       // {sentenceIndex: takeIndex}
  currentTakeIndex: 0,    // 当前句子中高亮的版本索引

  confirmedCount: 0,
  totalCount: 0,

  // 预览模式
  previewActive: false,
};

/* ──── 字幕设置存储 ──── */
const SUBTITLE_DEFAULTS = {
  font: 'Source Han Sans SC',
  fontSizeRatio: 0.08,
  color: '#FFFFFF',
  strokeColor: '#000000',
  strokeWidth: 0.04,
  positionY: -0.75,
  keywordColor: '#FFD700',
  maxChars: 12,
};

function loadSubtitleSettings() {
  try {
    const saved = localStorage.getItem('autocut-subtitle');
    if (saved) return { ...SUBTITLE_DEFAULTS, ...JSON.parse(saved) };
  } catch (e) { /* ignore */ }
  return { ...SUBTITLE_DEFAULTS };
}

function saveSubtitleSettings(settings) {
  localStorage.setItem('autocut-subtitle', JSON.stringify(settings));
}

let subtitleSettings = loadSubtitleSettings();

/* ──── 主题切换 ──── */
function loadTheme() {
  const saved = localStorage.getItem('autocut-theme');
  return saved || 'dark';
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  const btn = document.getElementById('btn-theme');
  if (btn) btn.textContent = theme === 'light' ? '☀️' : '🌙';
  localStorage.setItem('autocut-theme', theme);
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme') || 'dark';
  applyTheme(current === 'dark' ? 'light' : 'dark');
}

/* ──── 初始化 ──── */
document.addEventListener('DOMContentLoaded', () => {
  applyTheme(loadTheme());
  setupUploadHandlers();
  setupEditorButtons();
  setupThemeToggle();
  setupSubtitlePanel();
  setupPreviewButton();
  setupPanelToggles();
  setupPreviewModal();
  updateUI();
});

/* ──── 主题切换按钮 ──── */
function setupThemeToggle() {
  document.getElementById('btn-theme').addEventListener('click', toggleTheme);
}

/* ──── 面板折叠 ──── */
function setupPanelToggles() {
  const scriptPanel = document.getElementById('script-panel');
  const takesPanel = document.getElementById('takes-panel');

  document.getElementById('toggle-script-panel').addEventListener('click', () => {
    scriptPanel.classList.toggle('collapsed');
    const btn = document.getElementById('toggle-script-panel');
    btn.textContent = scriptPanel.classList.contains('collapsed') ? '▶' : '◀';
    if (typeof drawTimeline === 'function') setTimeout(drawTimeline, 350);
  });

  document.getElementById('toggle-takes-panel').addEventListener('click', () => {
    takesPanel.classList.toggle('collapsed');
    const btn = document.getElementById('toggle-takes-panel');
    btn.textContent = takesPanel.classList.contains('collapsed') ? '◀' : '▶';
    if (typeof drawTimeline === 'function') setTimeout(drawTimeline, 350);
  });
}

/* ──── 字幕设置面板 ──── */
function setupSubtitlePanel() {
  const gearBtn = document.getElementById('btn-subtitle-settings');
  const panel = document.getElementById('subtitle-panel');
  const closeBtn = document.getElementById('btn-close-subtitle');

  gearBtn.addEventListener('click', () => {
    panel.classList.toggle('hidden');
    gearBtn.classList.toggle('active');
  });

  closeBtn.addEventListener('click', () => {
    panel.classList.add('hidden');
    gearBtn.classList.remove('active');
  });

  // 绑定每个控件到 localStorage
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

  // 初始化控件值
  bindings.forEach(({ id, key }) => {
    const el = document.getElementById(id);
    if (el) el.value = subtitleSettings[key];
  });
  updateSubtitleValueLabels();

  // 变更事件
  bindings.forEach(({ id, key, parse }) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('input', () => {
      let val = el.value;
      if (parse) val = parse(val);
      subtitleSettings[key] = val;
      saveSubtitleSettings(subtitleSettings);
      updateSubtitleValueLabels();
      if (typeof updateSubtitleCanvas === 'function') updateSubtitleCanvas();
    });
  });
}

function updateSubtitleValueLabels() {
  const s = subtitleSettings;
  const elColor = document.getElementById('sub-color-val');
  const elStroke = document.getElementById('sub-stroke-color-val');
  const elKw = document.getElementById('sub-keyword-color-val');
  const elChars = document.getElementById('sub-max-chars-val');
  if (elColor) elColor.textContent = s.color;
  if (elStroke) elStroke.textContent = s.strokeColor;
  if (elKw) elKw.textContent = s.keywordColor;
  if (elChars) elChars.textContent = `${s.maxChars} 字`;
}

/* ──── 预览成品 ──── */
function setupPreviewButton() {
  document.getElementById('btn-preview').addEventListener('click', startPreview);
}

function getConfirmedTakes() {
  return STATE.sentences
    .map((sent, i) => {
      const idx = sent.confirmed_take_index;
      if (idx >= 0 && idx < sent.takes.length) {
        return { sentence: sent, take: sent.takes[idx], sentenceIndex: i };
      }
      return null;
    })
    .filter(Boolean)
    .sort((a, b) => a.take.start - b.take.start);
}

function setupPreviewModal() {
  const modal = document.getElementById('preview-modal');
  const closeBtn = document.getElementById('btn-close-preview');
  const progressBar = document.getElementById('preview-progress');
  const video = document.getElementById('preview-video');

  closeBtn.addEventListener('click', stopPreview);

  // ESC 关闭预览
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && STATE.previewActive) {
      stopPreview();
    }
  });

  // 进度条点击 seek
  progressBar.addEventListener('click', (e) => {
    if (!STATE._previewData) return;
    const rect = progressBar.getBoundingClientRect();
    const ratio = (e.clientX - rect.left) / rect.width;
    const seekTime = ratio * STATE._previewData.totalDuration;
    video.currentTime = seekTime;
  });

  // 更新进度
  video.addEventListener('timeupdate', () => {
    if (!STATE.previewActive || !STATE._previewData) return;
    updatePreviewProgress();
    renderPreviewSubtitle();
  });
}

function startPreview() {
  const confirmed = getConfirmedTakes();
  if (confirmed.length === 0) {
    alert('请先确认至少一个片段（Enter 确认）');
    return;
  }

  STATE.previewActive = true;
  STATE._previewData = { confirmed, currentIndex: 0 };

  const modal = document.getElementById('preview-modal');
  const video = document.getElementById('preview-video');

  modal.classList.remove('hidden');
  video.src = `${API}/video/${STATE.taskId}`;

  // 等待视频加载后开始播放
  video.onloadedmetadata = () => {
    playNextPreviewClip();
  };

  // 如果已经加载过
  if (video.readyState >= 1) {
    playNextPreviewClip();
  }
}

function playNextPreviewClip() {
  const data = STATE._previewData;
  if (!data || data.currentIndex >= data.confirmed.length) {
    stopPreview();
    return;
  }

  const item = data.confirmed[data.currentIndex];
  const video = document.getElementById('preview-video');
  video.currentTime = item.take.start;
  video.play().catch(() => {});

  // 监听片段结束
  const checkEnd = () => {
    if (!STATE.previewActive) {
      video.removeEventListener('timeupdate', checkEnd);
      return;
    }
    if (video.currentTime >= item.take.end - 0.05) {
      data.currentIndex++;
      if (data.currentIndex >= data.confirmed.length) {
        video.removeEventListener('timeupdate', checkEnd);
        stopPreview();
        return;
      }
      // 播放下一个
      const next = data.confirmed[data.currentIndex];
      video.currentTime = next.take.start;
      video.play().catch(() => {});
    }
  };
  video.addEventListener('timeupdate', checkEnd);

  // 保存清理函数
  STATE._previewCheckEnd = checkEnd;

  updatePreviewProgress();
  renderPreviewSubtitle();
}

function stopPreview() {
  const video = document.getElementById('preview-video');
  video.pause();
  if (STATE._previewCheckEnd) {
    video.removeEventListener('timeupdate', STATE._previewCheckEnd);
    STATE._previewCheckEnd = null;
  }
  STATE.previewActive = false;
  STATE._previewData = null;
  document.getElementById('preview-modal').classList.add('hidden');

  // 清除预览 Canvas
  const pCanvas = document.getElementById('preview-subtitle-canvas');
  if (pCanvas) {
    const ctx = pCanvas.getContext('2d');
    ctx.clearRect(0, 0, pCanvas.width, pCanvas.height);
  }
}

function updatePreviewProgress() {
  const data = STATE._previewData;
  if (!data) return;

  const video = document.getElementById('preview-video');
  const totalDuration = data.confirmed.reduce((sum, item) => sum + (item.take.end - item.take.start), 0);

  // 计算当前已播放的总时长
  let elapsed = 0;
  for (let i = 0; i < data.confirmed.length; i++) {
    const item = data.confirmed[i];
    const dur = item.take.end - item.take.start;
    if (video.currentTime >= item.take.end) {
      elapsed += dur;
    } else if (video.currentTime >= item.take.start) {
      elapsed += video.currentTime - item.take.start;
      break;
    }
  }

  data.totalDuration = totalDuration;
  const pct = totalDuration > 0 ? Math.min(100, (elapsed / totalDuration) * 100) : 0;

  document.getElementById('preview-progress-fill').style.width = `${pct}%`;
  document.getElementById('preview-time').textContent =
    `${formatTime(elapsed)} / ${formatDuration(totalDuration)}`;
}

function renderPreviewSubtitle() {
  const data = STATE._previewData;
  if (!data) return;

  const video = document.getElementById('preview-video');
  const currentTime = video.currentTime;

  // 找到当前播放时间对应的 take
  const current = data.confirmed.find(item =>
    currentTime >= item.take.start && currentTime <= item.take.end
  );

  const canvas = document.getElementById('preview-subtitle-canvas');
  if (!canvas) return;

  const container = document.getElementById('preview-video-container');
  const rect = container.getBoundingClientRect();
  canvas.width = rect.width;
  canvas.height = rect.height;
  canvas.style.width = rect.width + 'px';
  canvas.style.height = rect.height + 'px';

  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  if (!current) return;

  const s = subtitleSettings;
  const fontSize = canvas.height * s.fontSizeRatio;
  const yPos = canvas.height * (1 + s.positionY);
  const text = current.take.text;

  const tokens = typeof getKeywordTokens === 'function'
    ? getKeywordTokens(text, s.keywordColor, s.keywordColor)
    : [{ word: text, isKeyword: false, type: null, color: null }];

  // 测量总宽度
  ctx.font = `${fontSize}px "${s.font}", "Microsoft YaHei", sans-serif`;
  let totalWidth = 0;
  const measured = tokens.map(t => {
    const isKw = t.isKeyword;
    ctx.font = `${fontSize}px ${isKw ? 'bold ' : ''}"${s.font}", "Microsoft YaHei", sans-serif`;
    const w = ctx.measureText(t.word).width;
    totalWidth += w;
    return { ...t, width: w };
  });

  // 从居中位置开始画
  let x = (canvas.width - totalWidth) / 2;

  for (const token of measured) {
    const isKw = token.isKeyword;
    ctx.font = `${fontSize}px ${isKw ? 'bold ' : ''}"${s.font}", "Microsoft YaHei", sans-serif`;

    // 描边
    ctx.strokeStyle = s.strokeColor;
    ctx.lineWidth = fontSize * s.strokeWidth * 3;
    ctx.lineJoin = 'round';
    ctx.strokeText(token.word, x, yPos);

    // 填充
    ctx.fillStyle = isKw ? (s.keywordColor) : s.color;
    ctx.fillText(token.word, x, yPos);

    x += token.width;
  }
}

/* ──── 上传逻辑 ──── */
function setupUploadHandlers() {
  const dropZone = document.getElementById('video-drop-zone');
  const videoInput = document.getElementById('video-input');
  const videoBrowse = document.getElementById('video-browse');
  const scriptInput = document.getElementById('script-input');
  const btnStart = document.getElementById('btn-start');

  // 拖拽上传
  dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
  dropZone.addEventListener('drop', e => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    const file = e.dataTransfer.files[0];
    if (file && file.type.startsWith('video/')) handleVideoFile(file);
  });
  dropZone.addEventListener('click', () => videoInput.click());
  videoBrowse.addEventListener('click', e => { e.preventDefault(); videoInput.click(); });
  videoInput.addEventListener('change', () => {
    if (videoInput.files[0]) handleVideoFile(videoInput.files[0]);
  });

  // 脚本统计
  scriptInput.addEventListener('input', () => {
    const count = scriptInput.value.trim().split('\n').filter(l => l.trim()).length;
    document.getElementById('script-line-count').textContent = `${count} 句`;
    checkStartReady();
  });

  btnStart.addEventListener('click', startProcessing);
}

function handleVideoFile(file) {
  const sizeMB = (file.size / 1024 / 1024).toFixed(1);
  document.getElementById('video-info').classList.remove('hidden');
  document.getElementById('video-name').textContent = file.name;
  document.getElementById('video-size').textContent = `${sizeMB} MB`;

  const url = URL.createObjectURL(file);
  const video = document.createElement('video');
  video.preload = 'metadata';
  video.onloadedmetadata = () => {
    const dur = video.duration;
    document.getElementById('video-duration').textContent = formatDuration(dur);
    URL.revokeObjectURL(url);
  };
  video.src = url;

  window._selectedVideoFile = file;
  checkStartReady();
}

function checkStartReady() {
  const hasVideo = !!window._selectedVideoFile;
  document.getElementById('btn-start').disabled = !hasVideo;

  const scriptText = document.getElementById('script-input').value.trim();
  const modeHint = document.getElementById('script-mode-hint');
  if (!scriptText && hasVideo) {
    modeHint.style.display = 'inline';
    document.getElementById('btn-start').textContent = '开始处理（智能聚类）';
  } else {
    modeHint.style.display = 'none';
    document.getElementById('btn-start').textContent = '开始处理';
  }
}

async function startProcessing() {
  const file = window._selectedVideoFile;
  const script = document.getElementById('script-input').value;

  if (!file) return;

  STATE.status = 'processing';
  updateUI();

  const formData = new FormData();
  formData.append('video', file);
  formData.append('script', script);

  document.getElementById('upload-status').innerHTML =
    '<span class="status-dot status-processing"></span>上传中，正在处理...';

  try {
    const resp = await fetch(`${API}/upload`, { method: 'POST', body: formData });
    const data = await resp.json();
    STATE.taskId = data.task_id;

    pollTaskStatus(data.task_id);
  } catch (err) {
    document.getElementById('upload-status').textContent = `错误: ${err.message}`;
    STATE.status = 'idle';
    updateUI();
  }
}

async function pollTaskStatus(taskId) {
  const poll = async () => {
    try {
      const resp = await fetch(`${API}/task/${taskId}`);
      const data = await resp.json();

      const statusEl = document.getElementById('upload-status');
      statusEl.innerHTML = `<span class="status-dot status-processing"></span>${getStatusText(data.status)}`;

      if (data.status === 'done') {
        STATE.status = 'editing';
        STATE.sentences = data.sentences || [];
        STATE.unmatched = data.unmatched || [];
        STATE.totalCount = data.total_count || STATE.sentences.length;
        STATE.confirmedCount = data.confirmed_count || 0;
        STATE.videoDuration = data.video_duration || 0;
        STATE.currentSentence = 0;
        STATE.currentTakeIndex = 0;

        const hasScript = document.getElementById('script-input').value.trim().length > 0;
        document.getElementById('script-mode-label').textContent =
          hasScript ? '脚本行（对齐模式）' : '检测到的内容（聚类模式）';

        const video = document.getElementById('video-player');
        video.src = `${API}/video/${taskId}`;

        updateUI();
        renderAll();
        initKeyboard();
        initPlayer();
        initEditorSubtitleCanvas();

        jumpToFirstAvailable();
      } else if (data.status === 'error') {
        statusEl.textContent = `处理失败: ${data.error_message || '未知错误'}`;
        STATE.status = 'idle';
        updateUI();
      } else {
        setTimeout(poll, 2000);
      }
    } catch (err) {
      setTimeout(poll, 2000);
    }
  };
  poll();
}

function getStatusText(status) {
  const map = {
    uploading: '上传中...',
    extracting_audio: '提取音频中...',
    asr_processing: '语音识别中...',
    aligning: '语义聚类中...',
    analyzing: '分析质量中...',
    done: '处理完成！',
  };
  return map[status] || status;
}

/* ──── Canvas 字幕叠加（编辑模式） ──── */
function initEditorSubtitleCanvas() {
  const video = document.getElementById('video-player');
  video.addEventListener('timeupdate', updateEditorSubtitle);
  video.addEventListener('seeked', updateEditorSubtitle);
  video.addEventListener('pause', updateEditorSubtitle);
  video.addEventListener('play', updateEditorSubtitle);

  // 窗口 resize 时重设 canvas 尺寸
  window.addEventListener('resize', () => {
    if (STATE.status === 'editing') updateEditorSubtitle();
  });
}

function updateEditorSubtitle() {
  const canvas = document.getElementById('subtitle-canvas');
  const video = document.getElementById('video-player');
  if (!canvas || !video || video.readyState < 1) return;

  const videoRect = video.getBoundingClientRect();
  const parentRect = video.parentElement.getBoundingClientRect();

  canvas.width = videoRect.width;
  canvas.height = videoRect.height;
  canvas.style.width = videoRect.width + 'px';
  canvas.style.height = videoRect.height + 'px';
  canvas.style.left = (videoRect.left - parentRect.left) + 'px';
  canvas.style.top = (videoRect.top - parentRect.top) + 'px';

  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const currentTime = video.currentTime;

  // 找到当前播放时间对应的 take
  let currentTake = null;
  for (const sent of STATE.sentences) {
    for (const take of sent.takes) {
      if (currentTime >= take.start && currentTime <= take.end + 0.3) {
        currentTake = take;
        break;
      }
    }
    if (currentTake) break;
  }

  if (!currentTake) return;

  const s = subtitleSettings;
  const fontSize = Math.max(14, canvas.height * s.fontSizeRatio);
  const yPos = canvas.height * (1 + s.positionY);
  const text = currentTake.text;

  const tokens = typeof getKeywordTokens === 'function'
    ? getKeywordTokens(text, s.keywordColor, s.keywordColor)
    : [{ word: text, isKeyword: false, type: null, color: null }];

  // 测量总宽度
  const fontFamily = `"${s.font}", "Microsoft YaHei", "PingFang SC", sans-serif`;
  ctx.font = `${fontSize}px ${fontFamily}`;
  let totalWidth = 0;
  const measured = tokens.map(t => {
    ctx.font = `${fontSize}px ${t.isKeyword ? 'bold ' : ''}${fontFamily}`;
    const w = ctx.measureText(t.word).width;
    totalWidth += w;
    return { ...t, width: w };
  });

  let x = Math.max(20, (canvas.width - totalWidth) / 2);

  for (const token of measured) {
    ctx.font = `${fontSize}px ${token.isKeyword ? 'bold ' : ''}${fontFamily}`;

    ctx.strokeStyle = s.strokeColor;
    ctx.lineWidth = fontSize * s.strokeWidth * 3;
    ctx.lineJoin = 'round';
    ctx.strokeText(token.word, x, yPos);

    ctx.fillStyle = token.isKeyword ? s.keywordColor : s.color;
    ctx.fillText(token.word, x, yPos);

    x += token.width;
  }
}

/* ──── 编辑器按钮 ──── */
function setupEditorButtons() {
  document.getElementById('btn-play').addEventListener('click', () => togglePlay());
  document.getElementById('btn-confirm').addEventListener('click', () => confirmCurrent());
  document.getElementById('btn-reject').addEventListener('click', () => rejectCurrent());
  document.getElementById('btn-auto-confirm').addEventListener('click', () => autoConfirmAll());
  document.getElementById('btn-export').addEventListener('click', () => exportDraft());
}

/* ──── 渲染 ──── */
function renderAll() {
  renderScriptList();
  renderTakesList();
  renderTimeline();
  renderUnmatched();
  updateProgress();
  updateCurrentSentenceLabel();
  updateEditorSubtitle();
}

function renderScriptList() {
  const list = document.getElementById('script-list');
  if (!STATE.sentences.length) {
    list.innerHTML = '<div style="padding:16px;color:var(--text-dim);font-size:13px">无脚本或聚类结果，请在右侧查看未匹配片段</div>';
    return;
  }
  list.innerHTML = STATE.sentences.map((s, i) => {
    const grade = s.confirmed_take_index >= 0
      ? s.takes[s.confirmed_take_index]?.grade || ''
      : '';
    const cls = [
      'script-item',
      i === STATE.currentSentence ? 'current' : '',
      s.confirmed_take_index >= 0 ? 'confirmed' : '',
      s.takes.length === 0 ? 'no-takes' : ''
    ].join(' ');
    const gradeColor = gradeToCSS(grade);
    const dot = grade ? `<span class="script-gradedot" style="background:${gradeColor}"></span>` : '';
    const noTakesIcon = s.takes.length === 0 ? ' ⚠' : '';
    return `<div class="${cls}" data-index="${i}" onclick="selectSentence(${i})">
      ${dot}${truncate(s.text, 20)}${noTakesIcon}
    </div>`;
  }).join('');
}

function renderTakesList() {
  const sent = STATE.sentences[STATE.currentSentence];
  if (!sent) return;

  const list = document.getElementById('takes-list');

  if (!sent.takes.length) {
    const isScriptless = STATE.sentences.length > 0 && STATE.sentences.every(s => s.takes.length === 0);
    if (isScriptless) {
      list.innerHTML = '<div style="padding:16px;color:var(--text-dim)">未检测到有效语音片段<br><small>视频可能没有声音，或语音内容过短</small></div>';
    } else {
      list.innerHTML = '<div style="padding:16px;color:var(--text-dim)">⚠ 录音中未找到对应片段<br><small>此句脚本在录音中可能没有讲到</small></div>';
    }
    return;
  }

  list.innerHTML = sent.takes.map((t, i) => {
    const gradeCls = t.is_abandoned ? 'abandoned'
      : (sent.confirmed_take_index === i ? 'confirmed'
      : (i === STATE.currentTakeIndex ? 'active' : ''));
    const gradeIcon = gradeToIcon(t.grade);

    const tagsHtml = (t.tags || []).map(tag =>
      `<span class="tag tag-${tag.severity}">${tag.label}</span>`
    ).join('');

    const gradeBadgeCls = t.grade ? `grade-${t.grade === '废' ? 'W' : t.grade}` : '';

    return `<div class="take-item ${gradeCls}" data-index="${i}"
         onclick="selectTake(${i})" ondblclick="confirmCurrent()">
      <span class="take-grade-icon">${gradeIcon}</span>
      <span>第${i+1}遍 ${formatTime(t.start)}-${formatTime(t.end)}</span>
      <span class="take-meta">
        <span>${formatDuration(t.duration)}</span>
        <span>置信${(t.confidence*100).toFixed(0)}%</span>
        ${t.grade ? `<span class="grade-badge ${gradeBadgeCls}">${t.grade}级</span>` : ''}
      </span>
      <span class="take-tags">${tagsHtml}
        ${t.is_abandoned ? '<span class="tag tag-error">废片</span>' : ''}
        ${t.abandon_reason ? `<span class="tag tag-warning">${t.abandon_reason}</span>` : ''}
      </span>
    </div>`;
  }).join('');

  updateTakeInfo();
}

function renderTimeline() {
  if (typeof drawTimeline === 'function') {
    drawTimeline();
  }
}

function renderUnmatched() {
  const panel = document.getElementById('unmatched-panel');
  const list = document.getElementById('unmatched-list');

  if (!STATE.unmatched.length) {
    panel.classList.add('hidden');
    return;
  }

  panel.classList.remove('hidden');
  list.innerHTML = STATE.unmatched.map(u =>
    `<div class="unmatched-item" onclick="seekTo(${u.start})">
      [${formatTime(u.start)}] ${truncate(u.text, 30)}
    </div>`
  ).join('');
}

function updateCurrentSentenceLabel() {
  const sent = STATE.sentences[STATE.currentSentence];
  const el = document.getElementById('current-sentence-label');
  if (sent) {
    el.textContent = `S${sent.index+1} "${truncate(sent.text, 30)}"`;
  }
}

function updateTakeInfo() {
  const sent = STATE.sentences[STATE.currentSentence];
  if (!sent || !sent.takes.length) return;
  const t = sent.takes[STATE.currentTakeIndex] || sent.takes[0];

  const gradeEl = document.getElementById('take-grade');
  if (t.grade) {
    const gradeCls = `grade-${t.grade === '废' ? 'W' : t.grade}`;
    gradeEl.innerHTML = `<span class="grade-badge ${gradeCls}">${t.grade}级</span>`;
  } else {
    gradeEl.textContent = '';
  }
  document.getElementById('take-time').textContent = formatTime(t.start);
  document.getElementById('take-duration').textContent = formatDuration(t.duration);
  document.getElementById('take-tags').textContent = (t.tags || []).map(tg => tg.label).join(' ');
}

function updateProgress() {
  const count = STATE.sentences.filter(s => s.confirmed_take_index >= 0).length;
  STATE.confirmedCount = count;
  document.getElementById('progress-text').textContent =
    `已确认 ${count} / ${STATE.totalCount}`;

  document.getElementById('btn-export').disabled = STATE.status !== 'editing';
  document.getElementById('btn-auto-confirm').disabled = STATE.status !== 'editing';
}

/* ──── 导航操作 ──── */
function selectSentence(index) {
  if (index < 0 || index >= STATE.sentences.length) return;
  STATE.currentSentence = index;

  const sent = STATE.sentences[index];
  if (sent.confirmed_take_index >= 0) {
    STATE.currentTakeIndex = sent.confirmed_take_index;
  } else {
    const best = findBestTakeIndex(sent);
    STATE.currentTakeIndex = best >= 0 ? best : 0;
  }

  renderAll();
  if (sent.takes.length > 0) seekToCurrentTake();
}

function selectTake(index) {
  const sent = STATE.sentences[STATE.currentSentence];
  if (!sent || index < 0 || index >= sent.takes.length) return;
  STATE.currentTakeIndex = index;
  renderTakesList();
  updateTakeInfo();
  updateEditorSubtitle();
  seekToCurrentTake();
}

function findBestTakeIndex(sent) {
  if (!sent.takes.length) return -1;
  for (const grade of ['A', 'B', 'C']) {
    const idx = sent.takes.findIndex(t => t.grade === grade && !t.is_abandoned);
    if (idx >= 0) return idx;
  }
  const idx = sent.takes.findIndex(t => !t.is_abandoned);
  if (idx >= 0) return idx;
  return 0;
}

function jumpToFirstAvailable() {
  for (let i = 0; i < STATE.sentences.length; i++) {
    if (STATE.sentences[i].takes.length > 0) {
      selectSentence(i);
      return;
    }
  }
  if (STATE.sentences.length > 0) {
    selectSentence(0);
  }
}

/* ──── 确认/拒掉操作 ──── */
async function confirmCurrent() {
  const sent = STATE.sentences[STATE.currentSentence];
  if (!sent) return;
  const takeIdx = STATE.currentTakeIndex;
  if (takeIdx < 0 || takeIdx >= sent.takes.length) return;

  try {
    await fetch(
      `${API}/task/${STATE.taskId}/confirm/${STATE.currentSentence}/${takeIdx}`,
      { method: 'PUT' }
    );
  } catch (e) { /* 忽略 */ }

  sent.confirmed_take_index = takeIdx;
  updateProgress();

  // 确认动画
  flashTakeItem(takeIdx, 'confirm-flash');

  const next = STATE.currentSentence + 1;
  if (next < STATE.sentences.length) {
    selectSentence(next);
  } else {
    renderAll();
  }
}

async function rejectCurrent() {
  const sent = STATE.sentences[STATE.currentSentence];
  if (!sent) return;
  const takeIdx = STATE.currentTakeIndex;

  try {
    await fetch(
      `${API}/task/${STATE.taskId}/reject/${STATE.currentSentence}/${takeIdx}`,
      { method: 'PUT' }
    );
  } catch (e) {}

  sent.takes[takeIdx].is_abandoned = true;
  sent.takes[takeIdx].grade = '废';

  // 拒掉动画
  flashTakeItem(takeIdx, 'reject-flash');

  const next = sent.takes.findIndex((t, i) => i > takeIdx && !t.is_abandoned);
  if (next >= 0) {
    STATE.currentTakeIndex = next;
    renderTakesList();
    updateEditorSubtitle();
    seekToCurrentTake();
  }
}

function flashTakeItem(index, className) {
  const list = document.getElementById('takes-list');
  if (!list) return;
  const items = list.querySelectorAll('.take-item');
  const item = items[index];
  if (!item) return;
  item.classList.add(className);
  item.addEventListener('animationend', () => item.classList.remove(className), { once: true });
}

async function autoConfirmAll() {
  for (let i = 0; i < STATE.sentences.length; i++) {
    const sent = STATE.sentences[i];
    if (sent.confirmed_take_index >= 0) continue;
    if (!sent.takes.length) continue;

    const best = findBestTakeIndex(sent);
    if (best >= 0) {
      sent.confirmed_take_index = best;
      try {
        await fetch(
          `${API}/task/${STATE.taskId}/confirm/${i}/${best}`,
          { method: 'PUT' }
        );
      } catch (e) {}
    }
  }
  updateProgress();
  renderScriptList();
  renderTakesList();
}

/* ──── 导出 ──── */
async function exportDraft() {
  if (!STATE.taskId) return;
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
  window.open(`${API}/export/${STATE.taskId}/draft?${params}`, '_blank');
}

function seekToCurrentTake() {
  const sent = STATE.sentences[STATE.currentSentence];
  if (!sent || !sent.takes.length) return;
  const t = sent.takes[STATE.currentTakeIndex];
  if (t) seekTo(t.start);
}

/* ──── UI 状态 ──── */
function updateUI() {
  const uploadArea = document.getElementById('upload-area');
  const editorArea = document.getElementById('editor-area');
  const gearBtn = document.getElementById('btn-subtitle-settings');
  const previewBtn = document.getElementById('btn-preview');

  if (STATE.status === 'editing') {
    uploadArea.classList.add('hidden');
    editorArea.classList.remove('hidden');
    if (gearBtn) gearBtn.style.display = '';
    if (previewBtn) previewBtn.style.display = '';
  } else {
    uploadArea.classList.remove('hidden');
    editorArea.classList.add('hidden');
    if (gearBtn) gearBtn.style.display = 'none';
    if (previewBtn) previewBtn.style.display = 'none';
  }
}

/* ──── 工具函数 ──── */
function formatTime(seconds) {
  if (isNaN(seconds) || seconds < 0) return '00:00.0';
  const m = Math.floor(seconds / 60);
  const s = (seconds % 60).toFixed(1);
  return `${m.toString().padStart(2, '0')}:${s.padStart(4, '0')}`;
}

function formatDuration(seconds) {
  if (!seconds || isNaN(seconds)) return '0s';
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = (seconds % 60).toFixed(0);
  return `${m}m${s}s`;
}

function truncate(text, maxLen) {
  if (!text) return '';
  return text.length > maxLen ? text.substring(0, maxLen) + '...' : text;
}

function gradeToIcon(grade) {
  const icons = { A: '🟢', B: '🟡', C: '🟠', D: '🔴', '废': '💀' };
  return icons[grade] || '⬜';
}

function gradeToCSS(grade) {
  const colors = { A: '#2ecc71', B: '#f1c40f', C: '#f39c12', D: '#e74c3c', '废': '#6b7280' };
  return colors[grade] || '#888';
}
