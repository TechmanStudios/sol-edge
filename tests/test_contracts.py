from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from sol_edge.contracts import (
    CapabilityManifest,
    NumericRange,
    PolicyStatus,
    UnitCode,
    ValidatedParameter,
)
from sol_edge.errors import structured_errors
from sol_edge.fixtures import foundation_fixtures


def test_all_five_fixture_contract_graphs_are_valid() -> None:
    fixtures = foundation_fixtures()
    assert set(fixtures) == {
        "eligible",
        "requires_human_approval",
        "deferred",
        "quarantined",
        "rejected",
    }
    for fixture in fixtures.values():
        assert fixture.manifest.schema_version == "0.1.0"
        assert fixture.plan.capability_manifest_digest == fixture.manifest.semantic_digest()
        assert fixture.proposal.experiment_plan_digest == fixture.plan.semantic_digest()
        assert fixture.evidence.proposal_digest == fixture.proposal.semantic_digest()
        assert fixture.decision.evidence_digest == fixture.evidence.semantic_digest()
        assert fixture.evidence.reproducibility_digest == fixture.evidence.semantic_digest()
        assert fixture.decision.decision_digest == fixture.decision.semantic_digest()


def test_policy_fixtures_have_exact_distinct_non_authorizing_statuses() -> None:
    decisions = [fixture.decision for fixture in foundation_fixtures().values()]
    assert {decision.status for decision in decisions} == set(PolicyStatus)
    assert len({decision.decision_digest for decision in decisions}) == 5
    assert "AUTHORIZED" not in {status.value for status in PolicyStatus}
    eligible = foundation_fixtures()["eligible"].decision
    assert eligible.next_transition.value == "RELEASE_REVIEW"


def test_invalid_schema_version_is_rejected() -> None:
    manifest = foundation_fixtures()["eligible"].manifest
    payload = manifest.model_dump(mode="python")
    payload["schema_version"] = "0.2.0"
    with pytest.raises(ValidationError, match="schema_version"):
        CapabilityManifest.model_validate(payload)


def test_unknown_fields_are_rejected() -> None:
    manifest = foundation_fixtures()["eligible"].manifest
    payload = manifest.model_dump(mode="python")
    payload["authorization_token"] = "fabricated"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted") as error:
        CapabilityManifest.model_validate(payload)
    issues = structured_errors(error.value)
    assert issues[0].path == ("authorization_token",)
    assert issues[0].code == "extra_forbidden"


def test_contracts_are_immutable_after_validation() -> None:
    manifest = foundation_fixtures()["eligible"].manifest
    with pytest.raises(ValidationError, match="Instance is frozen"):
        manifest.manifest_id = "manifest:mutated"  # type: ignore[misc]


def test_invalid_identifiers_are_rejected() -> None:
    manifest = foundation_fixtures()["eligible"].manifest
    payload = manifest.model_dump(mode="python")
    payload["manifest_id"] = "Not valid!"
    with pytest.raises(ValidationError, match="manifest_id"):
        CapabilityManifest.model_validate(payload)


@pytest.mark.parametrize("unit", [None, "degrees", ""])
def test_missing_or_invalid_units_are_rejected(unit: object) -> None:
    payload = {
        "parameter_id": "target-temperature",
        "value": "25",
        "permitted_range": {"minimum": "20", "maximum": "80"},
    }
    if unit is not None:
        payload["unit"] = unit
    with pytest.raises(ValidationError, match="unit"):
        ValidatedParameter.model_validate(payload)


def test_out_of_range_value_is_rejected_at_parameter_boundary() -> None:
    with pytest.raises(ValidationError, match="outside its declared permitted range"):
        ValidatedParameter(
            parameter_id="target-temperature",
            value="80.0001",
            unit=UnitCode.CELSIUS,
            permitted_range=NumericRange(minimum="20", maximum="80"),
        )


def test_inclusive_range_boundary_is_valid() -> None:
    parameter = ValidatedParameter(
        parameter_id="target-temperature",
        value="80.000",
        unit=UnitCode.CELSIUS,
        permitted_range=NumericRange(minimum="20", maximum="80"),
    )
    assert parameter.value == Decimal("80.000")


def test_binary_float_measurement_is_rejected() -> None:
    with pytest.raises(TypeError, match="binary floating-point"):
        ValidatedParameter(
            parameter_id="target-temperature",
            value=25.1,
            unit=UnitCode.CELSIUS,
            permitted_range=NumericRange(minimum="20", maximum="80"),
        )


def test_malformed_model_like_output_is_rejected() -> None:
    proposal = foundation_fixtures()["eligible"].proposal
    payload = proposal.model_dump(mode="python")
    payload["chain_of_thought"] = "trust this hidden rationale"
    del payload["frozen_sensor_digest"]
    with pytest.raises(ValidationError) as error:
        proposal.__class__.model_validate(payload)
    messages = str(error.value)
    assert "chain_of_thought" in messages
    assert "frozen_sensor_digest" in messages


def test_tampered_derived_digests_are_rejected() -> None:
    fixture = foundation_fixtures()["eligible"]
    decision = fixture.decision.model_dump(mode="python")
    decision["decision_digest"] = "sha256:" + ("f" * 64)
    with pytest.raises(ValidationError, match="decision_digest does not match"):
        fixture.decision.__class__.model_validate(decision)

    evidence = fixture.evidence.model_dump(mode="python")
    evidence["reproducibility_digest"] = "sha256:" + ("f" * 64)
    with pytest.raises(ValidationError, match="reproducibility_digest does not match"):
        fixture.evidence.__class__.model_validate(evidence)
