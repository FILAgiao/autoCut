"""脚本匹配度分析器"""

import re
from .base import BaseAnalyzer, AnalysisContext, AnalysisResult

try:
    from Levenshtein import ratio as levenshtein_ratio
except ImportError:
    def levenshtein_ratio(a: str, b: str) -> float:
        if not a and not b:
            return 1.0
        if not a or not b:
            return 0.0
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


class ScriptMatchAnalyzer(BaseAnalyzer):
    """分析 ASR 文本与脚本原文的匹配程度"""

    name = "script_match"
    priority = 30

    # 口癖词（匹配时先去掉）
    FILLERS_TO_STRIP = {
        "呃", "啊", "嗯", "哦", "额", "唔", "唉", "啧", "嘛", "呢", "吧",
        "那个", "这个", "就是说", "然后呢", "就是", "反正", "怎么说呢",
        "你知道吧", "对吧", "然后", "所以呢", "其实", "那种",
    }

    def analyze(
        self,
        text: str,
        start: float,
        end: float,
        asr_confidence: float,
        script_sentence: str,
        context: AnalysisContext = None,
    ) -> AnalysisResult:
        if not script_sentence or not text:
            return AnalysisResult(self.name, [], 0, "error", {"ratio": 0})

        # 归一化
        norm_text = self._normalize(text)
        norm_script = self._normalize(script_sentence)

        # 去掉口癖词后再比一次
        clean_text = self._strip_fillers(norm_text)
        clean_script = self._strip_fillers(norm_script)

        # 编辑距离相似度
        raw_ratio = levenshtein_ratio(norm_text, norm_script)
        clean_ratio = levenshtein_ratio(clean_text, clean_script)

        # 取两种比对的较好值
        ratio = max(raw_ratio, clean_ratio)

        # 关键词覆盖
        script_keywords = self._extract_keywords(script_sentence)
        if script_keywords:
            kw_hits = sum(1 for kw in script_keywords if kw in text)
            kw_coverage = kw_hits / len(script_keywords)
        else:
            kw_coverage = 1.0

        # 综合匹配分（编辑距离为主，关键词覆盖为辅）
        match_score = ratio * 0.7 + kw_coverage * 0.3

        # 评级
        if match_score >= 0.9:
            score, severity = 95, "good"
            tag = "" if ratio >= 0.95 else "轻微偏离"
        elif match_score >= 0.7:
            score, severity = 70, "warning"
            tag = "部分偏离"
        elif match_score >= 0.5:
            score, severity = 45, "warning"
            tag = "较大偏离"
        else:
            score, severity = 20, "error"
            tag = "严重偏离"

        return AnalysisResult(
            analyzer_name=self.name,
            tags=[tag] if tag else [],
            score=score,
            severity=severity,
            details={
                "ratio": round(ratio, 2),
                "raw_ratio": round(raw_ratio, 2),
                "clean_ratio": round(clean_ratio, 2),
                "keyword_coverage": round(kw_coverage, 2),
                "match_score": round(match_score, 2),
            },
        )

    @staticmethod
    def _normalize(text: str) -> str:
        """文本归一化"""
        text = re.sub(r"[，。！？、；：\u201c\u201d\u2018\u2019（）【】《》\s,\.!\?;:\"'\(\)\[\]{}]", "", text)
        return text.lower()

    @staticmethod
    def _strip_fillers(text: str) -> str:
        """去掉口癖词"""
        result = text
        for filler in sorted(ScriptMatchAnalyzer.FILLERS_TO_STRIP, key=len, reverse=True):
            result = result.replace(filler, "")
        return result

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        """提取关键词（简单的2字以上实词）"""
        text = re.sub(r"[，。！？、；：\u201c\u201d\u2018\u2019（）【】《》\s,\.!\?;:\"'\(\)\[\]{}]", "", text)
        # 取 2-4 字的片段作为关键词
        kw = []
        for i in range(len(text) - 1):
            chunk = text[i:i+2]
            if chunk not in kw:
                kw.append(chunk)
        # 再取 4 字片段
        for i in range(len(text) - 3):
            chunk = text[i:i+4]
            if chunk not in kw:
                kw.append(chunk)
        return kw[:20]  # 限制数量
