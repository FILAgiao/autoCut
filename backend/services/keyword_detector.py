"""AI 重点词检测 — 用 LLM 识别口播中的关键/ punchline 词汇"""

from __future__ import annotations

import json
import re

from backend.config import settings

KEYWORD_PROMPT = """你是一个视频剪辑助手。分析以下口播文本，找出需要**重点高亮**的关键词，用于字幕中加粗+变色强调。

重点词类型：
- emphasis: 强调词/程度词（很、非常、超级、绝对、必须、最、极其、真的...）
- transition: 转折/逻辑连接词（但是、所以、因为、如果、当然、总之、其实...）
- number: 数字、百分比、金额、时间长度等有实际意义的数值（如"3个月""50万""80%"）
- proper_noun: 专有名词/产品名/品牌名/人名/地名/机构名（如"ChatGPT""抖音""剪映""北京"）
- content: 核心概念/关键词/行业术语/关键动作（应被观众注意的重要词汇）

规则：
1. 每个关键词返回 {word, type}，word 必须是从原文中连续截取的片段
2. 不要标记标点符号
3. 只标记真正需要突出的词，普通常用词不要标记
4. 优先标记 proper_noun 和 content 类型的词（这些是观众最需要关注的）
5. 数字只有在代表有意义的信息时才标记（跳过"一个""两个"这种口语数量词）
6. 返回 JSON 数组，不要其他内容

文本：
{text}

关键词 JSON:"""


async def detect_keywords_llm(texts: list[str], llm_client=None) -> list[list[dict]]:
    """
    用 LLM 检测每句话中的重点词。
    返回: [[{word, type}, ...], ...] 与输入 texts 一一对应。
    """
    if not texts:
        return []

    if llm_client is None:
        return [_detect_keywords_regex(t) for t in texts]

    results = []
    for text in texts:
        try:
            keywords = await _call_llm_for_keywords(llm_client, text)
            results.append(keywords)
        except Exception:
            results.append(_detect_keywords_regex(text))

    return results


async def _call_llm_for_keywords(llm_client, text: str) -> list[dict]:
    """单次 LLM 调用检测关键词 — 支持标准 OpenAI client 或兼容接口"""
    if not text.strip():
        return []

    prompt = KEYWORD_PROMPT.format(text=text)

    try:
        # Support both standard OpenAI client (chat.completions.create) and custom wrapper (.chat())
        if hasattr(llm_client, 'chat') and callable(llm_client.chat):
            response = await llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=512,
            )
            content = response if isinstance(response, str) else response.get("content", "")
        elif hasattr(llm_client, 'completions') or hasattr(llm_client, 'chat'):
            # Standard OpenAI client
            from openai import AsyncOpenAI
            if isinstance(llm_client, AsyncOpenAI):
                resp = await llm_client.chat.completions.create(
                    model=llm_client.model if hasattr(llm_client, 'model') else "doubao-seed-2-0-pro",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    max_tokens=512,
                )
                content = resp.choices[0].message.content.strip()
            else:
                # Sync fallback: use the synchronous OpenAI client
                resp = llm_client.chat.completions.create(
                    model=getattr(llm_client, 'model', 'doubao-seed-2-0-pro'),
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    max_tokens=512,
                )
                content = resp.choices[0].message.content.strip()
        else:
            return _detect_keywords_regex(text)

        return _parse_keyword_response(content)
    except Exception:
        return _detect_keywords_regex(text)


def _parse_keyword_response(content: str) -> list[dict]:
    """解析 LLM 返回的 JSON 关键词列表"""
    try:
        # Extract JSON array from response
        content = content.strip()
        # Remove markdown code block if present
        content = re.sub(r'^```(?:json)?\s*', '', content)
        content = re.sub(r'\s*```$', '', content)

        keywords = json.loads(content)
        if isinstance(keywords, list):
            return [
                {"word": k.get("word", ""), "type": k.get("type", "keyword")}
                for k in keywords
                if isinstance(k, dict) and k.get("word")
            ]
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _detect_keywords_regex(text: str) -> list[dict]:
    """正则回退方案：按规则检测关键词（与前端 keyword.js 保持一致）"""
    KEYWORD_DOUBLE = [
        '非常', '超级', '绝对', '一定', '必须', '真的', '极其', '尤其',
        '格外', '万分', '十分', '相当',
        '但是', '可是', '然而', '不过', '所以', '因此', '因为', '虽然',
        '如果', '那么', '而且', '并且', '或者', '然后', '接着', '于是',
        '否则', '总之', '其实', '当然', '毕竟', '反正',
        '甚至', '除非', '只要', '只有', '无论',
    ]
    KEYWORD_SINGLE = ['很', '最', '更', '超']

    num_pattern = re.compile(r'\d+(?:\.\d+)?[万亿千百]?')
    en_pattern = re.compile(r'[a-zA-Z]+')

    results = []
    pos = 0
    while pos < len(text):
        matched = False
        for kw in KEYWORD_DOUBLE:
            if text.startswith(kw, pos):
                results.append({"word": kw, "type": "transition" if kw in [
                    '但是','可是','然而','不过','所以','因此','因为','虽然',
                    '如果','那么','而且','并且','或者','然后','接着','于是',
                    '否则','总之','其实','当然','毕竟','反正',
                    '甚至','除非','只要','只有','无论',
                ] else "emphasis"})
                pos += len(kw)
                matched = True
                break
        if matched:
            continue

        for kw in KEYWORD_SINGLE:
            if text.startswith(kw, pos):
                results.append({"word": kw, "type": "emphasis"})
                pos += 1
                matched = True
                break
        if matched:
            continue

        m = num_pattern.match(text, pos)
        if m:
            results.append({"word": m.group(), "type": "number"})
            pos = m.end()
            continue

        m = en_pattern.match(text, pos)
        if m:
            results.append({"word": m.group(), "type": "keyword"})
            pos = m.end()
            continue

        pos += 1

    return results


def detect_keywords_sync(texts: list[str]) -> list[list[dict]]:
    """同步关键词检测（正则方案，无需 LLM）"""
    return [_detect_keywords_regex(t) for t in texts]
