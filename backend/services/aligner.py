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


# ──── 无脚本聚类 ────

CLUSTER_PROMPT = """你是一个文本聚类专家。以下是一段口播视频的语音识别结果。说话人把同一句话重复讲了多次（因为口播需要录到满意为止）。请找出所有语义相同、重复讲述的句子，把它们聚类。

【语音识别结果】（每个段落有编号、时间戳和文本）
{asr_segments}

任务：
1. 找出所有表达相同内容、但可能已讲过多次的句子，将它们归为一组
2. 每组代表"脚本中的一句话"，可能有多遍（takes）
3. 按时间顺序排列各组（取最早的 take 时间）
4. 任何不属于任何组的片段放入 unmatched
5. 为每个组生成一句最合理的"规范版本文本"（取讲得最好、最完整的版本）

返回严格的 JSON 格式，不要有其他文字：
{{
  "clusters": [
    {{
      "text": "规范版本文本",
      "takes": [
        {{"segment_index": 0, "confidence": 1.0}},
        {{"segment_index": 3, "confidence": 0.9}}
      ]
    }}
  ],
  "unmatched": [5, 7]
}}

注意事项：
- 语义相同但措辞不同也要归为一组（比如"这功能很好用"和"这个功能真的很好用"算同一组）
- 一组可能只有一遍（只讲了一次），也可能有多遍（重复讲了多次）
- confidence 表示这遍讲得有多好：1.0=完美，0.7以下=不太好
- 不要把不同内容的句子归到一起"""


class SegmentClusterer:
    """无脚本模式：聚类相似 ASR 片段"""

    def __init__(self):
        self.api_base = settings.LLM_API_BASE
        self.api_key = settings.LLM_API_KEY
        self.model = settings.LLM_MODEL

    @property
    def is_available(self) -> bool:
        return bool(self.api_key and self.model)

    def cluster(self, asr_segments: list[dict]) -> dict:
        """对 ASR 片段聚类，自动发现重复讲的内容"""
        if not asr_segments:
            return {"clusters": [], "unmatched": []}

        if self.is_available:
            try:
                return self._llm_cluster(asr_segments)
            except Exception as e:
                print(f"LLM 聚类失败，降级到简易聚类: {e}")

        return self._fallback_cluster(asr_segments)

    def _llm_cluster(self, asr_segments: list[dict]) -> dict:
        """使用 LLM 进行语义聚类"""
        seg_lines = "\n".join(
            f"[{i}] [{s['start']:.1f}s-{s['end']:.1f}s] conf={s.get('confidence', 0):.2f} {s['text']}"
            for i, s in enumerate(asr_segments)
        )
        prompt = CLUSTER_PROMPT.format(asr_segments=seg_lines)

        from openai import OpenAI
        client = OpenAI(base_url=self.api_base, api_key=self.api_key)
        resp = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=4096,
        )
        content = resp.choices[0].message.content.strip()

        if content.startswith("```"):
            content = re.sub(r"^```\w*\n?", "", content)
            content = re.sub(r"\n```$", "", content)

        return json.loads(content)

    def _fallback_cluster(self, asr_segments: list[dict]) -> dict:
        """降级方案：基于文本相似度的简易聚类"""
        threshold = 0.5
        clusters = []
        used = set()

        for i, seg_a in enumerate(asr_segments):
            if i in used:
                continue
            text_a = LLMAligner._normalize(seg_a.get("text", ""))
            if len(text_a) < 3:
                used.add(i)
                continue

            cluster = {"text": seg_a["text"], "takes": [
                {"segment_index": i, "confidence": 1.0}
            ]}
            used.add(i)

            for j, seg_b in enumerate(asr_segments):
                if j in used:
                    continue
                text_b = LLMAligner._normalize(seg_b.get("text", ""))
                if len(text_b) < 3:
                    used.add(j)
                    continue

                ratio = levenshtein_ratio(text_a, text_b)
                if ratio >= threshold:
                    cluster["takes"].append({
                        "segment_index": j,
                        "confidence": round(ratio, 2),
                    })
                    used.add(j)

            clusters.append(cluster)

        return {"clusters": clusters, "unmatched": []}


def cluster_result_to_model(
    asr_segments: list[dict],
    cluster_data: dict,
) -> tuple:
    """将聚类结果转换到数据模型"""
    from backend.models.schemas import (
        AnalyzedTake, ScriptSentence, UnmatchedSegment
    )

    clusters = cluster_data.get("clusters", [])
    sentences = []
    for ci, cluster in enumerate(clusters):
        takes = []
        for ti, take_info in enumerate(cluster.get("takes", [])):
            seg_idx = take_info["segment_index"]
            if seg_idx < len(asr_segments):
                seg = asr_segments[seg_idx]
                takes.append(AnalyzedTake(
                    index=ti,
                    text=seg["text"],
                    start=seg["start"],
                    end=seg["end"],
                    duration=round(seg["end"] - seg["start"], 2),
                    confidence=seg.get("confidence", 0.0),
                ))
        if takes:
            sentences.append(ScriptSentence(
                index=ci,
                text=cluster.get("text", takes[0].text if takes else ""),
                takes=takes,
            ))

    unmatched_indices = set(cluster_data.get("unmatched", []))
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
