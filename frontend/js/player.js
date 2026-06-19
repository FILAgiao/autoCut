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
  });

  _player.addEventListener('loadedmetadata', () => {
    if (typeof drawTimeline === 'function') drawTimeline();
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

  // 如果没在循环模式，先设定当前句的片段范围
  if (!_segmentLoop) {
    const sent = STATE.sentences[STATE.currentSentence];
    if (sent && sent.takes[STATE.currentTakeIndex]) {
      const t = sent.takes[STATE.currentTakeIndex];
      _segmentLoop = { start: t.start, end: t.end };
    }
  }

  if (_player.paused) {
    // 如果当前不在循环范围内，seek 到循环开始
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
  _segmentLoop = null;  // 手动 seek 时取消循环
  _player.currentTime = time;
}

function stopLoop() {
  _segmentLoop = null;
  if (_player) _player.pause();
}

function getPlayer() {
  return _player;
}
