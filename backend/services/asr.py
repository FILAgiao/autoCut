"""火山引擎豆包语音识别 - 录音文件识别标准版 (HTTP)

接口: POST https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit (提交任务)
      POST https://openspeech.bytedance.com/api/v3/auc/bigmodel/query  (查询结果)
鉴权: X-Api-App-Key / X-Api-Access-Key / X-Api-Resource-Id / X-Api-Request-Id

录音文件识别需要音频的公网 URL。可通过火山引擎 TOS 对象存储或本地 HTTP 服务 + ngrok 提供。
"""

import json
import time
import uuid
import tempfile
import subprocess

import requests

from backend.config import settings


class VolcASRClient:
    """火山引擎录音文件识别大模型客户端 (HTTP V3)"""

    # 接口地址
    SUBMIT_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
    QUERY_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"

    # 资源 ID - 豆包录音文件识别模型1.0
    RESOURCE_ID = "volc.bigasr.auc"

    def __init__(self):
        self.app_id = settings.VOLC_APP_ID
        self.access_token = settings.VOLC_ACCESS_TOKEN

    def _build_headers(self, request_id: str) -> dict:
        return {
            "X-Api-App-Key": self.app_id,
            "X-Api-Access-Key": self.access_token,
            "X-Api-Resource-Id": self.RESOURCE_ID,
            "X-Api-Request-Id": request_id,
            "Content-Type": "application/json",
        }

    # ──── 主流程 ────

    def submit_task(self, audio_url: str, language: str = "zh-CN") -> str:
        """提交识别任务

        Args:
            audio_url: 音频文件的公网可访问 URL
            language: 语言代码，默认 zh-CN

        Returns:
            task_id: 用于后续查询的任务 ID
        """
        task_id = str(uuid.uuid4())

        # 根据 URL 后缀推断音频格式
        ext = audio_url.split("?")[0].split(".")[-1].lower()
        fmt = "wav" if ext not in ("mp3", "ogg", "wav") else ext

        body = {
            "user": {"uid": self.app_id},
            "audio": {
                "format": fmt,
                "url": audio_url,
                "language": language,
            },
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": True,
                "show_utterances": True,
            },
        }

        resp = requests.post(
            self.SUBMIT_URL,
            headers=self._build_headers(task_id),
            json=body,
            timeout=30,
        )
        resp.raise_for_status()

        status_code = resp.headers.get("X-Api-Status-Code", "")
        status_msg = resp.headers.get("X-Api-Message", "")

        if status_code != "20000000":
            raise RuntimeError(f"提交 ASR 任务失败: [{status_code}] {status_msg}")

        return task_id

    def query_task(self, task_id: str) -> dict:
        """查询识别结果

        Returns:
            {"status": "running" | "success" | "failed", ...}
        """
        resp = requests.post(
            self.QUERY_URL,
            headers=self._build_headers(task_id),
            json={},
            timeout=30,
        )
        resp.raise_for_status()

        status_code = resp.headers.get("X-Api-Status-Code", "")

        if status_code == "20000000":
            data = resp.json()
            result = data.get("result", {})
            utterances = result.get("utterances", [])
            full_text = result.get("text", "")

            segments = []
            for u in utterances:
                text = u.get("text", "").strip()
                if text:
                    segments.append({
                        "text": text,
                        "start": u.get("start_time", 0) / 1000.0,  # ms → s
                        "end": u.get("end_time", 0) / 1000.0,
                        "confidence": 0.95,
                        "definite": u.get("definite", False),
                        "words": u.get("words", []),
                    })

            return {
                "status": "success",
                "segments": segments,
                "full_text": full_text,
            }

        elif status_code in ("20000001", "20000002"):
            return {"status": "running"}

        else:
            status_msg = resp.headers.get("X-Api-Message", "未知错误")
            return {"status": "failed", "error": f"[{status_code}] {status_msg}"}

    def wait_for_result(self, task_id: str, poll_interval: float = 2.0,
                        max_wait: float = 600.0) -> dict:
        """轮询等待识别完成"""
        start = time.time()

        while True:
            result = self.query_task(task_id)

            if result["status"] in ("success", "failed"):
                return result

            if time.time() - start > max_wait:
                return {
                    "status": "failed",
                    "error": f"ASR 超时 (等待 {max_wait}s)",
                }

            time.sleep(poll_interval)

    # ──── 音频预处理 ────

    @staticmethod
    def convert_to_wav(audio_path: str) -> str:
        """将音频转换为 16kHz 16bit mono WAV

        API 推荐 raw/wav 格式，pcm_s16le, 16kHz, mono。
        已经是正确格式的 WAV 则直接返回。
        """
        import os

        if audio_path.lower().endswith('.wav'):
            return audio_path

        from backend.services.media import _find_ffmpeg
        ffmpeg = _find_ffmpeg()

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()

        cmd = [
            ffmpeg, "-y",
            "-i", audio_path,
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            tmp.name,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"音频转换失败: {result.stderr}")

        return tmp.name


# ──── 便捷函数 ────

def process_audio_file(audio_url: str) -> dict:
    """处理单个音频文件（通过公网 URL）"""
    client = VolcASRClient()
    task_id = client.submit_task(audio_url=audio_url)
    result = client.wait_for_result(task_id)

    if result["status"] == "failed":
        raise RuntimeError(f"语音识别失败: {result.get('error', '未知错误')}")

    return {
        "segments": result["segments"],
        "full_text": result["full_text"],
    }
