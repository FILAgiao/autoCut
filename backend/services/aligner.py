"""LLM 语义对齐 — 将 ASR 结果匹配到脚本句子"""

import json
import re
from typing import Optional

try:
    from Levenshtein import ratio as levenshtein_ratio
except ImportError:
    # 纯 Python 降级
    def levenshtein_ratio(a: str, b: str) -> float:
        if not a and not b:
            return 1.0
        if not a or not b:
            return 0.0
        # 简化的编辑距离
        m, n = len(a), len(b)
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        for i in range(m + 1):
            dp[i][0] = i
        for j in range(n + 1):
            dp[0][j] = j
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                cost = 0 if a[i-1] == b[j-1] else 1
                dp[i][j] = min(dp[i-1][j] + 1, dp[i][j-1] + 1, dp[i-1][j-1] + cost)
        max_len = max(m, n)
        return 1.0 - dp[m][n] / max_len


from backend.config import settings


# ──── LLM 对齐 ────

ALIGNMENT_PROMPT = """你是一个文本对齐专家。请将语音识别结果匹配到对应的脚本句子。

【脚本文本】（一句一行，编号从0开始）
{script_lines}

【语音识别结果】（每个段落有编号、时间戳和文本）
{asr_segments}

任务：
1. 为每一句脚本，找出所有对应的识别结果（同一句话可能讲了多遍）
2. 识别结果中可能有多余的内容（跟脚本无关的），标记为 unmatched

返回严格的 JSON 格式，不要有其他文字：
{{
  "matches": [
    {{
      "script_index": 0,
      "takes": [
        {{"segment_index": 0, "confidence": 1.0}},
        {{"segment_index": 3, "confidence": 0.9}}
      ]
    }},
    ...
  ],
  "unmatched": [5, 7]
}}

注意事项：
- 语义相同但措辞不同也算匹配（比如"这功能很好用"匹配"这个功能真的很好用"）
- 一句话可能被重复讲多次，全部列出
- 识别结果中如果有一句跟所有脚本都不匹配，放入 unmatched
- confidence 表示匹配确信度: 1.0=完全匹配, 0.7以下=不太确定"""


class LLMAligner:
    """基于 LLM 的语义对齐器"""

    def __init__(self):
        self.api_base = settings.LLM_API_BASE
        self.api_key = settings.LLM_API_KEY
        self.model = settings.LLM_MODEL

    @property
    def is_available(self) -> bool:
        return bool(self.api_key and self.model)

    def align(self, script_sentences: list[str],
              asr_segments: list[dict]) -> dict:
        """
        对齐脚本和 ASR 结果
        script_sentences: ["句子1", "句子2", ...]
        asr_segments: [{"text": ..., "start": ..., "end": ..., "confidence": ...}, ...]
        返回: {"matches": [...], "unmatched": [...]}
        """
        if self.is_available:
            try:
                return self._llm_align(script_sentences, asr_segments)
            except Exception as e:
                print(f"LLM 对齐失败，降级到编辑距离: {e}")

        return self._fallback_align(script_sentences, asr_segments)

    def _llm_align(self, script_sentences: list[str],
                   asr_segments: list[dict]) -> dict:
        """使用 LLM 进行语义对齐"""
        # 构建 prompt
        script_lines = "\n".join(
            f"[{i}] {s}" for i, s in enumerate(script_sentences)
        )
        seg_lines = "\n".join(
            f"[{i}] [{s['start']:.1f}s-{s['end']:.1f}s] conf={s['confidence']:.2f} {s['text']}"
            for i, s in enumerate(asr_segments)
        )
        prompt = ALIGNMENT_PROMPT.format(
            script_lines=script_lines,
            asr_segments=seg_lines,
        )

        # 调 LLM
        from openai import OpenAI
        client = OpenAI(base_url=self.api_base, api_key=self.api_key)
        resp = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=4096,
        )
        content = resp.choices[0].message.content.strip()

        # 解析 JSON（可能被 markdown 代码块包裹）
        if content.startswith("```"):
            content = re.sub(r"^```\w*\n?", "", content)
            content = re.sub(r"\n```$", "", content)

        return json.loads(content)

    def _fallback_align(self, script_sentences: list[str],
                        asr_segments: list[dict]) -> dict:
        """降级方案：编辑距离匹配"""
        matches = {}
        unmatched = []

        for seg_idx, seg in enumerate(asr_segments):
            seg_text = seg["text"].strip()
            if not seg_text:
                unmatched.append(seg_idx)
                continue

            # 找最佳匹配的脚本句子
            best_idx = -1
            best_ratio = 0.0
            for scr_idx, scr_text in enumerate(script_sentences):
                ratio = levenshtein_ratio(self._normalize(seg_text),
                                         self._normalize(scr_text))
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_idx = scr_idx

            # 阈值 0.35，低于则认为不匹配
            if best_ratio < 0.35:
                unmatched.append(seg_idx)
            else:
                if best_idx not in matches:
                    matches[best_idx] = {"script_index": best_idx, "takes": []}
                matches[best_idx]["takes"].append({
                    "segment_index": seg_idx,
                    "confidence": round(best_ratio, 2),
                })

        return {
            "matches": sorted(matches.values(), key=lambda m: m["script_index"]),
            "unmatched": unmatched,
        }

    @staticmethod
    def _normalize(text: str) -> str:
        """文本归一化：去标点、去空格"""
        import re
        # 去掉所有标点和空白
        text = re.sub(r"[，。！？、；：\u201c\u201d\u2018\u2019（）【】《》\s,\.!\?;:\"'\(\)\[\]{}]", "", text)
        return text.lower()


