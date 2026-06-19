"""脚本智能分句 — 支持段落、换行、混合格式"""

import re


def smart_split_script(text: str) -> list[str]:
    """
    智能分句：自动识别并拆分句子。

    支持格式：
    - 段落文本（"大家好。今天分享一个东西。很好用！"）
    - 每行一句（传统格式）
    - 混合格式（段落 + 换行）

    拆分规则：
    1. 先按换行粗拆
    2. 再按句末标点（。！？!?）精拆
    3. 过滤空白行
    """
    if not text or not text.strip():
        return []

    lines = text.strip().split("\n")
    sentences = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        # 按句子结束标点拆分：。！？!? 后面是非空白字符时断开
        parts = re.split(r"(?<=[。！？!?])(?=\s*\S)", line)
        for part in parts:
            part = part.strip()
            if part:
                sentences.append(part)

    return sentences
