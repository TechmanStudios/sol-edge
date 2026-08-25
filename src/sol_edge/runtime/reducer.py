"""Pure, default-deny runtime transition reducer."""

from __future__ import annotations

from enum import StrEnum
from typing import NoReturn

from pydantic import Field, ValidationError

from sol_edge.contracts import Identifier, PolicyStatus, StrictModel
from sol_edge.runtime.events import (
    EventType,
    EvidenceRecordedPayload,
    PolicyDecisionRecordedPayload,
    ProposalRecordedPayload,
    RunOpenedPayload,
    RuntimeEvent,
)
from sol_edge.runtime.state import (
    TERMINAL_STATUSES,
    RuntimeState,
    RuntimeStatus,
    build_runtime_state,
)


class RuntimeErrorCode(StrEnum):
    EMPTY_STREAM = "EMPTY_STREAM"
    INVALID_STATE = "INVALID_STATE"
    INVALID_EVENT = "INVALID_EVENT"
    EVENT_DIGEST_MISMATCH = "EVENT_DIGEST_MISMATCH"
    SEQUENCE_MISMATCH = "SEQUENCE_MISMATCH"
    PREVIOUS_DIGEST_MISMATCH = "PREVIOUS_DIGEST_MISMATCH"
    DUPLICATE_EVENT_ID = "DUPLICATE_EVENT_ID"
    RUN_MISMATCH = "RUN_MISMATCH"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    TERMINAL_STATE = "TERMINAL_STATE"
    PLAN_MISMATCH = "PLAN_MISMATCH"
    MANIFEST_MISMATCH = "MANIFEST_MISMATCH"
    PROPOSAL_MISMATCH = "PROPOSAL_MISMATCH"
    EVIDENCE_MISMATCH = "EVIDENCE_MISMATCH"


class RuntimeIssue(StrictModel):
    code: RuntimeErrorCode
    message: str = Field(min_length=1, max_length=512)
    event_id: Identifier | None = None
    sequence_number: int | None = Field(default=None, ge=1)


class RuntimeTransitionError(ValueError):
    """Structured rejection emitted by reducer and replay boundaries."""

    def __init__(self, issue: RuntimeIssue) -> None:
        self.issue = issue
        super().__init__(f"{issue.code.value}: {issue.message}")


def _reject(
    code: RuntimeErrorCode,
    message: str,
    event: RuntimeEvent | None = None,
) -> NoReturn:
    raise RuntimeTransitionError(
        RuntimeIssue(
            code=code,
            message=message,
            event_id=event.event_id if event is not None else None,
            sequence_number=event.sequence_number if event is not None else None,
        )
    )


def _validated_state(state: RuntimeState) -> RuntimeState:
    if not isinstance(state, RuntimeState):
        _reject(RuntimeErrorCode.INVALID_STATE, "reducer input is not a RuntimeState")
    try:
        return RuntimeState.model_validate(state.model_dump(mode="python"))
    except ValidationError as error:
        _reject(RuntimeErrorCode.INVALID_STATE, str(error))


def _validated_event(event: RuntimeEvent) -> RuntimeEvent:
    if not isinstance(event, RuntimeEvent):
        _reject(RuntimeErrorCode.INVALID_EVENT, "stream item is not a RuntimeEvent")
    try:
        return RuntimeEvent.model_validate(event.model_dump(mode="python"))
    except ValidationError as error:
        code = (
            RuntimeErrorCode.EVENT_DIGEST_MISMATCH
            if "event_digest does not match" in str(error)
            else RuntimeErrorCode.INVALID_EVENT
        )
        _reject(code, str(error), event)


POLICY_STATUS_MAP: dict[PolicyStatus, RuntimeStatus] = {
    PolicyStatus.ELIGIBLE: RuntimeStatus.ELIGIBLE,
    PolicyStatus.REQUIRE_HUMAN_APPROVAL: RuntimeStatus.AWAITING_HUMAN_APPROVAL,
    PolicyStatus.DEFER: RuntimeStatus.DEFERRED,
    PolicyStatus.QUARANTINE: RuntimeStatus.QUARANTINED,
    PolicyStatus.REJECT: RuntimeStatus.REJECTED,
}


def _next_state(
    previous: RuntimeState,
    event: RuntimeEvent,
    *,
    status: RuntimeStatus,
    experiment_plan_digest: str | None = None,
    capability_manifest_digest: str | None = None,
    proposal_digest: str | None = None,
    evidence_digest: str | None = None,
    policy_decision_digest: str | None = None,
) -> RuntimeState:
    return build_runtime_state(
        run_id=event.run_id,
        status=status,
        experiment_plan_digest=(
            experiment_plan_digest
            if experiment_plan_digest is not None
            else previous.experiment_plan_digest
        ),
        capability_manifest_digest=(
            capability_manifest_digest
            if capability_manifest_digest is not None
            else previous.capability_manifest_digest
        ),
        proposal_digest=(
            proposal_digest if proposal_digest is not None else previous.proposal_digest
        ),
        evidence_digest=(
            evidence_digest if evidence_digest is not None else previous.evidence_digest
        ),
        policy_decision_digest=(
            policy_decision_digest
            if policy_decision_digest is not None
            else previous.policy_decision_digest
        ),
        last_accepted_sequence_number=event.sequence_number,
        last_accepted_event_digest=event.event_digest,
        accepted_event_ids=(*previous.accepted_event_ids, event.event_id),
    )


