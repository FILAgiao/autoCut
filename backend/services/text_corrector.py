"""LLM 文本纠错 — 用大模型检查 ASR 全文中的错别字、同音字错误

在 ASR 识别完成后运行，利用大语言模型的上下文理解能力，
发现语音识别容易出错的地方（如同音字、漏字、断句错误等）。
"""

import difflib
from openai import AsyncOpenAI
from backend.config import settings


async def correct_transcript(full_text: str) -> str:
    """用 LLM 校对口播全文，纠正明显错误

    Args:
        full_text: ASR 识别返回的完整文本

    Returns:
        纠正后的文本，如果 LLM 不可用则返回原文
    """
    if not full_text or not full_text.strip():
        return full_text

    if not (settings.LLM_API_KEY and settings.LLM_MODEL):
        return full_text  # LLM 未配置，跳过

    client = AsyncOpenAI(
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_API_BASE,
    )

    prompt = f"""你是一个专业的文字校对助手。以下是一段语音识别（ASR）转写的口播文本，可能包含一些错误。

常见的 ASR 错误类型：
1. 同音字错误（如 "在" 误识别为 "再"，"的" 误识别为 "得"）
2. 漏字或多字
3. 断句错误
4. 口语填充词造成的碎片

请检查并纠正文本中的明显错误。注意：
- 只修改明显错误的地方，保持原意不变
- 这是一段口播内容，保留口语化的表达方式
- 不要改写句子结构
- 直接返回纠正后的全文，不要加任何解释或标记

原文：
{full_text}

纠正后的文本："""

    try:
        response = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=min(len(full_text) * 2, 4096),
        )
        corrected = response.choices[0].message.content
        if corrected:
            return corrected.strip()
    except Exception as e:
        print(f"[text_corrector] LLM 纠错失败: {e}")

    return full_text


def apply_corrections_to_segments(segments: list[dict], corrected_full_text: str) -> list[dict]:
    """将 LLM 纠错后的全文变化映射回各个片段，更新每个片段的 text 字段"""
    if not segments or not corrected_full_text:
        return segments

    try:
        original_text = ""
        boundaries = []  # (start, end) for each segment in original_text
        for seg in segments:
            text = seg.get("text", "")
            start = len(original_text)
            original_text += text
            boundaries.append((start, len(original_text)))

        if original_text == corrected_full_text:
            return segments

        sm = difflib.SequenceMatcher(None, original_text, corrected_full_text)
        opcodes = sm.get_opcodes()

        for i, seg in enumerate(segments):
            seg_start, seg_end = boundaries[i]
            parts = []

            for tag, i1, i2, j1, j2 in opcodes:
                overlap_start = max(seg_start, i1)
                overlap_end = min(seg_end, i2)
                if overlap_start >= overlap_end:
                    continue

                if tag == 'equal':
                    offset = overlap_start - i1
                    length = overlap_end - overlap_start
                    parts.append(corrected_full_text[j1 + offset:j1 + offset + length])
                elif tag == 'replace':
                    if (overlap_start, overlap_end) == (i1, i2):
                        parts.append(corrected_full_text[j1:j2])
                    else:
                        ratio = (overlap_end - overlap_start) / max(i2 - i1, 1)
                        new_len = max(1, int(ratio * (j2 - j1)))
                        offset_in_op = overlap_start - i1
                        offset_in_new = int(offset_in_op / max(i2 - i1, 1) * (j2 - j1))
                        parts.append(corrected_full_text[j1 + offset_in_new:j1 + offset_in_new + new_len])
                elif tag == 'delete':
                    pass
                elif tag == 'insert':
                    if seg_start <= i1 < seg_end or abs(i1 - seg_end) <= 2:
                        parts.append(corrected_full_text[j1:j2])

            if parts:
                seg["text"] = "".join(parts)

    except Exception:
        pass

    return segments
