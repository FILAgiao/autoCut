"""上传路由 - 视频 + 脚本上传，触发后台处理"""

from __future__ import annotations

import uuid
import time
import asyncio
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import JSONResponse

from backend.config import settings
from backend.models.schemas import UploadResponse, TaskStatus

router = APIRouter()

# 简单的内存任务存储（生产环境应改用 Redis/DB）
_tasks: dict[str, dict] = {}


def get_task(task_id: str) -> dict | None:
    return _tasks.get(task_id)


def update_task(task_id: str, **kwargs):
    if task_id in _tasks:
        _tasks[task_id].update(kwargs)


@router.post("/upload", response_model=UploadResponse)
async def upload_video(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    script: str = Form(""),
):
    """上传视频和脚本（脚本可选），后台开始处理"""
    task_id = uuid.uuid4().hex[:12]

    # 保存视频
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(video.filename).suffix or ".mp4"
    safe_name = f"{task_id}{ext}"
    video_path = upload_dir / safe_name

    content = await video.read()
    video_path.write_bytes(content)

    # 解析脚本（一句一行），空脚本 = 无脚本模式
    script_text = script.strip() if script else ""
    script_lines = [s.strip() for s in script_text.split("\n") if s.strip()] if script_text else []

    # 初始化任务
    _tasks[task_id] = {
        "id": task_id,
        "status": TaskStatus.UPLOADING.value,
        "video_path": str(video_path.resolve()),
        "video_filename": video.filename,
        "script_lines": script_lines,
        "scriptless": len(script_lines) == 0,
        "started_at": time.time(),
        "result": None,
        "error": None,
    }

    # 后台处理
    background_tasks.add_task(process_video_task, task_id)

    return UploadResponse(task_id=task_id, status="processing")


async def process_video_task(task_id: str):
    """后台处理管道：提取音频 → ASR → 对齐 → 分析"""
    task = _tasks.get(task_id)
    if not task:
        return

    try:
        from backend.services.media import extract_audio, get_video_info, check_ffmpeg
        from backend.services.asr import VolcASRClient
        from backend.services.aligner import LLMAligner, align_result_to_model
        from backend.services.analyzers import run_all_analyzers, AnalysisContext
        from backend.models.schemas import AnalyzedTake, AnalysisTag

        # Step 0: 检查 ffmpeg
        if not check_ffmpeg():
            raise RuntimeError("ffmpeg 未安装，请先安装 ffmpeg")

        # Step 1: 获取视频信息
        update_task(task_id, status=TaskStatus.EXTRACTING_AUDIO.value)
        video_info = get_video_info(task["video_path"])
        video_duration = video_info["duration"]

        # Step 2: 提取音频
        audio_path = str(Path(task["video_path"]).with_suffix(".m4a"))
        extract_audio(task["video_path"], audio_path)

        # Step 3: ASR 流式识别（WebSocket，无需公网 URL）
        update_task(task_id, status=TaskStatus.ASR_PROCESSING.value)

        client = VolcASRClient()
        asr_result = await client.recognize(audio_path)

        if asr_result["status"] == "failed":
            raise RuntimeError(f"ASR 失败: {asr_result.get('error', '未知错误')}")

        segments = asr_result.get("segments", [])

        # Step 4: LLM 语义对齐 或 无脚本聚类
        update_task(task_id, status=TaskStatus.ALIGNING.value)

        scriptless = task.get("scriptless", False)
        alignment = None  # 聚类模式不需要 alignment
        if scriptless:
            # 无脚本模式：聚类相似片段
            from backend.services.aligner import SegmentClusterer, cluster_result_to_model
            clusterer = SegmentClusterer()
            cluster_data = clusterer.cluster(segments)
            sentences, unmatched = cluster_result_to_model(segments, cluster_data)
        else:
            # 有脚本模式：LLM 语义对齐
            aligner = LLMAligner()
            alignment = aligner.align(task["script_lines"], segments)
            sentences, unmatched = align_result_to_model(
                task["script_lines"], segments, alignment
            )

        # Step 5: 分析引擎
        update_task(task_id, status=TaskStatus.ANALYZING.value)

        all_segment_texts = [s.get("text", "") for s in segments]

        for sent in sentences:
            for take_idx, take in enumerate(sent.takes):
                # 构建分析上下文 — 找到对应的原始 ASR 片段索引
                seg_idx = None
                if alignment:
                    for match in alignment.get("matches", []):
                        if match["script_index"] == sent.index:
                            for t in match.get("takes", []):
                                if t.get("segment_index") == take_idx or (
                                    abs(segments[t["segment_index"]]["start"] - take.start) < 0.01
                                ):
                                    seg_idx = t["segment_index"]
                                    break
                else:
                    # 聚类模式：通过时间戳匹配
                    for si, s in enumerate(segments):
                        if abs(s["start"] - take.start) < 0.01:
                            seg_idx = si
                            break

                prev_text = ""
                next_text = ""
                prev_end = 0.0
                next_start = 0.0
                if seg_idx is not None:
                    if seg_idx > 0:
                        prev_text = segments[seg_idx - 1].get("text", "")
                        prev_end = segments[seg_idx - 1].get("end", 0)
                    if seg_idx < len(segments) - 1:
                        next_text = segments[seg_idx + 1].get("text", "")
                        next_start = segments[seg_idx + 1].get("start", 0)

                context = AnalysisContext(
                    segment_text=take.text,
                    segment_start=take.start,
                    segment_end=take.end,
                    segment_confidence=take.confidence,
                    script_sentence=sent.text,
                    total_duration=video_duration,
                    total_segments=len(segments),
                    prev_segment_text=prev_text,
                    next_segment_text=next_text,
                    prev_segment_end=prev_end,
                    next_segment_start=next_start,
                    all_segment_texts=all_segment_texts,
                )

                analysis = run_all_analyzers(
                    text=take.text,
                    start=take.start,
                    end=take.end,
                    asr_confidence=take.confidence,
                    script_sentence=sent.text,
                    context=context,
                )

                # 回填分析结果到 take
                take.grade = analysis["grade"]
                take.grade_score = analysis["grade_score"]
                take.is_abandoned = analysis["is_abandoned"]
                take.abandon_reason = analysis["abandon_reason"]
                take.tags = [
                    AnalysisTag(
                        label=tag,
                        severity=_tag_to_severity(tag, analysis),
                        detail=analysis["results"][i].get("details", {}).get("detail", "")
                        if i < len(analysis["results"]) else "",
                    )
                    for i, tag in enumerate(analysis.get("all_tags", []))
                ]

        # 保存结果
        from backend.models.schemas import ProcessResult
        result = ProcessResult(
            task_id=task_id,
            status="done",
            video_filename=task["video_filename"],
            video_duration=video_duration,
            sentences=sentences,
            unmatched=unmatched,
            confirmed_count=0,
            total_count=len(sentences),
        )
        _tasks[task_id]["result"] = result
        update_task(task_id, status=TaskStatus.DONE.value)

    except Exception as e:
        update_task(task_id, status=TaskStatus.ERROR.value, error=str(e))
        import traceback
        traceback.print_exc()


def _tag_to_severity(tag: str, analysis: dict) -> str:
    """根据标签内容推断严重程度"""
    good_tags = {"流畅", "干净", "清晰", "正常"}
    error_tags = {"废片", "卡顿多", "口癖多", "很不清晰", "严重偏离"}
    if tag in good_tags:
        return "good"
    if tag in error_tags:
        return "error"
    # 从分析结果中查找
    for r in analysis.get("results", []):
        if tag in r.get("tags", []):
            return r.get("severity", "info")
    return "info"
