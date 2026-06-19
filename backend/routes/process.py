"""处理状态查询路由"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.models.schemas import ProcessResult, TaskStatus
from backend.routes.upload import get_task

router = APIRouter()


@router.get("/task/{task_id}")
async def get_task_status(task_id: str):
    """查询任务处理状态和结果"""
    task = get_task(task_id)
    if not task:
        return JSONResponse({"error": "任务不存在"}, status_code=404)

    status = task.get("status")

    response = {
        "task_id": task_id,
        "status": status,
        "video_filename": task.get("video_filename", ""),
    }

    if status == TaskStatus.DONE.value and task.get("result"):
        result: ProcessResult = task["result"]
        response.update({
            "video_duration": result.video_duration,
            "sentences": [
                {
                    "index": s.index,
                    "text": s.text,
                    "takes": [
                        {
                            "index": t.index,
                            "text": t.text,
                            "start": t.start,
                            "end": t.end,
                            "duration": t.duration,
                            "confidence": t.confidence,
                            "grade": t.grade,
                            "grade_score": t.grade_score,
                            "is_abandoned": t.is_abandoned,
                            "abandon_reason": t.abandon_reason,
                            "tags": [
                                {"label": tag.label, "severity": tag.severity, "detail": tag.detail}
                                for tag in t.tags
                            ],
                        }
                        for t in s.takes
                    ],
                    "confirmed_take_index": s.confirmed_take_index,
                    "is_unmatched": s.is_unmatched,
                }
                for s in result.sentences
            ],
            "unmatched": [
                {"text": u.text, "start": u.start, "end": u.end, "confidence": u.confidence}
                for u in result.unmatched
            ],
            "confirmed_count": result.confirmed_count,
            "total_count": result.total_count,
        })
    elif status == TaskStatus.ERROR.value:
        response["error_message"] = task.get("error", "")

    return response


@router.get("/video/{task_id}")
async def get_video(task_id: str):
    """获取视频文件流（用于前端 <video> 播放）"""
    from fastapi.responses import FileResponse
    task = get_task(task_id)
    if not task:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    return FileResponse(task["video_path"])


@router.put("/task/{task_id}/confirm/{script_index}/{take_index}")
async def confirm_take(task_id: str, script_index: int, take_index: int):
    """确认某个脚本句子的某个版本"""
    task = get_task(task_id)
    if not task or not task.get("result"):
        return JSONResponse({"error": "任务未就绪"}, status_code=400)

    result: ProcessResult = task["result"]
    if script_index >= len(result.sentences):
        return JSONResponse({"error": "脚本序号超出范围"}, status_code=400)

    sent = result.sentences[script_index]
    if take_index >= len(sent.takes):
        return JSONResponse({"error": "版本序号超出范围"}, status_code=400)

    sent.confirmed_take_index = take_index
    result.confirmed_count = sum(1 for s in result.sentences if s.confirmed_take_index >= 0)

    return {"status": "ok", "confirmed_count": result.confirmed_count}


@router.put("/task/{task_id}/reject/{script_index}/{take_index}")
async def reject_take(task_id: str, script_index: int, take_index: int):
    """标记某个版本为废片"""
    task = get_task(task_id)
    if not task or not task.get("result"):
        return JSONResponse({"error": "任务未就绪"}, status_code=400)

    result: ProcessResult = task["result"]
    sent = result.sentences[script_index]
    if take_index < len(sent.takes):
        sent.takes[take_index].is_abandoned = True
        sent.takes[take_index].grade = "废"

    return {"status": "ok"}
