"""分析引擎 - 注册与调度

新增分析器步骤：
1. 新建 .py 文件，继承 BaseAnalyzer
2. 实现 analyze() 方法
3. 在此文件 import 并使用 @register 装饰
4. 放入 analyzers/ 目录即可
"""

from .base import BaseAnalyzer, AnalysisContext, AnalysisResult
from .filler_words import FillerWordAnalyzer
from .abandoned import AbandonedAnalyzer
from .fluency import FluencyAnalyzer
from .script_match import ScriptMatchAnalyzer
from .confidence import ConfidenceAnalyzer
from .grader import GraderAnalyzer, compute_grade

# ──── 分析器注册表 ────

_ANALYZER_REGISTRY: list[BaseAnalyzer] = []


def register(analyzer_cls):
    """装饰器：注册分析器"""
    instance = analyzer_cls()
    _ANALYZER_REGISTRY.append(instance)
    # 按 priority 排序
    _ANALYZER_REGISTRY.sort(key=lambda a: a.priority)
    return analyzer_cls


# ──── 注册所有分析器 ────

@register
class _Filler(FillerWordAnalyzer):
    pass


@register
class _Abandoned(AbandonedAnalyzer):
    pass


@register
class _Confidence(ConfidenceAnalyzer):
    pass


@register
class _Fluency(FluencyAnalyzer):
    pass


@register
class _ScriptMatch(ScriptMatchAnalyzer):
    pass


@register
class _Grader(GraderAnalyzer):
    pass


# ──── 统一分析接口 ────

def run_all_analyzers(
    text: str,
    start: float,
    end: float,
    asr_confidence: float,
    script_sentence: str,
    context: AnalysisContext = None,
) -> dict:
    """
    运行所有已注册的分析器，返回综合分析结果

    返回:
    {
        "grade": "A",       # A/B/C/D/废
        "grade_score": 92.5,
        "all_tags": [...],  # 所有标签
        "is_abandoned": bool,
        "abandon_reason": "",
        "results": [...],   # 每个分析器的详细结果
    }
    """
    all_results = []
    all_tags = []
    is_abandoned = False
    abandon_reason = ""

    for analyzer in _ANALYZER_REGISTRY:
        if analyzer.name == "grader":
            continue  # Grader 最后统一调

        try:
            result = analyzer.analyze(
                text, start, end, asr_confidence, script_sentence, context
            )
            all_results.append(result)
            all_tags.extend(result.tags)

            if result.is_abandoned:
                is_abandoned = True
                if result.abandon_reason:
                    abandon_reason = result.abandon_reason
        except Exception as e:
            # 单个分析器失败不影响整体
            all_results.append(AnalysisResult(
                analyzer_name=analyzer.name,
                tags=[],
                score=0,
                severity="info",
                details={"error": str(e)},
            ))

    # 综合评级
    grade, grade_score, _ = compute_grade(all_results)

    if is_abandoned:
        grade = "废"
        grade_score = 0

    # 转成可序列化的格式
    serializable_results = []
    for r in all_results:
        serializable_results.append({
            "analyzer_name": r.analyzer_name,
            "tags": r.tags,
            "score": r.score,
            "severity": r.severity,
            "details": r.details,
        })

    return {
        "grade": grade,
        "grade_score": grade_score,
        "all_tags": all_tags,
        "is_abandoned": is_abandoned,
        "abandon_reason": abandon_reason,
        "results": serializable_results,
    }


def get_registered_analyzers() -> list[str]:
    """列出所有已注册的分析器"""
    return [a.name for a in _ANALYZER_REGISTRY]
