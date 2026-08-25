"""Read-only fixture inspection command."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from sol_edge.canonical import canonical_json
from sol_edge.fixtures import foundation_fixtures
from sol_edge.runtime.fixtures import RUNTIME_FIXTURE_NAMES, runtime_event_stream
from sol_edge.runtime.replay import replay_events


def _canonical_fixture_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sol-edge",
        description="Print one deterministic policy fixture; never performs physical action.",
    )
    parser.add_argument(
        "fixture",
        nargs="?",
        default="eligible",
        choices=("eligible", "requires_human_approval", "deferred", "quarantined", "rejected"),
    )
    return parser


def _replay_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sol-edge replay",
        description="Replay one deterministic pre-execution event stream without writes.",
    )
    parser.add_argument("fixture", nargs="?", default="eligible", choices=RUNTIME_FIXTURE_NAMES)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    arguments = list(argv) if argv is not None else None
    if arguments is None:
        import sys

        arguments = sys.argv[1:]

    if arguments and arguments[0] == "replay":
        args = _replay_parser().parse_args(arguments[1:])
        events = runtime_event_stream(args.fixture)
        state = replay_events(events)
        print(f"status={state.status.value}")
        print(f"event_count={len(events)}")
        print(f"final_event_digest={state.last_accepted_event_digest}")
        print(f"final_state_digest={state.state_digest}")
        return

    args = _canonical_fixture_parser().parse_args(arguments)
    decision = foundation_fixtures()[args.fixture].decision
    print(canonical_json(decision))
    print(decision.decision_digest)


if __name__ == "__main__":
    main()
