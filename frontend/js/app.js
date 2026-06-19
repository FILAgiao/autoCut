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
};

/* ──── 初始化 ──── */
document.addEventListener('DOMContentLoaded', () => {
  setupUploadHandlers();
  setupEditorButtons();
  updateUI();
});

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

  // 尝试获取视频时长
  const url = URL.createObjectURL(file);
  const video = document.createElement('video');
  video.preload = 'metadata';
  video.onloadedmetadata = () => {
    const dur = video.duration;
    document.getElementById('video-duration').textContent = formatDuration(dur);
    URL.revokeObjectURL(url);
  };
  video.src = url;

  // 存到全局
  window._selectedVideoFile = file;
  checkStartReady();
}

function checkStartReady() {
  const hasVideo = !!window._selectedVideoFile;
  const hasScript = document.getElementById('script-input').value.trim().length > 0;
  document.getElementById('btn-start').disabled = !(hasVideo && hasScript);
}

async function startProcessing() {
  const file = window._selectedVideoFile;
  const script = document.getElementById('script-input').value;

  if (!file || !script) return;

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

    // 轮询等待处理完成
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
        // 加载结果
        STATE.status = 'editing';
        STATE.sentences = data.sentences;
        STATE.unmatched = data.unmatched;
        STATE.totalCount = data.total_count;
        STATE.confirmedCount = data.confirmed_count;
        STATE.videoDuration = data.video_duration;
        STATE.currentSentence = 0;
        STATE.currentTakeIndex = 0;

        // 设置视频源
        const video = document.getElementById('video-player');
        video.src = `${API}/video/${taskId}`;

        // 切换到编辑视图
        updateUI();
        renderAll();
        initKeyboard();
        initPlayer();

        // 自动跳到第一个有版本的句子
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
    aligning: '语义对齐中...',
    analyzing: '分析质量中...',
    done: '处理完成！',
  };
  return map[status] || status;
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
}

function renderScriptList() {
  const list = document.getElementById('script-list');
  list.innerHTML = STATE.sentences.map((s, i) => {
    const grade = s.confirmed_take_index >= 0
      ? s.takes[s.confirmed_take_index]?.grade || ''
      : '';
    const cls = [
      'script-item',
      i === STATE.currentSentence ? 'current' : '',
      s.confirmed_take_index >= 0 ? 'confirmed' : ''
    ].join(' ');
    const gradeColor = gradeToCSS(grade);
    const dot = grade ? `<span class="script-gradedot" style="background:${gradeColor}"></span>` : '';
    return `<div class="${cls}" data-index="${i}" onclick="selectSentence(${i})">
      ${dot}${truncate(s.text, 20)}
    </div>`;
  }).join('');
}

function renderTakesList() {
  const sent = STATE.sentences[STATE.currentSentence];
  if (!sent) return;

  const list = document.getElementById('takes-list');

  if (!sent.takes.length) {
    list.innerHTML = '<div style="padding:16px;color:var(--text-dim)">⚠ 录音中未找到对应片段</div>';
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

    return `<div class="take-item ${gradeCls}" data-index="${i}"
         onclick="selectTake(${i})" ondblclick="confirmCurrent()">
      <span class="take-grade">${gradeIcon}</span>
      <span>第${i+1}遍 ${formatTime(t.start)}-${formatTime(t.end)}</span>
      <span class="take-meta">
        <span>${formatDuration(t.duration)}</span>
        <span>置信${(t.confidence*100).toFixed(0)}%</span>
        ${t.grade ? `<span style="color:${gradeToCSS(t.grade)}">${t.grade}级</span>` : ''}
      </span>
      <span class="take-tags">${tagsHtml}
        ${t.is_abandoned ? '<span class="tag tag-error">废片</span>' : ''}
        ${t.abandon_reason ? `<span class="tag tag-warning">${t.abandon_reason}</span>` : ''}
      </span>
    </div>`;
  }).join('');

  // 更新播放按钮
  updateTakeInfo();
}

