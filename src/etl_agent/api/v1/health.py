"""Health check endpoint."""
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    version: str


@router.get("/health", response_model=HealthResponse, include_in_schema=True)
async def health_check() -> HealthResponse:
    """Returns service health status. No authentication required."""
    return HealthResponse(status="ok", version="0.1.0")
