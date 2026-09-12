from fastapi import APIRouter, File, Request, UploadFile, status
from fastapi.responses import JSONResponse

from app.schemas.models import AnalysisResponse, ErrorResponse
from app.services.ai_analyzer import AIAnalyzerError, analyze_image
from app.services.analysis_tasks import get_analysis_task, submit_analysis_task
from app.services.material_data_service import build_carbon_data


router = APIRouter(prefix="/api", tags=["analysis"])


@router.post(
    "/analyze",
    response_model=AnalysisResponse,
    responses={
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {"model": ErrorResponse},
        status.HTTP_502_BAD_GATEWAY: {"model": ErrorResponse},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse},
        status.HTTP_429_TOO_MANY_REQUESTS: {"model": ErrorResponse},
    },
)
async def analyze_packaging(
    request: Request,
    image: UploadFile = File(...),
) -> AnalysisResponse | JSONResponse:
    """Validate an uploaded image and analyze it with Qwen Vision."""
    print("[ANALYZE] request received", flush=True)
    if not image.content_type or not image.content_type.startswith("image/"):
        await image.close()
        return JSONResponse(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            content={
                "success": False,
                "error": {
                    "code": "INVALID_FILE_TYPE",
                    "message": "Please upload an image file.",
                },
            },
        )

    filename = image.filename or "uploaded-image"
    content_type = image.content_type
    image_bytes = await image.read()
    await image.close()

    if "respond-async" in request.headers.get("prefer", "").lower():
        if not image_bytes:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "success": False,
                    "error": {"code": "EMPTY_IMAGE", "message": "上传的图片为空。"},
                },
            )
        task = submit_analysis_task(image_bytes, content_type, filename)
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"success": True, "data": task},
        )

    try:
        data = await analyze_image(image_bytes, content_type, filename)
    except AIAnalyzerError as exc:
        if exc.code == "AI_RATE_LIMITED":
            status_code = status.HTTP_429_TOO_MANY_REQUESTS
        elif exc.code in {"AI_CONFIGURATION_ERROR", "AI_BILLING_ERROR", "AI_AUTH_ERROR"}:
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        else:
            status_code = status.HTTP_502_BAD_GATEWAY
        return JSONResponse(
            status_code=status_code,
            content={
                "success": False,
                "error": {"code": exc.code, "message": exc.message},
            },
        )
    data = data.model_copy(update={"carbon_data": build_carbon_data(data.model_dump())})
    return AnalysisResponse(data=data)


@router.get("/analyze/status/{task_id}")
async def analysis_status(task_id: str) -> JSONResponse:
    task = get_analysis_task(task_id)
    if task["status"] in {"PENDING", "RUNNING"}:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"success": True, "data": task},
        )
    if task["status"] == "FAILED":
        error = task["error"]
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"success": False, "error": error},
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"success": True, "data": task["result"]},
    )