def reduce_event(previous_state: RuntimeState, event: RuntimeEvent) -> RuntimeState:
    """Return the next state without I/O, mutation, time reads, or external calls."""
    previous = _validated_state(previous_state)
    accepted = _validated_event(event)

    if previous.status in TERMINAL_STATUSES:
        _reject(RuntimeErrorCode.TERMINAL_STATE, "terminal attempts cannot accept events", accepted)

    expected_sequence = previous.last_accepted_sequence_number + 1
    if accepted.sequence_number != expected_sequence:
        _reject(
            RuntimeErrorCode.SEQUENCE_MISMATCH,
            f"expected sequence {expected_sequence}, received {accepted.sequence_number}",
            accepted,
        )
    if accepted.event_id in previous.accepted_event_ids:
        _reject(
            RuntimeErrorCode.DUPLICATE_EVENT_ID, "event identifier was already accepted", accepted
        )
    if accepted.previous_event_digest != previous.last_accepted_event_digest:
        _reject(
            RuntimeErrorCode.PREVIOUS_DIGEST_MISMATCH,
            "previous event digest does not match the accepted chain head",
            accepted,
        )
    if previous.status is not RuntimeStatus.NEW and accepted.run_id != previous.run_id:
        _reject(RuntimeErrorCode.RUN_MISMATCH, "event belongs to a different run", accepted)

    if previous.status is RuntimeStatus.NEW:
        if accepted.event_type is not EventType.RUN_OPENED:
            _reject(RuntimeErrorCode.INVALID_TRANSITION, "NEW requires RUN_OPENED", accepted)
        payload = accepted.payload
        if not isinstance(payload, RunOpenedPayload):
            _reject(RuntimeErrorCode.INVALID_EVENT, "RUN_OPENED payload is invalid", accepted)
        return _next_state(
            previous,
            accepted,
            status=RuntimeStatus.OPEN,
            experiment_plan_digest=payload.experiment_plan_digest,
            capability_manifest_digest=payload.capability_manifest_digest,
        )

    if previous.status is RuntimeStatus.OPEN:
        if accepted.event_type is not EventType.PROPOSAL_RECORDED:
            _reject(
                RuntimeErrorCode.INVALID_TRANSITION, "OPEN requires PROPOSAL_RECORDED", accepted
            )
        payload = accepted.payload
        if not isinstance(payload, ProposalRecordedPayload):
            _reject(
                RuntimeErrorCode.INVALID_EVENT, "PROPOSAL_RECORDED payload is invalid", accepted
            )
        if payload.experiment_plan_digest != previous.experiment_plan_digest:
            _reject(
                RuntimeErrorCode.PLAN_MISMATCH, "proposal plan digest does not match run", accepted
            )
        if payload.capability_manifest_digest != previous.capability_manifest_digest:
            _reject(
                RuntimeErrorCode.MANIFEST_MISMATCH,
                "proposal capability-manifest digest does not match run",
                accepted,
            )
        return _next_state(
            previous,
            accepted,
            status=RuntimeStatus.PROPOSED,
            proposal_digest=payload.proposal_digest,
        )

    if previous.status is RuntimeStatus.PROPOSED:
        if accepted.event_type is not EventType.EVIDENCE_RECORDED:
            _reject(
                RuntimeErrorCode.INVALID_TRANSITION, "PROPOSED requires EVIDENCE_RECORDED", accepted
            )
        payload = accepted.payload
        if not isinstance(payload, EvidenceRecordedPayload):
            _reject(
                RuntimeErrorCode.INVALID_EVENT, "EVIDENCE_RECORDED payload is invalid", accepted
            )
        if payload.experiment_plan_digest != previous.experiment_plan_digest:
            _reject(
                RuntimeErrorCode.PLAN_MISMATCH, "evidence plan digest does not match run", accepted
            )
        if payload.capability_manifest_digest != previous.capability_manifest_digest:
            _reject(
                RuntimeErrorCode.MANIFEST_MISMATCH,
                "evidence capability-manifest digest does not match run",
                accepted,
            )
        if payload.proposal_digest != previous.proposal_digest:
            _reject(
                RuntimeErrorCode.PROPOSAL_MISMATCH,
                "evidence proposal digest does not match",
                accepted,
            )
        return _next_state(
            previous,
            accepted,
            status=RuntimeStatus.EVIDENCED,
            evidence_digest=payload.evidence_digest,
        )

    if previous.status is RuntimeStatus.EVIDENCED:
        if accepted.event_type is not EventType.POLICY_DECISION_RECORDED:
            _reject(
                RuntimeErrorCode.INVALID_TRANSITION,
                "EVIDENCED requires POLICY_DECISION_RECORDED",
                accepted,
            )
        payload = accepted.payload
        if not isinstance(payload, PolicyDecisionRecordedPayload):
            _reject(
                RuntimeErrorCode.INVALID_EVENT,
                "POLICY_DECISION_RECORDED payload is invalid",
                accepted,
            )
        if payload.proposal_digest != previous.proposal_digest:
            _reject(
                RuntimeErrorCode.PROPOSAL_MISMATCH,
                "policy-decision proposal digest does not match",
                accepted,
            )
        if payload.evidence_digest != previous.evidence_digest:
            _reject(
                RuntimeErrorCode.EVIDENCE_MISMATCH,
                "policy-decision evidence digest does not match",
                accepted,
            )
        return _next_state(
            previous,
            accepted,
            status=POLICY_STATUS_MAP[payload.policy_status],
            policy_decision_digest=payload.policy_decision_digest,
        )

    _reject(
        RuntimeErrorCode.INVALID_TRANSITION, "runtime state has no allowed transition", accepted
    )
