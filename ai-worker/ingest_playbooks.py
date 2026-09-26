"""One-off / idempotent script: chunk the markdown playbooks and upsert their embeddings into
Qdrant. Re-run any time you add/edit a playbook; pass --reset to wipe and rebuild from scratch."""
from __future__ import annotations

import argparse
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import settings
from rag import ensure_collection, get_embeddings, get_qdrant_client, get_vectorstore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Delete and recreate the collection first")
    args = parser.parse_args()

    playbooks_dir = Path(settings.playbooks_dir)
    md_files = sorted(playbooks_dir.glob("*.md"))
    if not md_files:
        raise SystemExit(f"No .md files found in {playbooks_dir.resolve()}")

    # Plain read instead of langchain_community's TextLoader: that package is being sunset
    # upstream, and reading a handful of local markdown files doesn't need a document-loader
    # abstraction on top of open().read().
    docs = [
        Document(page_content=path.read_text(encoding="utf-8"), metadata={"source": path.name})
        for path in md_files
    ]

    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
    chunks = splitter.split_documents(docs)
    print(f"Loaded {len(md_files)} playbook(s) -> {len(chunks)} chunks")

    qclient = get_qdrant_client()
    if args.reset and qclient.collection_exists(settings.qdrant_collection):
        qclient.delete_collection(settings.qdrant_collection)
        print(f"Deleted existing collection '{settings.qdrant_collection}'")

    # Probe embedding dimensionality from the model itself rather than hardcoding it.
    probe_vector = get_embeddings().embed_query("dimension probe")
    ensure_collection(qclient, vector_size=len(probe_vector))

    store = get_vectorstore()
    store.add_documents(chunks)
    print(f"Upserted {len(chunks)} chunks into collection '{settings.qdrant_collection}'")


if __name__ == "__main__":
    main()
