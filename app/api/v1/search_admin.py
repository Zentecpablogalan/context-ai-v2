from fastapi import APIRouter
from azure.search.documents.indexes.models import (
    SearchIndex, SimpleField, SearchFieldDataType, SearchableField
)
from app.core.search import get_index_client, INDEX_NAME

router = APIRouter()

@router.post("/search/admin/bootstrap", tags=["search-admin"])
def search_bootstrap():
    client = get_index_client()

    # If exists, return early
    try:
        existing = client.get_index(INDEX_NAME)
        return {"ok": True, "message": "Index already exists", "index": existing.name}
    except Exception:
        pass

    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SearchableField(name="content", type=SearchFieldDataType.String),
        SimpleField(name="source", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="url", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="created_at", type=SearchFieldDataType.DateTimeOffset, filterable=True, sortable=True),
    ]

    index = SearchIndex(name=INDEX_NAME, fields=fields)
    client.create_index(index)
    return {"ok": True, "created": INDEX_NAME}
