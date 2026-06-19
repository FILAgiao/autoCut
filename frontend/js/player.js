/* ====== 视频播放器控制 ====== */

let _player = null;
let _segmentLoop = null;    // {start, end} 当前循环播放的片段
let _loopTimer = null;

function initPlayer() {
  _player = document.getElementById('video-player');
  console.log('[initPlayer] video element found:', !!_player, 'src:', _player ? _player.src : 'N/A');

  if (!_player) {
    console.error('[initPlayer] video-player element not found in DOM');
    return;
  }

  _player.addEventListener('error', (e) => {
    const err = _player.error;
    console.error('[player] error event:', err ? `code=${err.code} message=${err.message}` : 'unknown');
  });

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
  if (!_player) {
    console.warn('[togglePlay] _player is null');
    return;
  }

  console.log('[togglePlay] paused:', _player.paused, 'segmentLoop:', _segmentLoop, 'readyState:', _player.readyState, 'src:', _player.src);

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
      console.log('[togglePlay] seeking to segment start:', _segmentLoop.start);
      _player.currentTime = _segmentLoop.start;
    }
    _player.play().catch((err) => {
      console.error('[togglePlay] play() failed:', err.message);
    });
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
  console.log('[seekTo] time:', time, 'currentTime was:', _player.currentTime, 'readyState:', _player.readyState);
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
