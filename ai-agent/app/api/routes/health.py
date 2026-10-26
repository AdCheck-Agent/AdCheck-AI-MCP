from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict:
    """서버가 떠 있으면 항상 200. `features`는 설정 때문에 꺼진 기능을 보여 준다."""
    features = getattr(request.app.state, "features", {})
    return {"status": "ok", "service": "adcheck-ai-agent", "features": features}
