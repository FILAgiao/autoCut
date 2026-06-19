/* ====== 首页 - 项目列表 ====== */

async function renderHome() {
  const app = document.getElementById('app');
  app.innerHTML = `
    <header id="top-bar">
      <span class="logo">AutoCut</span>
      <span id="progress-text"></span>
      <div id="top-actions">
        <button id="btn-theme" title="切换主题">${(localStorage.getItem('autocut-theme') || 'dark') === 'dark' ? '暗' : '亮'}</button>
      </div>
    </header>
    <section id="home-area">
      <div class="home-hero">
        <h1 class="hero-title">AutoCut</h1>
        <p class="hero-subtitle">智能口播剪辑 — 上传视频，自动对齐字幕，一键导出剪映草稿</p>
      </div>
      <div class="home-header">
        <h2>项目</h2>
        <button id="btn-new-project" class="btn-accent">+ 新建项目</button>
      </div>
      <div id="project-grid"></div>
    </section>
    <div id="new-project-modal" class="modal-overlay hidden">
      <div class="modal-card">
        <h3>新建项目</h3>
        <input type="text" id="new-project-name" placeholder="项目名称" maxlength="100">
        <textarea id="new-project-script" placeholder="粘贴口播脚本（可选）&#10;一句一行" rows="6"></textarea>
        <div class="modal-actions">
          <button id="btn-cancel-project">取消</button>
          <button id="btn-create-project">创建</button>
        </div>
      </div>
    </div>
  `;

  document.getElementById('btn-theme').addEventListener('click', toggleTheme);
  document.getElementById('btn-new-project').addEventListener('click', showNewProjectModal);
  document.getElementById('btn-cancel-project').addEventListener('click', hideNewProjectModal);
  document.getElementById('btn-create-project').addEventListener('click', createNewProject);

  // ESC 关闭弹窗
  document.getElementById('new-project-modal').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) hideNewProjectModal();
  });

  await loadProjectList();

  // 更新主题按钮状态（响应 toggleTheme 的变化）
  const origToggle = toggleTheme;
  toggleTheme = function() {
    origToggle();
    const btn = document.getElementById('btn-theme');
    if (btn) {
      const theme = document.documentElement.getAttribute('data-theme') || 'dark';
      btn.textContent = theme === 'light' ? '亮' : '暗';
    }
  };
}

async function loadProjectList() {
  const grid = document.getElementById('project-grid');
  if (!grid) return;

  try {
    const resp = await fetch('/api/projects');
    const projects = await resp.json();

    if (!projects.length) {
      grid.innerHTML = `
        <div class="project-card project-card-new" onclick="showNewProjectModal()">
          <div class="project-card-icon">+</div>
          <div class="project-card-name">新建项目</div>
          <div class="project-card-meta">上传视频，开始剪辑</div>
        </div>
        <div class="empty-state">
          <div class="empty-icon">&#9678;</div>
          <p>还没有项目</p>
          <p class="empty-hint">点击上方卡片或「新建项目」开始剪辑你的口播视频</p>
        </div>`;
      return;
    }

    let cards = projects.map(p => {
      const statusLabels = { idle: '待处理', processing: '处理中', done: '已处理', error: '处理失败' };
      const statusLabel = statusLabels[p.task_status] || p.task_status;
      const statusCls = `status-${p.task_status === 'done' ? 'done' : p.task_status === 'processing' ? 'processing' : p.task_status === 'error' ? 'error' : 'idle'}`;
      const timeAgo = formatTimeAgo(p.updated_at);

      return `
        <div class="project-card" data-id="${p.id}" onclick="openProject('${p.id}')">
          <div class="project-card-icon">&#9678;</div>
          <div class="project-card-name">${escapeHtml(p.name)}</div>
          <div class="project-card-meta">
            <span class="project-status ${statusCls}">${statusLabel}</span>
            <span>${p.clip_count} 片段</span>
          </div>
          <div class="project-card-time">${timeAgo}</div>
          <button class="project-card-delete" onclick="deleteProject(event, '${p.id}')" title="删除项目">✕</button>
        </div>`;
    });

    // Prepend "new project" card
    cards.unshift(`
      <div class="project-card project-card-new" onclick="showNewProjectModal()">
        <div class="project-card-icon">+</div>
        <div class="project-card-name">新建项目</div>
        <div class="project-card-meta">上传视频，开始剪辑</div>
      </div>`);

    grid.innerHTML = cards.join('');
  } catch (err) {
    grid.innerHTML = '<div class="empty-state"><p>加载失败，请检查服务是否启动</p></div>';
  }
}

function showNewProjectModal() {
  document.getElementById('new-project-modal').classList.remove('hidden');
  document.getElementById('new-project-name').focus();
}

function hideNewProjectModal() {
  document.getElementById('new-project-modal').classList.add('hidden');
  document.getElementById('new-project-name').value = '';
  document.getElementById('new-project-script').value = '';
}

async function createNewProject() {
  const name = document.getElementById('new-project-name').value.trim() || '未命名项目';
  const script = document.getElementById('new-project-script').value.trim();

  try {
    const resp = await fetch('/api/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, script }),
    });
    const project = await resp.json();
    hideNewProjectModal();
    window.location.hash = '#/project/' + project.id;
  } catch (err) {
    alert('创建失败: ' + err.message);
  }
}

function openProject(id) {
  window.location.hash = '#/project/' + id;
}

async function deleteProject(e, id) {
  e.stopPropagation();
  if (!confirm('确定要删除这个项目吗？所有数据将无法恢复。')) return;

  try {
    await fetch('/api/projects/' + id, { method: 'DELETE' });
    await loadProjectList();
  } catch (err) {
    alert('删除失败: ' + err.message);
  }
}

function formatTimeAgo(isoStr) {
  if (!isoStr) return '';
  const then = new Date(isoStr);
  const now = new Date();
  const diff = (now - then) / 1000;
  if (diff < 60) return '刚刚';
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
  if (diff < 604800) return `${Math.floor(diff / 86400)} 天前`;
  return then.toLocaleDateString('zh-CN');
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}
