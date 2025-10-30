from fastapi import FastAPI
import os

app = FastAPI(title="Context Search AI V2 – Probe")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/env")
def env():
    # Read env vars (should be resolved from Key Vault references)
    vals = {
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
        "STRIPE_SECRET_KEY": os.getenv("STRIPE_SECRET_KEY"),
        "GOOGLE_CLIENT_ID": os.getenv("GOOGLE_CLIENT_ID"),
        "GOOGLE_CLIENT_SECRET": os.getenv("GOOGLE_CLIENT_SECRET"),
    }

    # Return presence/length only (don’t echo secrets)
    masked = {
        k: (None if v is None else f"present(len={len(v)})")
        for k, v in vals.items()
    }
    return {"env": masked}
