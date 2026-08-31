from fastapi import APIRouter

from app.mock.mock_data import MATERIALS
from app.schemas.models import MaterialsResponse


router = APIRouter(prefix="/api", tags=["materials"])


@router.get("/materials", response_model=MaterialsResponse)
async def list_materials() -> MaterialsResponse:
    return MaterialsResponse(data=MATERIALS)
