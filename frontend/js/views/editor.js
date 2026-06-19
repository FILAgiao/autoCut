/* ====== 编辑 Tab - 上传 / 处理 / 三栏编辑器 ====== */

let _pollTimer = null;

function renderEditor(project, container) {
  if (_pollTimer) { clearTimeout(_pollTimer); _pollTimer = null; }

  if (project.task_status === 'done') {
    renderEditorMode(project, container);
  } else if (project.task_status === 'processing') {
    renderProcessingMode(project, container);
  } else if (project.task_status === 'error') {
    renderErrorMode(project, container);
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

  // Refresh clips list with file info
  if (project.clips && project.clips.length) {
    renderClipsList(project.clips);
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

  if (btnStart) {
    btnStart.addEventListener('click', () => startEditorProcessing());
  } else {
    console.warn('[renderIdleMode] btnStart is null, retrying with setTimeout');
    setTimeout(() => {
      const btn = document.getElementById('btn-start');
      if (btn) {
        btn.addEventListener('click', () => startEditorProcessing());
        console.log('[renderIdleMode] btnStart bound via setTimeout');
      } else {
        console.error('[renderIdleMode] btnStart still null after setTimeout');
      }
    }, 0);
  }

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

function renderClipsList(clips) {
  const list = document.getElementById('clips-list');
  if (!list) return;
  list.innerHTML = clips.map(c => {
    const sizeStr = c.file_size ? formatFileSize(c.file_size) : '';
    const exists = c.exists !== false;
    const durOk = c.duration > 0;
    const statusIcon = !exists ? '&#10005;' : (durOk ? '&#10003;' : '&#9888;');
    const statusCls = !exists ? 'clip-status-error' : (durOk ? 'clip-status-ok' : 'clip-status-warn');
    const statusTitle = !exists ? '文件丢失' : (durOk ? '正常' : '时长异常');
    return `<div class="clip-item">
      <span class="clip-status ${statusCls}" title="${statusTitle}">${statusIcon}</span>
      <span class="clip-name">${escapeHtml(c.original_name || c.filename)}</span>
      ${sizeStr ? `<span class="clip-size">${sizeStr}</span>` : ''}
      ${c.duration > 0 ? `<span class="clip-dur">${formatDuration(c.duration)}</span>` : ''}
      <button class="clip-delete" data-clip-id="${escapeHtml(c.id)}" title="删除此片段">&#10005;</button>
    </div>`;
  }).join('');

  list.querySelectorAll('.clip-delete').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const clipId = btn.dataset.clipId;
      await deleteEditorClip(clipId);
    });
  });
}

async function deleteEditorClip(clipId) {
  try {
    const resp = await fetch(`/api/projects/${_currentProjectId}/clips/${clipId}`, { method: 'DELETE' });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.error || '删除失败');
    }
    await renderProject(_currentProjectId);
  } catch (err) {
    const statusEl = document.getElementById('upload-status');
    if (statusEl) statusEl.innerHTML = `<span style="color:var(--error)">删除失败: ${err.message}</span>`;
  }
}

function checkEditorStartReady() {
  const btn = document.getElementById('btn-start');
  if (!btn) return;
  btn.disabled = !window._selectedVideoFile;
}

