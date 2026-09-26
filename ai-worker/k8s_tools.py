"""Read-only Kubernetes diagnostic tools for the AIOps agent.

Deliberately NO mutating tool (no apply_yaml / patch / delete) in Phase 3: project.md's Phase 4
explicitly says the agent must not run `kubectl apply` directly -- fixes get committed to git
and synced by Argo CD instead. Keeping the toolset read-only now means there's no safety
boundary to retrofit later; Phase 4 adds a separate, explicit "propose a commit" step.
"""
from __future__ import annotations

import json

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from langchain_core.tools import tool

from config import settings

try:
    config.load_kube_config(context=settings.k8s_context)
except Exception as exc:  # fail loudly at import time, not silently per-call
    raise RuntimeError(
        f"Could not load kubeconfig context '{settings.k8s_context}'. "
        f"Is the kind cluster running and is this the right context name? ({exc})"
    ) from exc

_core_v1 = client.CoreV1Api()

# The official kubernetes client's urllib3 transport has no read timeout unless passed
# explicitly per-call. Without one, a dropped connection (e.g. this sandbox's kubeconfig points
# at an SSH-tunneled API server; the tunnel hiccupped mid-request during testing) hangs the
# call forever -- and since main.py's consumer loop is single-threaded, one hung tool call
# freezes the entire worker, not just the event being processed. (connect_timeout, read_timeout)
_REQUEST_TIMEOUT = (5, 15)


def _api_error_message(exc: ApiException) -> str:
    """Kubernetes API errors carry the useful message in the JSON body, not exc.reason
    (which is just the HTTP reason phrase, e.g. "Bad Request")."""
    try:
        return json.loads(exc.body).get("message", exc.reason)
    except Exception:
        return exc.reason or str(exc)


@tool
def get_pod_logs(
    namespace: str,
    pod_name: str,
    container: str = "",
    tail_lines: int = 200,
    previous: bool = False,
) -> str:
    """Fetch the tail of a pod's container logs. Set previous=True to get the last
    terminated container's logs -- use this for CrashLoopBackOff, since the current container
    is usually mid-restart with no logs yet, but the previous instance crashed with the real
    error. Returns a clear 'NOT FOUND' string instead of raising if the pod is gone."""
    try:
        return _core_v1.read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            container=container or None,
            tail_lines=tail_lines,
            previous=previous,
            _request_timeout=_REQUEST_TIMEOUT,
        )
    except ApiException as exc:
        if exc.status == 404:
            return f"NOT FOUND: pod {namespace}/{pod_name} does not exist (likely already deleted)."
        return f"ERROR fetching logs for {namespace}/{pod_name}: HTTP {exc.status} {_api_error_message(exc)}"
    except Exception as exc:  # connection drop / timeout -- keep the agent loop alive
        return f"ERROR fetching logs for {namespace}/{pod_name}: {type(exc).__name__}: {exc}"


@tool
def describe_pod(namespace: str, pod_name: str) -> str:
    """Get a kubectl-describe-style summary of a pod: phase, conditions, container
    statuses (state/reason/restart count/image), resource requests+limits, and the most
    recent Kubernetes events involving this pod. Call this before reading logs -- it tells you
    *what* failed (e.g. ImagePullBackOff, OOMKilled, Pending/unschedulable) so you know whether
    logs are even relevant."""
    try:
        pod = _core_v1.read_namespaced_pod(name=pod_name, namespace=namespace, _request_timeout=_REQUEST_TIMEOUT)
    except ApiException as exc:
        if exc.status == 404:
            return f"NOT FOUND: pod {namespace}/{pod_name} does not exist (likely already deleted)."
        return f"ERROR describing {namespace}/{pod_name}: HTTP {exc.status} {_api_error_message(exc)}"
    except Exception as exc:  # connection drop / timeout -- keep the agent loop alive
        return f"ERROR describing {namespace}/{pod_name}: {type(exc).__name__}: {exc}"

    lines = [
        f"Pod: {namespace}/{pod_name}",
        f"Phase: {pod.status.phase}",
        f"Node: {pod.spec.node_name}",
    ]

    for cond in pod.status.conditions or []:
        lines.append(f"Condition: {cond.type}={cond.status} reason={cond.reason} message={cond.message}")

    for cs in pod.status.container_statuses or []:
        state = cs.state
        if state.waiting:
            state_str = f"Waiting(reason={state.waiting.reason}, message={state.waiting.message})"
        elif state.running:
            state_str = f"Running(since={state.running.started_at})"
        elif state.terminated:
            state_str = (
                f"Terminated(reason={state.terminated.reason}, "
                f"exit_code={state.terminated.exit_code}, message={state.terminated.message})"
            )
        else:
            state_str = "Unknown"
        lines.append(
            f"Container: {cs.name} image={cs.image} ready={cs.ready} "
            f"restartCount={cs.restart_count} state={state_str}"
        )

    for c in pod.spec.containers or []:
        req = (c.resources.requests or {}) if c.resources else {}
        lim = (c.resources.limits or {}) if c.resources else {}
        lines.append(f"Resources[{c.name}]: requests={req} limits={lim}")

    try:
        events = _core_v1.list_namespaced_event(
            namespace=namespace,
            field_selector=f"involvedObject.name={pod_name}",
            _request_timeout=_REQUEST_TIMEOUT,
        )
        for ev in sorted(events.items, key=lambda e: e.last_timestamp or e.event_time or ""):
            lines.append(f"Event: type={ev.type} reason={ev.reason} count={ev.count} message={ev.message}")
    except ApiException as exc:
        lines.append(f"(could not list events: HTTP {exc.status} {_api_error_message(exc)})")
    except Exception as exc:  # connection drop / timeout -- keep the agent loop alive
        lines.append(f"(could not list events: {type(exc).__name__}: {exc})")

    return "\n".join(lines)


@tool
def list_recent_warning_events(namespace: str, limit: int = 10) -> str:
    """List the most recent Warning-type events in a namespace, newest first. Use this to
    check whether the failing pod's problem is isolated or part of a wider issue in the
    namespace (e.g. a bad ConfigMap affecting multiple pods, or a node-level problem)."""
    try:
        events = _core_v1.list_namespaced_event(
            namespace=namespace, field_selector="type=Warning", _request_timeout=_REQUEST_TIMEOUT
        )
    except ApiException as exc:
        return f"ERROR listing events in {namespace}: HTTP {exc.status} {_api_error_message(exc)}"
    except Exception as exc:  # connection drop / timeout -- keep the agent loop alive
        return f"ERROR listing events in {namespace}: {type(exc).__name__}: {exc}"

    items = sorted(events.items, key=lambda e: e.last_timestamp or e.event_time or "", reverse=True)[:limit]

    if not items:
        return f"No Warning events found in namespace {namespace}."

    return "\n".join(
        f"[{ev.last_timestamp}] reason={ev.reason} object={ev.involved_object.kind}/{ev.involved_object.name} "
        f"count={ev.count} message={ev.message}"
        for ev in items
    )


ALL_TOOLS = [get_pod_logs, describe_pod, list_recent_warning_events]
