"""口癖检测分析器"""

import re
from .base import BaseAnalyzer, AnalysisContext, AnalysisResult


class FillerWordAnalyzer(BaseAnalyzer):
    """检测语气填充词和口头禅"""

    name = "filler_words"
    priority = 10

    # 分类词库
    FILLER_SINGLE = {"呃", "啊", "嗯", "哦", "额", "唔", "唉", "啧", "嘛", "呢", "吧"}

    FILLER_PHRASES = [
        "那个", "这个", "就是说", "然后呢", "就是",
        "反正", "怎么说呢", "你知道吧", "对吧",
        "然后", "所以呢", "其实", "那种",
    ]

    def analyze(
        self,
        text: str,
        start: float,
        end: float,
        asr_confidence: float,
        script_sentence: str,
        context: AnalysisContext = None,
    ) -> AnalysisResult:
        duration = end - start
        if duration <= 0:
            return AnalysisResult(self.name, [], 100, "good", {})

        # 检测单字口癖
        single_found = []
        for w in self.FILLER_SINGLE:
            count = len(re.findall(w, text))
            if count > 0:
                single_found.append((w, count))

        # 检测口头禅短语
        phrase_found = []
        for phrase in self.FILLER_PHRASES:
            count = text.count(phrase)
            if count > 0:
                phrase_found.append((phrase, count))

        # 检测重复音节: 我我我, 这这这
        stutter = re.findall(r"(.)\1{2,}", text)
        stutter_count = len(stutter)

        total_count = sum(c for _, c in single_found) + sum(c for _, c in phrase_found) + stutter_count * 3
        density = total_count / duration  # 个/秒

        # 评级
        chars = len(text.replace(" ", "").replace("\u3000", ""))
        filler_ratio = total_count / max(chars, 1)

        if density <= 0.2 and filler_ratio < 0.1:
            score, severity, tag = 95, "good", "干净"
        elif density <= 0.5 and filler_ratio < 0.2:
            score, severity, tag = 75, "warning", "口癖"
        else:
            score, severity, tag = 45, "error", "口癖多"

        # 详情
        found_words = [w for w, _ in single_found[:3]] + [p for p, _ in phrase_found[:3]]
        detail = "、".join(found_words[:5]) if found_words else ""

        return AnalysisResult(
            analyzer_name=self.name,
            tags=[tag] if tag else [],
            score=score,
            severity=severity,
            details={
                "single_fillers": dict(single_found),
                "phrase_fillers": dict(phrase_found),
                "stutter_count": stutter_count,
                "total_count": total_count,
                "density": round(density, 2),
                "filler_ratio": round(filler_ratio, 2),
                "detail": detail,
            },
        )


# ──── 辅助函数（供前端和其他模块使用）───

def extract_filler_highlight(text: str) -> list[tuple[int, int, str]]:
    """标记口癖词在文本中的位置"""
    highlights = []
    all_fillers = FillerWordAnalyzer.FILLER_SINGLE | set(FillerWordAnalyzer.FILLER_PHRASES)

    for filler in sorted(all_fillers, key=len, reverse=True):
        for m in re.finditer(re.escape(filler), text):
            highlights.append((m.start(), m.end(), "filler"))

    # 重复音节
    for m in re.finditer(r"(.)\1{2,}", text):
        highlights.append((m.start(), m.end(), "stutter"))

    return sorted(highlights, key=lambda x: x[0])
