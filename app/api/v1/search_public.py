from fastapi import APIRouter, HTTPException, Query
from typing import Any
from app.core.search import get_search_client, INDEX_NAME

router = APIRouter()

@router.get("/search", tags=["search"])
def search(q: str = Query(..., min_length=1), top: int = 10) -> dict[str, Any]:
    client = get_search_client(INDEX_NAME)
    try:
        results = client.search(search_text=q, top=top, include_total_count=True)
        items = []
        for r in results:
            doc = r.copy()  # MutableMapping
            items.append({
                "id": doc.get("id"),
                "content": doc.get("content"),
                "source": doc.get("source"),
                "url": doc.get("url"),
                "created_at": doc.get("created_at"),
                "score": getattr(r, "score", None),
            })
        return {"count": results.get_count(), "items": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search error: {e}")
