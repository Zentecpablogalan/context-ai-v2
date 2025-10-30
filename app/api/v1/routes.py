from fastapi import APIRouter
from app.core.config import get_settings

router = APIRouter()

@router.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}

@router.get("/env", tags=["meta"])
def env():
    s = get_settings()
    vals = {
        "OPENAI_API_KEY": s.openai_api_key,
        "STRIPE_SECRET_KEY": s.stripe_secret_key,
        "GOOGLE_CLIENT_ID": s.google_client_id,
        "GOOGLE_CLIENT_SECRET": s.google_client_secret,
    }
    masked = {k: (None if v is None else f"present(len={len(v)})") for k, v in vals.items()}
    return {"env": masked}

@router.get("/search", tags=["search"])
def search_placeholder(q: str | None = None):
    return {"detail": "Search API not implemented yet."}
