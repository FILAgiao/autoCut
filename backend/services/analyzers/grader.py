"""综合评级分析器 — 汇总所有分析结果，输出 A/B/C/D/废"""

from .base import BaseAnalyzer, AnalysisContext, AnalysisResult


class GraderAnalyzer(BaseAnalyzer):
    """汇总评级，利用前面所有分析器的结果"""

    name = "grader"
    priority = 100  # 最后跑

    # 各维度权重（可调）
    WEIGHTS = {
        "confidence": 0.25,
        "filler_words": 0.20,
        "fluency": 0.20,
        "script_match": 0.25,
        "abandoned": 0.10,
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
        # Grader 不单独分析，需要拿到前面所有结果
        # 这里返回默认值，实际评级在 run_all_analyzers 中完成
        return AnalysisResult(
            analyzer_name=self.name,
            tags=[],
            score=0,
            severity="good",
            details={},
        )


def compute_grade(results: list[AnalysisResult]) -> tuple[str, float, list[str]]:
    """
    根据所有分析结果计算综合等级
    返回: (等级, 分数, 所有标签)
    """
    weights = GraderAnalyzer.WEIGHTS

    weighted_score = 0.0
    total_weight = 0.0
    all_tags = []

    for r in results:
        w = weights.get(r.analyzer_name, 0.1)
        weighted_score += r.score * w
        total_weight += w

        if r.tags:
            all_tags.extend(r.tags)

    if total_weight > 0:
        final_score = weighted_score / total_weight
    else:
        final_score = 50

    # 检查是否废片
    is_abandoned = any(r.is_abandoned for r in results)

    if is_abandoned:
        grade = "废"
    elif final_score >= 85:
        grade = "A"
    elif final_score >= 70:
        grade = "B"
    elif final_score >= 50:
        grade = "C"
    else:
        grade = "D"

    return grade, round(final_score, 1), all_tags


def grade_to_color(grade: str) -> str:
    """等级对应的颜色"""
    return {
        "A": "#2ecc71",  # 绿色
        "B": "#f1c40f",  # 黄色
        "C": "#f39c12",  # 橙色
        "D": "#e74c3c",  # 红色
        "废": "#95a5a6",  # 灰色
    }.get(grade, "#888")
