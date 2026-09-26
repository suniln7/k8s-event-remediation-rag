"""Qdrant-backed RAG over the local playbook corpus (project.md Phase 3: "Pre-load your Vector
DB with your internal playbooks, architecture definitions, and Kubernetes documentation.")."""
from __future__ import annotations

from langchain_core.tools import tool
from langchain_ollama import OllamaEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from config import settings


def get_embeddings() -> OllamaEmbeddings:
    return OllamaEmbeddings(model=settings.ollama_embed_model, base_url=settings.ollama_base_url)


def get_qdrant_client() -> QdrantClient:
    return QdrantClient(url=settings.qdrant_url)


def ensure_collection(client: QdrantClient, vector_size: int) -> None:
    if not client.collection_exists(settings.qdrant_collection):
        client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )


def get_vectorstore() -> QdrantVectorStore:
    return QdrantVectorStore(
        client=get_qdrant_client(),
        collection_name=settings.qdrant_collection,
        embedding=get_embeddings(),
    )


@tool
def search_playbooks(query: str) -> str:
    """Search internal Kubernetes playbooks/runbooks for guidance relevant to a query (e.g. an
    event reason + message, like 'ImagePullBackOff nginx tag not found'). Returns the most
    relevant playbook excerpts. Always call this at least once before proposing a fix, to check
    whether there's a known pattern for this failure."""
    store = get_vectorstore()
    results = store.similarity_search(query, k=3)
    if not results:
        return "No relevant playbook entries found."
    return "\n\n---\n\n".join(f"[{r.metadata.get('source', 'unknown')}]\n{r.page_content}" for r in results)
