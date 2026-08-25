from __future__ import annotations

import builtins
import socket
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from typing import NoReturn

import pytest
from pydantic import ValidationError

from sol_edge.canonical import canonical_bytes, digest_data
from sol_edge.fixtures import foundation_fixtures
from sol_edge.runtime.events import (
    EventType,
    EvidenceRecordedPayload,
    PolicyDecisionRecordedPayload,
    ProposalRecordedPayload,
    RuntimeEvent,
    create_runtime_event,
)
from sol_edge.runtime.fixtures import RUNTIME_FIXTURE_TIME, runtime_event_stream
from sol_edge.runtime.reducer import (
    RuntimeErrorCode,
    RuntimeTransitionError,
    reduce_event,
)
from sol_edge.runtime.replay import replay_events
from sol_edge.runtime.state import RuntimeStatus, new_runtime_state

WRONG_DIGEST = digest_data({"fixture": "intentionally-wrong"})


def _rehash_event(event: RuntimeEvent, **updates: object) -> RuntimeEvent:
    data = event.model_dump(mode="python", exclude={"event_digest"})
    data.update(updates)
    data["event_digest"] = digest_data(data)
    return RuntimeEvent.model_validate(data)


def _assert_replay_error(
    events: tuple[RuntimeEvent, ...], expected: RuntimeErrorCode
) -> RuntimeTransitionError:
    with pytest.raises(RuntimeTransitionError) as captured:
        replay_events(events)
    assert captured.value.issue.code is expected
    return captured.value


def test_each_fixture_reaches_its_exact_terminal_status() -> None:
    expected = {
        "eligible": RuntimeStatus.ELIGIBLE,
        "requires_human_approval": RuntimeStatus.AWAITING_HUMAN_APPROVAL,
        "deferred": RuntimeStatus.DEFERRED,
        "quarantined": RuntimeStatus.QUARANTINED,
        "rejected": RuntimeStatus.REJECTED,
    }
    for name, status in expected.items():
        state = replay_events(runtime_event_stream(name))
        assert state.status is status
        assert state.last_accepted_sequence_number == 4
        assert state.state_digest == state.semantic_digest()


def test_identical_streams_produce_byte_identical_states() -> None:
    first = replay_events(runtime_event_stream("eligible"))
    second = replay_events(runtime_event_stream("eligible"))
    assert canonical_bytes(first) == canonical_bytes(second)
    assert first.state_digest == second.state_digest


def test_state_digest_is_identical_across_separate_python_processes() -> None:
    script = (
        "from sol_edge.runtime.fixtures import runtime_event_stream; "
        "from sol_edge.runtime.replay import replay_events; "
        "print(replay_events(runtime_event_stream('eligible')).state_digest)"
    )
    outputs = [
        subprocess.check_output([sys.executable, "-c", script], text=True).strip() for _ in range(2)
    ]
    expected = replay_events(runtime_event_stream("eligible")).state_digest
    assert outputs == [expected, expected]


def test_altered_payload_invalidates_event_digest() -> None:
    events = runtime_event_stream("eligible")
    proposal = events[1]
    assert isinstance(proposal.payload, ProposalRecordedPayload)
    altered_payload = proposal.payload.model_copy(update={"proposal_digest": WRONG_DIGEST})
    tampered = proposal.model_copy(update={"payload": altered_payload})
    _assert_replay_error((events[0], tampered), RuntimeErrorCode.EVENT_DIGEST_MISMATCH)


def test_altered_order_is_rejected() -> None:
    events = runtime_event_stream("eligible")
    _assert_replay_error(
        (events[1], events[0], events[2], events[3]), RuntimeErrorCode.SEQUENCE_MISMATCH
    )


def test_event_removed_from_middle_is_rejected() -> None:
    events = runtime_event_stream("eligible")
    _assert_replay_error((events[0], events[2], events[3]), RuntimeErrorCode.SEQUENCE_MISMATCH)


def test_inserted_event_is_rejected() -> None:
    events = runtime_event_stream("eligible")
    _assert_replay_error(
        (events[0], events[1], events[1], events[2], events[3]),
        RuntimeErrorCode.SEQUENCE_MISMATCH,
    )