# ──── 便捷函数 ────

def align_result_to_model(
    script_sentences: list[str],
    asr_segments: list[dict],
    alignment: dict,
) -> tuple:
    """
    将对齐结果转换到数据模型

    返回:
    - sentences: list[dict] 每个脚本句子及其匹配的 ASR 片段
    - unmatched: list[dict] 未匹配的 ASR 片段
    """
    from backend.models.schemas import (
        AnalyzedTake, ScriptSentence, UnmatchedSegment, AnalysisTag
    )

    # 构建 script_index -> takes 的映射
    script_takes_map: dict[int, list] = {}
    for match in alignment.get("matches", []):
        si = match["script_index"]
        if si not in script_takes_map:
            script_takes_map[si] = []
        for take in match.get("takes", []):
            seg_idx = take["segment_index"]
            seg = asr_segments[seg_idx]
            script_takes_map[si].append({
                "segment_index": seg_idx,
                "match_confidence": take.get("confidence", 0.5),
                "text": seg["text"],
                "start": seg["start"],
                "end": seg["end"],
                "asr_confidence": seg.get("confidence", 0.0),
            })

    # 构建 ScriptSentence 列表
    sentences = []
    for i, text in enumerate(script_sentences):
        takes_raw = script_takes_map.get(i, [])
        takes = []
        for ti, t in enumerate(takes_raw):
            takes.append(AnalyzedTake(
                index=ti,
                text=t["text"],
                start=t["start"],
                end=t["end"],
                duration=round(t["end"] - t["start"], 2),
                confidence=t["asr_confidence"],
            ))
        sentences.append(ScriptSentence(
            index=i,
            text=text,
            takes=takes,
            is_unmatched=(len(takes) == 0),
        ))

    # 构建 UnmatchedSegment 列表
    unmatched_indices = set(alignment.get("unmatched", []))
    unmatched = []
    for idx in unmatched_indices:
        if idx < len(asr_segments):
            seg = asr_segments[idx]
            unmatched.append(UnmatchedSegment(
                text=seg["text"],
                start=seg["start"],
                end=seg["end"],
                confidence=seg.get("confidence", 0.0),
            ))

    return sentences, unmatched
