/* ====== 重点词检测 ====== */

const KEYWORD_PATTERNS = {
  number: /\d+(?:\.\d+)?[万亿千百]?/,
  emphasis: /(很|非常|特别|超级|绝对|一定|必须|真的|极其|尤其|格外|万分|十分|相当|最|更|超)/,
  transition: /(但是|可是|然而|不过|所以|因此|因为|虽然|如果|那么|而且|并且|或者|然后|接着|于是|否则|总之|其实|当然|毕竟|反正|甚至|除非|只要|只有|无论)/,
  english: /[a-zA-Z]+/,
  quote: /[""「」『』].*?[""「」『』]/,
};

const KEYWORD_TYPES = {
  number: { label: '数字', color: '#FFD700' },
  emphasis: { label: '强调', color: '#FF6B6B' },
  transition: { label: '转折', color: '#4ECDC4' },
  english: { label: '英文', color: '#A78BFA' },
  quote: { label: '引语', color: '#F97316' },
};

function detectKeywords(text) {
  if (!text || !text.trim()) return [];

  const results = [];

  // 先按标点+空格分割大段
  const segments = text.split(/([，。！？、；：,\.!\?;:\s]+)/).filter(Boolean);

  for (const seg of segments) {
    // 纯标点/空格：直接输出
    if (/^[，。！？、；：,\.!\?;:\s]+$/.test(seg)) {
      results.push({ word: seg, isKeyword: false, type: null });
      continue;
    }

    // 扫描 segment 中的关键词匹配
    let pos = 0;
    while (pos < seg.length) {
      let matched = false;
      let bestMatch = null;
      let bestLen = 0;

      // 尝试每个模式，从当前位置匹配
      for (const [type, pattern] of Object.entries(KEYWORD_PATTERNS)) {
        const sub = seg.substring(pos);
        const m = sub.match(pattern);
        if (m && m.index === 0) {
          const matchLen = m[0].length;
          if (matchLen > bestLen) {
            bestMatch = { type, word: m[0] };
            bestLen = matchLen;
          }
        }
      }

      if (bestMatch) {
        matched = true;
        const info = KEYWORD_TYPES[bestMatch.type];
        results.push({
          word: bestMatch.word,
          isKeyword: true,
          type: bestMatch.type,
          ...info,
        });
        pos += bestLen;
      } else {
        // 未匹配：取下一个字符或到下一个可能的关键词
        const remaining = seg.substring(pos);
        // 查找下一个可能关键词的起始位置
        let nextPos = remaining.length;
        const multiCharPatterns = ['但是','可是','然而','不过','所以','因此','因为','虽然','如果','那么',
          '而且','并且','或者','然后','接着','于是','否则','总之','其实','当然','毕竟','反正',
          '甚至','除非','只要','只有','无论','非常','特别','超级','绝对','一定','必须','极其',
          '尤其','格外','万分','十分','相当'];
        for (const kw of multiCharPatterns) {
          const idx = remaining.indexOf(kw);
          if (idx > 0 && idx < nextPos) nextPos = idx;
        }
        // 也检查英文和数字
        const enMatch = remaining.match(/[a-zA-Z]/);
        if (enMatch && enMatch.index > 0 && enMatch.index < nextPos) nextPos = enMatch.index;
        const numMatch = remaining.match(/\d/);
        if (numMatch && numMatch.index > 0 && numMatch.index < nextPos) nextPos = numMatch.index;

        if (nextPos > 0) {
          results.push({ word: remaining.substring(0, nextPos), isKeyword: false, type: null });
          pos += nextPos;
        } else {
          results.push({ word: remaining, isKeyword: false, type: null });
          pos = seg.length;
        }
      }
    }
  }

  return results;
}

function getKeywordTokens(text, keywordColor, emphasizeColor) {
  const detected = detectKeywords(text);
  return detected.map(d => ({
    ...d,
    color: d.isKeyword ? (d.type === 'emphasis' ? (emphasizeColor || d.color) : (keywordColor || d.color)) : null,
  }));
}