async function startEditorProcessing() {
  console.log('[startEditorProcessing] called, _currentProjectId:', _currentProjectId);

  const file = window._selectedVideoFile;
  if (!file) {
    console.warn('[startEditorProcessing] no video file selected');
    return;
  }

  const btnStart = document.getElementById('btn-start');
  const statusEl = document.getElementById('upload-status');
  console.log('[startEditorProcessing] btnStart found:', !!btnStart, 'statusEl found:', !!statusEl);
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

    // Upload clip with progress and error handling
    statusEl.textContent = '上传视频...';
    const formData = new FormData();
    formData.append('video', file);

    const uploadResult = await new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `/api/projects/${_currentProjectId}/clips`);
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
          const pct = Math.round(e.loaded / e.total * 100);
          statusEl.textContent = `上传视频... ${pct}%`;
        }
      };
      xhr.onload = () => {
        try {
          const data = JSON.parse(xhr.responseText);
          if (xhr.status >= 200 && xhr.status < 300) {
            resolve(data);
          } else {
            reject(new Error(data.error || data.detail || `上传失败 (${xhr.status})`));
          }
        } catch (_) {
          if (xhr.status >= 200 && xhr.status < 300) {
            resolve({});
          } else {
            reject(new Error(`服务器错误 (${xhr.status})`));
          }
        }
      };
      xhr.onerror = () => reject(new Error('上传失败，请检查网络'));
      xhr.ontimeout = () => reject(new Error('上传超时，请重试'));
      xhr.send(formData);
    });

    // Post-upload: re-fetch project to verify clip was saved correctly
    statusEl.textContent = '校验视频文件...';
    const checkResp = await fetch(`/api/projects/${_currentProjectId}`);
    if (!checkResp.ok) throw new Error('获取项目信息失败');
    const projectData = await checkResp.json();
    const savedClips = projectData.clips || [];
    const savedClip = savedClips.find(c =>
      c.original_name === file.name || c.filename === uploadResult.filename
    );
    if (!savedClip) {
      throw new Error('视频片段未正确保存，请重新上传');
    }

    statusEl.innerHTML = '<span class="status-dot status-processing"></span>启动处理...';

    // Start processing
    const processResp = await fetch(`/api/projects/${_currentProjectId}/process`, { method: 'POST' });
    if (!processResp.ok) {
      const err = await processResp.json();
      throw new Error(err.error || '启动处理失败');
    }

    // Trigger re-render to show processing mode (sidebar polling will handle progress)
    await renderProject(_currentProjectId);
  } catch (err) {
    statusEl.innerHTML = `<span style="color:var(--error)">错误: ${err.message}</span>`;
    btnStart.disabled = false;
    btnStart.textContent = '开始处理';
  }
}

/* ──── 处理中：进度面板 ──── */
function renderProcessingMode(project, container) {
  const progress = project.pipeline_progress;
  container.innerHTML = `
    <div id="editor-processing" class="processing-view">
      <h3>正在处理视频</h3>
      <div id="pipeline-steps" class="pipeline-steps">
        ${progress ? renderProgressSteps(progress.steps) : '<div class="processing-spinner"></div>'}
      </div>
    </div>
  `;
}

/* ──── 处理失败：错误 + 重试 ──── */
function renderErrorMode(project, container) {
  container.innerHTML = `
    <div class="processing-view">
      <div style="font-size:48px;margin-bottom:16px;opacity:0.5;">&#10005;</div>
      <h3>处理失败</h3>
      <p style="color:var(--error);max-width:500px;text-align:center;margin-top:8px;">${escapeHtml(project.error_message || '未知错误')}</p>
      <button id="btn-retry" class="btn-accent" style="margin-top:24px;">重新处理</button>
    </div>
  `;
  document.getElementById('btn-retry').addEventListener('click', async () => {
    await fetch(`/api/projects/${_currentProjectId}/retry`, { method: 'POST' });
    await renderProject(_currentProjectId);
  });
}

