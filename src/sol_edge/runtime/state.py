"""Immutable derived state for a single SOL-Edge experiment attempt."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from sol_edge.canonical import digest_data
from sol_edge.contracts import Digest, Identifier, StrictModel


class RuntimeStatus(StrEnum):
    NEW = "NEW"
    OPEN = "OPEN"
    PROPOSED = "PROPOSED"
    EVIDENCED = "EVIDENCED"
    ELIGIBLE = "ELIGIBLE"
    AWAITING_HUMAN_APPROVAL = "AWAITING_HUMAN_APPROVAL"
    DEFERRED = "DEFERRED"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"


TERMINAL_STATUSES = frozenset(
    {
        RuntimeStatus.ELIGIBLE,
        RuntimeStatus.AWAITING_HUMAN_APPROVAL,
        RuntimeStatus.DEFERRED,
        RuntimeStatus.QUARANTINED,
        RuntimeStatus.REJECTED,
    }
)


class RuntimeState(StrictModel):
    schema_name: Literal["runtime_state"] = "runtime_state"
    schema_version: Literal["0.2.0"] = "0.2.0"
    run_id: Identifier | None
    status: RuntimeStatus
    experiment_plan_digest: Digest | None
    capability_manifest_digest: Digest | None
    proposal_digest: Digest | None
    evidence_digest: Digest | None
    policy_decision_digest: Digest | None
    last_accepted_sequence_number: int = Field(ge=0)
    last_accepted_event_digest: Digest | None
    accepted_event_ids: tuple[Identifier, ...]
    state_digest: Digest

    def semantic_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="python", exclude={"state_digest"})

    def semantic_digest(self) -> str:
        return digest_data(self.semantic_payload())

    @model_validator(mode="after")
    def state_consistency(self) -> RuntimeState:
        if self.last_accepted_sequence_number != len(self.accepted_event_ids):
            raise ValueError("accepted event count must equal the last accepted sequence number")
        if len(self.accepted_event_ids) != len(set(self.accepted_event_ids)):
            raise ValueError("accepted event identifiers must be unique")

        if self.status is RuntimeStatus.NEW:
            if (
                any(
                    value is not None
                    for value in (
                        self.run_id,
                        self.experiment_plan_digest,
                        self.capability_manifest_digest,
                        self.proposal_digest,
                        self.evidence_digest,
                        self.policy_decision_digest,
                        self.last_accepted_event_digest,
                    )
                )
                or self.last_accepted_sequence_number != 0
            ):
                raise ValueError("NEW state cannot contain accepted runtime facts")
        else:
            if (
                self.run_id is None
                or self.experiment_plan_digest is None
                or self.capability_manifest_digest is None
                or self.last_accepted_event_digest is None
            ):
                raise ValueError("non-NEW state requires run, plan, manifest, and event identity")

        if self.status is RuntimeStatus.OPEN:
            if any(
                value is not None
                for value in (
                    self.proposal_digest,
                    self.evidence_digest,
                    self.policy_decision_digest,
                )
            ):
                raise ValueError(
                    "OPEN state cannot contain proposal, evidence, or decision identity"
                )
        elif self.status is RuntimeStatus.PROPOSED:
            if self.proposal_digest is None or any(
                value is not None for value in (self.evidence_digest, self.policy_decision_digest)
            ):
                raise ValueError("PROPOSED state requires only proposal identity")
        elif self.status is RuntimeStatus.EVIDENCED:
            if (
                self.proposal_digest is None
                or self.evidence_digest is None
                or self.policy_decision_digest is not None
            ):
                raise ValueError("EVIDENCED state requires proposal and evidence identity")
        elif self.status in TERMINAL_STATUSES and (
            self.proposal_digest is None
            or self.evidence_digest is None
            or self.policy_decision_digest is None
        ):
            raise ValueError("terminal state requires proposal, evidence, and decision identity")

        if self.state_digest != self.semantic_digest():
            raise ValueError("state_digest does not match semantic runtime state")
        return self


def build_runtime_state(
    *,
    run_id: str | None,
    status: RuntimeStatus,
    experiment_plan_digest: str | None,
    capability_manifest_digest: str | None,
    proposal_digest: str | None,
    evidence_digest: str | None,
    policy_decision_digest: str | None,
    last_accepted_sequence_number: int,
    last_accepted_event_digest: str | None,
    accepted_event_ids: tuple[str, ...],
) -> RuntimeState:
    data: dict[str, object] = {
        "schema_name": "runtime_state",
        "schema_version": "0.2.0",
        "run_id": run_id,
        "status": status,
        "experiment_plan_digest": experiment_plan_digest,
        "capability_manifest_digest": capability_manifest_digest,
        "proposal_digest": proposal_digest,
        "evidence_digest": evidence_digest,
        "policy_decision_digest": policy_decision_digest,
        "last_accepted_sequence_number": last_accepted_sequence_number,
        "last_accepted_event_digest": last_accepted_event_digest,
        "accepted_event_ids": accepted_event_ids,
    }
    data["state_digest"] = digest_data(data)
    return RuntimeState.model_validate(data)


def new_runtime_state() -> RuntimeState:
    """Return the one deterministic initial state used by replay."""
    return build_runtime_state(
        run_id=None,
        status=RuntimeStatus.NEW,
        experiment_plan_digest=None,
        capability_manifest_digest=None,
        proposal_digest=None,
        evidence_digest=None,
        policy_decision_digest=None,
        last_accepted_sequence_number=0,
        last_accepted_event_digest=None,
        accepted_event_ids=(),
    )
