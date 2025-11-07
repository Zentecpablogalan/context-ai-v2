import os
import json
import logging
from typing import Any, Dict

import stripe
from fastapi import FastAPI, Depends, Request, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api.v1.search_admin import router as search_admin_router
from app.api.v1.search_public import router as search_public_router
from app.api.v1.search_ingest import router as search_ingest_router
from app.api.v1.routes import router as v1_router
from app.api.v1.auth_google import router as google_router
from app.core.config import get_settings
from app.core.logging import setup_logging


def create_app() -> FastAPI:
    setup_logging()
    settings = get_settings()

    app = FastAPI(title=settings.app_name)
    log = logging.getLogger("uvicorn.error")

    # --- CORS Configuration ---
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if "*" in origins else origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Session Middleware (for Google OAuth) ---
    if not settings.app_session_secret:
        raise RuntimeError("APP_SESSION_SECRET is not set.")
    app.add_middleware(SessionMiddleware, secret_key=settings.app_session_secret)

    # --- Mask Secrets Dependency ---
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

    # --- Include Routers ---
    app.include_router(v1_router, prefix="/v1", dependencies=[Depends(secret_dep)])
    app.include_router(google_router, prefix="/v1")
    app.include_router(search_admin_router, prefix="/v1")
    app.include_router(search_public_router, prefix="/v1")
    app.include_router(search_ingest_router, prefix="/v1")

    # -------------------------------------------------------------------------
    # Stripe Webhook — Robust, Production-Ready Implementation
    # -------------------------------------------------------------------------
    stripe.api_key = os.getenv("STRIPE_API_KEY", "")
    WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    seen_events = set()  # simple in-memory idempotency guard

    async def handle_checkout_completed(data: Dict[str, Any]) -> None:
        """Handle successful checkout sessions"""
        customer_id = data.get("customer")
        subscription_id = data.get("subscription")
        email = (data.get("customer_details") or {}).get("email")
        log.info(f"✅ Checkout completed: email={email}, customer={customer_id}, sub={subscription_id}")
        # TODO: activate subscription in your DB

    async def handle_subscription_updated(data: Dict[str, Any]) -> None:
        """Handle subscription updates (renewal, cancellation, etc.)"""
        sub_id = data.get("id")
        status = data.get("status")
        customer = data.get("customer")
        log.info(f"🔄 Subscription updated: sub={sub_id}, status={status}, customer={customer}")
        # TODO: update subscription in your DB

    def route_event(event_type: str):
        """Map Stripe event type → handler"""
        return {
            "checkout.session.completed": handle_checkout_completed,
            "customer.subscription.updated": handle_subscription_updated,
            "customer.subscription.created": handle_subscription_updated,
            "invoice.payment_succeeded": handle_subscription_updated,
            "invoice.payment_failed": handle_subscription_updated,
        }.get(event_type)

    @app.post("/v1/billing/webhook", include_in_schema=True)
    @app.post("/v1/billing/webhook/", include_in_schema=True)
    async def stripe_webhook(request: Request, background: BackgroundTasks):
        """Main Stripe webhook endpoint"""
        if not WEBHOOK_SECRET:
            log.error("❌ STRIPE_WEBHOOK_SECRET missing in environment")
            raise HTTPException(status_code=500, detail="Webhook not configured")

        payload = await request.body()
        sig = request.headers.get("stripe-signature")

        if not sig:
            raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")

        try:
            event = stripe.Webhook.construct_event(payload, sig, WEBHOOK_SECRET)
        except stripe.error.SignatureVerificationError:
            raise HTTPException(status_code=400, detail="Invalid signature")
        except Exception as e:
            log.exception("⚠️ Webhook parse error: %s", e)
            raise HTTPException(status_code=400, detail="Invalid payload")

        event_id = event.get("id")
        event_type = event.get("type")
        data = (event.get("data") or {}).get("object") or {}

        # Idempotency check
        if event_id in seen_events:
            log.info(f"🔁 Duplicate Stripe event ignored: {event_id}")
            return {"received": True, "duplicate": True}
        seen_events.add(event_id)

        log.info(f"🎯 Stripe event received: {event_type}")

        handler = route_event(event_type)
        if handler:
            background.add_task(handler, data)
        else:
            log.info(f"No handler for event type {event_type}")

        return {"received": True}

    # -------------------------------------------------------------------------
    # Health Check Endpoint
    # -------------------------------------------------------------------------
    @app.get("/health")
    def health():
        return {"status": "ok"}

    # -------------------------------------------------------------------------
    # Route Logging on Startup
    # -------------------------------------------------------------------------
    @app.on_event("startup")
    async def log_routes():
        for route in app.router.routes:
            methods = getattr(route, "methods", [])
            path = getattr(route, "path", "")
            log.info("ROUTE %s %s", ",".join(sorted(methods)), path)

    return app


app = create_app()
