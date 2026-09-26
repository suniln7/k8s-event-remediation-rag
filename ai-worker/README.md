# Phase 3 -- LangChain AI Worker

Consumes Warning events from Kafka (`k8s-cluster-alerts`), investigates each one with a
tool-calling LangGraph agent (RAG over local playbooks + read-only Kubernetes API tools), and
writes a structured `RemediationReport` to `output/`. Runs as a plain process on the host Mac --
not containerized, not deployed into the kind cluster.

## Why host-run, not in-cluster
Ollama (Phase 1) already runs natively on the Mac, not in Kubernetes. Qdrant is reachable at
`localhost:6333` via `cluster.yaml`'s kind `extraPortMappings`. Kafka has no such mapping, so
it's reached via a plain `kubectl port-forward`. Running the worker in-cluster would need a way
for a kind node container to reach back out to the Mac's Ollama process (`host.docker.internal`
-- not reliably available under Rancher Desktop's dockerd without extra, non-persistent
container config), for no real benefit at this phase. Revisit if/when this gets containerized.

## Phase boundary: no auto-apply
Per `project.md`'s Phase 4, the agent must **not** call `kubectl apply` directly -- fixes get
committed to git and synced by Argo CD instead. So `k8s_tools.py` only exposes read-only tools
(`get_pod_logs`, `describe_pod`, `list_recent_warning_events`); there is no `apply_yaml` tool.
The agent's output is a `RemediationReport` (see `models.py`) written to `output/*.json` for a
human (or, once Phase 4 exists, a git-commit step) to act on.

## One-time setup
```bash
cd ai-worker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Embedding model for RAG (pulls from Ollama's registry -- if this hangs on VPN, see the
# project's Phase 2 notes on the corporate proxy; disconnecting VPN was the working fix there)
ollama pull nomic-embed-text

# Kafka has no host port mapping. The "plain" listener's advertised address is an in-cluster-only
# DNS name (Strimzi redirects any client there after its first metadata fetch), so a plain
# bootstrap-service port-forward isn't enough. kafka-cluster.yaml adds a second "external" nodeport
# listener that advertises localhost:9094 instead -- one tunnel straight to the broker pod covers
# both the bootstrap connection and the post-metadata redirect (keep this running in its own
# terminal/background):
kubectl port-forward pod/my-cluster-mixed-pool-0 9094:9094 -n kafka

# Load the starter playbooks into Qdrant
python ingest_playbooks.py --reset
```

## Running
```bash
source .venv/bin/activate
python main.py
```
Consumes from `auto.offset.reset=latest` -- it only sees events produced *after* it starts, not
whatever's already sitting in the topic from earlier testing. Ctrl+C to stop.

Trigger a test event in another terminal:
```bash
kubectl run bad-image-test3 --image=nginx:this-tag-still-does-not-exist -n default
```

## Config
All settings live in `.env` (see `.env.example` for the full list) -- Kafka/Qdrant/Ollama
endpoints, model names, the kubeconfig context to use, and the output directory.

## Files
- `models.py` -- `K8sEvent` (parses the exact JSON shape confirmed on the topic in Phase 2) and
  `RemediationReport` (the agent's structured output schema).
- `k8s_tools.py` -- read-only LangChain tools backed by the `kubernetes` python client.
- `rag.py` / `ingest_playbooks.py` / `playbooks/*.md` -- Qdrant vector store + starter runbooks
  (ImagePull errors, CrashLoopBackOff, OOMKilled, FailedScheduling, probe failures).
- `agent.py` -- the two-stage LangGraph ReAct agent + structured-output finalizer.
- `main.py` -- Kafka consumer loop, dedup, report writer.
