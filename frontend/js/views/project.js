/* ====== 项目详情容器 - 侧边栏 + Tab 切换 ====== */

let _currentProjectId = null;
let _currentTab = 'editor';

async function renderProject(projectId) {
  _currentProjectId = projectId;

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
        <button id="btn-back" class="btn-back" title="返回">← 返回</button>
        <span class="logo" style="margin-left:8px;">${escapeHtml(project.name)}</span>
        <span id="progress-text">${project.task_status === 'idle' ? '待处理' : project.task_status === 'done' ? '已处理' : '处理中...'}</span>
        <div id="top-actions">
          <button id="btn-theme" title="切换主题">${(localStorage.getItem('autocut-theme') || 'dark') === 'dark' ? '🌙' : '☀️'}</button>
        </div>
      </header>
      <div id="project-layout">
        <aside id="sidebar">
          <nav id="sidebar-nav">
            <div class="sidebar-item ${_currentTab === 'editor' ? 'active' : ''}" data-tab="editor">
              <span class="sidebar-icon">📋</span> 编辑
            </div>
            <div class="sidebar-item ${_currentTab === 'export' ? 'active' : ''}" data-tab="export">
              <span class="sidebar-icon">🎬</span> 导出
            </div>
          </nav>
        </aside>
        <main id="main-area"></main>
      </div>
    `;

    document.getElementById('btn-back').addEventListener('click', () => {
      window.location.hash = '#/';
    });
    document.getElementById('btn-theme').addEventListener('click', toggleTheme);

    // Sidebar tab switching — change hash, let router handle it
    document.querySelectorAll('.sidebar-item').forEach(item => {
      item.addEventListener('click', () => {
        const tab = item.dataset.tab;
        window.location.hash = `#/project/${_currentProjectId}${tab === 'export' ? '/export' : ''}`;
      });
    });

    // Determine which tab to show based on hash
    const hash = window.location.hash;
    _currentTab = hash.includes('/export') ? 'export' : 'editor';

    switchTab(_currentTab, project);
  } catch (err) {
    document.getElementById('app').innerHTML = `<div class="empty-state"><p>加载失败: ${err.message}</p></div>`;
  }
}

function switchTab(tab, project) {
  const main = document.getElementById('main-area');
  if (!main) return;

  // Update sidebar active state
  document.querySelectorAll('.sidebar-item').forEach(i => {
    i.classList.toggle('active', i.dataset.tab === tab);
  });

  if (tab === 'editor') {
    renderEditor(project, main);
  } else if (tab === 'export') {
    renderExport(project, main);
  }
}
