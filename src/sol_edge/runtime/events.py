"""Versioned, hash-chained event semantics for one experiment attempt."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, TypeAlias

from pydantic import Field, model_validator

from sol_edge.canonical import digest_data
from sol_edge.contracts import Digest, Identifier, PolicyStatus, StrictModel, UtcTimestamp

RUNTIME_SCHEMA_VERSION = "0.2.0"


class EventType(StrEnum):
    RUN_OPENED = "RUN_OPENED"
    PROPOSAL_RECORDED = "PROPOSAL_RECORDED"
    EVIDENCE_RECORDED = "EVIDENCE_RECORDED"
    POLICY_DECISION_RECORDED = "POLICY_DECISION_RECORDED"


class RunOpenedPayload(StrictModel):
    experiment_plan_digest: Digest
    capability_manifest_digest: Digest


class ProposalRecordedPayload(StrictModel):
    proposal_digest: Digest
    experiment_plan_digest: Digest
    capability_manifest_digest: Digest


class EvidenceRecordedPayload(StrictModel):
    evidence_digest: Digest
    proposal_digest: Digest
    experiment_plan_digest: Digest
    capability_manifest_digest: Digest


class PolicyDecisionRecordedPayload(StrictModel):
    policy_decision_digest: Digest
    policy_status: PolicyStatus
    proposal_digest: Digest
    evidence_digest: Digest


EventPayload: TypeAlias = (
    RunOpenedPayload
    | ProposalRecordedPayload
    | EvidenceRecordedPayload
    | PolicyDecisionRecordedPayload
)


def _payload_matches_type(event_type: EventType, payload: EventPayload) -> bool:
    return (
        (event_type is EventType.RUN_OPENED and isinstance(payload, RunOpenedPayload))
        or (
            event_type is EventType.PROPOSAL_RECORDED
            and isinstance(payload, ProposalRecordedPayload)
        )
        or (
            event_type is EventType.EVIDENCE_RECORDED
            and isinstance(payload, EvidenceRecordedPayload)
        )
        or (
            event_type is EventType.POLICY_DECISION_RECORDED
            and isinstance(payload, PolicyDecisionRecordedPayload)
        )
    )


class RuntimeEvent(StrictModel):
    schema_name: Literal["runtime_event"] = "runtime_event"
    schema_version: Literal["0.2.0"] = "0.2.0"
    event_id: Identifier
    run_id: Identifier
    sequence_number: int = Field(ge=1)
    event_type: EventType
    occurred_at: UtcTimestamp
    payload: EventPayload
    previous_event_digest: Digest | None
    event_digest: Digest

    def semantic_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="python", exclude={"event_digest"})

    def semantic_digest(self) -> str:
        return digest_data(self.semantic_payload())

    @model_validator(mode="after")
    def event_consistency(self) -> RuntimeEvent:
        if not _payload_matches_type(self.event_type, self.payload):
            raise ValueError("event_type does not match the typed payload")
        if self.sequence_number == 1 and self.previous_event_digest is not None:
            raise ValueError("the first event cannot declare a previous event digest")
        if self.sequence_number > 1 and self.previous_event_digest is None:
            raise ValueError("events after sequence one require a previous event digest")
        if self.event_digest != self.semantic_digest():
            raise ValueError("event_digest does not match semantic event content")
        return self


def create_runtime_event(
    *,
    event_id: str,
    run_id: str,
    sequence_number: int,
    event_type: EventType,
    occurred_at: object,
    payload: EventPayload,
    previous_event_digest: str | None,
) -> RuntimeEvent:
    """Construct and validate an event whose digest binds its complete semantic envelope."""
    data: dict[str, object] = {
        "schema_name": "runtime_event",
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "event_id": event_id,
        "run_id": run_id,
        "sequence_number": sequence_number,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "payload": payload,
        "previous_event_digest": previous_event_digest,
    }
    data["event_digest"] = digest_data(data)
    return RuntimeEvent.model_validate(data)
