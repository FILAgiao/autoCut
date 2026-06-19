"""导出服务 - 剪映草稿 + SRT + 剪辑清单"""

import os
import re
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.config import settings
from backend.models.schemas import ProcessResult, ScriptSentence, SubtitleStyle


# ──── 剪映草稿导出 ────

def export_jianying_draft(result: ProcessResult, video_path: str, subtitle_style: SubtitleStyle | None = None) -> str:
    """
    生成剪映草稿文件夹

    使用 pyJianYingDraft 库:
    - 视频轨：原始视频，按 source_timerange 保留确认片段
    - 字幕轨：已确认句子 → 短字幕 + 预设样式

    返回: 草稿文件夹路径
    """
    style = subtitle_style or SubtitleStyle()
    confirmed = _get_confirmed_sorted(result)

    try:
        import pyJianYingDraft as draft
        from pyJianYingDraft import tim, trange, SEC

        # 创建脚本
        w, h = settings.OUTPUT_WIDTH, settings.OUTPUT_HEIGHT
        script = draft.Script_file(w, h)

        # ──── 视频轨 ────
        video_mat = draft.Video_material(video_path)
        script.add_material(video_mat)

        script.add_track(draft.Track_type.video, track_name="口播")

        current_time_us = 0
        for sent in confirmed:
            take = sent.takes[sent.confirmed_take_index]
            dur_sec = take.end - take.start

            seg = draft.Video_segment(
                video_mat,
                target_timerange=trange(tim(f"{current_time_us/1e6}s"), tim(f"{dur_sec}s")),
                source_timerange=trange(tim(f"{take.start}s"), tim(f"{take.end}s")),
            )
            script.add_segment(seg, "口播")
            current_time_us += int(dur_sec * SEC)

        # ──── 字幕轨 ────
        script.add_track(draft.Track_type.text, track_name="字幕")

        # 字幕样式
        color = _hex_to_rgb(style.color)
        stroke_color = _hex_to_rgb(style.stroke_color)
        stroke_width = style.stroke_width
        font = style.font
        max_chars = style.max_chars
        pos_y = style.position_y

        text_style = draft.Text_style(
            font=font,
            font_size=h * settings.SUBTITLE_SIZE_RATIO,
            color=(color[0], color[1], color[2]),
            stroke_color=(stroke_color[0], stroke_color[1], stroke_color[2]),
            stroke_width=stroke_width,
            align=1,  # 居中
        )

        subtitle_time_us = 0
        for sent in confirmed:
            take = sent.takes[sent.confirmed_take_index]
            dur_sec = take.end - take.start

            # 拆分为短字幕
            short_lines = _split_to_short_lines(take.text, max_chars)

            sub_duration = dur_sec / len(short_lines) if short_lines else dur_sec

            for i, line in enumerate(short_lines):
                seg = draft.Text_segment(
                    line,
                    trange(
                        tim(f"{(subtitle_time_us + i * int(sub_duration * SEC)) / 1e6}s"),
                        tim(f"{sub_duration}s"),
                    ),
                    style=text_style,
                    clip_settings=draft.Clip_settings(transform_y=pos_y),
                )
                script.add_segment(seg, "字幕")

            subtitle_time_us += int(dur_sec * SEC)

        # 导出到临时目录
        temp_dir = TemporaryDirectory()
        draft_dir = Path(temp_dir.name) / "draft"
        draft_dir.mkdir(parents=True, exist_ok=True)

        script.dump(str(draft_dir / "draft_content.json"))

        # 复制视频文件到草稿目录
        import shutil
        video_dest = draft_dir / Path(video_path).name
        if not video_dest.exists():
            shutil.copy2(video_path, video_dest)

        # 注意: TemporaryDirectory 会在函数返回后被清理
        # 实际使用时，我们在 export.py 中创建持久化目录
        # 这里直接返回 draft_dir，由调用方负责清理

        # 对于实际导出，我们用持久化路径重新做一遍
        output_dir = Path(settings.OUTPUT_DIR) / f"draft_{result.task_id}"
        output_dir.mkdir(parents=True, exist_ok=True)

        script.dump(str(output_dir / "draft_content.json"))

        # 复制视频文件
        video_dest = output_dir / Path(video_path).name
        if not video_dest.exists():
            shutil.copy2(video_path, video_dest)

        return str(output_dir)

    except ImportError:
        # pyJianYingDraft 未安装时，生成一个最小可用草稿 JSON
        return _export_minimal_draft(result, video_path, subtitle_style)


