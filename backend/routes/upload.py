"""上传路由 - 视频 + 脚本上传，触发后台处理"""

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
    script: str = Form(...),
):
    """上传视频和脚本，后台开始处理"""
    task_id = uuid.uuid4().hex[:12]

    # 保存视频
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(video.filename).suffix or ".mp4"
    safe_name = f"{task_id}{ext}"
    video_path = upload_dir / safe_name

    content = await video.read()
    video_path.write_bytes(content)

    # 解析脚本（一句一行）
    script_lines = [s.strip() for s in script.strip().split("\n") if s.strip()]

    # 初始化任务
    _tasks[task_id] = {
        "id": task_id,
        "status": TaskStatus.UPLOADING.value,
        "video_path": str(video_path.resolve()),
        "video_filename": video.filename,
        "script_lines": script_lines,
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

        # Step 3: ASR 识别（录音文件识别，需要公网 URL）
        update_task(task_id, status=TaskStatus.ASR_PROCESSING.value)

        # 转换为 API 要求的 WAV 格式，放入 uploads 目录供静态文件服务访问
        import shutil
        wav_name = f"{task_id}.wav"
        wav_path = str(upload_dir / wav_name)
        tmp_wav = VolcASRClient.convert_to_wav(audio_path)
        shutil.move(tmp_wav, wav_path)

        # 获取音频的公网 URL（TOS 上传 或 本地 HTTP 服务 + ngrok）
        audio_url = _get_or_upload_audio_url(wav_path, task_id)

        client = VolcASRClient()
        asr_task_id = client.submit_task(audio_url=audio_url)
        asr_result = client.wait_for_result(asr_task_id)

        if asr_result["status"] == "failed":
            raise RuntimeError(f"ASR 失败: {asr_result.get('error', '未知错误')}")

        segments = asr_result.get("segments", [])

        # Step 4: LLM 语义对齐
        update_task(task_id, status=TaskStatus.ALIGNING.value)

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
                # 构建分析上下文
                seg_idx = None
                for match in alignment.get("matches", []):
                    if match["script_index"] == sent.index:
                        for t in match.get("takes", []):
                            if t.get("segment_index") == take_idx or (
                                abs(segments[t["segment_index"]]["start"] - take.start) < 0.01
                            ):
                                seg_idx = t["segment_index"]
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
            total_count=len(task["script_lines"]),
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


def _get_or_upload_audio_url(audio_path: str, task_id: str) -> str:
    """
    获取音频的公网 URL。
    优先级：TOS 上传 > 本地服务（开发用）
    """
    from backend.config import settings as cfg

    # 方式1：如果配置了 TOS，上传到火山引擎对象存储
    tos_bucket = getattr(cfg, "TOS_BUCKET", "")
    tos_endpoint = getattr(cfg, "TOS_ENDPOINT", "")
    if tos_bucket and tos_endpoint:
        return _upload_to_tos(audio_path, task_id, tos_bucket, tos_endpoint)

    # 方式2：本地开发 - 使用本地 HTTP 服务
    # 注意：这需要 ASR 服务能访问你的本地地址（不适用于生产）
    local_url = getattr(cfg, "LOCAL_AUDIO_BASE_URL", "")
    if local_url:
        filename = Path(audio_path).name
        return f"{local_url.rstrip('/')}/{filename}"

    raise RuntimeError(
        "音频需要公网可访问的 URL 才能进行语音识别。\n\n"
        "请配置以下任一方式:\n"
        "1. [推荐] 火山引擎 TOS:\n"
        "   在 .env 中添加 TOS_BUCKET、TOS_ENDPOINT、TOS_ACCESS_KEY、TOS_SECRET_KEY\n"
        "2. [开发] 本地 HTTP 服务:\n"
        "   在 .env 中设置 LOCAL_AUDIO_BASE_URL=http://your-ip:8520/uploads\n"
        "   并使用 ngrok 等工具暴露本地服务\n\n"
        f"音频文件已提取到: {audio_path}"
    )


def _upload_to_tos(filepath: str, task_id: str, bucket: str, endpoint: str) -> str:
    """上传文件到火山引擎 TOS（S3 兼容协议）"""
    import hashlib
    import base64
    import hmac
    import requests
    from datetime import datetime, timezone
    from pathlib import Path

    from backend.config import settings as cfg
    ak = getattr(cfg, "TOS_ACCESS_KEY", "")
    sk = getattr(cfg, "TOS_SECRET_KEY", "")
    region = getattr(cfg, "TOS_REGION", "cn-beijing")

    filename = Path(filepath).name
    object_key = f"koubo-audio/{task_id}/{filename}"

    # 读取文件
    with open(filepath, "rb") as f:
        content = f.read()

    if filename.endswith(".wav"):
        content_type = "audio/wav"
    elif filename.endswith(".m4a") or filename.endswith(".mp4"):
        content_type = "audio/mp4"
    elif filename.endswith(".mp3"):
        content_type = "audio/mpeg"
    elif filename.endswith(".ogg"):
        content_type = "audio/ogg"
    else:
        content_type = "application/octet-stream"

    # TOS S3 签名上传
    host = f"{bucket}.{endpoint}"
    url = f"https://{host}/{object_key}"

    xdate = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    short_date = xdate[:8]

    payload_hash = hashlib.sha256(content).hexdigest()
    canonical_headers = f"content-type:{content_type}\nhost:{host}\nx-amz-content-sha256:{payload_hash}\nx-amz-date:{xdate}\n"
    signed_headers = "content-type;host;x-amz-content-sha256;x-amz-date"

    canonical_request = f"PUT\n/{object_key}\n\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
    credential_scope = f"{short_date}/{region}/tos/request"
    hashed_canonical = hashlib.sha256(canonical_request.encode()).hexdigest()
    string_to_sign = f"AWS4-HMAC-SHA256\n{xdate}\n{credential_scope}\n{hashed_canonical}"

    def _sign(key, msg):
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()

    k_date = _sign(("AWS4" + sk).encode(), short_date)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, "tos")
    k_signing = _sign(k_service, "request")
    signature = hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()

    auth = (
        f"AWS4-HMAC-SHA256 Credential={ak}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    headers = {
        "Host": host,
        "Content-Type": content_type,
        "x-amz-date": xdate,
        "x-amz-content-sha256": payload_hash,
        "Authorization": auth,
    }

    resp = requests.put(url, headers=headers, data=content, timeout=60)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"TOS 上传失败 ({resp.status_code}): {resp.text}")

    # 返回可访问的 URL（如果 bucket 是公开的）
    return f"https://{host}/{object_key}"
