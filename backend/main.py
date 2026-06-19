"""AutoCut - FastAPI 入口"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时确保目录存在
    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    Path(settings.OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="AutoCut", version="0.1.0", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

# 上传/输出目录挂载
uploads_dir = Path(settings.UPLOAD_DIR).resolve()
outputs_dir = Path(settings.OUTPUT_DIR).resolve()
if uploads_dir.exists():
    app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")
if outputs_dir.exists():
    app.mount("/outputs", StaticFiles(directory=str(outputs_dir)), name="outputs")


@app.get("/")
async def index():
    """返回前端页面"""
    from fastapi.responses import FileResponse
    return FileResponse(str(frontend_dir / "index.html"))


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


# 延迟注册路由（避免循环导入）
from backend.routes import upload, process, export
app.include_router(upload.router, prefix="/api", tags=["upload"])
app.include_router(process.router, prefix="/api", tags=["process"])
app.include_router(export.router, prefix="/api", tags=["export"])
