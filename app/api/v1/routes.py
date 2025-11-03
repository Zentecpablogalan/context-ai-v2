from fastapi import APIRouter, Depends
from typing import Dict, Any

router = APIRouter()

@router.get("/env", tags=["meta"])
def env(secret_dep: Dict[str, Any] = Depends()):
    # secret_dep comes from main.py's dependency and already contains masked values
    s = secret_dep
    def mask(v: str | None) -> str | None:
        if v is None:
            return None
        # If value is the literal string "present" we keep it as-is
        if v == "present":
            return "present"
        # Otherwise show "present(len=...)" like before
        return f"present(len={len(v)})"
    return {
        "env": {
            "OPENAI_API_KEY": mask(s.get("openai_api_key")),
            "STRIPE_SECRET_KEY": mask(s.get("stripe_secret_key")),
            "GOOGLE_CLIENT_ID": mask(s.get("google_client_id")),
            "GOOGLE_CLIENT_SECRET": mask(s.get("google_client_secret")),
            # New:
            "AZURE_SEARCH_ENDPOINT": s.get("azure_search_endpoint"),
            "AZURE_SEARCH_KEY": mask(s.get("azure_search_key")),
        }
    }
