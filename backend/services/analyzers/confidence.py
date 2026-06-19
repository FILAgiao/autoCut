"""置信度评级分析器"""

from .base import BaseAnalyzer, AnalysisContext, AnalysisResult


class ConfidenceAnalyzer(BaseAnalyzer):
    """基于 ASR 置信度评级"""

    name = "confidence"
    priority = 15

    def analyze(
        self,
        text: str,
        start: float,
        end: float,
        asr_confidence: float,
        script_sentence: str,
        context: AnalysisContext = None,
    ) -> AnalysisResult:
        if asr_confidence >= 0.95:
            score, severity, tag = 95, "good", "清晰"
        elif asr_confidence >= 0.85:
            score, severity, tag = 75, "warning", "略模糊"
        elif asr_confidence >= 0.70:
            score, severity, tag = 50, "warning", "模糊"
        else:
            score, severity, tag = 20, "error", "很不清晰"

        return AnalysisResult(
            analyzer_name=self.name,
            tags=[tag],
            score=score,
            severity=severity,
            details={
                "confidence": round(asr_confidence, 3),
            },
        )
