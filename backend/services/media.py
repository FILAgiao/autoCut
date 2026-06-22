"""媒体处理 - ffmpeg 封装"""

import subprocess
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

# ──── ffmpeg/ffprobe 路径自动检测 ────

_FFMPEG = "ffmpeg"
_FFPROBE = "ffprobe"

_EXE_SUFFIX = ".exe" if sys.platform == "win32" else ""


def _find_ffmpeg() -> str:
    """自动检测 ffmpeg 路径"""
    # 优先使用包装脚本（处理剪映内置 ffmpeg 的 rpath 和签名问题）
    local_ffmpeg = os.path.expanduser("~/.local/bin/ffmpeg")
    if os.path.exists(local_ffmpeg):
        return local_ffmpeg

    if sys.platform == "darwin":
        vf_path = "/Applications/VideoFusion-macOS.app/Contents/Resources/ffmpeg"
        if os.path.exists(vf_path):
            return vf_path

    known_dirs = []
    if sys.platform == "win32":
        home = os.path.expanduser("~")
        jianying_base = Path.home() / "AppData" / "Local" / "JianyingPro" / "Apps"
        if jianying_base.exists():
            versions = sorted(
                [d for d in jianying_base.iterdir() if d.is_dir()],
                reverse=True,
            )
            known_dirs.extend(str(v) for v in versions)
        known_dirs.extend([
            os.path.join(home, "ffmpeg", "bin"),
            "C:\\ffmpeg\\bin",
            os.path.join(home, "AppData", "Local", "Programs", "ffmpeg", "bin"),
        ])

    for d in known_dirs:
        exe = os.path.join(d, f"ffmpeg{_EXE_SUFFIX}")
        if os.path.exists(exe):
            return exe

    return "ffmpeg"


def _find_ffprobe() -> str:
    """自动检测 ffprobe 路径（独立于 ffmpeg）"""
    # 优先使用包装脚本
    local_ffprobe = os.path.expanduser("~/.local/bin/ffprobe")
    if os.path.exists(local_ffprobe):
        return local_ffprobe

    if sys.platform == "darwin":
        return _FFMPEG if _FFMPEG != "ffmpeg" else "ffprobe"

    known_dirs = []
    if sys.platform == "win32":
        home = os.path.expanduser("~")
        known_dirs.extend([
            os.path.join(home, "ffmpeg", "bin"),
            "C:\\ffmpeg\\bin",
            os.path.join(home, "AppData", "Local", "Programs", "ffmpeg", "bin"),
        ])

    for d in known_dirs:
        exe = os.path.join(d, f"ffprobe{_EXE_SUFFIX}")
        if os.path.exists(exe):
            return exe

    return "ffprobe"


_FFMPEG = _find_ffmpeg()
_FFPROBE = _find_ffprobe()


def get_video_info(filepath: str) -> dict:
    """获取视频元信息（优先 ffprobe，降级 ffmpeg 解析）"""
    # 尝试 ffprobe
    if _FFPROBE != "ffprobe":
        try:
            return _get_video_info_ffprobe(filepath)
        except (RuntimeError, FileNotFoundError):
            pass

    # 降级：用 ffmpeg 解析
    return _get_video_info_ffmpeg(filepath)


