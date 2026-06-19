"""导出路由"""

import os
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

from backend.config import settings
from backend.models.schemas import ProcessResult
from backend.routes.upload import get_task

router = APIRouter()


@router.get("/export/{task_id}/draft")
async def export_draft(task_id: str):
    """导出剪映草稿文件（ZIP 包）"""
    task = get_task(task_id)
    if not task or not task.get("result"):
        return JSONResponse({"error": "任务未就绪"}, status_code=400)

    result: ProcessResult = task["result"]

    # 检查是否有确认的句子
    confirmed = [s for s in result.sentences if s.confirmed_take_index >= 0]
    if not confirmed:
        return JSONResponse({"error": "请至少确认一句后再导出"}, status_code=400)

    try:
        from backend.services.exporter import export_jianying_draft
        draft_dir = export_jianying_draft(result, task["video_path"])

        # 打包为 ZIP
        output_dir = Path(settings.OUTPUT_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)
        zip_path = output_dir / f"koubo_draft_{task_id}.zip"

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(draft_dir):
                for f in files:
                    file_path = Path(root) / f
                    arcname = file_path.relative_to(draft_dir)
                    zf.write(file_path, arcname)

        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename=f"剪映草稿_{task_id}.zip",
            headers={"Content-Disposition": f'attachment; filename="剪映草稿_{task_id}.zip"'},
        )
    except Exception as e:
        return JSONResponse({"error": f"导出失败: {str(e)}"}, status_code=500)


@router.get("/export/{task_id}/srt")
async def export_srt(task_id: str):
    """导出 SRT 短字幕"""
    task = get_task(task_id)
    if not task or not task.get("result"):
        return JSONResponse({"error": "任务未就绪"}, status_code=400)

    result: ProcessResult = task["result"]

    confirmed = [s for s in result.sentences if s.confirmed_take_index >= 0]
    if not confirmed:
        return JSONResponse({"error": "请至少确认一句后再导出"}, status_code=400)

    try:
        from backend.services.exporter import export_srt_subtitles
        srt_content = export_srt_subtitles(result)

        output_dir = Path(settings.OUTPUT_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)
        srt_path = output_dir / f"subtitle_{task_id}.srt"
        srt_path.write_text(srt_content, encoding="utf-8")

        return FileResponse(
            srt_path,
            media_type="text/plain; charset=utf-8",
            filename=f"字幕_{task_id}.srt",
            headers={"Content-Disposition": f'attachment; filename="字幕_{task_id}.srt"'},
        )
    except Exception as e:
        return JSONResponse({"error": f"导出失败: {str(e)}"}, status_code=500)


@router.get("/export/{task_id}/text")
async def export_text_guide(task_id: str):
    """导出剪辑清单（纯文本）"""
    task = get_task(task_id)
    if not task or not task.get("result"):
        return JSONResponse({"error": "任务未就绪"}, status_code=400)

    result: ProcessResult = task["result"]
    confirmed = sorted(
        [s for s in result.sentences if s.confirmed_take_index >= 0],
        key=lambda s: s.takes[s.confirmed_take_index].start,
    )

    lines = ["口播剪辑清单", "=" * 40, ""]
    for s in confirmed:
        take = s.takes[s.confirmed_take_index]
        lines.append(
            f"[{_format_time(take.start)} - {_format_time(take.end)}] "
            f"S{s.index+1}: {s.text}"
        )

    text = "\n".join(lines)
    output_dir = Path(settings.OUTPUT_DIR)
    srt_path = output_dir / f"guide_{task_id}.txt"
    srt_path.write_text(text, encoding="utf-8")

    return FileResponse(srt_path, media_type="text/plain",
                        filename=f"剪辑清单_{task_id}.txt")


def _format_time(seconds: float) -> str:
    m = int(seconds // 60)
    s = seconds % 60
    return f"{m:02d}:{s:05.2f}"
