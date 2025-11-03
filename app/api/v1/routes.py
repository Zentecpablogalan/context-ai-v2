from fastapi import APIRouter
from app.core.config import get_settings

router = APIRouter()

def _mask(v: str | None) -> str | None:
    if v is None:
        return None
    return f"present(len={len(v)})"

@router.get("/env", tags=["meta"])
def env():
    s = get_settings()
    return {
        "env": {
            "OPENAI_API_KEY": _mask(s.openai_api_key),
            "STRIPE_SECRET_KEY": _mask(s.stripe_secret_key),
            "GOOGLE_CLIENT_ID": _mask(s.google_client_id),
            "GOOGLE_CLIENT_SECRET": _mask(s.google_client_secret),
            # Azure Search
            "AZURE_SEARCH_ENDPOINT": s.azure_search_endpoint,
            "AZURE_SEARCH_KEY": "present" if s.azure_search_key else None,
        }
    }
