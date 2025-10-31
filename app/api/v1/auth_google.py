from fastapi import APIRouter, Request, HTTPException
from authlib.integrations.starlette_client import OAuth
import os
from app.core.config import get_settings

router = APIRouter()
settings = get_settings()
oauth = OAuth()

oauth.register(
    name="google",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

@router.get("/auth/google/login", tags=["auth"])
async def google_login(request: Request):
    base_url = os.getenv("BASE_URL")
    if not base_url:
        raise HTTPException(status_code=500, detail="BASE_URL not configured")
    redirect_uri = f"{base_url}/v1/auth/google/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)

@router.get("/auth/google/callback", tags=["auth"])
async def google_callback(request: Request):
    token = await oauth.google.authorize_access_token(request)
    userinfo = token.get("userinfo") or {}
    # Save minimal profile in session
    request.session["user"] = {
        "email": userinfo.get("email"),
        "name": userinfo.get("name"),
        "picture": userinfo.get("picture"),
    }
    # Return something simple (later we'll redirect to frontend)
    return {"email": userinfo.get("email"), "name": userinfo.get("name")}

@router.get("/auth/me", tags=["auth"])
async def auth_me(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user

@router.post("/auth/logout", tags=["auth"])
async def auth_logout(request: Request):
    request.session.clear()
    return {"ok": True}
