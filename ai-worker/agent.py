"""LangChain/LangGraph AIOps agent: given a Kubernetes Warning event, gather evidence via
read-only tools + RAG, then produce a structured RemediationReport.

Two-stage design:
  1. A ReAct tool-calling loop (langgraph's prebuilt agent) investigates freely: it can call
     search_playbooks / describe_pod / get_pod_logs / list_recent_warning_events in any order,
     as many times as it wants, and reasons in free text.
  2. A separate, tools-free "structurer" call converts that free-form investigation into the
     strict RemediationReport schema.
Local models are considerably less reliable at emitting strict structured output in the same
turn as a tool-calling loop than in a dedicated finalization call -- splitting the two keeps
each call doing one job.
"""
from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from langgraph.prebuilt import create_react_agent

from config import settings
from k8s_tools import ALL_TOOLS
from models import K8sEvent, RemediationReport
from rag import search_playbooks

SYSTEM_PROMPT = """You are an expert AIOps Controller for a Kubernetes cluster.

You have received a Kubernetes Warning Event. Use your tools to inspect the namespace,
diagnose the root cause, and work out the exact remediation steps or corrected YAML manifest.

Rules:
- Always call search_playbooks at least once to check for a known runbook pattern.
- Prefer describe_pod before get_pod_logs -- the container state/reason tells you WHAT failed;
  logs tell you WHY, and are often empty or irrelevant for scheduling/pull failures.
- If a tool reports a pod as NOT FOUND, treat that as informative (the object no longer exists,
  e.g. it was deleted after the event fired) rather than retrying the same call.
- You may NOT apply changes to the cluster. Your job ends at producing a diagnosis and a
  proposed fix for a human (or a future GitOps pipeline) to apply.
- Be concrete: cite the exact evidence (log lines, event reasons, container states) that led to
  your conclusion.
"""

_chat_model = ChatOllama(model=settings.ollama_chat_model, base_url=settings.ollama_base_url, temperature=0)

_agent = create_react_agent(
    model=_chat_model,
    tools=[*ALL_TOOLS, search_playbooks],
    prompt=SYSTEM_PROMPT,
)

_structurer = ChatOllama(
    model=settings.ollama_chat_model, base_url=settings.ollama_base_url, temperature=0
).with_structured_output(RemediationReport)


def analyze_event(event: K8sEvent) -> tuple[RemediationReport, list[str]]:
    user_prompt = (
        "A Kubernetes Warning event was received:\n\n"
        f"{event.model_dump_json(indent=2)}\n\n"
        "Investigate and diagnose the root cause, then propose a remediation."
    )

    result = _agent.invoke({"messages": [HumanMessage(content=user_prompt)]})
    investigation_transcript = "\n\n".join(
        f"[{m.type}] {m.content}" for m in result["messages"] if getattr(m, "content", None)
    )
    # Audit trail computed directly from the message log (not LLM-reported, so it's trustworthy
    # regardless of how well the model narrates its own actions) -- which tools actually fired,
    # in order. Phase 4 will want this alongside the report to show a fix wasn't hallucinated
    # from the event text alone.
    tools_used = [
        tc["name"]
        for m in result["messages"]
        for tc in (getattr(m, "tool_calls", None) or [])
    ]

    structuring_prompt = (
        "Below is an AIOps agent's full investigation of a Kubernetes Warning event (tool "
        "calls, tool outputs, and its final free-form conclusion). Convert it into the "
        "required structured report. If the investigation was inconclusive, say so honestly "
        "in root_cause, set confidence to 'low' and requires_human_review to true -- do not "
        "invent a root cause the evidence doesn't support.\n\n"
        f"{investigation_transcript}"
    )

    report = _structurer.invoke([SystemMessage(content=structuring_prompt)])
    return report, tools_used
