from fastapi import APIRouter, File, UploadFile, status
from fastapi.responses import JSONResponse

from app.schemas.models import AnalysisResponse, ErrorResponse
from app.services.ai_analyzer import AIAnalyzerError, analyze_image


router = APIRouter(prefix="/api", tags=["analysis"])


@router.post(
    "/analyze",
    response_model=AnalysisResponse,
    responses={
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {"model": ErrorResponse},
        status.HTTP_502_BAD_GATEWAY: {"model": ErrorResponse},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse},
    },
)
async def analyze_packaging(image: UploadFile = File(...)) -> AnalysisResponse | JSONResponse:
    """Validate an uploaded image and analyze it with Qwen Vision."""
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
    image_bytes = await image.read()
    await image.close()

    try:
        data = await analyze_image(image_bytes, image.content_type, filename)
    except AIAnalyzerError as exc:
        status_code = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if exc.code == "AI_CONFIGURATION_ERROR"
            else status.HTTP_502_BAD_GATEWAY
        )
        return JSONResponse(
            status_code=status_code,
            content={
                "success": False,
                "error": {"code": exc.code, "message": exc.message},
            },
        )
    return AnalysisResponse(data=data)