def test_incorrect_previous_digest_is_rejected() -> None:
    events = runtime_event_stream("eligible")
    changed = _rehash_event(events[1], previous_event_digest=WRONG_DIGEST)
    _assert_replay_error((events[0], changed), RuntimeErrorCode.PREVIOUS_DIGEST_MISMATCH)


def test_sequence_gap_is_rejected() -> None:
    events = runtime_event_stream("eligible")
    changed = _rehash_event(events[1], sequence_number=3)
    _assert_replay_error((events[0], changed), RuntimeErrorCode.SEQUENCE_MISMATCH)


def test_duplicate_event_id_is_rejected() -> None:
    events = runtime_event_stream("eligible")
    duplicate_id = _rehash_event(events[2], event_id=events[0].event_id)
    _assert_replay_error((events[0], events[1], duplicate_id), RuntimeErrorCode.DUPLICATE_EVENT_ID)


def test_cross_run_event_is_rejected() -> None:
    events = runtime_event_stream("eligible")
    changed = _rehash_event(events[1], run_id="run:foreign")
    _assert_replay_error((events[0], changed), RuntimeErrorCode.RUN_MISMATCH)


def test_mismatched_plan_digest_is_rejected() -> None:
    events = runtime_event_stream("eligible")
    original = events[1].payload
    assert isinstance(original, ProposalRecordedPayload)
    payload = ProposalRecordedPayload(
        proposal_digest=original.proposal_digest,
        experiment_plan_digest=WRONG_DIGEST,
        capability_manifest_digest=original.capability_manifest_digest,
    )
    changed = _rehash_event(events[1], payload=payload)
    _assert_replay_error((events[0], changed), RuntimeErrorCode.PLAN_MISMATCH)


def test_mismatched_manifest_digest_is_rejected() -> None:
    events = runtime_event_stream("eligible")
    original = events[1].payload
    assert isinstance(original, ProposalRecordedPayload)
    payload = ProposalRecordedPayload(
        proposal_digest=original.proposal_digest,
        experiment_plan_digest=original.experiment_plan_digest,
        capability_manifest_digest=WRONG_DIGEST,
    )
    changed = _rehash_event(events[1], payload=payload)
    _assert_replay_error((events[0], changed), RuntimeErrorCode.MANIFEST_MISMATCH)


def test_mismatched_proposal_digest_is_rejected() -> None:
    events = runtime_event_stream("eligible")
    original = events[2].payload
    assert isinstance(original, EvidenceRecordedPayload)
    payload = EvidenceRecordedPayload(
        evidence_digest=original.evidence_digest,
        proposal_digest=WRONG_DIGEST,
        experiment_plan_digest=original.experiment_plan_digest,
        capability_manifest_digest=original.capability_manifest_digest,
    )
    changed = _rehash_event(events[2], payload=payload)
    _assert_replay_error((events[0], events[1], changed), RuntimeErrorCode.PROPOSAL_MISMATCH)


def test_mismatched_evidence_digest_is_rejected() -> None:
    events = runtime_event_stream("eligible")
    original = events[3].payload
    assert isinstance(original, PolicyDecisionRecordedPayload)
    payload = PolicyDecisionRecordedPayload(
        policy_decision_digest=original.policy_decision_digest,
        policy_status=original.policy_status,
        proposal_digest=original.proposal_digest,
        evidence_digest=WRONG_DIGEST,
    )
    changed = _rehash_event(events[3], payload=payload)
    _assert_replay_error(
        (events[0], events[1], events[2], changed), RuntimeErrorCode.EVIDENCE_MISMATCH
    )


def test_policy_decision_before_evidence_is_rejected() -> None:
    events = runtime_event_stream("eligible")
    early_decision = create_runtime_event(
        event_id="event:eligible:early-decision",
        run_id=events[0].run_id,
        sequence_number=3,
        event_type=EventType.POLICY_DECISION_RECORDED,
        occurred_at=RUNTIME_FIXTURE_TIME + timedelta(seconds=2),
        payload=events[3].payload,
        previous_event_digest=events[1].event_digest,
    )
    _assert_replay_error(
        (events[0], events[1], early_decision), RuntimeErrorCode.INVALID_TRANSITION
    )


