/* ====== 项目详情容器 - 侧边栏 + Tab 切换 + 进度面板 ====== */

let _currentProjectId = null;
let _currentTab = 'editor';
let _progressTimer = null;

async function renderProject(projectId) {
  _currentProjectId = projectId;

  // 停止旧的轮询
  stopProgressPolling();

  try {
    const resp = await fetch(`/api/projects/${projectId}`);
    if (!resp.ok) {
      document.getElementById('app').innerHTML = '<div class="empty-state"><p>项目不存在</p><button onclick="window.location.hash=\'#/\'" class="btn-accent">返回首页</button></div>';
      return;
    }
    const project = await resp.json();

    const app = document.getElementById('app');
    app.innerHTML = `
      <header id="top-bar">
        <button id="btn-back" class="btn-back" title="返回">&#8592; 返回</button>
        <span class="logo">${escapeHtml(project.name)}</span>
        <span id="progress-text">${getProjectStatusText(project)}</span>
        <div id="top-actions">
          <button id="btn-theme" title="切换主题">${(localStorage.getItem('autocut-theme') || 'dark') === 'dark' ? '暗' : '亮'}</button>
        </div>
      </header>
      <div id="project-layout">
        <aside id="sidebar">
          <nav id="sidebar-nav">
            <div class="sidebar-item ${_currentTab === 'editor' ? 'active' : ''}" data-tab="editor">
              <span class="sidebar-icon">&#9776;</span> 编辑
            </div>
            <div class="sidebar-item ${_currentTab === 'export' ? 'active' : ''}" data-tab="export">
              <span class="sidebar-icon">&#8593;</span> 导出
            </div>
          </nav>
          <div id="sidebar-progress"></div>
        </aside>
        <main id="main-area"></main>
      </div>
    `;

    document.getElementById('btn-back').addEventListener('click', () => {
      window.location.hash = '#/';
    });
    document.getElementById('btn-theme').addEventListener('click', toggleTheme);

    // Sidebar tab switching
    document.querySelectorAll('.sidebar-item').forEach(item => {
      item.addEventListener('click', () => {
        const tab = item.dataset.tab;
        window.location.hash = `#/project/${_currentProjectId}${tab === 'export' ? '/export' : ''}`;
      });
    });

    // Determine tab from hash
    const hash = window.location.hash;
    _currentTab = hash.includes('/export') ? 'export' : 'editor';

    // Render sidebar progress if processing
    if (project.task_status === 'processing') {
      renderSidebarProgress(project);
      startProgressPolling();
    }

    switchTab(_currentTab, project);
  } catch (err) {
    document.getElementById('app').innerHTML = `<div class="empty-state"><p>加载失败: ${err.message}</p></div>`;
  }
}

function switchTab(tab, project) {
  const main = document.getElementById('main-area');
  if (!main) return;

  document.querySelectorAll('.sidebar-item').forEach(i => {
    i.classList.toggle('active', i.dataset.tab === tab);
  });

  if (tab === 'editor') {
    renderEditor(project, main);
  } else if (tab === 'export') {
    renderExport(project, main);
  }
}

/* ──── 侧边栏进度面板 ──── */

function renderSidebarProgress(project) {
  const container = document.getElementById('sidebar-progress');
  if (!container) return;
  const progress = project.pipeline_progress;
  if (!progress) {
    container.innerHTML = '<div class="sidebar-progress"><div class="sidebar-progress-header">处理中...</div></div>';
    return;
  }
  container.innerHTML = `
    <div class="sidebar-progress">
      <div class="sidebar-progress-header">处理进度</div>
      <div class="sidebar-progress-steps">
        ${renderProgressSteps(progress.steps)}
      </div>
    </div>
  `;
}

function startProgressPolling() {
  stopProgressPolling();
  _progressTimer = setTimeout(pollProgress, 1000);
}

function stopProgressPolling() {
  if (_progressTimer) {
    clearTimeout(_progressTimer);
    _progressTimer = null;
  }
}

async function pollProgress() {
  if (!_currentProjectId) return;

  try {
    const resp = await fetch(`/api/projects/${_currentProjectId}`);
    const project = await resp.json();

    if (project.task_status === 'done' || project.task_status === 'error') {
      stopProgressPolling();
      await renderProject(_currentProjectId);
      return;
    }

    // Update sidebar progress in-place
    if (project.pipeline_progress) {
      const stepsContainer = document.querySelector('#sidebar-progress .sidebar-progress-steps');
      if (stepsContainer) {
        stepsContainer.innerHTML = renderProgressSteps(project.pipeline_progress.steps);
      }
    }

    // Update editor processing view in-place
    const editorSteps = document.getElementById('pipeline-steps');
    if (editorSteps && project.pipeline_progress) {
      editorSteps.innerHTML = renderProgressSteps(project.pipeline_progress.steps);
    }

    // Update top bar text
    const progressText = document.getElementById('progress-text');
    if (progressText) {
      progressText.textContent = getProjectStatusText(project);
    }

  } catch (e) {
    // Retry on next tick
  }

  _progressTimer = setTimeout(pollProgress, 1000);
}

/* ──── 辅助 ──── */

function getProjectStatusText(project) {
  const status = project.task_status;
  if (status === 'idle') return '待处理';
  if (status === 'done') {
    const confirmed = project.confirmed_count || 0;
    const total = project.total_count || 0;
    return total ? `已确认 ${confirmed} / ${total}` : '已处理';
  }
  if (status === 'error') return '处理失败';
  if (status === 'processing') {
    const pp = project.pipeline_progress;
    if (pp && pp.current_step) {
      const step = pp.steps.find(s => s.name === pp.current_step);
      if (step) return `处理中 — ${step.label}`;
    }
    return '处理中...';
  }
  return status;
}
