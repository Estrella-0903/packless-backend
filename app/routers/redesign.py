from fastapi import APIRouter

from app.mock.mock_data import build_mock_redesign
from app.schemas.models import RedesignRequest, RedesignResponse


router = APIRouter(prefix="/api", tags=["redesign"])


@router.post("/redesign", response_model=RedesignResponse)
async def redesign_packaging(request: RedesignRequest) -> RedesignResponse:
    return RedesignResponse(data=build_mock_redesign(request))
