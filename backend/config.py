"""配置管理，从 .env 读取"""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # 火山引擎 ASR
    VOLC_APP_ID: str = os.getenv("VOLC_APP_ID", "")
    VOLC_ACCESS_TOKEN: str = os.getenv("VOLC_ACCESS_TOKEN", "")
    VOLC_SECRET_KEY: str = os.getenv("VOLC_SECRET_KEY", "")

    # LLM
    LLM_API_BASE: str = os.getenv("LLM_API_BASE", "https://ark.cn-beijing.volces.com/api/v3")
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "")

    # 字幕样式
    SUBTITLE_FONT: str = os.getenv("SUBTITLE_FONT", "Source Han Sans SC")
    SUBTITLE_SIZE_RATIO: float = float(os.getenv("SUBTITLE_SIZE_RATIO", "0.08"))
    SUBTITLE_COLOR: tuple = tuple(map(float, os.getenv("SUBTITLE_COLOR", "1.0,1.0,1.0").split(",")))
    SUBTITLE_STROKE_COLOR: tuple = tuple(map(float, os.getenv("SUBTITLE_STROKE_COLOR", "0.0,0.0,0.0").split(",")))
    SUBTITLE_STROKE_WIDTH: float = float(os.getenv("SUBTITLE_STROKE_WIDTH", "0.04"))
    SUBTITLE_MAX_CHARS: int = int(os.getenv("SUBTITLE_MAX_CHARS", "12"))
    SUBTITLE_POSITION_Y: float = float(os.getenv("SUBTITLE_POSITION_Y", "-0.75"))

    # 视频输出
    _resolution = os.getenv("OUTPUT_RESOLUTION", "1080,1920").split(",")
    OUTPUT_WIDTH: int = int(_resolution[0])
    OUTPUT_HEIGHT: int = int(_resolution[1])

    # TOS 对象存储
    TOS_BUCKET: str = os.getenv("TOS_BUCKET", "")
    TOS_ENDPOINT: str = os.getenv("TOS_ENDPOINT", "")
    TOS_ACCESS_KEY: str = os.getenv("TOS_ACCESS_KEY", "")
    TOS_SECRET_KEY: str = os.getenv("TOS_SECRET_KEY", "")
    TOS_REGION: str = os.getenv("TOS_REGION", "cn-beijing")

    # 本地音频服务 (开发用)
    LOCAL_AUDIO_BASE_URL: str = os.getenv("LOCAL_AUDIO_BASE_URL", "")

    # 服务
    HOST: str = os.getenv("HOST", "127.0.0.1")
    PORT: int = int(os.getenv("PORT", "8520"))
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "./uploads")
    OUTPUT_DIR: str = os.getenv("OUTPUT_DIR", "./outputs")
    MAX_VIDEO_SIZE_MB: int = int(os.getenv("MAX_VIDEO_SIZE_MB", "500"))


settings = Settings()
