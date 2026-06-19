/* ====== 时间轴可视化 ====== */

function drawTimeline() {
  const canvas = document.getElementById('timeline-canvas');
  if (!canvas) return;

  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;

  // 设置 canvas 实际尺寸
  const rect = canvas.parentElement.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  canvas.style.width = rect.width + 'px';
  canvas.style.height = rect.height + 'px';
  ctx.scale(dpr, dpr);

  const w = rect.width;
  const h = rect.height;
  const padX = 4;
  const padY = 6;
  const barH = h - padY * 2;

  if (!STATE.videoDuration || !STATE.sentences.length) {
    ctx.fillStyle = '#555';
    ctx.fillRect(padX, padY, w - padX * 2, barH);
    return;
  }

  // 计算每个句子在时间轴上的位置
  ctx.clearRect(0, 0, w, h);

  STATE.sentences.forEach((sent, i) => {
    if (!sent.takes.length) return;

    // 找一个代表 take 来确定时间位置
    const take = sent.confirmed_take_index >= 0
      ? sent.takes[sent.confirmed_take_index]
      : sent.takes[0];

    const xStart = padX + (take.start / STATE.videoDuration) * (w - padX * 2);
    const xEnd = padX + (take.end / STATE.videoDuration) * (w - padX * 2);
    const rectW = Math.max(xEnd - xStart, 3);

    // 颜色
    let color;
    if (sent.confirmed_take_index >= 0) {
      const grade = sent.takes[sent.confirmed_take_index]?.grade || '';
      color = gradeToCSS(grade);
    } else if (i === STATE.currentSentence) {
      color = '#f1c40f';  // 黄色 = 当前
    } else if (sent.takes.some(t => t.is_abandoned || t.grade === '废')) {
      color = '#e74c3c';  // 红色 = 含废片
    } else {
      color = '#555';     // 灰色 = 待处理
    }

    ctx.fillStyle = color;
    ctx.fillRect(xStart, padY, rectW, barH);

    // 当前句子高亮边框
    if (i === STATE.currentSentence) {
      ctx.strokeStyle = '#fff';
      ctx.lineWidth = 1.5;
      ctx.strokeRect(xStart - 1, padY - 1, rectW + 2, barH + 2);
    }
  });
}

// 窗口改变时重绘
window.addEventListener('resize', () => {
  if (STATE.status === 'editing') drawTimeline();
});
