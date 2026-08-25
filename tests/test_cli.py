from __future__ import annotations

import subprocess
import sys

from sol_edge.fixtures import foundation_fixtures


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