def test_event_after_terminal_status_is_rejected() -> None:
    events = runtime_event_stream("eligible")
    extra = create_runtime_event(
        event_id="event:eligible:after-terminal",
        run_id=events[0].run_id,
        sequence_number=5,
        event_type=EventType.RUN_OPENED,
        occurred_at=RUNTIME_FIXTURE_TIME + timedelta(seconds=4),
        payload=events[0].payload,
        previous_event_digest=events[3].event_digest,
    )
    _assert_replay_error((*events, extra), RuntimeErrorCode.TERMINAL_STATE)


@pytest.mark.parametrize(
    ("field", "value"),
    [("schema_version", "0.3.0"), ("event_type", "EXECUTE_COMMAND")],
)
def test_unsupported_schema_versions_and_unknown_event_types_fail(field: str, value: str) -> None:
    payload = runtime_event_stream("eligible")[0].model_dump(mode="python")
    payload[field] = value
    with pytest.raises(ValidationError):
        RuntimeEvent.model_validate(payload)


def test_unknown_event_fields_fail() -> None:
    payload = runtime_event_stream("eligible")[0].model_dump(mode="python")
    payload["operator_approval"] = "fabricated"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RuntimeEvent.model_validate(payload)


def test_unknown_payload_fields_fail() -> None:
    payload = runtime_event_stream("eligible")[0].model_dump(mode="python")
    assert isinstance(payload["payload"], dict)
    payload["payload"]["approval_token"] = "fabricated"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RuntimeEvent.model_validate(payload)


def test_event_type_must_match_typed_payload() -> None:
    event = runtime_event_stream("eligible")[0]
    payload = event.model_dump(mode="python", exclude={"event_digest"})
    payload["event_type"] = EventType.PROPOSAL_RECORDED
    payload["event_digest"] = digest_data(payload)
    with pytest.raises(ValidationError):
        RuntimeEvent.model_validate(payload)


def test_event_and_state_are_immutable() -> None:
    event = runtime_event_stream("eligible")[0]
    state = new_runtime_state()
    with pytest.raises(ValidationError, match="Instance is frozen"):
        event.run_id = "run:changed"  # type: ignore[misc]
    with pytest.raises(ValidationError, match="Instance is frozen"):
        state.status = RuntimeStatus.OPEN  # type: ignore[misc]


def test_reducer_does_not_mutate_inputs() -> None:
    events = runtime_event_stream("eligible")
    previous = replay_events(events[:1])
    state_before = previous.model_dump(mode="python")
    event_before = events[1].model_dump(mode="python")
    reduce_event(previous, events[1])
    assert previous.model_dump(mode="python") == state_before
    assert events[1].model_dump(mode="python") == event_before


def test_replay_performs_no_filesystem_or_network_access(monkeypatch: pytest.MonkeyPatch) -> None:
    events = runtime_event_stream("eligible")

    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("replay attempted external I/O")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    assert replay_events(events).status is RuntimeStatus.ELIGIBLE


def test_sequence_not_wall_clock_time_determines_replay_order() -> None:
    originals = runtime_event_stream("eligible")
    rebuilt: list[RuntimeEvent] = []
    previous_digest: str | None = None
    for index, original in enumerate(originals):
        event = create_runtime_event(
            event_id=original.event_id,
            run_id=original.run_id,
            sequence_number=original.sequence_number,
            event_type=original.event_type,
            occurred_at=RUNTIME_FIXTURE_TIME - timedelta(seconds=index),
            payload=original.payload,
            previous_event_digest=previous_digest,
        )
        rebuilt.append(event)
        previous_digest = event.event_digest
    assert replay_events(tuple(rebuilt)).status is RuntimeStatus.ELIGIBLE


def test_empty_stream_is_rejected() -> None:
    _assert_replay_error((), RuntimeErrorCode.EMPTY_STREAM)


def test_malformed_stream_item_is_structurally_rejected() -> None:
    malformed = (object(),)
    with pytest.raises(RuntimeTransitionError) as captured:
        replay_events(malformed)  # type: ignore[arg-type]
    assert captured.value.issue.code is RuntimeErrorCode.INVALID_EVENT


def test_foundation_01_eligible_decision_digest_is_unchanged() -> None:
    expected = "sha256:00d2b5ad1759bcdcfb2bf4b14f292cbcdcecc2eed918963e41f8f04e95131b53"
    assert foundation_fixtures()["eligible"].decision.decision_digest == expected
