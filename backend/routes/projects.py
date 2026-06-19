"""项目路由 - CRUD + 处理管道 + 状态轮询 + 确认/拒掉 + 导出"""

import time
import asyncio
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse

from backend.config import settings
from backend.models.schemas import (
    UploadResponse, TaskStatus, ProcessResult,
    AnalyzedTake, ScriptSentence, UnmatchedSegment, AnalysisTag,
    SubtitleStyle,
)
from backend.services import project_store as store

router = APIRouter()


# ═══════════════════════════════════════════
# 项目 CRUD
# ═══════════════════════════════════════════

@router.get("/projects")
async def list_projects():
    projects = store.list_projects()
    return [
        {
            "id": p["id"],
            "name": p["name"],
            "clip_count": len(p.get("clips", [])),
            "task_status": p.get("task_status", "idle"),
            "updated_at": p.get("updated_at", ""),
        }
        for p in projects
    ]


@router.post("/projects")
async def create_project(data: dict):
    name = data.get("name", "").strip() or "未命名项目"
    script = data.get("script", "")
    project = store.create_project(name, script)
    return project


@router.get("/projects/{project_id}")
async def get_project_detail(project_id: str):
    project = store.get_project(project_id)
    if not project:
        return JSONResponse({"error": "项目不存在"}, status_code=404)

    response = {
        "id": project["id"],
        "name": project["name"],
        "script": project.get("script", ""),
        "created_at": project.get("created_at", ""),
        "updated_at": project.get("updated_at", ""),
        "clips": project.get("clips", []),
        "task_id": project.get("task_id", project["id"]),
        "task_status": project.get("task_status", "idle"),
        "confirmed_count": project.get("confirmed_count", 0),
        "total_count": project.get("total_count", 0),
    }

    response["pipeline_progress"] = project.get("pipeline_progress")

    result = project.get("result")
    if result and project.get("task_status") == "done":
        response.update({
            "video_duration": result.get("video_duration", 0),
            "sentences": result.get("sentences", []),
            "unmatched": result.get("unmatched", []),
            "confirmed_count": result.get("confirmed_count", 0),
            "total_count": result.get("total_count", 0),
        })
    elif project.get("task_status") == "error":
        response["error_message"] = project.get("error", "")

    return response


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    if store.delete_project(project_id):
        return {"status": "ok"}
    return JSONResponse({"error": "项目不存在"}, status_code=404)


