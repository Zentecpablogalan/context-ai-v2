from fastapi import Depends, HTTPException, Request

def require_user(request: Request):
    if not request.session.get("user"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return request.session["user"]
