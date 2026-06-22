"""项目持久化 - 文件系统 CRUD

每个项目一个子目录:
projects/
  {project_id}/
    ├── project.json    # 完整项目数据
    ├── clips/          # 上传的视频片段
    └── exports/        # 导出产物
"""

from __future__ import annotations

import json
import uuid
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from backend.services.media import _FFMPEG, _FFPROBE

PROJECTS_DIR = Path("projects")


def _ensure_dir():
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


def _project_dir(project_id: str) -> Path:
    return PROJECTS_DIR / project_id


def _project_file(project_id: str) -> Path:
    return _project_dir(project_id) / "project.json"


def _read_project_json(project_id: str) -> dict | None:
    fp = _project_file(project_id)
    if not fp.exists():
        return None
    return json.loads(fp.read_text(encoding="utf-8"))


def _write_project_json(project_id: str, data: dict):
    _ensure_dir()
    d = _project_dir(project_id)
    d.mkdir(parents=True, exist_ok=True)
    fp = d / "project.json"
    fp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


# --- Public API ---

def create_project(name: str, script: str = "") -> dict:
    """创建新项目，返回 project 数据"""
    _ensure_dir()
    project_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()
    project = {
        "id": project_id,
        "name": name,
        "script": script,
        "created_at": now,
        "updated_at": now,
        "clips": [],
        "task_id": project_id,
        "task_status": "idle",
        "result": None,
        "confirmed_count": 0,
        "total_count": 0,
    }
    _write_project_json(project_id, project)
    return project


def get_project(project_id: str) -> dict | None:
    return _read_project_json(project_id)


def list_projects() -> list[dict]:
    """返回所有项目摘要列表，按更新时间倒序"""
    _ensure_dir()
    projects = []
    for d in PROJECTS_DIR.iterdir():
        if d.is_dir():
            data = _read_project_json(d.name)
            if data:
                projects.append(data)
    projects.sort(key=lambda p: p.get("updated_at", ""), reverse=True)
    return projects


def update_project(project_id: str, **kwargs) -> dict | None:
    """部分更新项目数据，返回更新后的完整 project"""
    project = _read_project_json(project_id)
    if project is None:
        return None
    project.update(kwargs)
    project["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_project_json(project_id, project)
    return project


def delete_project(project_id: str) -> bool:
    """删除整个项目目录"""
    d = _project_dir(project_id)
    if d.exists():
        shutil.rmtree(d)
        return True
    return False


def save_clip(project_id: str, filename: str, content: bytes, original_name: str = "") -> dict:
    """保存视频片段到项目的 clips/ 目录，返回 clip 信息

    原始文件保留不动（导出剪映草稿用高质量原片）。
    同时生成一个 H.264 预览文件（浏览器播放用，参数从低保证兼容即可）。
    """
    _ensure_dir()
    d = _project_dir(project_id)
    clips_dir = d / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    # 生成唯一文件名（排除 preview 文件，只数原始文件）
    ext = Path(filename).suffix or ".mp4"
    existing = [p for p in clips_dir.glob(f"clip_*{ext}") if "_preview" not in p.stem]
    clip_idx = len(existing) + 1
    clip_filename = f"clip_{clip_idx:03d}{ext}"
    preview_filename = f"clip_{clip_idx:03d}_preview.mp4"
    clip_path = clips_dir / clip_filename
    clip_path.write_bytes(content)

    # 生成浏览器预览文件 (H.264 + faststart + 1080p max, 低质量快速编码)
    import subprocess
    preview_path = clips_dir / preview_filename
    try:
        result = subprocess.run([
            _FFMPEG, '-i', str(clip_path),
            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28',
            '-vf', 'scale=1920:1080:force_original_aspect_ratio=decrease',
            '-c:a', 'aac', '-b:a', '96k',
            '-movflags', '+faststart',
            '-y', str(preview_path)
        ], capture_output=True, timeout=300)
        if not (preview_path.exists() and preview_path.stat().st_size > 1000):
            preview_path.unlink(missing_ok=True)
    except Exception:
        pass  # 转码失败不阻塞上传，前端回退用原始文件

    # 获取原始视频时长
    duration = 0
    try:
        result = subprocess.run([
            _FFPROBE, '-v', 'quiet', '-show_entries', 'format=duration',
            '-of', 'csv=p=0', str(clip_path)
        ], capture_output=True, text=True, timeout=10)
        duration = float(result.stdout.strip() or 0)
    except Exception:
        pass

    clip_id = f"c{clip_idx}"
    clip_info = {
        "id": clip_id,
        "filename": clip_filename,
        "preview_filename": preview_filename if preview_path.exists() else None,
        "original_name": original_name or filename,
        "duration": duration,
        "file_size": clip_path.stat().st_size,
    }

    # 追加到 project
    project = _read_project_json(project_id)
    if project is not None:
        project.setdefault("clips", []).append(clip_info)
        project["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_project_json(project_id, project)

    return clip_info


def get_clip_path(project_id: str, filename: str) -> Path | None:
    """通过文件名获取 clips/ 下的原始文件路径（导出用）"""
    p = _project_dir(project_id) / "clips" / filename
    return p if p.exists() else None


def get_preview_path(project_id: str, filename: str, preview_filename: str | None = None) -> Path | None:
    """获取预览文件路径，不存在时回退到原始文件"""
    clips_dir = _project_dir(project_id) / "clips"
    if preview_filename:
        preview_path = clips_dir / preview_filename
        if preview_path.exists():
            return preview_path
    # 回退到原始文件
    original = clips_dir / filename
    return original if original.exists() else None


def clip_exists(project_id: str, filename: str) -> bool:
    """检查 clips/ 下的文件是否真实存在"""
    path = _project_dir(project_id) / "clips" / filename
    return path.exists() and path.is_file()


def get_first_clip_path(project_id: str) -> Path | None:
    """获取第一个视频片段文件路径"""
    project = _read_project_json(project_id)
    if not project:
        return None
    clips = project.get("clips", [])
    if not clips:
        return None
    return get_clip_path(project_id, clips[0]["filename"])


def get_export_dir(project_id: str) -> Path:
    """获取项目的导出目录"""
    d = _project_dir(project_id) / "exports"
    d.mkdir(parents=True, exist_ok=True)
    return d
