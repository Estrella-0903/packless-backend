from fastapi import APIRouter, File, UploadFile, status
from fastapi.responses import JSONResponse

from app.mock.mock_data import build_mock_analysis
from app.schemas.models import AnalysisResponse, ErrorResponse


router = APIRouter(prefix="/api", tags=["analysis"])


@router.post(
    "/analyze",
    response_model=AnalysisResponse,
    responses={status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {"model": ErrorResponse}},
)
async def analyze_packaging(image: UploadFile = File(...)) -> AnalysisResponse | JSONResponse:
    """Validate an uploaded image and return deterministic MVP analysis data."""
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
    await image.close()
    return AnalysisResponse(data=build_mock_analysis(filename))
