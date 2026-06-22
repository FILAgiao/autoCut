/* ====== AutoCut - 核心 + 路由 ====== */

const API = '/api';
const STATE = {
  taskId: null,
  projectId: null,
  status: 'idle',
  videoDuration: 0,

  sentences: [],
  unmatched: [],
  currentSentence: 0,
  selectedTake: {},
  currentTakeIndex: 0,

  confirmedCount: 0,
  totalCount: 0,

  previewActive: false,
  takeSortMode: 'grade',  // 'grade' = 按评级排序, 'time' = 按时间排序
};

/* ──── 字幕设置存储 ──── */
const SUBTITLE_DEFAULTS = {
  font: 'Source Han Sans SC',
  fontSizeRatio: 0.08,
  color: '#FFFFFF',
  strokeColor: '#000000',
  strokeWidth: 0.04,
  positionY: -0.75,
  keywordColor: '#FFD700',       // 导出时的关键词颜色
  reviewKeywordColor: '#FFD700', // 审阅时的关键词颜色（独立设置）
  maxChars: 12,
  showDuringReview: true,        // 审阅时显示字幕
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

/* ──── 关键词覆盖（全局共享） ──── */
window._keywordOverrides = {};

(function loadKeywordOverrides() {
  try {
    const saved = localStorage.getItem('autocut-keyword-overrides');
    if (saved) window._keywordOverrides = JSON.parse(saved);
  } catch (e) {}
})();

function saveKeywordOverridesGlobal() {
  try {
    localStorage.setItem('autocut-keyword-overrides', JSON.stringify(window._keywordOverrides));
  } catch (e) {}
}

/* ──── 主题切换 ──── */
function loadTheme() {
  return localStorage.getItem('autocut-theme') || 'dark';
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('autocut-theme', theme);
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme') || 'dark';
  applyTheme(current === 'dark' ? 'light' : 'dark');
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

function formatFileSize(bytes) {
  if (!bytes || bytes < 0) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function truncate(text, maxLen) {
  if (!text) return '';
  return text.length > maxLen ? text.substring(0, maxLen) + '...' : text;
}

function gradeToIcon(grade) {
  const icons = { A: 'A', B: 'B', C: 'C', D: 'D', '废': '&#10005;' };
  return icons[grade] || '?';
}

function gradeToCSS(grade) {
  const colors = { A: '#2ecc71', B: '#f1c40f', C: '#f39c12', D: '#e74c3c', '废': '#6b7280' };
  return colors[grade] || '#888';
}

/* ──── 路由 ──── */
function initRouter() {
  applyTheme(loadTheme());
  handleRoute();
  window.addEventListener('hashchange', handleRoute);
}

function handleRoute() {
  const hash = window.location.hash || '#/';
  const projectMatch = hash.match(/^#\/project\/([a-f0-9]+)(\/export)?$/);

  if (projectMatch) {
    renderProject(projectMatch[1]);
  } else {
    renderHome();
  }
}

/* ──── 渲染函数（被 editor.js 调用） ──── */
function renderAll() {
  console.log('[renderAll] sentences:', STATE.sentences.length, 'currentSentence:', STATE.currentSentence, 'currentTakeIndex:', STATE.currentTakeIndex);
  renderScriptList();
  renderTakesList();
  renderTimeline();
  renderUnmatched();
  updateEditorProgress();
  updateCurrentSentenceLabel();
  updateEditorSubtitle();
}

function renderScriptList() {
  const list = document.getElementById('script-list');
  if (!list) return;
  if (!STATE.sentences.length) {
    list.innerHTML = '<div style="padding:16px;color:var(--text-dim);font-size:13px;">无脚本数据，请在右侧查看未匹配片段</div>';
    return;
  }
  const matchedCount = STATE.sentences.filter(s => s.takes.length > 0).length;
  const totalCount = STATE.sentences.length;
  const label = document.getElementById('script-mode-label');
  if (label) {
    label.innerHTML = `脚本行 <span class="script-match-count">${matchedCount}/${totalCount} 已录制</span>`;
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
    const noTakesBadge = s.takes.length === 0 ? '<span class="no-takes-badge">未录制</span>' : '';
    return `<div class="${cls}" data-index="${i}" onclick="selectSentence(${i})">
      ${dot}${escapeHtml(s.text)}${noTakesBadge}
    </div>`;
  }).join('');
}

function renderTakesList() {
  const sent = STATE.sentences[STATE.currentSentence];
  if (!sent) return;

  const list = document.getElementById('takes-list');
  if (!list) return;

  console.log('[renderTakesList] sentence:', STATE.currentSentence, 'takes:', sent.takes.length,
    'confirmed:', sent.confirmed_take_index,
    'currentTakeIndex:', STATE.currentTakeIndex,
    'abandoned:', sent.takes.map(t => t.is_abandoned));

  if (!sent.takes.length) {
    list.innerHTML = '<div style="padding:16px;color:var(--text-dim);font-size:13px;">未找到对应片段</div>';
    return;
  }

  // Sort takes according to current sort mode
  const _gradeOrder = { 'A': 0, 'B': 1, 'C': 2, 'D': 3, '废': 4, '': 5 };
  let sorted = [...sent.takes];
  let indexMap = {}; // sortedIndex → originalIndex
  if (STATE.takeSortMode === 'time') {
    sorted.sort((a, b) => a.start - b.start);
  } else {
    // grade mode: A > B > C > D > 废, abandoned at bottom
    sorted.sort((a, b) => {
      const abandonDiff = (a.is_abandoned ? 1 : 0) - (b.is_abandoned ? 1 : 0);
      if (abandonDiff !== 0) return abandonDiff;
      const gradeDiff = (_gradeOrder[a.grade] || 5) - (_gradeOrder[b.grade] || 5);
      if (gradeDiff !== 0) return gradeDiff;
      return (b.grade_score || 0) - (a.grade_score || 0);
    });
  }
  // Build map: for each sorted position, what was the original index in sent.takes
  sorted.forEach((t, si) => {
    const origIdx = sent.takes.findIndex(ot =>
      ot.start === t.start && ot.text === t.text && ot.index === t.index
    );
    indexMap[si] = origIdx >= 0 ? origIdx : si;
  });

  // Find sorted index of currentTakeIndex
  const currentOrigIdx = STATE.currentTakeIndex;
  let currentSortedIdx = 0;
  for (let si = 0; si < sorted.length; si++) {
    if (indexMap[si] === currentOrigIdx) { currentSortedIdx = si; break; }
  }

  list.innerHTML = sorted.map((t, si) => {
    const origIdx = indexMap[si];
    const gradeCls = [
      si === currentSortedIdx ? 'active' : '',
      sent.confirmed_take_index === origIdx ? 'confirmed' : '',
      t.is_abandoned ? 'abandoned' : '',
    ].filter(Boolean).join(' ');
    const gradeIcon = gradeToIcon(t.grade);
    const tagsHtml = (t.tags || []).map(tag =>
      `<span class="tag tag-${tag.severity}">${tag.label}</span>`
    ).join('');
    const gradeBadgeCls = t.grade ? `grade-${t.grade === '废' ? 'W' : t.grade}` : '';

    return `<div class="take-item ${gradeCls}" data-index="${si}" data-orig="${origIdx}"
         onclick="selectTake(${origIdx})" ondblclick="editorConfirm()">
      <span class="take-grade-icon">${gradeIcon}</span>
      <span>第${origIdx+1}遍 ${formatTime(t.start)}-${formatTime(t.end)}</span>
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
  if (!panel || !list) return;

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
  if (sent && el) {
    el.textContent = `S${sent.index+1} "${truncate(sent.text, 30)}"`;
  }
}

function updateTakeInfo() {
  const sent = STATE.sentences[STATE.currentSentence];
  if (!sent || !sent.takes.length) return;
  const t = sent.takes[STATE.currentTakeIndex] || sent.takes[0];

  const gradeEl = document.getElementById('take-grade');
  if (gradeEl && t.grade) {
    const gradeCls = `grade-${t.grade === '废' ? 'W' : t.grade}`;
    gradeEl.innerHTML = `<span class="grade-badge ${gradeCls}">${t.grade}级</span>`;
  } else if (gradeEl) {
    gradeEl.textContent = '';
  }
  const timeEl = document.getElementById('take-time');
  if (timeEl) timeEl.textContent = formatTime(t.start);
  const durEl = document.getElementById('take-duration');
  if (durEl) durEl.textContent = formatDuration(t.duration);
  const tagsEl = document.getElementById('take-tags');
  if (tagsEl) tagsEl.textContent = (t.tags || []).map(tg => tg.label).join(' ');
}

/* ──── 导航操作 ──── */
function selectSentence(index) {
  console.log('[selectSentence] index:', index, 'total sentences:', STATE.sentences.length);
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
  if (sent.takes.length > 0) {
    // 片段循环播放：只在当前 take 的时间范围内循环
    const t = sent.takes[STATE.currentTakeIndex];
    if (t && typeof playSegment === 'function') {
      playSegment(t.start, t.end);
    }
  }
}

function selectTake(index) {
  console.log('[selectTake] index:', index, 'currentSentence:', STATE.currentSentence);
  const sent = STATE.sentences[STATE.currentSentence];
  if (!sent || index < 0 || index >= sent.takes.length) return;
  STATE.currentTakeIndex = index;
  renderTakesList();
  updateTakeInfo();
  updateEditorSubtitle();
  if (typeof updateKeywordEditor === 'function') updateKeywordEditor();
  // 片段循环播放：只在当前 take 的时间范围内循环
  const t = sent.takes[index];
  if (t && typeof playSegment === 'function') {
    playSegment(t.start, t.end);
  }
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
  console.log('[jumpToFirstAvailable] sentences:', STATE.sentences.length);
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

function seekToCurrentTake() {
  const sent = STATE.sentences[STATE.currentSentence];
  if (!sent || !sent.takes.length) return;
  const t = sent.takes[STATE.currentTakeIndex];
  console.log('[seekToCurrentTake] sentence:', STATE.currentSentence, 'takeIndex:', STATE.currentTakeIndex, 'start:', t ? t.start : 'N/A');
  if (t) seekTo(t.start);
}

function flashTakeItem(index, className) {
  console.log('[flashTakeItem] index:', index, 'className:', className);
  const list = document.getElementById('takes-list');
  if (!list) return;
  const items = list.querySelectorAll('.take-item');
  const item = items[index];
  if (!item) {
    console.warn('[flashTakeItem] item not found at index:', index, 'total items:', items.length);
    return;
  }
  item.classList.add(className);
  item.addEventListener('animationend', () => item.classList.remove(className), { once: true });
}

/* ──── Canvas 字幕叠加（编辑模式） ──── */
function initEditorSubtitleCanvas() {
  const video = document.getElementById('video-player');
  console.log('[initEditorSubtitleCanvas] video element:', !!video);
  if (!video) return;
  video.addEventListener('timeupdate', updateEditorSubtitle);
  video.addEventListener('seeked', updateEditorSubtitle);
  video.addEventListener('pause', updateEditorSubtitle);
  video.addEventListener('play', updateEditorSubtitle);
  window.addEventListener('resize', () => {
    if (STATE.status === 'editing') updateEditorSubtitle();
  });
}

function updateEditorSubtitle() {
  // 审阅模式下不显示字幕
  if (!subtitleSettings.showDuringReview) {
    const canvas = document.getElementById('subtitle-canvas');
    if (canvas) {
      const ctx = canvas.getContext('2d');
      if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
    return;
  }

  const canvas = document.getElementById('subtitle-canvas');
  const video = document.getElementById('video-player');
  if (!canvas || !video) return;
  if (video.readyState < 1) {
    // Video not loaded yet; called too early, skip silently
    return;
  }

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

  const aiKw = (currentTake && currentTake.keywords && currentTake.keywords.length)
    ? currentTake.keywords
    : null;
  const tokens = typeof getKeywordTokens === 'function'
    ? getKeywordTokens(text, s.reviewKeywordColor || s.keywordColor, s.reviewKeywordColor || s.keywordColor, aiKw)
    : [{ word: text, isKeyword: false, type: null, color: null }];

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

/* ──── 启动 ──── */
document.addEventListener('DOMContentLoaded', initRouter);
