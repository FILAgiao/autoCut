"""火山引擎豆包语音识别 - 流式语音识别大模型 (WebSocket)

接口: wss://openspeech.bytedance.com/api/v3/sauc/bigmodel (双向流式)
鉴权: X-Api-App-Key / X-Api-Access-Key / X-Api-Resource-Id / X-Api-Connect-Id
协议: 自定义二进制帧 (header + payload_size + payload)

将完整音频文件分块发送，接收带时间戳的识别结果。
与录音文件识别不同，流式接口无需公网 URL，音频数据通过 WebSocket 直接传输。

参考文档: https://www.volcengine.com/docs/6561/1354869
"""

import gzip
import json
import struct
import tempfile
import uuid

import websockets

from backend.config import settings


class VolcASRClient:
    """火山引擎流式语音识别大模型客户端 (WebSocket V3)"""

    # 双向流式模式端点
    WS_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"

    # 资源 ID - 豆包流式语音识别模型1.0
    RESOURCE_ID = "volc.bigasr.sauc.duration"

    # ──── 协议常量 ────
    PROTOCOL_VERSION = 0b0001
    HEADER_SIZE = 0b0001  # 1 x 4 = 4 bytes

    # 消息类型
    MSG_FULL_CLIENT_REQUEST = 0b0001
    MSG_AUDIO_ONLY_REQUEST = 0b0010
    MSG_FULL_SERVER_RESPONSE = 0b1001
    MSG_SERVER_ERROR_RESPONSE = 0b1111

    # 序列化方式
    SERIALIZATION_JSON = 0b0001
    SERIALIZATION_NONE = 0b0000

    # 压缩方式
    COMPRESSION_NONE = 0b0000
    COMPRESSION_GZIP = 0b0001

    # 标志位
    FLAG_NO_SEQUENCE = 0b0000        # 无序号
    FLAG_POS_SEQUENCE = 0b0001       # 有序号（正数）
    FLAG_NEG_SEQUENCE = 0b0010       # 最后一包（无序号）
    FLAG_NEG_WITH_SEQUENCE = 0b0011  # 最后一包（有序号）

    def __init__(self):
        self.app_id = settings.VOLC_APP_ID
        self.access_token = settings.VOLC_ACCESS_TOKEN

    # ──── 协议构建 ────

    @staticmethod
    def _build_header(
        message_type: int,
        compression: int = 0b0000,
        serialization: int = 0b0001,
        flags: int = 0b0000,
    ) -> bytes:
        """构建 4 字节二进制协议头

        Byte 0: protocol_version(4) | header_size(4)
        Byte 1: message_type(4) | message_type_specific_flags(4)
        Byte 2: serialization_method(4) | message_compression(4)
        Byte 3: reserved(8)
        """
        return bytes([
            (0b0001 << 4) | 0b0001,
            (message_type << 4) | flags,
            (serialization << 4) | compression,
            0x00,
        ])

    # ──── 鉴权 ────

    def _build_ws_headers(self) -> dict:
        """构建 WebSocket 鉴权头"""
        return {
            "X-Api-App-Key": self.app_id,
            "X-Api-Access-Key": self.access_token,
            "X-Api-Resource-Id": self.RESOURCE_ID,
            "X-Api-Connect-Id": str(uuid.uuid4()),
        }

    # ──── 主流程 ────

    async def transcribe(self, audio_path: str) -> dict:
        """将音频文件通过 WebSocket 发送并获取识别结果

        返回: {"status": "success", "segments": [...], "full_text": "..."}
        """
        # 转换音频为 API 支持的格式 (16kHz, 16bit, mono PCM)
        wav_path = self._convert_to_wav(audio_path)
        try:
            with open(wav_path, "rb") as f:
                wav_data = f.read()
        finally:
            if wav_path != audio_path:
                import os
                try:
                    os.unlink(wav_path)
                except OSError:
                    pass

        audio_bytes = wav_data
        audio_format = "wav"

        async with websockets.connect(
            self.WS_URL,
            additional_headers=self._build_ws_headers(),
            ping_interval=20,
            ping_timeout=10,
            max_size=10 * 1024 * 1024,
        ) as ws:
            # Step 1: 发送 full client request
            metadata = {
                "user": {"uid": self.app_id},
                "audio": {
                    "format": audio_format,
                    "codec": "raw",
                    "rate": 16000,
                    "bits": 16,
                    "channel": 1,
                    "language": "zh-CN",
                },
                "request": {
                    "model_name": "bigmodel",
                    "enable_itn": True,
                    "enable_punc": True,
                    "show_utterances": True,
                    "result_type": "full",
                },
            }
            await self._send_full_request(ws, metadata)

            # Step 2: 分块发送音频数据（每包 ~100ms）
            chunk_size = 3200
            for i in range(0, len(audio_bytes), chunk_size):
                chunk = audio_bytes[i:i + chunk_size]
                is_last = (i + chunk_size >= len(audio_bytes))
                await self._send_audio_chunk(ws, chunk, is_last)

            # Step 3: 接收结果
            return await self._recv_result(ws)

    # ──── 发送消息 ────

    async def _send_full_request(self, ws, params: dict) -> None:
        """发送 full client request

        格式: header(4) + payload_size(4, uint32) + gzip(payload)
        标志位: NO_SEQUENCE (无序号)
        """
        payload = gzip.compress(json.dumps(params).encode())

        header = self._build_header(
            self.MSG_FULL_CLIENT_REQUEST,
            compression=self.COMPRESSION_GZIP,
            flags=self.FLAG_NO_SEQUENCE,
        )
        size = struct.pack(">I", len(payload))
        await ws.send(header + size + payload)

    async def _send_audio_chunk(self, ws, audio: bytes, is_last: bool) -> None:
        """发送 audio only request

        非最后一包: header + payload_size + gzip(audio)  [flags=NO_SEQUENCE]
        最后一包:   header + payload_size + gzip(audio)  [flags=NEG_SEQUENCE]
        """
        if not audio and not is_last:
            return

        flags = self.FLAG_NEG_SEQUENCE if is_last else self.FLAG_NO_SEQUENCE
        compressed = gzip.compress(audio) if audio else b""

        header = self._build_header(
            self.MSG_AUDIO_ONLY_REQUEST,
            compression=self.COMPRESSION_GZIP if audio else self.COMPRESSION_NONE,
            serialization=self.SERIALIZATION_NONE,
            flags=flags,
        )
        size = struct.pack(">I", len(compressed))
        await ws.send(header + size + compressed)

    # ──── 接收结果 ────

    async def _recv_result(self, ws) -> dict:
        """接收服务器响应并解析"""
        full_text = ""
        utterances = []

        while True:
            raw = await ws.recv()
            if isinstance(raw, str):
                raw = raw.encode()

            result = self._parse_response(raw)

            if "error" in result:
                raise RuntimeError(f"ASR 错误: {result['error']}")

            msg = result.get("message", {})
            if isinstance(msg, dict):
                res = msg.get("result", {})
                if isinstance(res, dict):
                    text = res.get("text", "")
                    if text and text.strip():
                        full_text += text
                    for u in res.get("utterances", []):
                        utterances.append({
                            "text": u.get("text", ""),
                            "start": u.get("start_time", 0) / 1000.0,
                            "end": u.get("end_time", 0) / 1000.0,
                            "confidence": u.get("confidence", 0.9),
                            "definite": u.get("definite", False),
                            "words": u.get("words", []),
                        })

            if result.get("is_last_package"):
                break

        # 去重（双向流式可能返回重复结果）
        segments = []
        seen = set()
        for u in utterances:
            text = u["text"].strip()
            if text and text not in seen:
                seen.add(text)
                segments.append(u)

        if not segments and full_text:
            segments = [{
                "text": full_text,
                "start": 0,
                "end": 0,
                "confidence": 0.9,
            }]

        return {
            "status": "success",
            "segments": segments,
            "full_text": full_text,
        }

    # ──── 响应解析 ────

    @staticmethod
    def _parse_response(data: bytes) -> dict:
        """解析二进制响应

        Full server response:
            header(4) + sequence(4, int32) + payload_size(4, uint32) + payload
        Error response:
            header(4) + error_code(4, uint32) + error_size(4, uint32) + error_msg(UTF8)
        """
        if len(data) < 4:
            return {"error": "响应太短"}

        header_size = (data[0] & 0x0F) * 4
        message_type = (data[1] >> 4) & 0x0F
        flags = data[1] & 0x0F
        compression = data[2] & 0x0F

        payload = data[header_size:]
        result = {"is_last_package": False}

        # 检查序号: flag 0b0001 (POS_SEQUENCE) 或 0b0011 (NEG_WITH_SEQUENCE)
        has_sequence = bool(flags & 0x01)
        if has_sequence and len(payload) >= 4:
            seq = struct.unpack(">i", payload[:4])[0]
            payload = payload[4:]
            if seq < 0:
                result["is_last_package"] = True

        # 检查最后一包标志: flag 0b0010 (NEG_SEQUENCE)
        if flags & 0x02:
            result["is_last_package"] = True

        # 按消息类型处理
        msg = VolcASRClient

        if message_type == msg.MSG_FULL_SERVER_RESPONSE:
            if len(payload) >= 4:
                payload_size = struct.unpack(">I", payload[:4])[0]
                payload = payload[4:4 + payload_size]

        elif message_type == msg.MSG_SERVER_ERROR_RESPONSE:
            if len(payload) >= 8:
                code = struct.unpack(">I", payload[:4])[0]
                payload_size = struct.unpack(">I", payload[4:8])[0]
                error_msg = payload[8:8 + payload_size]
                try:
                    error_msg = error_msg.decode("utf-8")
                except UnicodeDecodeError:
                    error_msg = str(error_msg)
                return {"error": f"code={code}, msg={error_msg}"}
        else:
            return {"message": None}

        # 解压并解析 JSON
        if compression == msg.COMPRESSION_GZIP:
            try:
                payload = gzip.decompress(payload)
            except Exception:
                pass

        try:
            result["message"] = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            result["message"] = None

        return result

    # ──── 音频转换 ────

    @staticmethod
    def _convert_to_wav(audio_path: str) -> str:
        """将音频转换为 16kHz 16bit mono WAV

        API 要求 pcm_s16le, 16kHz, mono。
        已经是正确格式的 WAV 则直接返回。
        """
        import subprocess

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

    # ──── 同步兼容接口 ────

    def submit_task(self, audio_url: str = "", audio_path: str = "",
                    language: str = "zh-CN") -> str:
        """提交识别任务（兼容同步接口）

        流式 API 通过 WebSocket 同步完成，此方法保存参数后由 wait_for_result 实际执行。
        """
        self._audio_path = audio_path
        self._audio_url = audio_url
        self._task_id = str(uuid.uuid4())
        return self._task_id

    def query_task(self, task_id: str) -> dict:
        """轮询接口"""
        if not hasattr(self, "_result_cache"):
            self._result_cache = {}
        if task_id in self._result_cache:
            return self._result_cache[task_id]
        return {"status": "running"}

    def wait_for_result(self, task_id: str, poll_interval: float = 2.0,
                        max_wait: float = 600.0) -> dict:
        """等待识别完成（流式 API 同步执行）"""
        import asyncio

        async def _run():
            audio_path = getattr(self, "_audio_path", "")
            audio_url = getattr(self, "_audio_url", "")

            if audio_url and not audio_path:
                import requests as r
                resp = r.get(audio_url, timeout=60)
                resp.raise_for_status()
                tmp = tempfile.NamedTemporaryFile(suffix=".m4a", delete=False)
                tmp.write(resp.content)
                tmp.close()
                audio_path = tmp.name

            if not audio_path:
                raise ValueError("必须提供音频文件路径或 URL")

            return await self.transcribe(audio_path)

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, _run())
                    return future.result(timeout=max_wait)
            else:
                return asyncio.run(_run())
        except RuntimeError:
            return asyncio.run(_run())


# ──── 便捷函数 ────

def process_audio_file(audio_path: str) -> dict:
    """处理单个音频文件"""
    client = VolcASRClient()
    task_id = client.submit_task(audio_path=audio_path)
    result = client.wait_for_result(task_id)

    if result["status"] == "failed":
        raise RuntimeError(f"语音识别失败: {result.get('error', '未知错误')}")

    return {
        "segments": result["segments"],
        "full_text": result["full_text"],
    }
