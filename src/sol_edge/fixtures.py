"""Deterministic Foundation 0.1 fixtures; none represent live device data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sol_edge.canonical import digest_data
from sol_edge.contracts import (
    SCHEMA_VERSION,
    ActionProposal,
    ActorRef,
    ActorType,
    ArtifactRef,
    CapabilityManifest,
    CommandParameterSpec,
    Condition,
    DeviceIdentity,
    EvidencePacket,
    ExecutionWindow,
    ExpectedObservation,
    ExperimentPlan,
    InvariantResult,
    InvariantSpec,
    JustificationClaim,
    NextTransition,
    NumericRange,
    Observation,
    ParameterAssignment,
    PlanStep,
    PolicyDecision,
    PolicyStatus,
    ProvenanceRef,
    ReadableChannel,
    SafeState,
    SafeStateAction,
    TargetRef,
    TimeoutPolicy,
    UnitCode,
    ValidatedParameter,
    WritableCommand,
)

FIXTURE_TIME = datetime(2030, 1, 2, 12, 0, tzinfo=UTC)
STALE_TIME = datetime(2029, 12, 1, 12, 0, tzinfo=UTC)
UNBOUND_POLICY_DIGEST = "sha256:" + ("0" * 64)


def _digest(label: str) -> str:
    return digest_data({"fixture_label": label})


def capability_manifest() -> CapabilityManifest:
    return CapabilityManifest(
        manifest_id="manifest:bench-controller",
        manifest_version="1.0.0",
        device=DeviceIdentity(
            device_id="device:sim-bench-01",
            manufacturer="Techman Studios",
            model="Deterministic Bench Simulator",
            serial_number="fixture-0001",
        ),
        device_type="simulator:thermal-bench",
        firmware_or_simulator_version="1.0.0",
        readable_channels=(
            ReadableChannel(
                channel_id="temperature",
                unit=UnitCode.CELSIUS,
                value_type="decimal",
                permitted_range=NumericRange(minimum=Decimal("0"), maximum=Decimal("120")),
                freshness_seconds=Decimal("5"),
            ),
            ReadableChannel(
                channel_id="fan-rpm",
                unit=UnitCode.RPM,
                value_type="integer",
                permitted_range=NumericRange(minimum=Decimal("0"), maximum=Decimal("5000")),
                freshness_seconds=Decimal("2"),
            ),
        ),
        writable_commands=(
            WritableCommand(
                command_id="set-fan",
                parameters=(
                    CommandParameterSpec(
                        parameter_id="fan-percent",
                        unit=UnitCode.PERCENT,
                        permitted_range=NumericRange(minimum=Decimal("0"), maximum=Decimal("100")),
                        safe_value=Decimal("0"),
                    ),
                ),
                max_duration_seconds=Decimal("30"),
                readback_channels=("fan-rpm",),
                human_approval_required=False,
            ),
            WritableCommand(
                command_id="heat",
                parameters=(
                    CommandParameterSpec(
                        parameter_id="target-temperature",
                        unit=UnitCode.CELSIUS,
                        permitted_range=NumericRange(minimum=Decimal("20"), maximum=Decimal("80")),
                        safe_value=Decimal("20"),
                    ),
                ),
                max_duration_seconds=Decimal("60"),
                readback_channels=("temperature",),
                human_approval_required=True,
            ),
            WritableCommand(
                command_id="safe-stop",
                parameters=(
                    CommandParameterSpec(
                        parameter_id="shutdown-delay",
                        unit=UnitCode.SECOND,
                        permitted_range=NumericRange(minimum=Decimal("0"), maximum=Decimal("10")),
                        safe_value=Decimal("0"),
                    ),
                ),
                max_duration_seconds=Decimal("10"),
                readback_channels=("temperature",),
                human_approval_required=False,
            ),
        ),
        safe_state=SafeState(
            command_id="safe-stop",
            description="Set all simulator outputs to their declared safe values.",
        ),
        fail_safe_behavior="On timeout or readback failure, request safe-stop and quarantine.",
        human_approval_required=False,
    )


def experiment_plan(manifest: CapabilityManifest) -> ExperimentPlan:
    return ExperimentPlan(
        plan_id="plan:fan-characterization",
        plan_version="1.0.0",
        objective="Characterize simulator fan response without physical execution.",
        capability_manifest_digest=manifest.semantic_digest(),
        steps=(
            PlanStep(
                step_id="step:set-fan",
                sequence=1,
                command_id="set-fan",
                parameters=(
                    ParameterAssignment(
                        parameter_id="fan-percent",
                        value=Decimal("25"),
                        unit=UnitCode.PERCENT,
                    ),
                ),
                duration_seconds=Decimal("10"),
            ),
        ),
        preconditions=(
            Condition(
                code="SENSOR_SNAPSHOT_FRESH",
                description=(
                    "The frozen simulator sensor snapshot is no more than five seconds old."
                ),
            ),
        ),
        expected_observations=(
            ExpectedObservation(
                observation_id="observation:fan-rpm",
                channel_id="fan-rpm",
                unit=UnitCode.RPM,
                expected_range=NumericRange(minimum=Decimal("900"), maximum=Decimal("1500")),
            ),
        ),
        invariants=(
            InvariantSpec(
                invariant_id="invariant:temperature",
                channel_id="temperature",
                operator="between",
                expected_range=NumericRange(minimum=Decimal("0"), maximum=Decimal("80")),
                unit=UnitCode.CELSIUS,
                violation_transition="QUARANTINE",
            ),
        ),
        timeout=TimeoutPolicy(timeout_seconds=Decimal("30"), transition="DEFER"),
        compensation_and_safe_state=(
            SafeStateAction(
                command_id="safe-stop",
                parameters=(
                    ParameterAssignment(
                        parameter_id="shutdown-delay",
                        value=Decimal("0"),
                        unit=UnitCode.SECOND,
                    ),
                ),
                rationale="Return simulator outputs to their declared safe values.",
            ),
        ),
        required_evidence=("sensor-snapshot", "simulator-output", "readback"),
    )


def _proposal(
    plan: ExperimentPlan,
    manifest: CapabilityManifest,
    fixture_name: str,
) -> ActionProposal:
    command_id = "set-fan"
    parameter_id = "fan-percent"
    unit = UnitCode.PERCENT
    value = Decimal("25")
    permitted_range = NumericRange(minimum=Decimal("0"), maximum=Decimal("100"))
    readback = ("fan-rpm",)
    if fixture_name == "requires_human_approval":
        command_id = "heat"
        parameter_id = "target-temperature"
        unit = UnitCode.CELSIUS
        value = Decimal("55")
        permitted_range = NumericRange(minimum=Decimal("20"), maximum=Decimal("80"))
        readback = ("temperature",)
    elif fixture_name == "rejected":
        command_id = "open-valve"
        parameter_id = "pressure-setpoint"
        unit = UnitCode.PASCAL
        value = Decimal("110")
        permitted_range = NumericRange(minimum=Decimal("0"), maximum=Decimal("120"))
        readback = ("temperature",)

    sensor_digest = _digest(f"sensor:{fixture_name}")
    return ActionProposal(
        proposal_id=f"proposal:{fixture_name.replace('_', '-')}",
        actor=ActorRef(actor_id="actor:fixture-ai", actor_type=ActorType.AI),
        experiment_plan_digest=plan.semantic_digest(),
        capability_manifest_digest=manifest.semantic_digest(),
        target=TargetRef(
            device_id=manifest.device.device_id,
            device_type=manifest.device_type,
        ),
        command_id=command_id,
        validated_parameters=(
            ValidatedParameter(
                parameter_id=parameter_id,
                value=value,
                unit=unit,
                permitted_range=permitted_range,
            ),
        ),
        frozen_sensor_digest=sensor_digest,
        rationale="Fixture proposer predicts a bounded simulator response; policy must verify it.",
        structured_justification=(
            JustificationClaim(
                claim_code="BOUNDED_SIMULATION_PREDICTION",
                statement="The claim is backed only by the referenced deterministic fixture input.",
                evidence_digest=sensor_digest,
            ),
        ),
        execution_window=ExecutionWindow(
            not_before=FIXTURE_TIME,
            not_after=FIXTURE_TIME.replace(minute=5),
        ),
        required_readback_channels=readback,
    )


def _evidence(
    fixture_name: str,
    proposal: ActionProposal,
    plan: ExperimentPlan,
    manifest: CapabilityManifest,
) -> EvidencePacket:
    observed_at = STALE_TIME if fixture_name == "deferred" else FIXTURE_TIME
    observed_value = Decimal("42")
    expected_range = NumericRange(minimum=Decimal("0"), maximum=Decimal("80"))
    if fixture_name == "quarantined":
        observed_value = Decimal("999")
    elif fixture_name == "rejected":
        observed_value = Decimal("110")
    passed = expected_range.contains(observed_value)

    data: dict[str, object] = {
        "schema_name": "evidence_packet",
        "schema_version": SCHEMA_VERSION,
        "evidence_id": f"evidence:{fixture_name.replace('_', '-')}",
        "proposal_digest": proposal.semantic_digest(),
        "experiment_plan_digest": plan.semantic_digest(),
        "capability_manifest_digest": manifest.semantic_digest(),
        "input_digest": proposal.frozen_sensor_digest,
        "policy_digest": UNBOUND_POLICY_DIGEST,
        "simulation_or_dry_run_version": "1.0.0",
        "predicted_output_digest": _digest(f"prediction:{fixture_name}"),
        "observations": (
            Observation(
                observation_id="observation:temperature",
                channel_id="temperature",
                value=observed_value,
                unit=UnitCode.CELSIUS,
                observed_at=observed_at,
                source_digest=proposal.frozen_sensor_digest,
            ),
        ),
        "invariant_results": (
            InvariantResult(
                invariant_id="invariant:temperature",
                passed=passed,
                observed_value=observed_value,
                expected_range=expected_range,
                unit=UnitCode.CELSIUS,
            ),
        ),
        "overall_passed": passed,
        "artifacts": (
            ArtifactRef(
                artifact_id=f"artifact:{fixture_name.replace('_', '-')}",
                uri=f"fixture://{fixture_name}/simulator-output.json",
                media_type="application/json",
                digest=_digest(f"artifact:{fixture_name}"),
            ),
        ),
        "provenance": (
            ProvenanceRef(
                source_id="source:fixture-generator",
                source_type="fixture",
                digest=_digest("fixture-generator:1.0.0"),
                description="Deterministic local fixture generator.",
            ),
            ProvenanceRef(
                source_id="source:simulator",
                source_type="simulator",
                digest=_digest("simulator:1.0.0"),
                description="Declared simulator build; no live device was used.",
            ),
        ),
    }
    data["reproducibility_digest"] = digest_data(data)
    return EvidencePacket.model_validate(data)


def _decision(
    fixture_name: str,
    status: PolicyStatus,
    proposal: ActionProposal,
    evidence: EvidencePacket,
) -> PolicyDecision:
    configuration = {
        PolicyStatus.ELIGIBLE: (
            ("ALL_DECLARED_CHECKS_PASS",),
            "Declared checks pass; this may advance only to release review.",
            (),
            NextTransition.RELEASE_REVIEW,
        ),
        PolicyStatus.REQUIRE_HUMAN_APPROVAL: (
            ("CONSEQUENTIAL_COMMAND", "OPERATOR_APPROVAL_REQUIRED"),
            "The command is eligible for consideration but requires separate operator approval.",
            ("OPERATOR_APPROVAL",),
            NextTransition.AWAIT_OPERATOR_APPROVAL,
        ),
        PolicyStatus.DEFER: (
            ("EVIDENCE_STALE",),
            "The sensor snapshot is stale; obtain fresh evidence before reevaluation.",
            ("FRESH_SENSOR_SNAPSHOT",),
            NextTransition.REFRESH_EVIDENCE,
        ),
        PolicyStatus.QUARANTINE: (
            ("SENSOR_INTEGRITY_MISMATCH", "INVARIANT_VIOLATION"),
            "The observed value is inconsistent with the declared device envelope.",
            ("DEVICE_INTEGRITY_CLEARANCE",),
            NextTransition.INVESTIGATE_AND_CLEAR_QUARANTINE,
        ),
        PolicyStatus.REJECT: (
            ("PROHIBITED_COMMAND", "AUTHORITATIVE_RANGE_MISMATCH"),
            (
                "The requested command is absent from the manifest and violates its authoritative "
                "scope."
            ),
            ("COMMAND_NOT_PERMITTED",),
            NextTransition.NO_TRANSITION,
        ),
    }
    reason_codes, explanation, unmet, transition = configuration[status]
    data: dict[str, object] = {
        "schema_name": "policy_decision",
        "schema_version": SCHEMA_VERSION,
        "decision_id": f"decision:{fixture_name.replace('_', '-')}",
        "status": status,
        "proposal_digest": proposal.semantic_digest(),
        "evidence_digest": evidence.semantic_digest(),
        "policy_name": "policy:foundation-default-deny",
        "policy_version": "1.0.0",
        "policy_digest": _digest("policy:foundation-default-deny:1.0.0"),
        "reason_codes": reason_codes,
        "explanation": explanation,
        "unmet_requirements": unmet,
        "next_transition": transition,
        "decided_at": FIXTURE_TIME,
    }
    data["decision_digest"] = digest_data(data)
    return PolicyDecision.model_validate(data)


@dataclass(frozen=True, slots=True)
class FixtureSet:
    """Frozen grouping returned only by the deterministic fixture factory."""

    manifest: CapabilityManifest
    plan: ExperimentPlan
    proposal: ActionProposal
    evidence: EvidencePacket
    decision: PolicyDecision


def foundation_fixtures() -> dict[str, FixtureSet]:
    manifest = capability_manifest()
    plan = experiment_plan(manifest)
    status_by_name = {
        "eligible": PolicyStatus.ELIGIBLE,
        "requires_human_approval": PolicyStatus.REQUIRE_HUMAN_APPROVAL,
        "deferred": PolicyStatus.DEFER,
        "quarantined": PolicyStatus.QUARANTINE,
        "rejected": PolicyStatus.REJECT,
    }
    fixtures: dict[str, FixtureSet] = {}
    for name, status in status_by_name.items():
        proposal = _proposal(plan, manifest, name)
        evidence = _evidence(name, proposal, plan, manifest)
        decision = _decision(name, status, proposal, evidence)
        fixtures[name] = FixtureSet(manifest, plan, proposal, evidence, decision)
    return fixtures
