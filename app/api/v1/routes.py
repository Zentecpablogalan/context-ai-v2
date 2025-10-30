from fastapi import APIRouter, HTTPException

router = APIRouter()

@router.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}

@router.get("/env", tags=["meta"])
def env(openai_api_key: str | None = None,
        stripe_secret_key: str | None = None,
        google_client_id: str | None = None,
        google_client_secret: str | None = None):
    vals = {
        "OPENAI_API_KEY": openai_api_key,
        "STRIPE_SECRET_KEY": stripe_secret_key,
        "GOOGLE_CLIENT_ID": google_client_id,
        "GOOGLE_CLIENT_SECRET": google_client_secret,
    }
    masked = {k: (None if v is None else f"present(len={len(v)})") for k, v in vals.items()}
    return {"env": masked}

@router.get("/search", tags=["search"])
def search_placeholder(q: str | None = None):
    # Placeholder endpoint for v1 search; raises 501 until implemented
    raise HTTPException(status_code=501, detail="Search API not implemented yet.")
