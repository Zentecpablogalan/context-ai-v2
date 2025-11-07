import os
import json
import base64
import logging
from typing import Any, Dict, Optional

import stripe
from fastapi import FastAPI, Depends, Request, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from google.cloud import firestore  # type: ignore
from google.oauth2 import service_account  # type: ignore
from google.api_core import exceptions as gcloud_exceptions  # type: ignore

from app.api.v1.search_admin import router as search_admin_router
from app.api.v1.search_public import router as search_public_router
from app.api.v1.search_ingest import router as search_ingest_router
from app.api.v1.routes import router as v1_router
from app.api.v1.auth_google import router as google_router
from app.core.config import get_settings
from app.core.logging import setup_logging


# -----------------------------
# Firestore client helper
# -----------------------------
_firestore_client: Optional[firestore.Client] = None

def get_firestore_client() -> firestore.Client:
    """
    Build a Firestore client from FIRESTORE_SA_B64 (base64 of the service account JSON).
    Falls back to ADC if the var is missing (but we expect it to be present in Azure env).
    """
    global _firestore_client
    if _firestore_client is not None:
        return _firestore_client

    log = logging.getLogger("uvicorn.error")
    b64 = os.getenv("FIRESTORE_SA_B64", "")
    project_id = os.getenv("FIRESTORE_PROJECT_ID")

    if not b64:
        log.warning("FIRESTORE_SA_B64 is not set; attempting ADC for Firestore")
        _firestore_client = firestore.Client(project=project_id) if project_id else firestore.Client()
        return _firestore_client

    try:
        info = json.loads(base64.b64decode(b64).decode("utf-8"))
        creds = service_account.Credentials.from_service_account_info(info)
        if not project_id:
            project_id = info.get("project_id")
        if not project_id:
            raise RuntimeError("No FIRESTORE_PROJECT_ID and no project_id in SA JSON.")
        _firestore_client = firestore.Client(project=project_id, credentials=creds)
        log.info("Firestore client initialized for project %s", project_id)
        return _firestore_client
    except Exception as e:
        log.exception("Failed to initialize Firestore client: %s", e)
        raise


def write_customer_subscription_snapshot(
    customer_id: str,
    email: Optional[str],
    subscription_id: Optional[str],
    status: Optional[str],
    raw: Dict[str, Any],
) -> None:
    """
    Upsert a customer subscription snapshot into:
      subscriptions/{customer_id}
        - email
        - lastSubscriptionId
        - lastStatus
        - updatedAt (server timestamp)
      subscriptions/{customer_id}/events/{stripe_event_id}
        - raw event/object for auditing
    """
    log = logging.getLogger("uvicorn.error")
    db = get_firestore_client()

    # document paths
    cust_ref = db.collection("subscriptions").document(customer_id)

    # We’ll store the 'raw' under events with the Stripe event id if present
    event_id = raw.get("id") or raw.get("latest_invoice") or "no_event_id"
    evt_ref = cust_ref.collection("events").document(str(event_id))

    try:
        db.batch()\
          .set(cust_ref, {
              "email": email,
              "lastSubscriptionId": subscription_id,
              "lastStatus": status,
              "updatedAt": firestore.SERVER_TIMESTAMP,
          }, merge=True)\
          .set(evt_ref, {"raw": raw, "createdAt": firestore.SERVER_TIMESTAMP}, merge=True)\
          .commit()

        log.info("🟩 Firestore write OK for customer %s (sub=%s, status=%s)", customer_id, subscription_id, status)
    except gcloud_exceptions.GoogleAPIError as ge:
        log.exception("🟥 Firestore API error: %s", ge)
    except Exception as e:
        log.exception("🟥 Firestore write unexpected error: %s", e)


# -----------------------------
# App factory
# -----------------------------
def create_app() -> FastAPI:
    setup_logging()
    settings = get_settings()

    app = FastAPI(title=settings.app_name)
    log = logging.getLogger("uvicorn.error")

    # --- CORS ---
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
    # Stripe Webhook — with Firestore integration
    # -------------------------------------------------------------------------
    stripe.api_key = os.getenv("STRIPE_API_KEY", "")
    WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    seen_events: set[str] = set()  # simple in-memory idempotency

    async def handle_checkout_completed(data: Dict[str, Any], full_event: Dict[str, Any]) -> None:
        email = (data.get("customer_details") or {}).get("email")
        customer_id = data.get("customer")
        subscription_id = data.get("subscription")
        status = (data.get("status") or "").lower()  # often "complete"
        log.info("✅ Checkout completed: email=%s, customer=%s, sub=%s", email, customer_id, subscription_id)

        if customer_id:
            write_customer_subscription_snapshot(
                customer_id=customer_id,
                email=email,
                subscription_id=subscription_id,
                status=status,
                raw=full_event,
            )

    async def handle_subscription_updated(data: Dict[str, Any], full_event: Dict[str, Any]) -> None:
        # subscription object shape
        customer_id = data.get("customer")
        subscription_id = data.get("id")
        status = data.get("status")
        log.info("🔄 Subscription update: customer=%s, sub=%s, status=%s", customer_id, subscription_id, status)

        # Try to grab email if present via default_payment_method.billing_details.email
        email = None
        if isinstance(data.get("default_payment_method"), dict):
            pm = data["default_payment_method"]
            email = (pm.get("billing_details") or {}).get("email")

        if customer_id:
            write_customer_subscription_snapshot(
                customer_id=customer_id,
                email=email,
                subscription_id=subscription_id,
                status=status,
                raw=full_event,
            )

    def route_event(event_type: str):
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
            log.info("🔁 Duplicate Stripe event ignored: %s", event_id)
            return {"received": True, "duplicate": True}
        seen_events.add(event_id)

        log.info("🎯 Stripe event received: %s", event_type)
        handler = route_event(event_type)
        if handler:
            background.add_task(handler, data, event)
        else:
            log.info("No handler for event type %s", event_type)

        return {"received": True}

    # Health
    @app.get("/health")
    def health():
        return {"status": "ok"}

    # Route log on startup (nice for sanity)
    @app.on_event("startup")
    async def log_routes():
        for route in app.router.routes:
            methods = getattr(route, "methods", [])
            path = getattr(route, "path", "")
            log.info("ROUTE %s %s", ",".join(sorted(methods)), path)

    return app


app = create_app()
