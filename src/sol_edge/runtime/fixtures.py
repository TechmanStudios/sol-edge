"""Deterministic, pre-execution event streams for all five policy outcomes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sol_edge.fixtures import foundation_fixtures
from sol_edge.runtime.events import (
    EventType,
    EvidenceRecordedPayload,
    PolicyDecisionRecordedPayload,
    ProposalRecordedPayload,
    RunOpenedPayload,
    RuntimeEvent,
    create_runtime_event,
)

RUNTIME_FIXTURE_TIME = datetime(2030, 1, 2, 13, 0, tzinfo=UTC)
RUNTIME_FIXTURE_NAMES = (
    "eligible",
    "requires_human_approval",
    "deferred",
    "quarantined",
    "rejected",
)


def runtime_event_stream(fixture_name: str) -> tuple[RuntimeEvent, ...]:
    foundations = foundation_fixtures()
    if fixture_name not in foundations:
        allowed = ", ".join(RUNTIME_FIXTURE_NAMES)
        raise ValueError(f"unknown runtime fixture {fixture_name!r}; choose one of: {allowed}")
    fixture = foundations[fixture_name]
    suffix = fixture_name.replace("_", "-")
    run_id = f"run:{suffix}"

    opened = create_runtime_event(
        event_id=f"event:{suffix}:opened",
        run_id=run_id,
        sequence_number=1,
        event_type=EventType.RUN_OPENED,
        occurred_at=RUNTIME_FIXTURE_TIME,
        payload=RunOpenedPayload(
            experiment_plan_digest=fixture.plan.semantic_digest(),
            capability_manifest_digest=fixture.manifest.semantic_digest(),
        ),
        previous_event_digest=None,
    )
    proposed = create_runtime_event(
        event_id=f"event:{suffix}:proposal",
        run_id=run_id,
        sequence_number=2,
        event_type=EventType.PROPOSAL_RECORDED,
        occurred_at=RUNTIME_FIXTURE_TIME + timedelta(seconds=1),
        payload=ProposalRecordedPayload(
            proposal_digest=fixture.proposal.semantic_digest(),
            experiment_plan_digest=fixture.plan.semantic_digest(),
            capability_manifest_digest=fixture.manifest.semantic_digest(),
        ),
        previous_event_digest=opened.event_digest,
    )
    evidenced = create_runtime_event(
        event_id=f"event:{suffix}:evidence",
        run_id=run_id,
        sequence_number=3,
        event_type=EventType.EVIDENCE_RECORDED,
        occurred_at=RUNTIME_FIXTURE_TIME + timedelta(seconds=2),
        payload=EvidenceRecordedPayload(
            evidence_digest=fixture.evidence.semantic_digest(),
            proposal_digest=fixture.proposal.semantic_digest(),
            experiment_plan_digest=fixture.plan.semantic_digest(),
            capability_manifest_digest=fixture.manifest.semantic_digest(),
        ),
        previous_event_digest=proposed.event_digest,
    )
    decided = create_runtime_event(
        event_id=f"event:{suffix}:decision",
        run_id=run_id,
        sequence_number=4,
        event_type=EventType.POLICY_DECISION_RECORDED,
        occurred_at=RUNTIME_FIXTURE_TIME + timedelta(seconds=3),
        payload=PolicyDecisionRecordedPayload(
            policy_decision_digest=fixture.decision.decision_digest,
            policy_status=fixture.decision.status,
            proposal_digest=fixture.proposal.semantic_digest(),
            evidence_digest=fixture.evidence.semantic_digest(),
        ),
        previous_event_digest=evidenced.event_digest,
    )
    return opened, proposed, evidenced, decided


def runtime_event_streams() -> dict[str, tuple[RuntimeEvent, ...]]:
    return {name: runtime_event_stream(name) for name in RUNTIME_FIXTURE_NAMES}