/* ──── 进度步骤渲染（共享函数） ──── */
function renderProgressSteps(steps) {
  if (!steps) return '';
  return steps.map(s => {
    let icon, cls = s.status;
    if (s.status === 'done') {
      icon = '<svg width="16" height="16" viewBox="0 0 16 16"><polyline points="3,8 6.5,12 13,4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    } else if (s.status === 'processing') {
      icon = '<span class="spinner-icon"></span>';
    } else if (s.status === 'error') {
      icon = '&#10005;';
    } else {
      icon = '&#8728;';
    }

    const barHtml = s.status === 'processing'
      ? `<div class="progress-step-bar"><div class="progress-step-fill" style="width:${s.percent}%"></div></div>
         <span class="progress-step-pct">${s.percent}%</span>`
      : (s.status === 'done'
        ? ''
        : '');

    return `<div class="progress-step ${cls}">
      <span class="progress-step-icon">${icon}</span>
      <span class="progress-step-label">${escapeHtml(s.label)}</span>
      ${barHtml}
    </div>`;
  }).join('');
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
          <video id="video-player" controls disablepictureinpicture preload="auto" playsinline>
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
    const clipUrl = `/api/projects/${project.id}/clips/${clips[0].id}`;
    console.log('[renderEditorMode] setting video.src to:', clipUrl, 'clip:', clips[0]);
    video.src = clipUrl;
  } else {
    console.warn('[renderEditorMode] no clips available for video, clips:', clips);
  }

  video.onerror = (e) => {
    const err = video.error;
    console.error('[video] error event:', err ? `code=${err.code} message=${err.message}` : 'unknown', 'src:', video.src);
    document.getElementById('take-info').textContent =
      `视频加载失败: ${err ? err.message : '未知错误'} (${video.src})`;
  };
  video.oncanplay = () => console.log('[video] canplay, readyState:', video.readyState, 'duration:', video.duration);
  video.onloadeddata = () => console.log('[video] loadeddata, videoWidth:', video.videoWidth, 'videoHeight:', video.videoHeight);
  video.onwaiting = () => console.log('[video] waiting (buffering)...');
  video.onstalled = () => console.warn('[video] stalled');

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
  console.log('[editorConfirm] called, currentSentence:', STATE.currentSentence, 'currentTakeIndex:', STATE.currentTakeIndex);
  const sent = STATE.sentences[STATE.currentSentence];
  if (!sent) return;
  const takeIdx = STATE.currentTakeIndex;
  if (takeIdx < 0 || takeIdx >= sent.takes.length) {
    console.warn('[editorConfirm] invalid takeIdx:', takeIdx, 'takes.length:', sent.takes.length);
    return;
  }

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
  console.log('[editorReject] called, currentSentence:', STATE.currentSentence, 'currentTakeIndex:', STATE.currentTakeIndex);
  const sent = STATE.sentences[STATE.currentSentence];
  if (!sent || !sent.takes.length) {
    console.warn('[editorReject] no sentence or no takes');
    return;
  }
  const takeIdx = STATE.currentTakeIndex;
  if (takeIdx < 0 || takeIdx >= sent.takes.length) {
    console.warn('[editorReject] invalid takeIdx:', takeIdx, 'takes.length:', sent.takes.length);
    return;
  }
  console.log('[editorReject] rejecting take', takeIdx, 'text:', sent.takes[takeIdx].text);

  try {
    const url = `/api/projects/${_currentProjectId}/reject/${STATE.currentSentence}/${takeIdx}`;
    console.log('[editorReject] PUT', url);
    const resp = await fetch(url, { method: 'PUT' });
    if (!resp.ok) {
      const errText = await resp.text();
      console.error('[editorReject] API error:', resp.status, errText);
    }
  } catch (e) {
    console.error('[editorReject] fetch error:', e.message);
  }

  sent.takes[takeIdx].is_abandoned = true;
  sent.takes[takeIdx].grade = '废';

  flashTakeItem(takeIdx, 'reject-flash');

  // Find next non-abandoned take (forward first, then wrap)
  let next = sent.takes.findIndex((t, i) => i > takeIdx && !t.is_abandoned);
  if (next < 0) {
    next = sent.takes.findIndex((t, i) => !t.is_abandoned);
  }

  if (next >= 0) {
    STATE.currentTakeIndex = next;
    seekToCurrentTake();
  }
  // Always re-render so abandoned styling is visible
  renderTakesList();
  updateEditorSubtitle();
  updateCurrentSentenceLabel();
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
