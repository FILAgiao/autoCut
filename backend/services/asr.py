"""火山引擎豆包语音识别 - 流式识别 (WebSocket)

接口: wss://openspeech.bytedance.com/api/v3/sauc/bigmodel
协议: 火山引擎流式语音识别二进制协议 V3
鉴权: X-Api-App-Key / X-Api-Access-Key / X-Api-Resource-Id / X-Api-Request-Id / X-Api-Sequence

无需公网 URL，直接读取本地音频文件流式上传。
"""

import asyncio
import json
import gzip
import struct
import uuid
import tempfile
import subprocess
import os

import websockets
from websockets.exceptions import ConnectionClosedOK, ConnectionClosedError

from backend.config import settings

# ──── 协议常量 ────
PROTOCOL_VERSION = 0b0001
HEADER_SIZE      = 0b0001
MSG_FULL_CLIENT_REQUEST = 0b0001
MSG_AUDIO_ONLY_REQUEST  = 0b0010
SERIALIZATION_JSON = 0b0001
SERIALIZATION_NONE = 0b0000
COMPRESSION_GZIP  = 0b0001
COMPRESSION_NONE  = 0b0000
FLAG_NO_SEQUENCE   = 0b0000  # 无序列号
FLAG_HAS_SEQUENCE  = 0b0001  # 负载前 4 字节为序列号
FLAG_NEG_SEQUENCE  = 0b0010  # 负序列号（-1 首包 / -2 末包）

# ──── 资源配置 ────
WS_URL     = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
RESOURCE_ID = "volc.bigasr.sauc.duration"


