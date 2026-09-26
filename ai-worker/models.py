"""Pydantic models for parsing kubernetes-event-exporter Kafka messages and shaping agent output."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class InvolvedObject(BaseModel):
    kind: str = ""
    namespace: str = ""
    name: str = ""
    uid: str = ""
    apiVersion: str = ""
    resourceVersion: str = ""
    fieldPath: str = ""
    deleted: bool = False


class EventSource(BaseModel):
    component: str = ""
    host: str = ""


class K8sEvent(BaseModel):
    """Matches the JSON shape produced by kubernetes-event-exporter's kube.EnhancedEvent --
    confirmed field-for-field against a live message consumed from k8s-cluster-alerts in Phase 2
    (see e.g. {"reason":"Failed","message":"Error: ErrImagePull","type":"Warning",
    "involvedObject":{"kind":"Pod","namespace":"default","name":"bad-image-test",...}})."""

    reason: str = ""
    message: str = ""
    type: str = ""
    count: int = 1
    firstTimestamp: Optional[str] = None
    lastTimestamp: Optional[str] = None
    reportingComponent: str = ""
    source: EventSource = Field(default_factory=EventSource)
    involvedObject: InvolvedObject = Field(default_factory=InvolvedObject)

    @property
    def dedup_key(self) -> str:
        """Same underlying object + same reason = same failure, even though
        kubernetes-event-exporter re-emits it repeatedly with an incrementing `count`."""
        return f"{self.involvedObject.uid}:{self.reason}"

    def summary(self) -> str:
        obj = self.involvedObject
        return (
            f"reason={self.reason} type={self.type} count={self.count} "
            f"object={obj.kind}/{obj.namespace}/{obj.name} message={self.message!r}"
        )


class RemediationReport(BaseModel):
    """Structured final output the agent must produce for every Warning event it processes."""

    root_cause: str = Field(description="Concise root cause diagnosis")
    evidence: str = Field(description="What logs/describe/events output led to this diagnosis")
    remediation_summary: str = Field(description="Plain-language explanation of the fix")
    remediation_yaml: Optional[str] = Field(
        default=None,
        description="Corrected YAML manifest, if applicable to this failure type. Null/omitted if not applicable.",
    )
    confidence: str = Field(description="One of: high, medium, low")
    requires_human_review: bool = Field(
        description="True if this should NOT be auto-applied without a human looking at it first"
    )
