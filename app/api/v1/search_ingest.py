from fastapi import APIRouter
from datetime import datetime, timezone
from app.core.search import get_search_client, INDEX_NAME

router = APIRouter()

@router.post("/search/admin/add-doc", tags=["search-admin"])
def add_doc(id: str, content: str, source: str = "manual", url: str = ""):
    client = get_search_client(INDEX_NAME)
    doc = {
        "id": id,
        "content": content,
        "source": source,
        "url": url,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    result = client.upload_documents(documents=[doc])
    return {"ok": True, "result": [r.succeeded for r in result]}
