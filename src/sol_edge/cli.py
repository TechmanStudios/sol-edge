"""Read-only fixture inspection command."""

from __future__ import annotations

import argparse

from sol_edge.canonical import canonical_json
from sol_edge.fixtures import foundation_fixtures


def main() -> None:
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
    args = parser.parse_args()
    decision = foundation_fixtures()[args.fixture].decision
    print(canonical_json(decision))
    print(decision.decision_digest)


if __name__ == "__main__":
    main()