@router.put("/projects/{project_id}")
async def update_project(project_id: str, data: dict):
    project = store.get_project(project_id)
    if not project:
        return JSONResponse({"error": "项目不存在"}, status_code=404)

    allowed = {"name", "script"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if updates:
        store.update_project(project_id, **updates)
    return store.get_project(project_id)


# ═══════════════════════════════════════════
# 视频片段管理
# ═══════════════════════════════════════════

@router.post("/projects/{project_id}/clips")
async def upload_clip(project_id: str, video: UploadFile = File(...)):
    print(f"[upload_clip] project_id={project_id}, filename={video.filename}, content_type={video.content_type}")
    project = store.get_project(project_id)
    if not project:
        print(f"[upload_clip] project not found: {project_id}")
        return JSONResponse({"error": "项目不存在"}, status_code=404)

    content = await video.read()
    print(f"[upload_clip] read {len(content)} bytes")
    clip = store.save_clip(project_id, video.filename, content, video.filename)
    print(f"[upload_clip] saved clip: {clip}")
    return clip


@router.get("/projects/{project_id}/clips/{clip_id}")
async def get_clip_video(project_id: str, clip_id: str):
    path = store.get_clip_path(project_id, clip_id)
    if not path:
        return JSONResponse({"error": "视频片段不存在"}, status_code=404)
    return FileResponse(str(path))


# ═══════════════════════════════════════════
# 处理管道
# ═══════════════════════════════════════════

@router.post("/projects/{project_id}/process")
async def start_processing(project_id: str, background_tasks: BackgroundTasks):
    print(f"[start_processing] project_id={project_id}")
    project = store.get_project(project_id)
    if not project:
        print(f"[start_processing] project not found: {project_id}")
        return JSONResponse({"error": "项目不存在"}, status_code=404)

    clips = project.get("clips", [])
    print(f"[start_processing] clips count: {len(clips)}")
    if not clips:
        return JSONResponse({"error": "请先上传视频片段"}, status_code=400)

    project["task_status"] = "processing"
    store.update_project(project_id, task_status="processing", error=None)
    print(f"[start_processing] starting pipeline for {project_id}")

    background_tasks.add_task(run_pipeline, project_id)
    return {"status": "processing", "task_id": project.get("task_id", project_id)}


@router.post("/projects/{project_id}/retry")
async def retry_processing(project_id: str):
    """重置项目状态为 idle，清理旧的错误和结果"""
    project = store.get_project(project_id)
    if not project:
        return JSONResponse({"error": "项目不存在"}, status_code=404)

    store.update_project(
        project_id,
        task_status="idle",
        result=None,
        error=None,
        pipeline_progress=None,
        confirmed_count=0,
        total_count=0,
    )
    return {"status": "idle"}


async def run_pipeline(project_id: str):
    """后台处理管道：提取音频 → ASR → 对齐 → 分析"""
    project = store.get_project(project_id)
    if not project:
        return

    task_id = project.get("task_id", project_id)
    script_text = project.get("script", "").strip()

    # ── 初始化进度步骤 ──
    _STEPS = [
        {"name": "extract_audio", "label": "提取音频", "status": "pending", "percent": 0},
        {"name": "asr", "label": "语音识别", "status": "pending", "percent": 0},
        {"name": "align", "label": "语义对齐", "status": "pending", "percent": 0},
        {"name": "analyze", "label": "智能分析", "status": "pending", "percent": 0},
    ]

    def _update_progress(step_name: str, status: str, percent: int | None = None):
        for s in _STEPS:
            if s["name"] == step_name:
                s["status"] = status
                if percent is not None:
                    s["percent"] = percent
                break
        store.update_project(project_id, pipeline_progress={
            "steps": _STEPS,
            "current_step": step_name,
        })

    try:
        from backend.services.media import extract_audio, get_video_info, check_ffmpeg
        from backend.services.asr import VolcASRClient
        from backend.services.aligner import LLMAligner, align_result_to_model

        if not check_ffmpeg():
            raise RuntimeError("ffmpeg 未安装，请先安装 ffmpeg")

        # 获取第一个片段路径
        video_path = store.get_first_clip_path(project_id)
        if not video_path:
            raise RuntimeError("找不到视频文件")

        video_path_str = str(video_path.resolve())

        # Step 1: 提取音频
        _update_progress("extract_audio", "processing", 50)
        video_info = get_video_info(video_path_str)
        video_duration = video_info["duration"]

        clips = project.get("clips", [])
        if clips:
            clips[0]["duration"] = video_duration
            store.update_project(project_id, clips=clips)

        audio_path = str(video_path.with_suffix(".m4a"))
        extract_audio(video_path_str, audio_path)
        _update_progress("extract_audio", "done", 100)

        # Step 2: ASR 流式识别
        _update_progress("asr", "processing", 0)

        def asr_progress_callback(pct: int):
            _update_progress("asr", "processing", pct)

        client = VolcASRClient()
        asr_result = await client.recognize(audio_path, on_progress=asr_progress_callback)

        if asr_result["status"] == "failed":
            raise RuntimeError(f"ASR 失败: {asr_result.get('error', '未知错误')}")

        segments = asr_result.get("segments", [])
        _update_progress("asr", "done", 100)

        # Step 3: LLM 语义对齐 或 无脚本聚类
        _update_progress("align", "processing", 50)
        from backend.services.script_parser import smart_split_script
        script_lines = smart_split_script(script_text)
        scriptless = len(script_lines) == 0
        alignment = None

        if scriptless:
            from backend.services.aligner import SegmentClusterer, cluster_result_to_model
            clusterer = SegmentClusterer()
            cluster_data = clusterer.cluster(segments)
            sentences, unmatched = cluster_result_to_model(segments, cluster_data)
        else:
            aligner = LLMAligner()
            alignment = aligner.align(script_lines, segments)
            sentences, unmatched = align_result_to_model(script_lines, segments, alignment)
        _update_progress("align", "done", 100)

        # Step 4: 分析引擎
        _update_progress("analyze", "processing", 50)
        from backend.services.analyzers import run_all_analyzers, AnalysisContext

        all_segment_texts = [s.get("text", "") for s in segments]

        for sent in sentences:
            for take_idx, take in enumerate(sent.takes):
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

        _update_progress("analyze", "done", 100)

        # 保存结果到 project.json
        result_data = {
            "task_id": task_id,
            "status": "done",
            "video_duration": video_duration,
            "sentences": [s.model_dump() for s in sentences],
            "unmatched": [u.model_dump() for u in unmatched],
            "confirmed_count": 0,
            "total_count": len(sentences),
        }
        store.update_project(
            project_id,
            task_status="done",
            result=result_data,
            confirmed_count=0,
            total_count=len(sentences),
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        store.update_project(project_id, task_status="error", error=str(e))


def _tag_to_severity(tag: str, analysis: dict) -> str:
    good_tags = {"流畅", "干净", "清晰", "正常"}
    error_tags = {"废片", "卡顿多", "口癖多", "很不清晰", "严重偏离"}
    if tag in good_tags:
        return "good"
    if tag in error_tags:
        return "error"
    for r in analysis.get("results", []):
        if tag in r.get("tags", []):
            return r.get("severity", "info")
    return "info"


# ═══════════════════════════════════════════
# 状态轮询
# ═══════════════════════════════════════════

@router.get("/projects/{project_id}/status")
async def get_project_status(project_id: str):
    project = store.get_project(project_id)
    if not project:
        return JSONResponse({"error": "项目不存在"}, status_code=404)

    status = project.get("task_status", "idle")
    response = {
        "task_id": project.get("task_id", project_id),
        "status": status,
        "confirmed_count": project.get("confirmed_count", 0),
        "total_count": project.get("total_count", 0),
        "pipeline_progress": project.get("pipeline_progress"),
    }

    if status == "done":
        result = project.get("result", {})
        response.update({
            "video_duration": result.get("video_duration", 0),
            "sentences": result.get("sentences", []),
            "unmatched": result.get("unmatched", []),
            "confirmed_count": result.get("confirmed_count", 0),
            "total_count": result.get("total_count", 0),
        })
    elif status == "error":
        response["error_message"] = project.get("error", "")

    return response


# ═══════════════════════════════════════════
# 确认 / 拒掉
# ═══════════════════════════════════════════

@router.put("/projects/{project_id}/confirm/{script_index}/{take_index}")
async def confirm_take(project_id: str, script_index: int, take_index: int):
    project = store.get_project(project_id)
    if not project or not project.get("result"):
        return JSONResponse({"error": "项目未就绪"}, status_code=400)

    result = project["result"]
    sentences = result.get("sentences", [])
    if script_index >= len(sentences):
        return JSONResponse({"error": "脚本序号超出范围"}, status_code=400)

    sent = sentences[script_index]
    takes = sent.get("takes", [])
    if take_index >= len(takes):
        return JSONResponse({"error": "版本序号超出范围"}, status_code=400)

    sent["confirmed_take_index"] = take_index
    result["confirmed_count"] = sum(1 for s in sentences if s.get("confirmed_take_index", -1) >= 0)

    store.update_project(project_id, result=result, confirmed_count=result["confirmed_count"])
    return {"status": "ok", "confirmed_count": result["confirmed_count"]}


@router.put("/projects/{project_id}/reject/{script_index}/{take_index}")
async def reject_take(project_id: str, script_index: int, take_index: int):
    project = store.get_project(project_id)
    if not project or not project.get("result"):
        return JSONResponse({"error": "项目未就绪"}, status_code=400)

    result = project["result"]
    sentences = result.get("sentences", [])
    if script_index < len(sentences):
        takes = sentences[script_index].get("takes", [])
        if take_index < len(takes):
            takes[take_index]["is_abandoned"] = True
            takes[take_index]["grade"] = "废"
            store.update_project(project_id, result=result)

    return {"status": "ok"}


# ═══════════════════════════════════════════
# 导出（项目维度）
# ═══════════════════════════════════════════

def _auto_confirm_best(sentences: list[dict]):
    """为每句自动选择最佳 take（A级优先，跳过废片）"""
    for sent in sentences:
        if sent.get("confirmed_take_index", -1) >= 0:
            continue
        takes = sent.get("takes", [])
        if not takes:
            continue
        for grade in ['A', 'B', 'C']:
            for i, t in enumerate(takes):
                if t.get("grade") == grade and not t.get("is_abandoned"):
                    sent["confirmed_take_index"] = i
                    break
            if sent.get("confirmed_take_index", -1) >= 0:
                break
        if sent.get("confirmed_take_index", -1) < 0:
            sent["confirmed_take_index"] = 0


def _build_process_result(project: dict):
    """从 project.json 构建 ProcessResult 对象"""
    result = project.get("result", {})
    sentences_data = result.get("sentences", [])
    unmatched_data = result.get("unmatched", [])

    sentences = []
    for s in sentences_data:
        takes = []
        for t in s.get("takes", []):
            takes.append(AnalyzedTake(
                index=t.get("index", 0),
                text=t.get("text", ""),
                start=t.get("start", 0),
                end=t.get("end", 0),
                duration=t.get("duration", 0),
                confidence=t.get("confidence", 0),
                grade=t.get("grade", ""),
                grade_score=t.get("grade_score", 0),
                is_abandoned=t.get("is_abandoned", False),
                abandon_reason=t.get("abandon_reason", ""),
                tags=[AnalysisTag(**tag) for tag in t.get("tags", [])],
            ))
        sentences.append(ScriptSentence(
            index=s.get("index", 0),
            text=s.get("text", ""),
            takes=takes,
            confirmed_take_index=s.get("confirmed_take_index", -1),
            is_unmatched=s.get("is_unmatched", False),
        ))

    unmatched = [UnmatchedSegment(**u) for u in unmatched_data]

    video_path = store.get_first_clip_path(project["id"])
    return ProcessResult(
        task_id=project.get("task_id", project["id"]),
        status="done",
        video_filename=str(video_path) if video_path else "",
        video_duration=result.get("video_duration", 0),
        sentences=sentences,
        unmatched=unmatched,
        confirmed_count=result.get("confirmed_count", 0),
        total_count=result.get("total_count", 0),
    ), str(video_path) if video_path else ""


import os
import zipfile
from tempfile import TemporaryDirectory


@router.get("/projects/{project_id}/export/draft")
async def export_project_draft(
    project_id: str,
    font: str = "Source Han Sans SC",
    fontSizeRatio: float = 0.08,
    color: str = "FFFFFF",
    strokeColor: str = "000000",
    strokeWidth: float = 0.04,
    positionY: float = -0.75,
    keywordColor: str = "FFD700",
    maxChars: int = 12,
):
    project = store.get_project(project_id)
    if not project or not project.get("result"):
        return JSONResponse({"error": "项目未就绪"}, status_code=400)

    result, video_path = _build_process_result(project)
    if not video_path:
        return JSONResponse({"error": "找不到视频文件"}, status_code=400)

    _auto_confirm_best(project["result"]["sentences"])
    store.update_project(project_id, result=project["result"])
    # rebuild result after auto-confirm
    result, video_path = _build_process_result(project)

    subtitle_style = SubtitleStyle(
        font=font,
        font_size_ratio=fontSizeRatio,
        color=f"#{color}",
        stroke_color=f"#{strokeColor}",
        stroke_width=strokeWidth,
        position_y=positionY,
        keyword_color=f"#{keywordColor}",
        max_chars=maxChars,
    )

    try:
        from backend.services.exporter import export_jianying_draft
        draft_dir = export_jianying_draft(result, video_path, subtitle_style)

        export_dir = store.get_export_dir(project_id)
        zip_path = export_dir / f"koubo_draft_{project_id}.zip"

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(draft_dir):
                for f in files:
                    file_path = Path(root) / f
                    arcname = file_path.relative_to(draft_dir)
                    zf.write(file_path, arcname)

        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename=f"剪映草稿_{project_id}.zip",
            headers={"Content-Disposition": f'attachment; filename="剪映草稿_{project_id}.zip"'},
        )
    except Exception as e:
        return JSONResponse({"error": f"导出失败: {str(e)}"}, status_code=500)


@router.get("/projects/{project_id}/export/srt")
async def export_project_srt(project_id: str):
    project = store.get_project(project_id)
    if not project or not project.get("result"):
        return JSONResponse({"error": "项目未就绪"}, status_code=400)

    result, _ = _build_process_result(project)
    _auto_confirm_best(project["result"]["sentences"])
    store.update_project(project_id, result=project["result"])
    result, _ = _build_process_result(project)

    try:
        from backend.services.exporter import export_srt_subtitles
        srt_content = export_srt_subtitles(result)

        export_dir = store.get_export_dir(project_id)
        srt_path = export_dir / f"subtitle_{project_id}.srt"
        srt_path.write_text(srt_content, encoding="utf-8")

        return FileResponse(
            srt_path,
            media_type="text/plain; charset=utf-8",
            filename=f"字幕_{project_id}.srt",
            headers={"Content-Disposition": f'attachment; filename="字幕_{project_id}.srt"'},
        )
    except Exception as e:
        return JSONResponse({"error": f"导出失败: {str(e)}"}, status_code=500)


@router.get("/projects/{project_id}/export/text")
async def export_project_text_guide(project_id: str):
    project = store.get_project(project_id)
    if not project or not project.get("result"):
        return JSONResponse({"error": "项目未就绪"}, status_code=400)

    result, _ = _build_process_result(project)
    confirmed = sorted(
        [s for s in result.sentences if s.confirmed_take_index >= 0],
        key=lambda s: s.takes[s.confirmed_take_index].start,
    )

    lines = ["口播剪辑清单", "=" * 40, ""]
    for s in confirmed:
        take = s.takes[s.confirmed_take_index]
        m = int(take.start // 60)
        sec = take.start % 60
        lines.append(
            f"[{m:02d}:{sec:05.2f}] "
            f"S{s.index+1}: {s.text}"
        )

    text = "\n".join(lines)
    export_dir = store.get_export_dir(project_id)
    txt_path = export_dir / f"guide_{project_id}.txt"
    txt_path.write_text(text, encoding="utf-8")

    return FileResponse(txt_path, media_type="text/plain",
                        filename=f"剪辑清单_{project_id}.txt")
