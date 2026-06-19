"""流畅度分析器"""

import re
from .base import BaseAnalyzer, AnalysisContext, AnalysisResult


class FluencyAnalyzer(BaseAnalyzer):
    """分析语速、停顿、结巴等流畅度指标"""

    name = "fluency"
    priority = 20

    # 正常中文语速范围（字/秒）
    NORMAL_MIN = 3.0
    NORMAL_MAX = 5.0

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

        # 有效字数（去掉标点和空白）
        clean_text = re.sub(r"[，。！？、；：\u201c\u201d\u2018\u2019（）【】《》\s,\.!\?;:\"'\(\)\[\]{}]", "", text)
        char_count = len(clean_text)

        tags = []
        score_deduct = 0

        # 1. 语速
        speed = char_count / duration if duration > 0 else 0
        speed_label = ""
        if speed < self.NORMAL_MIN:
            score_deduct += 20
            speed_label = "偏慢"
            tags.append("偏慢")
        elif speed > self.NORMAL_MAX:
            score_deduct += 15
            speed_label = "偏快"
            tags.append("偏快")
        else:
            speed_label = "正常"

        # 2. 结巴检测（同字重复3次以上）
        stutter_patterns = re.findall(r"(.)\1{2,}", text)
        stutter_count = len(stutter_patterns)
        if stutter_count > 2:
            score_deduct += 25
            tags.append("结巴")
        elif stutter_count > 0:
            score_deduct += 10

        # 3. 长停顿检测（基于标点间隙估算）
        # ASR 如果有词级时间戳会更精确，这里用标点做粗略估计
        long_pause_count = text.count("。。。") + text.count("......")
        if long_pause_count > 0:
            score_deduct += 10
            tags.append("停顿多")

        # 4. 句首语气词（呃...今天 | 啊...那个）
        # 如果句子开头是语气词+很短的片段，可能是忘词
        if duration < 3.0 and re.match(r"^[呃嗯啊哦额唔]", text.strip()):
            score_deduct += 5
            tags.append("开头犹豫")

        score = max(100 - score_deduct, 10)

        if score >= 85:
            severity = "good"
            if not tags:
                tags = ["流畅"]
        elif score >= 60:
            severity = "warning"
        else:
            severity = "error"
            if "偏慢" in tags and "结巴" in tags:
                tags = ["卡顿多"]

        return AnalysisResult(
            analyzer_name=self.name,
            tags=tags if tags else ["流畅"],
            score=score,
            severity=severity,
            details={
                "speed": round(speed, 1),
                "speed_label": speed_label,
                "char_count": char_count,
                "stutter_count": stutter_count,
            },
        )
