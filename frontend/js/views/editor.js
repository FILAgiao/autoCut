/* ====== 编辑 Tab - 上传 / 处理 / 三栏编辑器 ====== */

let _pollTimer = null;

function renderEditor(project, container) {
  // Stop any existing poll
  if (_pollTimer) { clearTimeout(_pollTimer); _pollTimer = null; }

  if (project.task_status === 'done') {
    renderEditorMode(project, container);
  } else if (project.task_status === 'processing') {
    renderProcessingMode(project, container);
  } else {
    renderIdleMode(project, container);
  }
}

/* ──── 待处理：上传区 ──── */
function renderIdleMode(project, container) {
  container.innerHTML = `
    <div id="editor-idle">
      <div class="upload-card">
        <h2><span class="card-icon">&#9678;</span> 上传视频</h2>
        <div class="drop-zone" id="video-drop-zone">
          <input type="file" id="video-input" accept="video/*" hidden>
          <span class="drop-icon">&#8682;</span>
          <span>拖拽视频到此处，或 <a href="#" id="video-browse">点击选择</a></span>
          <span class="hint" style="margin-top:4px;">支持 MP4 / MOV / AVI 等常见格式</span>
        </div>
        <div id="clips-list" class="clips-list"></div>
        <div id="video-info" class="file-info hidden">
          <span id="video-name"></span>
          <span id="video-size"></span>
          <span id="video-duration"></span>
        </div>
      </div>
      <div class="upload-card">
        <h2><span class="card-icon">&#9776;</span> 口播脚本 <span class="optional-badge">可选</span></h2>
        <textarea id="script-input" placeholder="粘贴口播脚本，支持段落格式，自动智能分句&#10;例如：&#10;大家好我是小飞。今天给大家分享一个好东西。这个功能真的很好用！" rows="10">${escapeHtml(project.script || '')}</textarea>
        <span class="hint"><span id="script-line-count">0 句</span> <span style="color:var(--text-dim)">— 自动按句号/感叹号/问号分句</span></span>
      </div>
      <button id="btn-start" disabled>开始处理</button>
      <div id="upload-status"></div>
    </div>
  `;

  // Refresh clips list
  if (project.clips && project.clips.length) {
    const list = document.getElementById('clips-list');
    list.innerHTML = project.clips.map(c =>
      `<div class="clip-item">&#9678; ${escapeHtml(c.original_name || c.filename)}</div>`
    ).join('');
  }

  // Upload handlers
  const dropZone = document.getElementById('video-drop-zone');
  const videoInput = document.getElementById('video-input');
  const videoBrowse = document.getElementById('video-browse');
  const scriptInput = document.getElementById('script-input');
  const btnStart = document.getElementById('btn-start');

  dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
  dropZone.addEventListener('drop', e => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    const file = e.dataTransfer.files[0];
    if (file && file.type.startsWith('video/')) handleEditorVideoFile(file);
  });
  dropZone.addEventListener('click', () => videoInput.click());
  videoBrowse.addEventListener('click', e => { e.preventDefault(); videoInput.click(); });
  videoInput.addEventListener('change', () => {
    if (videoInput.files[0]) handleEditorVideoFile(videoInput.files[0]);
  });

  scriptInput.addEventListener('input', () => {
    const text = scriptInput.value.trim();
    const lines = text ? text.split(/[。！？!?\n]+/).filter(l => l.trim()).length : 0;
    document.getElementById('script-line-count').textContent = `${lines} 句`;
    checkEditorStartReady();
  });

  // Init script line count
  const text = scriptInput.value.trim();
  const initCount = text ? text.split(/[。！？!?\n]+/).filter(l => l.trim()).length : 0;
  document.getElementById('script-line-count').textContent = `${initCount} 句`;

  btnStart.addEventListener('click', () => startEditorProcessing());

  checkEditorStartReady();
}

function handleEditorVideoFile(file) {
  const sizeMB = (file.size / 1024 / 1024).toFixed(1);
  document.getElementById('video-info').classList.remove('hidden');
  document.getElementById('video-name').textContent = file.name;
  document.getElementById('video-size').textContent = `${sizeMB} MB`;

  const url = URL.createObjectURL(file);
  const video = document.createElement('video');
  video.preload = 'metadata';
  video.onloadedmetadata = () => {
    document.getElementById('video-duration').textContent = formatDuration(video.duration);
    URL.revokeObjectURL(url);
  };
  video.src = url;

  window._selectedVideoFile = file;
  checkEditorStartReady();
}

