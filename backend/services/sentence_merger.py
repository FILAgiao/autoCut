"""LLM 语句归并 — 将 ASR 零散片段合并成完整有意义的句子

语音识别经常产生不完整的片段（比如说话人停顿、犹豫、口吃导致的碎片）。
本模块使用大模型理解语义，将这些碎片归并成完整的句子。
"""

import json
from openai import AsyncOpenAI
from backend.config import settings


async def merge_segments(segments: list[dict]) -> list[dict]:
    """用 LLM 将零散 ASR 片段归并为完整句子

    Args:
        segments: ASR 返回的片段列表
                  [{text, start, end, confidence, ...}, ...]

    Returns:
        归并后的片段列表（格式同输入），如果归并失败返回空列表
    """
    if not segments or len(segments) <= 1:
        return []  # 只有一个片段，无需归并

    if not (settings.LLM_API_KEY and settings.LLM_MODEL):
        return []

    # 构建片段描述
    segment_descriptions = []
    for i, seg in enumerate(segments):
        text = seg.get("text", "").strip()
        start = seg.get("start", 0)
        end = seg.get("end", 0)
        if text:
            segment_descriptions.append(
                f"{i}. [{start:.1f}s-{end:.1f}s] \"{text}\""
            )

    if not segment_descriptions:
        return []

    segment_text = "\n".join(segment_descriptions)

    client = AsyncOpenAI(
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_API_BASE,
    )

    prompt = f"""你是一个专业的语音内容编辑助手。以下是一段语音识别转写的片段列表。

这段音频是口播内容，说话人可能因为忘词、表达不满意等原因，对同一句话尝试了多遍。
你的任务是将这些片段归并成可用于剪辑的句子。

归并规则：

1. **相邻合并**：语义上连续、属于同一句话的相邻片段合并在一起
2. **半句合并**：明显的半句话（缺少主语或宾语）优先与相邻片段合并
3. **填充词处理**：独词片段（如单独的"嗯"、"对"、"然后"）与上下文合并
4. **完整句保留**：如果片段已经是一个完整的句子，则保持不变
5. **语义转折**：不要合并有明显语义转折的片段
6. **重复识别（重要）**：如果多个不邻接的片段表达的是**同一句话的不同遍**（如说话人讲了一半忘词、重讲完整版、补录安全句），请将这些片段归为一组。
   - 文本有包含关系的优先归组（如 "今天我们来" 包含在 "今天我们来讲一下这个视频剪辑的流程" 中 → 是同一句的片段和完整版）
   - 语义相同但措辞略有不同也算同一句
   - 只保留**讲得最完整、最通顺的那一版**作为该组的 text

返回 JSON 格式：
```json
{{
  "sentences": [
    {{
      "text": "归并后的完整句子文本（取最佳版本）",
      "segment_indices": [2, 3],
      "alternative_segment_indices": [0, 1, 4]
    }}
  ]
}}
```

- `segment_indices`: 组成这句最佳版本的原始片段编号
- `alternative_segment_indices`: 同一句话的其他尝试（半句、重讲、补录），这些不会被单独列出为句子

片段列表：
{segment_text}

请返回归并结果（JSON）："""

    try:
        response = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=2048,
        )
        content = response.choices[0].message.content
        if not content:
            return []

        # 提取 JSON
        json_start = content.find("{")
        json_end = content.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            data = json.loads(content[json_start:json_end])
        else:
            return []

        merged = data.get("sentences", [])
        if not merged:
            return []

        # 转换回 segments 格式
        result = []
        for item in merged:
            indices = item.get("segment_indices", [])
            if not indices:
                continue

            first_idx = indices[0]
            last_idx = indices[-1]
            primary = {
                "text": item.get("text", "").strip(),
                "start": segments[first_idx].get("start", 0),
                "end": segments[last_idx].get("end", 0),
                "confidence": sum(
                    segments[i].get("confidence", 0.9) for i in indices
                ) / len(indices),
            }

            # 保存同句的其他尝试（半句、重讲、补录）以备编辑时选用
            alt_indices = item.get("alternative_segment_indices", [])
            if alt_indices:
                alts = []
                for ai in alt_indices:
                    for idx in (ai if isinstance(ai, list) else [ai]):
                        if 0 <= idx < len(segments):
                            seg = segments[idx]
                            alts.append({
                                "text": seg.get("text", "").strip(),
                                "start": seg.get("start", 0),
                                "end": seg.get("end", 0),
                                "confidence": seg.get("confidence", 0.9),
                            })
                if alts:
                    primary["_alternatives"] = alts

            result.append(primary)

        return result if len(result) < len(segments) else []

    except Exception as e:
        print(f"[sentence_merger] LLM 归并失败: {e}")
        return []