def _get_video_info_ffprobe(filepath: str) -> dict:
    """使用 ffprobe 获取视频信息"""
    cmd = [
        _FFPROBE, "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", filepath
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe 失败: {result.stderr}")

    info = json.loads(result.stdout)
    fmt = info.get("format", {})
    duration = float(fmt.get("duration", 0))

    video_stream = None
    audio_stream = None
    for s in info.get("streams", []):
        if s["codec_type"] == "video" and video_stream is None:
            video_stream = s
        elif s["codec_type"] == "audio" and audio_stream is None:
            audio_stream = s

    return {
        "duration": duration,
        "width": video_stream.get("width", 0) if video_stream else 0,
        "height": video_stream.get("height", 0) if video_stream else 0,
        "fps": _parse_fps_ffprobe(video_stream) if video_stream else 0,
        "video_codec": video_stream.get("codec_name", "") if video_stream else "",
        "audio_codec": audio_stream.get("codec_name", "") if audio_stream else "",
        "has_audio": audio_stream is not None,
    }


def _get_video_info_ffmpeg(filepath: str) -> dict:
    """使用 ffmpeg 解析视频信息（ffprobe 不可用时的降级方案）"""
    cmd = [_FFMPEG, "-i", filepath]
    result = subprocess.run(cmd, capture_output=True, text=True)
    # ffmpeg 将信息输出到 stderr
    output = result.stderr

    # 解析 Duration
    duration = 0.0
    dur_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", output)
    if dur_match:
        h, m, s, cs = map(int, dur_match.groups())
        duration = h * 3600 + m * 60 + s + cs / 100.0

    # 解析视频流
    width = 0
    height = 0
    fps = 0.0
    video_codec = ""
    has_audio = False
    audio_codec = ""

    for line in output.split("\n"):
        if "Stream #" in line:
            if "Video:" in line:
                video_codec = _parse_ffmpeg_codec(line)
                # 解析分辨率: 如 "1080x1920"
                res_match = re.search(r"(\d{2,})x(\d{2,})", line)
                if res_match:
                    width = int(res_match.group(1))
                    height = int(res_match.group(2))
                # 解析帧率: 如 "30 fps", "29.97 fps"
                fps_match = re.search(r"([\d.]+)\s*fps", line)
                if fps_match:
                    fps = float(fps_match.group(1))
            elif "Audio:" in line:
                has_audio = True
                audio_codec = _parse_ffmpeg_codec(line)

    return {
        "duration": duration,
        "width": width,
        "height": height,
        "fps": fps,
        "video_codec": video_codec,
        "audio_codec": audio_codec,
        "has_audio": has_audio,
    }


def _parse_ffmpeg_codec(stream_line: str) -> str:
    """从 ffmpeg Stream 行解析编码器名称"""
    # "Video: h264 (High) ..." -> "h264"
    # "Audio: aac (LC) ..." -> "aac"
    match = re.search(r"(?:Video|Audio):\s*(\S+)", stream_line)
    return match.group(1) if match else ""


def _parse_fps_ffprobe(stream: dict) -> float:
    """解析帧率（ffprobe 输出）"""
    fps_str = stream.get("r_frame_rate", "0/1")
    if "/" in fps_str:
        num, den = fps_str.split("/")
        return float(num) / float(den) if float(den) != 0 else 0
    return float(fps_str)


def extract_audio(video_path: str, output_path: str) -> str:
    """从视频中提取音频轨（AAC -> M4A）"""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        _FFMPEG, "-y", "-i", video_path,
        "-vn",                    # 不要视频
        "-acodec", "copy",        # 直接复制音频流，不重编码
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # 如果直接复制失败，尝试重编码为 AAC
        cmd = [
            _FFMPEG, "-y", "-i", video_path,
            "-vn", "-acodec", "aac", "-b:a", "192k",
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"提取音频失败: {result.stderr}")
    return output_path


def concat_video_segments(
    video_path: str,
    segments: list[tuple[float, float]],  # [(start, end), ...]
    output_path: str,
) -> str:
    """
    将视频的多个片段拼接成一个视频（无损、不重编码）
    使用 concat demuxer
    """
    if not segments:
        raise ValueError("没有提供视频片段")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # 写 concat 列表文件
    concat_file = output_path + ".concat.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        for start, end in segments:
            # 无损裁剪需要对齐关键帧，这里用精确 seek
            f.write(f"file '{video_path.replace(chr(92), '/')}'\n")
            f.write(f"inpoint {start:.6f}\n")
            f.write(f"outpoint {end:.6f}\n")

    cmd = [
        _FFMPEG, "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_file,
        "-c", "copy",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    os.unlink(concat_file)  # 清理临时文件

    if result.returncode != 0:
        raise RuntimeError(f"拼接视频失败: {result.stderr}")
    return output_path


def cut_video_segment(
    video_path: str,
    start: float,
    end: float,
    output_path: str,
    reencode: bool = False,
) -> str:
    """剪切视频的一个片段"""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    if reencode:
        cmd = [
            _FFMPEG, "-y",
            "-ss", str(start),
            "-to", str(end),
            "-i", video_path,
            "-c:v", "libx264", "-c:a", "aac",
            "-preset", "fast",
            output_path
        ]
    else:
        cmd = [
            _FFMPEG, "-y",
            "-ss", str(start),
            "-to", str(end),
            "-i", video_path,
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            output_path
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"剪切视频失败: {result.stderr}")
    return output_path


def check_ffmpeg() -> bool:
    """检查 ffmpeg 是否可用"""
    try:
        subprocess.run([_FFMPEG, "-version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