class VolcASRClient:
    """火山引擎流式语音识别客户端 (WebSocket)"""

    def __init__(self):
        self.app_id = settings.VOLC_APP_ID
        self.access_token = settings.VOLC_ACCESS_TOKEN

    @staticmethod
    def _build_header(msg_type, compression=COMPRESSION_NONE,
                      serialization=SERIALIZATION_JSON, flags=FLAG_NO_SEQUENCE):
        return bytes([
            (PROTOCOL_VERSION << 4) | HEADER_SIZE,
            (msg_type << 4) | flags,
            (serialization << 4) | compression,
            0x00,
        ])

    @staticmethod
    def _parse_response(raw):
        """解析 WebSocket 二进制响应"""
        if isinstance(raw, str):
            raw = raw.encode()

        hdr_size   = (raw[0] & 0x0F) * 4
        msg_type   = (raw[1] >> 4) & 0x0F
        flags      = raw[1] & 0x0F
        compression = raw[2] & 0x0F
        payload    = raw[hdr_size:]

        if flags & 0x01:          # 跳过序列号
            payload = payload[4:]

        if msg_type == 0b1111:    # ERROR
            code = struct.unpack('>I', payload[:4])[0]
            size = struct.unpack('>I', payload[4:8])[0]
            err  = payload[8:8 + size]
            try:
                err = json.loads(gzip.decompress(err))
            except Exception:
                pass
            return {"type": "error", "code": code, "error": err}

        if msg_type == 0b1001:    # SERVER_RESPONSE
            size = struct.unpack('>I', payload[:4])[0]
            data = payload[4:4 + size]
            if compression == COMPRESSION_GZIP:
                data = gzip.decompress(data)
            return {"type": "response", "data": json.loads(data)}

        return {"type": "unknown", "msg_type": msg_type}

    # ──── 主流程 ────

    async def recognize(self, audio_path: str, on_progress=None) -> dict:
        """流式识别音频文件

        将本地音频通过 WebSocket 流式发送到火山引擎进行语音识别，
        无需公网 URL。

        on_progress: 可选回调，接收 0-100 的百分比整数

        Returns:
            {"status": "success", "segments": [...], "full_text": "..."}
        """
        wav_path = self.convert_to_wav(audio_path)

        with open(wav_path, 'rb') as f:
            audio_data = f.read()

        total_bytes = len(audio_data)

        request_id = str(uuid.uuid4())
        headers = {
            "X-Api-App-Key":    self.app_id,
            "X-Api-Access-Key": self.access_token,
            "X-Api-Resource-Id": RESOURCE_ID,
            "X-Api-Request-Id": request_id,
            "X-Api-Sequence":   "-1",
        }

        all_utterances = []
        full_text = ""

        async with websockets.connect(
            WS_URL,
            additional_headers=headers,
            ping_interval=20,
            ping_timeout=10,
            max_size=10 * 1024 * 1024,
        ) as ws:
            # ── 1. 发送元数据 ──
            metadata = {
                "user": {"uid": self.app_id},
                "audio": {
                    "format": "wav", "codec": "raw",
                    "rate": 16000, "bits": 16, "channel": 1,
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
            payload = gzip.compress(json.dumps(metadata).encode())
            header = self._build_header(
                MSG_FULL_CLIENT_REQUEST,
                compression=COMPRESSION_GZIP,
                flags=FLAG_NO_SEQUENCE,
            )
            await ws.send(header + struct.pack('>I', len(payload)) + payload)

            # ── 2. 发送音频数据（分块，无序列号）──
            chunk_size = 6400  # 200ms @ 16kHz 16bit mono
            bytes_sent = 0
            for idx, offset in enumerate(range(0, len(audio_data), chunk_size)):
                chunk = audio_data[offset:offset + chunk_size]
                bytes_sent += len(chunk)
                audio_header = self._build_header(
                    MSG_AUDIO_ONLY_REQUEST,
                    compression=COMPRESSION_NONE,
                    serialization=SERIALIZATION_NONE,
                    flags=FLAG_NO_SEQUENCE,
                )
                await ws.send(
                    audio_header + struct.pack('>I', len(chunk)) + chunk
                )

                if on_progress and idx % 5 == 0:
                    pct = min(90, int(bytes_sent / total_bytes * 100))
                    on_progress(pct)

            # ── 3. 发送结束包（与 test_streaming_all.py 完全一致）──
            last_header = self._build_header(
                MSG_AUDIO_ONLY_REQUEST,
                compression=COMPRESSION_NONE,
                serialization=SERIALIZATION_NONE,
                flags=FLAG_NEG_SEQUENCE,
            )
            await ws.send(last_header + struct.pack('>I', 0))

            # ── 4. 接收结果 ──
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=30)
                except (asyncio.TimeoutError, ConnectionClosedOK, ConnectionClosedError):
                    break

                resp = self._parse_response(raw)

                if resp["type"] == "error":
                    raise RuntimeError(f"ASR 识别错误: {resp['error']}")

                if resp["type"] == "response":
                    data = resp["data"]
                    result = data.get("result", {})
                    utterances = result.get("utterances", [])
                    text = result.get("text", "")

                    if utterances:
                        all_utterances = utterances
                    if text:
                        full_text = text

                    if full_text or utterances:
                        # 再收几秒确保拿完后续包
                        try:
                            while True:
                                raw = await asyncio.wait_for(ws.recv(), timeout=2)
                                resp = self._parse_response(raw)
                                if resp["type"] == "response":
                                    data = resp["data"]
                                    result = data.get("result", {})
                                    u2 = result.get("utterances", [])
                                    t2 = result.get("text", "")
                                    if u2:
                                        all_utterances = u2
                                    if t2:
                                        full_text = t2
                        except (asyncio.TimeoutError, ConnectionClosedOK, ConnectionClosedError):
                            pass
                        break

        # 清理临时文件
        if wav_path != audio_path:
            try:
                os.unlink(wav_path)
            except OSError:
                pass

        # 转换为统一格式
        segments = []
        for u in all_utterances:
            utt_text = u.get("text", "").strip()
            if utt_text:
                segments.append({
                    "text": utt_text,
                    "start": u.get("start_time", 0) / 1000.0,
                    "end":   u.get("end_time", 0) / 1000.0,
                    "confidence": u.get("confidence", 0.95),
                    "definite":   u.get("definite", False),
                    "words":      u.get("words", []),
                })

        return {
            "status": "success",
            "segments": segments,
            "full_text": full_text,
        }

    # ──── 音频预处理 ────

    @staticmethod
    def convert_to_wav(audio_path: str) -> str:
        """将音频转换为 16kHz 16bit mono WAV"""
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


def process_audio_file(audio_path: str) -> dict:
    """同步封装：通过流式识别处理本地音频文件"""
    return asyncio.run(VolcASRClient().recognize(audio_path))
