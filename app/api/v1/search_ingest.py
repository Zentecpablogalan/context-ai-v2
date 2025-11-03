from fastapi import APIRouter, Depends
from datetime import datetime, timezone
from app.core.search import get_search_client, INDEX_NAME
from app.api.v1.deps import require_user

router = APIRouter()

@router.post("/search/admin/add-doc", tags=["search-admin"])
def add_doc(
    id: str,
    content: str,
    source: str = "manual",
    url: str = "",
    user = Depends(require_user),
):
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
