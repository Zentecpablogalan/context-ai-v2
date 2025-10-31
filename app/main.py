from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.api.v1.routes import router as v1_router
from app.api.v1.auth_google import router as google_router

def create_app() -> FastAPI:
    setup_logging()
    settings = get_settings()

    app = FastAPI(title=settings.app_name)

    # CORS
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if "*" in origins else origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


    # Sessions for OAuth (required)
    if not settings.app_session_secret:
        raise RuntimeError("APP_SESSION_SECRET is not set.")
    app.add_middleware(SessionMiddleware, secret_key=settings.app_session_secret)

    # Optional dependency for /v1/env to mask secrets
    def secret_dep() -> dict[str, str | None]:
        s = get_settings()
        return dict(
            openai_api_key=s.openai_api_key,
            stripe_secret_key=s.stripe_secret_key,
            google_client_id=s.google_client_id,
            google_client_secret=s.google_client_secret,
        )

    # Routers
    app.include_router(v1_router, prefix="/v1", dependencies=[Depends(secret_dep)])
    app.include_router(google_router, prefix="/v1")

    # Azure health ping
    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
