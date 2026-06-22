"""项目路由 - CRUD + 处理管道 + 状态轮询 + 确认/拒掉 + 导出"""

from __future__ import annotations

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

    clips = project.get("clips", [])
    for clip in clips:
        clip["exists"] = store.clip_exists(project_id, clip["filename"])

    response = {
        "id": project["id"],
        "name": project["name"],
        "script": project.get("script", ""),
        "created_at": project.get("created_at", ""),
        "updated_at": project.get("updated_at", ""),
        "clips": clips,
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
    project = store.get_project(project_id)
    if not project:
        return JSONResponse({"error": "项目不存在"}, status_code=404)
    clip = next((c for c in project.get("clips", []) if c["id"] == clip_id), None)
    if not clip:
        return JSONResponse({"error": "视频片段不存在"}, status_code=404)
    # 优先返回预览文件（浏览器兼容），不存在时回退到原始文件
    path = store.get_preview_path(project_id, clip["filename"], clip.get("preview_filename"))
    if not path:
        return JSONResponse({"error": "视频片段文件不存在"}, status_code=404)
    return FileResponse(str(path))


@router.delete("/projects/{project_id}/clips/{clip_id}")
async def delete_clip(project_id: str, clip_id: str):
    """删除项目中的视频片段"""
    project = store.get_project(project_id)
    if not project:
        return JSONResponse({"error": "项目不存在"}, status_code=404)

    clips = project.get("clips", [])
    clip = next((c for c in clips if c["id"] == clip_id), None)
    if not clip:
        return JSONResponse({"error": "视频片段不存在"}, status_code=404)

    # Delete original file from disk
    clip_path = store.get_clip_path(project_id, clip["filename"])
    if clip_path and clip_path.exists():
        clip_path.unlink()

    # Delete preview file from disk (if exists)
    preview_filename = clip.get("preview_filename")
    if preview_filename:
        preview_path = Path("projects") / project_id / "clips" / preview_filename
        if preview_path.exists():
            preview_path.unlink()

    # Remove from project
    clips = [c for c in clips if c["id"] != clip_id]
    store.update_project(project_id, clips=clips)
    return {"status": "ok"}


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

    for clip in clips:
        clip_path = store.get_clip_path(project_id, clip["filename"])
        if not clip_path:
            return JSONResponse({"error": f"视频文件 {clip.get('original_name', clip['filename'])} 不存在，请重新上传"}, status_code=400)

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
        {"name": "extract_audio",  "label": "提取音频",     "status": "pending", "percent": 0, "message": ""},
        {"name": "asr_connect",    "label": "连接识别服务", "status": "pending", "percent": 0, "message": ""},
        {"name": "asr_send",       "label": "发送音频数据", "status": "pending", "percent": 0, "message": ""},
        {"name": "asr_wait",       "label": "等待识别结果", "status": "pending", "percent": 0, "message": ""},
        {"name": "correct_text",   "label": "智能纠错",     "status": "pending", "percent": 0, "message": ""},
        {"name": "merge_sentences","label": "语句归并",     "status": "pending", "percent": 0, "message": ""},
        {"name": "align",          "label": "语义对齐",     "status": "pending", "percent": 0, "message": ""},
        {"name": "analyze",        "label": "智能分析",     "status": "pending", "percent": 0, "message": ""},
        {"name": "keywords",       "label": "关键词检测",   "status": "pending", "percent": 0, "message": ""},
    ]

    def _update_progress(step_name: str, status: str, percent: int | None = None, message: str | None = None):
        for s in _STEPS:
            if s["name"] == step_name:
                s["status"] = status
                if percent is not None:
                    s["percent"] = percent
                if message is not None:
                    s["message"] = message
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
        if not video_path or not video_path.exists():
            raise RuntimeError("找不到视频文件或文件已损坏")

        video_path_str = str(video_path.resolve())

        # Step 1: 提取音频
        _update_progress("extract_audio", "processing", 50, "正在用 ffmpeg 提取音频...")
        video_info = get_video_info(video_path_str)
        video_duration = video_info["duration"]

        clips = project.get("clips", [])
        if clips:
            clips[0]["duration"] = video_duration
            store.update_project(project_id, clips=clips)

        audio_path = str(video_path.with_suffix(".m4a"))
        extract_audio(video_path_str, audio_path)
        _update_progress("extract_audio", "done", 100, "音频提取完成")

        # Step 2: ASR 流式识别（拆分为连接→发送→等待）
        _update_progress("asr_connect", "processing", 50, "正在连接火山引擎识别服务...")

        def asr_progress_callback(pct: int, msg: str = None):
            mb_sent = pct * 0.01 * (video_duration * 16000 * 2 / 1024 / 1024) if video_duration else 0
            display_msg = msg or f"已发送 {pct}% (约 {mb_sent:.1f}MB)"
            _update_progress("asr_send", "processing", pct, display_msg)

        client = VolcASRClient()
        _update_progress("asr_connect", "done", 100, "已连接到识别服务")

        _update_progress("asr_send", "processing", 0, "开始发送音频数据...")

        # 更新 asr_send 的 progress callback 以支持 message
        async def recognize_with_progress():
            # 包装原 callback，让它可以传 message
            original = client.recognize
            async def wrapper(audio, on_progress=None):
                def progress_wrapper(pct):
                    if on_progress:
                        on_progress(pct)
                return await original.__wrapped__(audio, on_progress=progress_wrapper) if hasattr(original, '__wrapped__') else await original(audio, on_progress=asr_progress_callback)
            return await wrapper(audio_path, on_progress=asr_progress_callback)

        asr_result = await client.recognize(audio_path, on_progress=asr_progress_callback)

        if asr_result["status"] == "failed":
            raise RuntimeError(f"ASR 失败: {asr_result.get('error', '未知错误')}")

        segments = asr_result.get("segments", [])
        full_text = asr_result.get("full_text", "")
        _update_progress("asr_send", "done", 100, f"已发送全部音频数据")

        _update_progress("asr_wait", "processing", 80, "正在等待识别结果返回...")
        await asyncio.sleep(0.5)  # 短暂停让用户看到等待状态
        _update_progress("asr_wait", "done", 100, f"识别完成，共 {len(segments)} 个片段")

        # Step 2.5: LLM 文本纠错
        corrected_full_text = None
        _update_progress("correct_text", "processing", 30, "正在用大模型检查错别字...")
        try:
            from backend.services.text_corrector import correct_transcript, apply_corrections_to_segments
            corrected_text = await correct_transcript(full_text)
            if corrected_text and len(corrected_text.strip()) > len(full_text) * 0.5:
                full_text = corrected_text
                corrected_full_text = corrected_text
                # 将纠正后的文本映射回各个片段
                apply_corrections_to_segments(segments, corrected_text)
                _update_progress("correct_text", "done", 100, "纠错完成")
            else:
                _update_progress("correct_text", "done", 100, "无需纠错")
        except Exception:
            _update_progress("correct_text", "done", 100, "纠错跳过（LLM 不可用）")

        # Step 2.6: LLM 语句归并（含重复句分组）
        _alt_map = {}  # 原始片段文本 → 同句的其他尝试
        _update_progress("merge_sentences", "processing", 30, "正在用大模型归并碎片语句...")
        try:
            from backend.services.sentence_merger import merge_segments
            merged = await merge_segments(segments)
            if merged and len(merged) > 0:
                # 提取同句其他尝试（半句、重讲、补录），稍后在对齐后补充为 take
                for seg in merged:
                    alts = seg.pop("_alternatives", None)
                    if alts:
                        _alt_map[seg["text"]] = alts
                segments = merged
                alt_count = sum(len(v) for v in _alt_map.values())
                msg = f"归并完成，共 {len(segments)} 个句子"
                if alt_count:
                    msg += f"（含 {alt_count} 个重复尝试已归组）"
                _update_progress("merge_sentences", "done", 100, msg)
            else:
                _update_progress("merge_sentences", "done", 100, "无需归并")
        except Exception:
            _update_progress("merge_sentences", "done", 100, "归并跳过（LLM 不可用）")

        # Step 3: LLM 语义对齐 或 无脚本聚类
        _update_progress("align", "processing", 30, "正在请求大模型进行语义对齐...")
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

        matched_count = len([s for s in sentences if s.takes])
        _update_progress("align", "done", 100, f"已匹配 {matched_count}/{len(script_lines)} 句")

        # 将对齐结果中匹配到的句子的备用 takes（半句、重讲、补录）展开
        if _alt_map:
            for sent in sentences:
                extra_takes = []
                for take in sent.takes:
                    alts = _alt_map.get(take.text)
                    if alts:
                        for alt in alts:
                            extra_takes.append(AnalyzedTake(
                                index=len(sent.takes) + len(extra_takes),
                                text=alt["text"],
                                start=alt["start"],
                                end=alt["end"],
                                duration=round(alt["end"] - alt["start"], 2),
                                confidence=alt.get("confidence", 0.0),
                            ))
                if extra_takes:
                    sent.takes.extend(extra_takes)

        # Step 4: 分析引擎
        _update_progress("analyze", "processing", 0, "开始智能分析...")
        from backend.services.analyzers import run_all_analyzers, AnalysisContext

        all_segment_texts = [s.get("text", "") for s in segments]
        total_takes = sum(len(sent.takes) for sent in sentences)
        processed_takes = 0

        for sent in sentences:
            for take_idx, take in enumerate(sent.takes):
                processed_takes += 1
                # 每处理一个 take 更新进度
                _update_progress("analyze", "processing",
                    int(processed_takes / total_takes * 100) if total_takes else 50,
                    f"正在分析第 {processed_takes}/{total_takes} 个片段...")

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

        _update_progress("analyze", "done", 100, f"分析完成，共处理 {total_takes} 个片段")

        # AI 关键词检测：用 LLM 识别专有名词、重点词、大数字等
        _update_progress("keywords", "running", 0, "正在用 AI 识别重点词...")
        try:
            from backend.services.keyword_detector import detect_keywords_llm, detect_keywords_sync

            # Collect text from best take of each sentence
            keyword_texts = []
            keyword_map = []  # [(sent_idx, take_idx), ...]
            for si, sent in enumerate(sentences):
                best = _find_best_take_idx(sent)
                if best >= 0:
                    keyword_texts.append(sent.takes[best].text)
                    keyword_map.append((si, best))

            if keyword_texts:
                # Try LLM detection first, fall back to regex
                ai_keywords = None
                try:
                    from openai import OpenAI
                    _update_progress("keywords", "running", 30, "LLM 分析中...")
                    llm_client = OpenAI(
                        base_url=settings.LLM_API_BASE,
                        api_key=settings.LLM_API_KEY,
                    )
                    ai_keywords = await detect_keywords_llm(keyword_texts, llm_client)
                    _update_progress("keywords", "running", 80, "LLM 关键词检测完成")
                except Exception as e_llm:
                    _log.warning(f"[keywords] LLM detection failed, using regex: {e_llm}")
                    ai_keywords = detect_keywords_sync(keyword_texts)

                if ai_keywords:
                    for (si, ti), kws in zip(keyword_map, ai_keywords):
                        if kws:
                            sentences[si].takes[ti].keywords = kws
                            _log.info(f"[keywords] S{si} take{ti}: {kws}")
            _update_progress("keywords", "done", 100, f"关键词检测完成")
        except Exception as e_key:
            _log.warning(f"[keywords] detection failed: {e_key}")
            _update_progress("keywords", "done", 100, f"关键词检测跳过")

        # 每个句子内的 take 按质量排序：A > B > C > D > 废，同级按分数降序
        _grade_order = {'A': 0, 'B': 1, 'C': 2, 'D': 3, '废': 4, '': 5}
        for sent in sentences:
            sent.takes.sort(key=lambda t: (
                1 if t.is_abandoned else 0,                # 废片排最后
                _grade_order.get(t.grade, 5),              # 按等级排序
                -(t.grade_score or 0),                     # 同级按分数降序
            ))
            # 更新 index 字段以匹配新顺序
            for i, take in enumerate(sent.takes):
                take.index = i
            # 如果已确认，更新 confirmed_take_index 指向新位置
            if sent.confirmed_take_index >= 0:
                # confirmed_take_index 存储的是旧 index，通过寻找同名 take 来重新确认位置
                sent.confirmed_take_index = -1  # 分析阶段尚未确认，保持 -1

        # 保存结果到 project.json
        result_data = {
            "task_id": task_id,
            "status": "done",
            "video_duration": video_duration,
            "full_text": corrected_full_text or full_text,
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
