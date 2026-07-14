from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class LiveResponse(BaseModel):
    status: str
    service: str


@router.get("/live", response_model=LiveResponse)
def live() -> LiveResponse:
    return LiveResponse(status="ok", service="bi-system")
