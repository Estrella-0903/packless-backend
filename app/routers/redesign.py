from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile

from app.schemas.models import ErrorResponse, RedesignResponse
from app.services.image_generator import submit_optimized_image_task, check_optimized_image_task
from app.services.prompt_builder import build_image_generation_prompt
from app.services.redesign_service import create_redesign_plan


router = APIRouter(prefix="/api", tags=["redesign"])


def _error(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "success": False,
            "error": {"code": "INVALID_REDESIGN_REQUEST", "message": message},
        },
    )


async def _parse_request(request: Request) -> tuple[dict[str, Any], bytes | None] | JSONResponse:
    content_type = request.headers.get("content-type", "").lower()
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        raw_analysis = form.get("analysis_result")
        image = form.get("image")
        if raw_analysis is None:
            return _error("Multipart requests must include analysis_result JSON.")
        try:
            analysis = json.loads(str(raw_analysis))
        except json.JSONDecodeError:
            return _error("analysis_result must be valid JSON.")
        if not isinstance(analysis, dict):
            return _error("analysis_result must be a JSON object.")
        if image is not None and not isinstance(image, UploadFile):
            return _error("image must be an uploaded image file.")
        if isinstance(image, UploadFile):
            if not image.content_type or not image.content_type.startswith("image/"):
                await image.close()
                return _error("image must be an image file.")
            image_bytes = await image.read()
            await image.close()
            return analysis, image_bytes
        return analysis, None

    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _error("Request body must be JSON or multipart/form-data.")
    if not isinstance(body, dict):
        return _error("Request body must be a JSON object.")
    analysis = body.get("analysis_result", body)
    if not isinstance(analysis, dict):
        return _error("analysis_result must be a JSON object.")
    return analysis, None


@router.post(
    "/redesign",
    response_model=RedesignResponse,
    responses={status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse}},
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["analysis_result"],
                        "properties": {
                            "analysis_result": {
                                "type": "string",
                                "description": "JSON returned by POST /api/analyze",
                            },
                            "image": {"type": "string", "format": "binary"},
                        },
                    }
                },
                "application/json": {"schema": {"type": "object"}},
            },
        }
    },
)
async def redesign_packaging(request: Request) -> RedesignResponse | JSONResponse:
    print("[REDESIGN] request received", flush=True)
    parsed = await _parse_request(request)
    if isinstance(parsed, JSONResponse):
        return parsed
    analysis_result, image_bytes = parsed
    print(
        f"[REDESIGN] image uploaded={bool(image_bytes)}, "
        f"analysis received={bool(analysis_result)}",
        flush=True,
    )
    plan = create_redesign_plan(analysis_result)

    if image_bytes:
        prompt = build_image_generation_prompt(
            analysis_result,
            plan.change_plan.model_dump(by_alias=True),
            plan.after_render_spec.model_dump(by_alias=True),
        )
        try:
            print("[REDESIGN] starting Seedream image generation", flush=True)
            generation = await submit_optimized_image_task(image_bytes, prompt)
        except Exception:
            generation = {
                "success": False,
                "image_url": "",
                "error": "Unexpected image generation error.",
            }
        if generation["success"] and generation.get("task_id"):
            plan = plan.model_copy(
                update={
                    "optimized_image_url": "",
                    "image_task_id": generation["task_id"],
                    "image_generation_status": "PENDING",
                    "image_generation_failed": False,
                    "image_generation_error": "",
                }
            )
        else:
            plan = plan.model_copy(
                update={
                    "optimized_image_url": "",
                    "image_generation_failed": True,
                    "image_generation_error": generation.get("error")
                    or "AI image generation failed.",
                }
            )

    print(
        f"[REDESIGN] returning image_generation_failed="
        f"{plan.image_generation_failed}, "
        f"optimized_image_url={plan.optimized_image_url}, "
        f"error={plan.image_generation_error}",
        flush=True,
    )
    return RedesignResponse(data=plan)


@router.get("/redesign/image-status/{task_id}")
async def redesign_image_status(task_id: str) -> dict:
    return {"success": True, "data": await check_optimized_image_task(task_id)}
