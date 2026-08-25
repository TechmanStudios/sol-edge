from __future__ import annotations

import subprocess
import sys

import pytest

from sol_edge.fixtures import foundation_fixtures
from sol_edge.runtime.fixtures import runtime_event_stream
from sol_edge.runtime.replay import replay_events


def test_cli_prints_canonical_fixture_and_digest() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "sol_edge", "eligible"],
        check=True,
        capture_output=True,
        text=True,
    )
    lines = completed.stdout.strip().splitlines()
    assert len(lines) == 2
    assert lines[0].startswith('{"decided_at":')
    assert lines[1] == foundation_fixtures()["eligible"].decision.decision_digest


@pytest.mark.parametrize(
    ("fixture_name", "expected_status"),
    [
        ("eligible", "ELIGIBLE"),
        ("requires_human_approval", "AWAITING_HUMAN_APPROVAL"),
        ("deferred", "DEFERRED"),
        ("quarantined", "QUARANTINED"),
        ("rejected", "REJECTED"),
    ],
)
def test_replay_cli_is_read_only_and_reports_final_identity(
    fixture_name: str, expected_status: str
) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "sol_edge", "replay", fixture_name],
        check=True,
        capture_output=True,
        text=True,
    )
    output = dict(line.split("=", maxsplit=1) for line in completed.stdout.strip().splitlines())
    expected = replay_events(runtime_event_stream(fixture_name))
    assert output == {
        "status": expected_status,
        "event_count": "4",
        "final_event_digest": expected.last_accepted_event_digest,
        "final_state_digest": expected.state_digest,
    }
