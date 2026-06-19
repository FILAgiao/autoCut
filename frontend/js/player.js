/* ====== 视频播放器控制 ====== */

let _player = null;
let _segmentLoop = null;    // {start, end} 当前循环播放的片段
let _loopTimer = null;

function initPlayer() {
  _player = document.getElementById('video-player');

  _player.addEventListener('timeupdate', () => {
    // 片段循环：播到 end 时自动跳回 start
    if (_segmentLoop && _player.currentTime >= _segmentLoop.end - 0.05) {
      _player.currentTime = _segmentLoop.start;
      _player.play().catch(() => {});
    }
    // 更新编辑模式字幕 Canvas（在 app.js 中定义）
    if (typeof updateEditorSubtitle === 'function') {
      updateEditorSubtitle();
    }
  });

  _player.addEventListener('loadedmetadata', () => {
    if (typeof drawTimeline === 'function') drawTimeline();
    if (typeof updateEditorSubtitle === 'function') updateEditorSubtitle();
  });

  // 双击全屏
  _player.addEventListener('dblclick', (e) => {
    e.preventDefault();
    if (document.fullscreenElement) {
      document.exitFullscreen();
    } else {
      _player.requestFullscreen();
    }
  });

  // seek 时更新字幕
  _player.addEventListener('seeked', () => {
    if (typeof updateEditorSubtitle === 'function') {
      updateEditorSubtitle();
    }
  });

  // 暂停时保持字幕
  _player.addEventListener('pause', () => {
    if (typeof updateEditorSubtitle === 'function') {
      updateEditorSubtitle();
    }
  });

  _player.addEventListener('play', () => {
    if (typeof updateEditorSubtitle === 'function') {
      updateEditorSubtitle();
    }
  });

  // 阻止画中画（避免干扰）
  _player.disablePictureInPicture = true;
}

function playSegment(start, end) {
  if (!_player) return;
  _segmentLoop = { start, end };
  _player.currentTime = start;
  _player.play().catch(() => {});
}

function togglePlay() {
  if (!_player) return;

  if (!_segmentLoop) {
    const sent = STATE.sentences[STATE.currentSentence];
    if (sent && sent.takes[STATE.currentTakeIndex]) {
      const t = sent.takes[STATE.currentTakeIndex];
      _segmentLoop = { start: t.start, end: t.end };
    }
  }

  if (_player.paused) {
    if (_segmentLoop &&
        (_player.currentTime < _segmentLoop.start || _player.currentTime >= _segmentLoop.end)) {
      _player.currentTime = _segmentLoop.start;
    }
    _player.play().catch(() => {});
  } else {
    _player.pause();
  }
}

function playCurrentTake() {
  const sent = STATE.sentences[STATE.currentSentence];
  if (!sent) return;
  const t = sent.takes[STATE.currentTakeIndex];
  if (t) playSegment(t.start, t.end);
}

function seekTo(time) {
  if (!_player) return;
  _segmentLoop = null;
  _player.currentTime = time;
}

function stopLoop() {
  _segmentLoop = null;
  if (_player) _player.pause();
}

function getPlayer() {
  return _player;
}

/* ──── Canvas 字幕叠加辅助 ──── */
function updateSubtitleCanvas() {
  if (typeof updateEditorSubtitle === 'function') {
    updateEditorSubtitle();
  }
}