def _export_minimal_draft(result: ProcessResult, video_path: str, subtitle_style: SubtitleStyle | None = None) -> str:
    """降级方案：生成最小可用的剪映草稿 JSON（无需 pyJianYingDraft）"""
    import json
    import shutil
    style = subtitle_style or SubtitleStyle()

    confirmed = _get_confirmed_sorted(result)
    w, h = settings.OUTPUT_WIDTH, settings.OUTPUT_HEIGHT

    output_dir = Path(settings.OUTPUT_DIR) / f"draft_{result.task_id}"
    output_dir.mkdir(parents=True, exist_ok=True)

    video_name = Path(video_path).name
    video_dest = output_dir / video_name
    if not video_dest.exists():
        shutil.copy2(video_path, video_dest)

    # 构建视频轨道 segments
    current_time = 0.0
    video_segments = []
    for sent in confirmed:
        take = sent.takes[sent.confirmed_take_index]
        dur = take.end - take.start
        video_segments.append({
            "id": f"vid_{sent.index}",
            "source": video_name,
            "source_start": take.start,
            "source_end": take.end,
            "target_start": current_time,
            "target_end": current_time + dur,
            "speed": 1.0,
        })
        current_time += dur

    # 构建字幕轨道 segments（短字幕）
    subtitle_segments = []
    subtitle_time = 0.0
    subtitle_id = 0
    max_chars = style.max_chars

    for sent in confirmed:
        take = sent.takes[sent.confirmed_take_index]
        dur = take.end - take.start
        short_lines = _split_to_short_lines(take.text, max_chars)
        sub_duration = dur / len(short_lines) if short_lines else dur

        for line in short_lines:
            subtitle_segments.append({
                "id": f"sub_{subtitle_id}",
                "text": line,
                "target_start": subtitle_time,
                "target_end": subtitle_time + sub_duration,
                "style": {
                    "font": style.font,
                    "font_size": int(h * style.font_size_ratio),
                    "color": _hex_to_rgb_list(style.color),
                    "stroke_color": _hex_to_rgb_list(style.stroke_color),
                    "stroke_width": style.stroke_width,
                    "align": 1,
                    "position_y": style.position_y,
                },
            })
            subtitle_time += sub_duration
            subtitle_id += 1

    # 剪映 draft_content.json 最小结构
    draft = {
        "version": "5.9.0",
        "platform": "windows",
        "resolution": {"width": w, "height": h},
        "tracks": [
            {"type": "video", "name": "口播", "segments": video_segments},
            {"type": "text", "name": "字幕", "segments": subtitle_segments},
        ],
        "duration": current_time,
    }

    draft_path = output_dir / "draft_content.json"
    draft_path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")

    return str(output_dir)


# ──── SRT 导出 ────

def export_srt_subtitles(result: ProcessResult, max_chars: int = None) -> str:
    """导出 SRT 短字幕"""
    if max_chars is None:
        max_chars = settings.SUBTITLE_MAX_CHARS

    confirmed = _get_confirmed_sorted(result)
    entries = []

    for sent in confirmed:
        take = sent.takes[sent.confirmed_take_index]
        short_lines = _split_to_short_lines(take.text, max_chars)
        dur = take.end - take.start
        sub_duration = dur / len(short_lines) if short_lines else dur

        for i, line in enumerate(short_lines):
            start = take.start + i * sub_duration
            end = start + sub_duration
            entries.append((start, end, line))

    # 生成 SRT
    lines = []
    for idx, (start, end, text) in enumerate(entries, 1):
        lines.append(str(idx))
        lines.append(f"{_srt_time(start)} --> {_srt_time(end)}")
        lines.append(text)
        lines.append("")

    return "\n".join(lines)


# ──── 辅助函数 ────

def _get_confirmed_sorted(result: ProcessResult) -> list[ScriptSentence]:
    """获取已确认的句子，按时间排序"""
    confirmed = [s for s in result.sentences if s.confirmed_take_index >= 0]
    return sorted(confirmed, key=lambda s: s.takes[s.confirmed_take_index].start)


def _split_to_short_lines(text: str, max_chars: int) -> list[str]:
    """
    将长句拆分为短字幕
    优先在标点处拆分，其次按字数拆分
    """
    text = text.strip()
    if len(text) <= max_chars:
        return [text]

    # 标点拆分位置
    punctuations = r"[，。！？、；：,\.!\?;:]"
    parts = re.split(f"({punctuations})", text)

    lines = []
    current = ""
    for part in parts:
        if re.match(punctuations, part):
            # 标点附加到当前行
            if len(current) + len(part) <= max_chars:
                current += part
            else:
                if current:
                    lines.append(current)
                current = part
        else:
            if len(current) + len(part) <= max_chars:
                current += part
            else:
                if current:
                    lines.append(current)
                # 如果单个片段超过限制，按字数切
                while len(part) > max_chars:
                    lines.append(part[:max_chars])
                    part = part[max_chars:]
                current = part

    if current:
        lines.append(current)

    # 如果没拆开（没有标点），按字数均分
    if len(lines) == 1 and len(lines[0]) > max_chars:
        text = lines[0]
        n = (len(text) + max_chars - 1) // max_chars
        chunk_size = (len(text) + n - 1) // n
        lines = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

    return lines


def _srt_time(seconds: float) -> str:
    """秒数 → SRT 时间格式 HH:MM:SS,mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _hex_to_rgb(hex_color: str) -> tuple[float, ...]:
    """#FFFFFF → (1.0, 1.0, 1.0)"""
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16) / 255.0
    g = int(hex_color[2:4], 16) / 255.0
    b = int(hex_color[4:6], 16) / 255.0
    return (r, g, b)


def _hex_to_rgb_list(hex_color: str) -> list[float]:
    """#FFFFFF → [1.0, 1.0, 1.0]"""
    return list(_hex_to_rgb(hex_color))
