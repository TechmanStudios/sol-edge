from __future__ import annotations

import subprocess
import sys
from collections import OrderedDict
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from sol_edge.canonical import canonical_bytes, canonical_json, digest_data
from sol_edge.contracts import Annotation, NonSemanticAnnotations
from sol_edge.fixtures import foundation_fixtures


def test_canonical_json_is_byte_identical_for_repeated_serialization() -> None:
    decision = foundation_fixtures()["eligible"].decision
    first = canonical_bytes(decision)
    assert first == canonical_bytes(decision)
    assert first == canonical_json(decision).encode("utf-8")


def test_dictionary_insertion_order_does_not_affect_bytes_or_digest() -> None:
    first = OrderedDict([("zeta", Decimal("1.2300")), ("alpha", {"b": 2, "a": 1})])
    second = OrderedDict([("alpha", {"a": 1, "b": 2}), ("zeta", Decimal("1.23"))])
    assert canonical_bytes(first) == canonical_bytes(second)
    assert digest_data(first) == digest_data(second)


def test_decimal_and_timestamp_normalization() -> None:
    value = {
        "negative_zero": Decimal("-0.000"),
        "measurement": Decimal("12.34000"),
        "timestamp": datetime(2030, 1, 2, 7, 0, tzinfo=UTC),
    }
    assert canonical_json(value) == (
        '{"measurement":"12.34","negative_zero":"0","timestamp":"2030-01-02T07:00:00Z"}'
    )


def test_same_sha_across_separate_python_processes() -> None:
    script = (
        "from sol_edge.fixtures import foundation_fixtures; "
        "print(foundation_fixtures()['eligible'].decision.decision_digest)"
    )
    outputs = [
        subprocess.check_output([sys.executable, "-c", script], text=True).strip() for _ in range(2)
    ]
    expected = foundation_fixtures()["eligible"].decision.decision_digest
    assert outputs == [expected, expected]


def test_semantic_change_changes_digest() -> None:
    plan = foundation_fixtures()["eligible"].plan
    changed = plan.semantic_payload()
    changed["objective"] = "A materially different objective."
    assert digest_data(changed) != plan.semantic_digest()


def test_schema_version_change_changes_digest_even_when_version_is_not_supported() -> None:
    plan = foundation_fixtures()["eligible"].plan
    changed = plan.semantic_payload()
    changed["schema_version"] = "0.1.1"
    assert digest_data(changed) != plan.semantic_digest()


def test_non_semantic_annotations_do_not_change_identity() -> None:
    decision = foundation_fixtures()["eligible"].decision
    annotated = decision.model_copy(
        update={
            "annotations": NonSemanticAnnotations(
                entries=(Annotation(key="display:correlation", value="ui-only-123"),)
            )
        }
    )
    assert decision.semantic_digest() == annotated.semantic_digest()
    assert canonical_bytes(decision) == canonical_bytes(annotated)


@pytest.mark.parametrize("value", [1.25, float("nan"), float("inf")])
def test_canonicalizer_rejects_binary_floats(value: float) -> None:
    with pytest.raises((TypeError, ValueError)):
        canonical_bytes({"value": value})
