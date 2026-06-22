/* ====== 键盘快捷键 ====== */

function initKeyboard() {
  document.addEventListener('keydown', handleKeyDown);
}

function handleKeyDown(e) {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

  console.log('[keyboard] key:', e.key, 'ctrl:', e.ctrlKey || e.metaKey);
  const handled = dispatchKey(e);
  if (handled) {
    e.preventDefault();
    e.stopPropagation();
  }
}

function dispatchKey(e) {
  const key = e.key;
  const ctrl = e.ctrlKey || e.metaKey;

  switch (true) {
    // ──── 导航 ────
    case key === 'ArrowLeft':
      selectSentence(STATE.currentSentence - 1);
      return true;

    case key === 'ArrowRight':
      selectSentence(STATE.currentSentence + 1);
      return true;

    case key === 'ArrowUp':
      navigateTake(-1);
      return true;

    case key === 'ArrowDown':
      navigateTake(1);
      return true;

    // ──── 确认 / 拒掉 ────
    case key === 'Enter' && !ctrl:
      if (typeof editorConfirm === 'function') editorConfirm();
      return true;

    case key === 'r' || key === 'R':
      if (typeof editorReject === 'function') editorReject();
      return true;

    // ──── 播放 ────
    case key === ' ':
      e.preventDefault();
      togglePlay();
      return true;

    // ──── 速选 (1-9) ────
    case key >= '1' && key <= '9':
      quickSelect(parseInt(key) - 1);
      return true;

    // ──── 撤销 ────
    case key === 'Backspace':
      undoConfirm();
      return true;

    // ──── 组合键 ────
    case ctrl && key === 'Enter':
      autoConfirmAll();
      return true;

    case ctrl && (key === 's' || key === 'S'):
      if (typeof exportProjectDraft === 'function') exportProjectDraft();
      return true;

    case ctrl && (key === 'z' || key === 'Z'):
      undoConfirm();
      return true;

    // ──── 全屏 ────
    case key === 'Escape':
      if (document.fullscreenElement) {
        document.exitFullscreen();
        return true;
      }
      return false;

    default:
      return false;
  }
}

function navigateTake(direction) {
  console.log('[navigateTake] direction:', direction, 'currentTakeIndex:', STATE.currentTakeIndex);
  const sent = STATE.sentences[STATE.currentSentence];
  if (!sent || !sent.takes.length) return;

  let nextIdx = STATE.currentTakeIndex + direction;
  if (nextIdx < 0 || nextIdx >= sent.takes.length) return;

  selectTake(nextIdx);
  playCurrentTake();
}

function quickSelect(index) {
  const sent = STATE.sentences[STATE.currentSentence];
  if (!sent || index >= sent.takes.length) return;

  selectTake(index);
  playCurrentTake();
}

function undoConfirm() {
  const sent = STATE.sentences[STATE.currentSentence];
  if (!sent || sent.confirmed_take_index < 0) return;

  sent.confirmed_take_index = -1;
  if (typeof updateEditorProgress === 'function') updateEditorProgress();
  renderScriptList();
  renderTakesList();
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
          `/api/projects/${_currentProjectId}/confirm/${i}/${best}`,
          { method: 'PUT' }
        );
      } catch (e) {}
    }
  }
  if (typeof updateEditorProgress === 'function') updateEditorProgress();
  renderScriptList();
  renderTakesList();
}
