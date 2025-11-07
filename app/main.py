import os
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
    """Create and configure FastAPI app."""
    setup_logging()
    settings = get_settings()

    app = FastAPI(title=settings.app_name)
    log = logging.getLogger("uvicorn.error")

    # -------------------------------------------------------------------------
    # CORS Configuration
    # -------------------------------------------------------------------------
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if "*" in origins else origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -------------------------------------------------------------------------
    # Session Middleware (Google OAuth)
    # -------------------------------------------------------------------------
    if not settings.app_session_secret:
        raise RuntimeError("APP_SESSION_SECRET is not set.")
    app.add_middleware(SessionMiddleware, secret_key=settings.app_session_secret)

    # -------------------------------------------------------------------------
    # Secrets Dependency
    # -------------------------------------------------------------------------
    def secret_dep() -> Dict[str, str | None]:
        s = get_settings()
        return {
            "openai_api_key": s.openai_api_key,
            "stripe_secret_key": s.stripe_secret_key,
            "google_client_id": s.google_client_id,
            "google_client_secret": s.google_client_secret,
            "azure_search_endpoint": s.azure_search_endpoint,
            "azure_search_key": "present" if s.azure_search_key else None,
        }

    # -------------------------------------------------------------------------
    # Include Routers
    # -------------------------------------------------------------------------
    app.include_router(v1_router, prefix="/v1", dependencies=[Depends(secret_dep)])
    app.include_router(google_router, prefix="/v1")
    app.include_router(search_admin_router, prefix="/v1")
    app.include_router(search_public_router, prefix="/v1")
    app.include_router(search_ingest_router, prefix="/v1")

    # -------------------------------------------------------------------------
    # Stripe Webhook — Handle Subscription Lifecycle
    # -------------------------------------------------------------------------
    stripe.api_key = os.getenv("STRIPE_API_KEY", "")
    WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    seen_events = set()  # simple in-memory idempotency guard

    # Temporary user "database" simulation
    user_subscriptions: Dict[str, Dict[str, str]] = {}

    async def activate_user(data: Dict[str, Any]) -> None:
        """Activate user when checkout completes"""
        email = (data.get("customer_details") or {}).get("email")
        sub_id = data.get("subscription")
        if not email:
            log.warning("⚠️ No email found in Stripe data")
            return
        user_subscriptions[email] = {"status": "active", "subscription_id": sub_id}
        log.info(f"✅ Activated subscription for {email} ({sub_id})")

    async def update_subscription_status(data: Dict[str, Any]) -> None:
        """Update subscription status"""
        sub_id = data.get("id")
        status = data.get("status")
        for email, info in user_subscriptions.items():
            if info.get("subscription_id") == sub_id:
                user_subscriptions[email]["status"] = status
                log.info(f"🔄 Updated {email} → {status}")
                return
        log.warning(f"Subscription {sub_id} not found in store")

    async def suspend_user(data: Dict[str, Any]) -> None:
        """Suspend user after failed payment"""
        sub_id = data.get("subscription") or data.get("customer")
        for email, info in user_subscriptions.items():
            if info.get("subscription_id") == sub_id:
                user_subscriptions[email]["status"] = "suspended"
                log.warning(f"🚫 Suspended {email} due to failed payment")
                return
        log.warning(f"Failed payment: subscription {sub_id} not found")

    # Map event types to handler functions
    def route_event(event_type: str):
        return {
            "checkout.session.completed": activate_user,
            "customer.subscription.created": update_subscription_status,
            "customer.subscription.updated": update_subscription_status,
            "invoice.payment_succeeded": update_subscription_status,
            "invoice.payment_failed": suspend_user,
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
