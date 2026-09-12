from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from uuid import uuid4

from app.services.ai_analyzer import AIAnalyzerError, analyze_image
from app.services.material_data_service import build_carbon_data


logger = logging.getLogger(__name__)
ANALYSIS_TASK_CACHE: dict[str, dict[str, Any]] = {}
TASK_TTL_SECONDS = 30 * 60


def _remove_expired_tasks() -> None:
    cutoff = time.monotonic() - TASK_TTL_SECONDS
    expired = [
        task_id
        for task_id, entry in ANALYSIS_TASK_CACHE.items()
        if entry.get("created", 0) < cutoff and entry.get("status") in {"SUCCEEDED", "FAILED"}
    ]
    for task_id in expired:
        ANALYSIS_TASK_CACHE.pop(task_id, None)


def _task_view(task_id: str, entry: dict[str, Any]) -> dict[str, Any]:
    view: dict[str, Any] = {
        "analysis_task_id": task_id,
        "status": entry["status"],
    }
    if entry["status"] == "SUCCEEDED":
        view["result"] = entry["result"]
    elif entry["status"] == "FAILED":
        view["error"] = entry["error"]
    return view


async def _run_analysis_task(
    task_id: str,
    image_bytes: bytes,
    content_type: str,
    filename: str,
) -> None:
    entry = ANALYSIS_TASK_CACHE[task_id]
    entry["status"] = "RUNNING"
    try:
        data = await analyze_image(image_bytes, content_type, filename)
        data = data.model_copy(update={"carbon_data": build_carbon_data(data.model_dump())})
        entry.update(status="SUCCEEDED", result=data.model_dump(mode="json"), error=None)
    except AIAnalyzerError as exc:
        entry.update(
            status="FAILED",
            result=None,
            error={"code": exc.code, "message": exc.message},
        )
    except Exception:
        logger.exception("[ANALYZE TASK] unexpected failure task_id=%s", task_id)
        entry.update(
            status="FAILED",
            result=None,
            error={
                "code": "AI_ANALYSIS_FAILED",
                "message": "AI 包装分析服务调用失败，请稍后重试。",
            },
        )


def submit_analysis_task(
    image_bytes: bytes,
    content_type: str,
    filename: str,
) -> dict[str, Any]:
    _remove_expired_tasks()
    task_id = f"analysis_{uuid4().hex[:24]}"
    entry: dict[str, Any] = {
        "status": "PENDING",
        "created": time.monotonic(),
        "result": None,
        "error": None,
        "work": None,
    }
    ANALYSIS_TASK_CACHE[task_id] = entry
    entry["work"] = asyncio.create_task(
        _run_analysis_task(task_id, image_bytes, content_type, filename)
    )
    return _task_view(task_id, entry)


def get_analysis_task(task_id: str) -> dict[str, Any]:
    _remove_expired_tasks()
    entry = ANALYSIS_TASK_CACHE.get(task_id)
    if entry is None:
        return {
            "analysis_task_id": task_id,
            "status": "FAILED",
            "error": {
                "code": "ANALYSIS_TASK_NOT_FOUND",
                "message": "分析任务不存在或已过期，请重新上传图片。",
            },
        }
    return _task_view(task_id, entry)
