"""分析器基类"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AnalysisContext:
    """分析上下文 - 提供给每个分析器的辅助信息"""
    # 当前 segment
    segment_text: str
    segment_start: float
    segment_end: float
    segment_confidence: float

    # 对应的脚本句子
    script_sentence: str

    # 全局信息
    total_duration: float = 0.0       # 整个视频时长
    total_segments: int = 0           # 总片段数

    # 相邻片段（用于判断上下文）
    prev_segment_text: str = ""
    next_segment_text: str = ""
    prev_segment_end: float = 0.0
    next_segment_start: float = 0.0

    # 所有 ASR 段文本（用于全局统计）
    all_segment_texts: list[str] = field(default_factory=list)

    # 音频特征（如可用）
    audio_rms: Optional[list[float]] = None  # 段内音量采样


@dataclass
class AnalysisResult:
    analyzer_name: str
    tags: list[str]           # ["口癖多", "流畅", "废片"]
    score: float              # 0-100，越高越好
    severity: str             # "good" | "info" | "warning" | "error"
    details: dict = field(default_factory=dict)

    # 特殊标记
    is_abandoned: bool = False
    abandon_reason: str = ""


class BaseAnalyzer:
    """分析器基类 - 所有分析器继承此类"""

    name: str = "base"
    version: str = "1.0"
    priority: int = 100  # 越小越先执行

    def analyze(
        self,
        text: str,
        start: float,
        end: float,
        asr_confidence: float,
        script_sentence: str,
        context: Optional[AnalysisContext] = None,
    ) -> AnalysisResult:
        raise NotImplementedError
