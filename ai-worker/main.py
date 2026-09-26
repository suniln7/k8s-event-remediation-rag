"""Phase 3 entrypoint: consume Warning events from Kafka, run each through the AIOps agent, and
write a structured remediation report for a human (or, later, Phase 4's GitOps flow) to act on.

Does NOT apply anything to the cluster -- see agent.py's system prompt and k8s_tools.py's module
docstring for why.
"""
from __future__ import annotations

import json
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

from confluent_kafka import Consumer, KafkaError

from agent import analyze_event
from config import settings
from models import K8sEvent

# dedup key -> the exporter re-sends the same underlying failure repeatedly with an
# incrementing `count`; one agent run per real failure, not per Kafka message.
_seen: set[str] = set()


def _make_consumer() -> Consumer:
    return Consumer(
        {
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            "group.id": settings.kafka_group_id,
            # "latest": we care about *new* failures from here on, not the stale Phase-2 test
            # events already sitting in the topic (whose pods are long deleted).
            "auto.offset.reset": "latest",
            "enable.auto.commit": True,
        }
    )


def _write_report(
    event: K8sEvent, report: "RemediationReport", tools_used: list[str]  # noqa: F821 (see import)
) -> Path:
    out_dir = Path(settings.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_name = f"{event.involvedObject.namespace}_{event.involvedObject.name}_{event.reason}_{ts}.json"
    out_path = out_dir / safe_name
    payload = {"event": event.model_dump(), "report": report.model_dump(), "tools_used": tools_used}
    out_path.write_text(json.dumps(payload, indent=2))
    return out_path


def _handle_message(raw_value: bytes) -> None:
    try:
        data = json.loads(raw_value)
        event = K8sEvent.model_validate(data)
    except Exception as exc:
        print(f"[WARN] Skipping unparseable message: {exc}", file=sys.stderr)
        return

    if event.dedup_key in _seen:
        print(f"[SKIP] Already processed {event.dedup_key} ({event.reason} on {event.involvedObject.name})")
        return
    _seen.add(event.dedup_key)

    print(f"[EVENT] {event.summary()}")
    try:
        report, tools_used = analyze_event(event)
    except Exception as exc:
        print(f"[ERROR] Agent failed on {event.dedup_key}: {exc}", file=sys.stderr)
        return

    out_path = _write_report(event, report, tools_used)
    print(
        f"[REPORT] root_cause={report.root_cause!r} confidence={report.confidence} "
        f"tools_used={tools_used} -> {out_path}"
    )


def main() -> None:
    consumer = _make_consumer()
    consumer.subscribe([settings.kafka_topic])
    print(
        f"Listening on topic '{settings.kafka_topic}' at {settings.kafka_bootstrap_servers} "
        f"(group={settings.kafka_group_id}, offset=latest)..."
    )

    running = True

    def _stop(*_args):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    try:
        while running:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                print(f"[ERROR] Kafka error: {msg.error()}", file=sys.stderr)
                continue
            _handle_message(msg.value())
    finally:
        consumer.close()
        print("Consumer closed.")


if __name__ == "__main__":
    main()
