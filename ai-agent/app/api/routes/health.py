from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict:
    """Always 200 while the server runs; `features` shows what is switched off by settings."""
    features = getattr(request.app.state, "features", {})
    return {"status": "ok", "service": "adcheck-ai-agent", "features": features}