function checkEditorStartReady() {
  const btn = document.getElementById('btn-start');
  if (!btn) return;
  btn.disabled = !window._selectedVideoFile;
}

async function startEditorProcessing() {
  const file = window._selectedVideoFile;
  if (!file) return;

  const btnStart = document.getElementById('btn-start');
  const statusEl = document.getElementById('upload-status');
  btnStart.disabled = true;
  btnStart.textContent = '处理中...';

  try {
    const script = document.getElementById('script-input').value;

    // Save script to project
    statusEl.textContent = '保存脚本...';
    await fetch(`/api/projects/${_currentProjectId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ script }),
    });

    // Upload clip
    statusEl.textContent = '上传视频...';
    const formData = new FormData();
    formData.append('video', file);
    const uploadResp = await fetch(`/api/projects/${_currentProjectId}/clips`, { method: 'POST', body: formData });
    if (!uploadResp.ok) {
      const err = await uploadResp.json();
      throw new Error(err.detail || err.error || '上传失败');
    }

    statusEl.innerHTML = '<span class="status-dot status-processing"></span>启动处理...';

    // Start processing
    const processResp = await fetch(`/api/projects/${_currentProjectId}/process`, { method: 'POST' });
    if (!processResp.ok) {
      const err = await processResp.json();
      throw new Error(err.error || '启动处理失败');
    }

    // Switch to processing mode
    pollProjectStatus();
  } catch (err) {
    statusEl.innerHTML = `<span style="color:var(--error)">错误: ${err.message}</span>`;
    btnStart.disabled = false;
    btnStart.textContent = '开始处理';
  }
}

/* ──── 处理中：进度轮询 ──── */
function renderProcessingMode(project, container) {
  container.innerHTML = `
    <div id="editor-processing" class="processing-view">
      <div class="processing-spinner"></div>
      <h3>正在处理视频</h3>
      <p id="processing-status-text">${getStatusText(project.task_status)}</p>
    </div>
  `;
  pollProjectStatus();
}

function getStatusText(status) {
  const map = {
    extracting_audio: '提取音频中...',
    asr_processing: '语音识别中...',
    aligning: '语义对齐中...',
    analyzing: '分析质量中...',
    processing: '处理中...',
  };
  return map[status] || status;
}

async function pollProjectStatus() {
  if (!_currentProjectId) return;

  try {
    const resp = await fetch(`/api/projects/${_currentProjectId}/status`);
    const data = await resp.json();

    const statusEl = document.getElementById('processing-status-text');
    if (statusEl) {
      statusEl.textContent = getStatusText(data.status);
    }

    if (data.status === 'done') {
      // Restore STATE and render editor
      STATE.taskId = data.task_id || _currentProjectId;
      STATE.status = 'editing';
      STATE.sentences = data.sentences || [];
      STATE.unmatched = data.unmatched || [];
      STATE.totalCount = data.total_count || STATE.sentences.length;
      STATE.confirmedCount = data.confirmed_count || 0;
      STATE.videoDuration = data.video_duration || 0;
      STATE.currentSentence = 0;
      STATE.currentTakeIndex = 0;
      STATE.projectId = _currentProjectId;

      // Re-render project view with updated data
      await renderProject(_currentProjectId);
      return;
    } else if (data.status === 'error') {
      if (statusEl) {
        statusEl.textContent = `处理失败: ${data.error_message || '未知错误'}`;
      }
      return;
    }
  } catch (err) {
    // Retry
  }

  _pollTimer = setTimeout(pollProjectStatus, 2000);
}

/* ──── 已完成：三栏编辑器 ──── */
function renderEditorMode(project, container) {
  // Initialize STATE from project data
  STATE.taskId = project.task_id || project.id;
  STATE.status = 'editing';
  STATE.sentences = project.sentences || [];
  STATE.unmatched = project.unmatched || [];
  STATE.totalCount = project.total_count || STATE.sentences.length;
  STATE.confirmedCount = project.confirmed_count || 0;
  STATE.videoDuration = project.video_duration || 0;
  STATE.currentSentence = 0;
  STATE.currentTakeIndex = 0;
  STATE.projectId = project.id;

  container.innerHTML = `
    <div id="editor-area">
      <div id="timeline-bar">
        <canvas id="timeline-canvas"></canvas>
      </div>
      <div id="editor-columns">
        <aside id="script-panel">
          <button class="panel-toggle" id="toggle-script-panel" title="折叠面板">◀</button>
          <div id="script-mode-label">脚本行</div>
          <div id="script-list"></div>
        </aside>
        <main id="video-panel">
          <video id="video-player" controls disablepictureinpicture>
            您的浏览器不支持视频播放
          </video>
          <canvas id="subtitle-canvas"></canvas>
          <div id="take-info">
            <span id="take-grade"></span>
            <span id="take-time"></span>
            <span id="take-duration"></span>
            <span id="take-tags"></span>
          </div>
          <div id="take-actions">
            <button id="btn-play" title="Space">&#9654; 播放此段</button>
            <button id="btn-confirm" title="Enter">&#10003; 确认</button>
            <button id="btn-reject" title="R">&#10005; 拒掉</button>
          </div>
        </main>
        <aside id="takes-panel">
          <button class="panel-toggle" id="toggle-takes-panel" title="折叠面板">▶</button>
          <div id="current-sentence-label"></div>
          <div id="takes-list"></div>
          <div id="unmatched-panel" class="hidden">
            <h3>未匹配片段</h3>
            <div id="unmatched-list"></div>
          </div>
        </aside>
      </div>
      <footer id="shortcut-bar">
        <span>← → 切句</span>
        <span>↑ ↓ 切换本</span>
        <span>Enter 确认</span>
        <span>Space 播放</span>
        <span>R 拒掉</span>
        <span>1-9 速选</span>
        <span>Ctrl+Enter 全确认</span>
        <span>Ctrl+S 导出</span>
      </footer>
    </div>
  `;

  // Set video source
  const video = document.getElementById('video-player');
  const clips = project.clips || [];
  if (clips.length > 0) {
    video.src = `/api/projects/${project.id}/clips/${clips[0].id}`;
  }

  // Determine mode label
  const hasScript = (project.script || '').trim().length > 0;
  document.getElementById('script-mode-label').textContent =
    hasScript ? '脚本行（对齐模式）' : '检测到的内容（聚类模式）';

  // Bind editor buttons
  document.getElementById('btn-play').addEventListener('click', () => togglePlay());
  document.getElementById('btn-confirm').addEventListener('click', () => editorConfirm());
  document.getElementById('btn-reject').addEventListener('click', () => editorReject());

  // Panel toggles
  setupPanelToggles();

  // Restore confirmed state
  for (const s of STATE.sentences) {
    if (s.confirmed_take_index >= 0 && s.confirmed_take_index < s.takes.length) {
      // already confirmed
    }
  }

  // Render all
  renderAll();
  initKeyboard();
  initPlayer();
  initEditorSubtitleCanvas();
  jumpToFirstAvailable();
}

/* ──── Editor confirm / reject (project-based) ──── */
async function editorConfirm() {
  const sent = STATE.sentences[STATE.currentSentence];
  if (!sent) return;
  const takeIdx = STATE.currentTakeIndex;
  if (takeIdx < 0 || takeIdx >= sent.takes.length) return;

  try {
    await fetch(
      `/api/projects/${_currentProjectId}/confirm/${STATE.currentSentence}/${takeIdx}`,
      { method: 'PUT' }
    );
  } catch (e) {}

  sent.confirmed_take_index = takeIdx;
  updateEditorProgress();

  const next = STATE.currentSentence + 1;
  if (next < STATE.sentences.length) {
    selectSentence(next);
  } else {
    renderAll();
  }
}

async function editorReject() {
  const sent = STATE.sentences[STATE.currentSentence];
  if (!sent) return;
  const takeIdx = STATE.currentTakeIndex;

  try {
    await fetch(
      `/api/projects/${_currentProjectId}/reject/${STATE.currentSentence}/${takeIdx}`,
      { method: 'PUT' }
    );
  } catch (e) {}

  sent.takes[takeIdx].is_abandoned = true;
  sent.takes[takeIdx].grade = '废';

  flashTakeItem(takeIdx, 'reject-flash');

  const next = sent.takes.findIndex((t, i) => i > takeIdx && !t.is_abandoned);
  if (next >= 0) {
    STATE.currentTakeIndex = next;
    renderTakesList();
    updateEditorSubtitle();
    seekToCurrentTake();
  }
}

function updateEditorProgress() {
  const count = STATE.sentences.filter(s => s.confirmed_take_index >= 0).length;
  STATE.confirmedCount = count;
  document.getElementById('progress-text').textContent =
    `已确认 ${count} / ${STATE.totalCount}`;
}

function setupPanelToggles() {
  const scriptPanel = document.getElementById('script-panel');
  const takesPanel = document.getElementById('takes-panel');
  if (!scriptPanel || !takesPanel) return;

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
