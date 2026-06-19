"""Pydantic 数据模型"""

from pydantic import BaseModel
from enum import Enum


# ──── 上传 ────

class UploadResponse(BaseModel):
    task_id: str
    status: str  # "processing" | "done" | "error"


# ──── ASR 结果 ────

class ASRSegment(BaseModel):
    text: str
    start: float  # 秒
    end: float
    confidence: float


# ──── 分析结果 ────

class AnalysisTag(BaseModel):
    label: str        # "口癖多" / "废片" / "流畅" / ...
    severity: str     # "good" | "info" | "warning" | "error"
    detail: str = ""  # "呃x2, 那个" / "截断" / ...


class AnalyzedTake(BaseModel):
    """一个录音版本（一句话讲了一遍）"""
    index: int                    # 在本句中的序号 0-based
    text: str                     # ASR 转写文本
    start: float                  # 开始时间（秒）
    end: float                    # 结束时间（秒）
    duration: float               # 时长（秒）
    confidence: float             # ASR 置信度
    grade: str = ""               # A/B/C/D/废
    grade_score: float = 0        # 0-100
    tags: list[AnalysisTag] = []
    is_abandoned: bool = False    # 是否废片
    abandon_reason: str = ""


class ScriptSentence(BaseModel):
    """脚本中的一句话"""
    index: int                    # 序号
    text: str                     # 脚本原文
    takes: list[AnalyzedTake] = []
    confirmed_take_index: int = -1  # 用户确认了哪个版本，-1=未确认
    is_unmatched: bool = False    # 在录音中没找到对应


class UnmatchedSegment(BaseModel):
    """ASR 中多出来、没匹配到脚本的片段"""
    text: str
    start: float
    end: float
    confidence: float


class ProcessResult(BaseModel):
    """处理完成后的完整结果"""
    task_id: str
    status: str  # "processing" | "done" | "error"
    error_message: str = ""
    video_filename: str = ""
    video_duration: float = 0
    sentences: list[ScriptSentence] = []
    unmatched: list[UnmatchedSegment] = []
    confirmed_count: int = 0
    total_count: int = 0


# ──── 分析器基类相关 ────

class AnalyzerResult(BaseModel):
    analyzer_name: str
    tags: list[str]
    score: float  # 0-100
    severity: str  # "good" | "info" | "warning" | "error"
    details: dict = {}


# ──── 字幕样式 ────

class SubtitleStyle(BaseModel):
    font: str = "Source Han Sans SC"
    font_size_ratio: float = 0.08
    color: str = "#FFFFFF"
    stroke_color: str = "#000000"
    stroke_width: float = 0.04
    position_y: float = -0.75
    keyword_color: str = "#FFD700"
    max_chars: int = 12


# ──── 导出请求 ────

class ExportOptions(BaseModel):
    include_srt: bool = True
    include_draft: bool = True
    include_text_guide: bool = False
    subtitle_style: SubtitleStyle | None = None


# ──── 状态 ────

class TaskStatus(str, Enum):
    UPLOADING = "uploading"
    EXTRACTING_AUDIO = "extracting_audio"
    ASR_PROCESSING = "asr_processing"
    ALIGNING = "aligning"
    ANALYZING = "analyzing"
    DONE = "done"
    ERROR = "error"