function renderTimeline() {
  // 在 timeline.js 中实现
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

  document.getElementById('take-grade').textContent = t.grade ? `${t.grade}级` : '';
  document.getElementById('take-time').textContent = formatTime(t.start);
  document.getElementById('take-duration').textContent = formatDuration(t.duration);
  document.getElementById('take-tags').textContent = (t.tags || []).map(tg => tg.label).join(' ');
}

function updateProgress() {
  const count = STATE.sentences.filter(s => s.confirmed_take_index >= 0).length;
  STATE.confirmedCount = count;
  document.getElementById('progress-text').textContent =
    `已确认 ${count} / ${STATE.totalCount}`;

  document.getElementById('btn-export').disabled = count === 0;
  document.getElementById('btn-auto-confirm').disabled = STATE.status !== 'editing';
}

/* ──── 导航操作 ──── */
function selectSentence(index) {
  if (index < 0 || index >= STATE.sentences.length) return;
  STATE.currentSentence = index;

  // 重置当前版本为已确认的版本或推荐版本
  const sent = STATE.sentences[index];
  if (sent.confirmed_take_index >= 0) {
    STATE.currentTakeIndex = sent.confirmed_take_index;
  } else {
    STATE.currentTakeIndex = findBestTakeIndex(sent);
  }

  renderAll();
  seekToCurrentTake();
}

function selectTake(index) {
  const sent = STATE.sentences[STATE.currentSentence];
  if (!sent || index < 0 || index >= sent.takes.length) return;
  STATE.currentTakeIndex = index;
  renderTakesList();
  updateTakeInfo();
  seekToCurrentTake();
}

function findBestTakeIndex(sent) {
  if (!sent.takes.length) return 0;
  // 优先选 A 级的，其次 B，最后第一个非废片
  for (const grade of ['A', 'B', 'C']) {
    const idx = sent.takes.findIndex(t => t.grade === grade && !t.is_abandoned);
    if (idx >= 0) return idx;
  }
  // 返回第一个非废片
  const idx = sent.takes.findIndex(t => !t.is_abandoned);
  return idx >= 0 ? idx : 0;
}

function jumpToFirstAvailable() {
  for (let i = 0; i < STATE.sentences.length; i++) {
    if (STATE.sentences[i].takes.length > 0) {
      selectSentence(i);
      return;
    }
  }
}

/* ──── 确认/拒掉操作 ──── */
async function confirmCurrent() {
  const sent = STATE.sentences[STATE.currentSentence];
  if (!sent) return;
  const takeIdx = STATE.currentTakeIndex;
  if (takeIdx < 0 || takeIdx >= sent.takes.length) return;

  // 调用 API
  try {
    await fetch(
      `${API}/task/${STATE.taskId}/confirm/${STATE.currentSentence}/${takeIdx}`,
      { method: 'PUT' }
    );
  } catch (e) { /* 忽略，本地状态为主 */ }

  sent.confirmed_take_index = takeIdx;
  updateProgress();

  // 自动跳到下一句
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

  // 跳到下一个非废片版本
  const next = sent.takes.findIndex((t, i) => i > takeIdx && !t.is_abandoned);
  if (next >= 0) {
    STATE.currentTakeIndex = next;
    renderTakesList();
    seekToCurrentTake();
  }
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
  window.open(`${API}/export/${STATE.taskId}/draft`, '_blank');
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

  if (STATE.status === 'editing') {
    uploadArea.classList.add('hidden');
    editorArea.classList.remove('hidden');
  } else {
    uploadArea.classList.remove('hidden');
    editorArea.classList.add('hidden');
  }
}

/* ──── 工具函数 ──── */
function formatTime(seconds) {
  const m = Math.floor(seconds / 60);
  const s = (seconds % 60).toFixed(1);
  return `${m.toString().padStart(2, '0')}:${s.padStart(4, '0')}`;
}

function formatDuration(seconds) {
  if (!seconds) return '0s';
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
  return icons[grade] || '';
}

function gradeToCSS(grade) {
  const colors = { A: '#2ecc71', B: '#f1c40f', C: '#f39c12', D: '#e74c3c', '废': '#95a5a6' };
  return colors[grade] || '#888';
}
