"""Central configuration for the AI remediation worker, loaded from environment variables
(via .env in this directory). Nothing here holds secrets -- Kafka/Qdrant/Ollama are all
unauthenticated on localhost for this learning setup."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


class Settings:
    # Kafka
    kafka_bootstrap_servers: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    kafka_topic: str = os.getenv("KAFKA_TOPIC", "k8s-cluster-alerts")
    kafka_group_id: str = os.getenv("KAFKA_GROUP_ID", "ai-remediation-worker")

    # Qdrant
    qdrant_url: str = os.getenv("QDRANT_URL", "http://localhost:6333")
    qdrant_collection: str = os.getenv("QDRANT_COLLECTION", "k8s-playbooks")

    # Ollama
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_chat_model: str = os.getenv("OLLAMA_CHAT_MODEL", "Qwen2.5:32b-instruct-q4_K_M")
    ollama_embed_model: str = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

    # Kubernetes
    k8s_context: str = os.getenv("K8S_CONTEXT", "kind-qdrant-local-cluster")

    # Output / corpus paths
    output_dir: str = os.getenv("OUTPUT_DIR", "./output")
    playbooks_dir: str = os.getenv("PLAYBOOKS_DIR", "./playbooks")


settings = Settings()
