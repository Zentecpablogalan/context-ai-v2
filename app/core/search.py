from typing import Optional
from azure.core.credentials import AzureKeyCredential
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents import SearchClient
from app.core.config import get_settings

INDEX_NAME = "docs-v1"

def get_index_client() -> SearchIndexClient:
    s = get_settings()
    if not s.azure_search_endpoint or not s.azure_search_key:
        raise RuntimeError("Azure Search not configured.")
    return SearchIndexClient(
        endpoint=s.azure_search_endpoint,
        credential=AzureKeyCredential(s.azure_search_key),
    )

def get_search_client(index_name: Optional[str] = None) -> SearchClient:
    s = get_settings()
    if not s.azure_search_endpoint or not s.azure_search_key:
        raise RuntimeError("Azure Search not configured.")
    return SearchClient(
        endpoint=s.azure_search_endpoint,
        index_name=index_name or INDEX_NAME,
        credential=AzureKeyCredential(s.azure_search_key),
    )
