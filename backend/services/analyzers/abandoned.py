"""废片检测分析器"""

import re
from .base import BaseAnalyzer, AnalysisContext, AnalysisResult


class AbandonedAnalyzer(BaseAnalyzer):
    """检测录音是否被放弃（NG、中断、重录）"""

    name = "abandoned"
    priority = 5  # 最先跑

    # 强信号词：几乎一定表示废片
    STRONG_ABANDON = [
        "重来", "重新来", "再来一遍", "重录", "不录了",
        "NG", "过吧", "废了", "说错了", "嘴瓢了",
    ]

    # 弱信号词：可能出现在正常语句中，需额外条件
    WEAK_ABANDON = ["算了", "不行", "再来", "不好", "不对", "错了"]

    # 叹气词
    SIGH_WORDS = {"唉", "哎", "害", "嗨"}

    def analyze(
        self,
        text: str,
        start: float,
        end: float,
        asr_confidence: float,
        script_sentence: str,
        context: AnalysisContext = None,
    ) -> AnalysisResult:
        reasons = []
        is_abandoned = False
        duration = end - start

        # 1. 检测放弃关键词
        text_lower = text.lower()
        # 强信号：几乎一定废片
        for phrase in self.STRONG_ABANDON:
            if phrase in text_lower:
                reasons.append(f"含放弃词「{phrase}」")
                is_abandoned = True
                break
        # 弱信号：需要额外条件（短文本 或 出现在句首）
        if not is_abandoned:
            for phrase in self.WEAK_ABANDON:
                pos = text_lower.find(phrase)
                if pos >= 0:
                    text_short = len(text.strip()) < 15
                    at_start = pos <= 3
                    if text_short or at_start:
                        reasons.append(f"含放弃词「{phrase}」")
                        is_abandoned = True
                        break

        # 2. 检测句子不完整（不以正常结束符收尾）
        if not is_abandoned and len(text.strip()) > 5:
            if not re.search(r"[。！？\.!\?]$", text.strip()):
                # 只有比较短的时候才怀疑
                expected_dur = len(script_sentence) / 3.5 if script_sentence else duration
                if duration < expected_dur * 0.6 and asr_confidence < 0.9:
                    reasons.append("句子不完整（被截断）")
                    is_abandoned = True

        # 3. 检测时长明显过短
        if not is_abandoned and script_sentence:
            expected_duration = len(script_sentence) / 3.5  # 约3.5字/秒
            if duration < expected_duration * 0.35:
                reasons.append(f"过短（{duration:.1f}s，预期 ~{expected_duration:.1f}s）")
                is_abandoned = True

        # 4. 检测跟上一遍开头相同（说明刚才是废片，立刻重录）
        if not is_abandoned and context and context.prev_segment_text:
            this_start = text[:6] if len(text) >= 6 else text
            prev_start = context.prev_segment_text[:6] if len(context.prev_segment_text) >= 6 else context.prev_segment_text
            # 前一段结束和这一段开始之间的间隔
            gap = start - context.prev_segment_end
            if gap < 1.5 and this_start == prev_start and len(this_start) >= 4:
                reasons.append("疑似连续重录（开头相同且间隔短）")
                # 不一定是废片，只是可疑

        # 5. 检测极度低置信度
        if asr_confidence < 0.5 and duration < 3.0:
            reasons.append("极低置信度（可能是乱语/环境音）")
            is_abandoned = True

        # 评级
        if is_abandoned:
            score, severity = 0, "error"
        elif reasons:
            score, severity = 40, "warning"
        else:
            score, severity = 100, "good"

        return AnalysisResult(
            analyzer_name=self.name,
            tags=["废片"] if is_abandoned else (["可疑"] if reasons else []),
            score=score,
            severity=severity,
            details={"reasons": reasons},
            is_abandoned=is_abandoned,
            abandon_reason="; ".join(reasons) if reasons else "",
        )
