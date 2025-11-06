import os
import logging
import stripe
from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api.v1.search_admin import router as search_admin_router
from app.api.v1.search_public import router as search_public_router
from app.api.v1.search_ingest import router as search_ingest_router
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.api.v1.routes import router as v1_router
from app.api.v1.auth_google import router as google_router


def create_app() -> FastAPI:
    setup_logging()
    settings = get_settings()

    app = FastAPI(title=settings.app_name)
    log = logging.getLogger("uvicorn.error")

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

    # Dependency to mask secrets in /v1/env
    def secret_dep() -> dict[str, str | None]:
        s = get_settings()
        return {
            "openai_api_key": s.openai_api_key,
            "stripe_secret_key": s.stripe_secret_key,
            "google_client_id": s.google_client_id,
            "google_client_secret": s.google_client_secret,
            "azure_search_endpoint": s.azure_search_endpoint,
            "azure_search_key": "present" if s.azure_search_key else None,
        }

    # Routers
    app.include_router(v1_router, prefix="/v1", dependencies=[Depends(secret_dep)])
    app.include_router(google_router, prefix="/v1")
    app.include_router(search_admin_router, prefix="/v1")
    app.include_router(search_public_router, prefix="/v1")
    app.include_router(search_ingest_router, prefix="/v1")

    # Stripe webhook configuration
    stripe.api_key = os.getenv("STRIPE_API_KEY", "")
    WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

    @app.post("/v1/billing/webhook", include_in_schema=True)
    @app.post("/v1/billing/webhook/", include_in_schema=True)
    async def stripe_webhook(request: Request):
        """Handle Stripe webhook events"""
        payload = await request.body()
        sig = request.headers.get("stripe-signature")

        try:
            event = stripe.Webhook.construct_event(payload, sig, WEBHOOK_SECRET)
        except stripe.error.SignatureVerificationError:
            raise HTTPException(status_code=400, detail="Invalid signature")
        except Exception as e:
            log.exception("Webhook error: %s", e)
            raise HTTPException(status_code=400, detail="Invalid payload")

        log.info("✅ Stripe event received: %s", event.get("type"))
        return {"received": True}

    # Azure health ping
    @app.get("/health")
    def health():
        return {"status": "ok"}

    # Log all routes at startup for verification
    @app.on_event("startup")
    async def log_routes():
        for route in app.router.routes:
            methods = getattr(route, "methods", [])
            path = getattr(route, "path", "")
            log.info("ROUTE %s %s", ",".join(sorted(methods)), path)

    return app


app = create_app()
