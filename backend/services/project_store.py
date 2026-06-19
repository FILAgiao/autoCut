"""项目持久化 - 文件系统 CRUD

每个项目一个子目录:
projects/
  {project_id}/
    ├── project.json    # 完整项目数据
    ├── clips/          # 上传的视频片段
    └── exports/        # 导出产物
"""

import json
import uuid
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

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
    """保存视频片段到项目的 clips/ 目录，返回 clip 信息"""
    _ensure_dir()
    d = _project_dir(project_id)
    clips_dir = d / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    # 生成唯一文件名
    ext = Path(filename).suffix or ".mp4"
    existing = list(clips_dir.glob(f"clip_*{ext}"))
    clip_idx = len(existing) + 1
    clip_filename = f"clip_{clip_idx:03d}{ext}"
    clip_path = clips_dir / clip_filename
    clip_path.write_bytes(content)

    clip_id = f"c{clip_idx}"
    clip_info = {
        "id": clip_id,
        "filename": clip_filename,
        "original_name": original_name or filename,
        "duration": 0,  # 后续处理时更新
    }

    # 追加到 project
    project = _read_project_json(project_id)
    if project is not None:
        project.setdefault("clips", []).append(clip_info)
        project["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_project_json(project_id, project)

    return clip_info


def get_clip_path(project_id: str, clip_id: str) -> Path | None:
    """获取视频片段文件路径"""
    project = _read_project_json(project_id)
    if not project:
        return None
    for clip in project.get("clips", []):
        if clip["id"] == clip_id:
            p = _project_dir(project_id) / "clips" / clip["filename"]
            if p.exists():
                return p
    return None


def get_first_clip_path(project_id: str) -> Path | None:
    """获取第一个视频片段文件路径"""
    project = _read_project_json(project_id)
    if not project:
        return None
    clips = project.get("clips", [])
    if not clips:
        return None
    return get_clip_path(project_id, clips[0]["id"])


def get_export_dir(project_id: str) -> Path:
    """获取项目的导出目录"""
    d = _project_dir(project_id) / "exports"
    d.mkdir(parents=True, exist_ok=True)
    return d
