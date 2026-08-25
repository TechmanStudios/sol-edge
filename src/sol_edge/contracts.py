"""Strongly validated Foundation 0.1 contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Any, ClassVar, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
    model_validator,
)

from sol_edge.canonical import decimal_text, digest_data, timestamp_text

SCHEMA_VERSION = "0.1.0"

Identifier = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=128,
        pattern=r"^[a-z][a-z0-9]*(?:[-_.:][a-z0-9]+)*$",
    ),
]
SemanticVersion = Annotated[
    str,
    StringConstraints(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"),
]
Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
ReasonCode = Annotated[
    str,
    StringConstraints(min_length=3, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$"),
]


def _parse_decimal(value: Any) -> Decimal:
    if isinstance(value, (bool, float)):
        raise TypeError("binary floating-point and boolean values are not decimal measurements")
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError("value must be a valid decimal string or Decimal") from error
    if not parsed.is_finite():
        raise ValueError("decimal measurements must be finite")
    return parsed


DecimalValue = Annotated[
    Decimal,
    BeforeValidator(_parse_decimal),
    PlainSerializer(decimal_text, return_type=str),
]
PositiveDecimal = Annotated[DecimalValue, Field(gt=Decimal("0"))]
NonNegativeDecimal = Annotated[DecimalValue, Field(ge=Decimal("0"))]


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, str):
        candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            value = datetime.fromisoformat(candidate)
        except ValueError as error:
            raise ValueError("timestamp must be RFC 3339") from error
    if not isinstance(value, datetime):
        raise TypeError("timestamp must be an RFC 3339 string or datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include an offset")
    return value.astimezone(UTC)


UtcTimestamp = Annotated[
    datetime,
    BeforeValidator(_parse_timestamp),
    PlainSerializer(timestamp_text, return_type=str),
]


class StrictModel(BaseModel):
    """Frozen, unknown-field-rejecting model used throughout the contract graph."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class Annotation(StrictModel):
    key: Identifier
    value: Annotated[str, Field(min_length=1, max_length=512)]


class NonSemanticAnnotations(StrictModel):
    """Explicitly non-semantic display or correlation data."""

    entries: tuple[Annotation, ...] = ()

    @model_validator(mode="after")
    def unique_keys(self) -> NonSemanticAnnotations:
        keys = [entry.key for entry in self.entries]
        if len(keys) != len(set(keys)):
            raise ValueError("annotation keys must be unique")
        return self


class CanonicalContract(StrictModel):
    schema_name: str
    schema_version: Literal["0.1.0"] = "0.1.0"
    annotations: NonSemanticAnnotations | None = None

    derived_digest_fields: ClassVar[frozenset[str]] = frozenset()

    def semantic_payload(self) -> dict[str, Any]:
        excluded = {"annotations", *self.derived_digest_fields}
        return self.model_dump(mode="python", exclude=excluded)

    def semantic_digest(self) -> str:
        return digest_data(self.semantic_payload())


class UnitCode(StrEnum):
    UNITLESS = "1"
    CELSIUS = "Cel"
    KELVIN = "K"
    PERCENT = "%"
    SECOND = "s"
    MILLISECOND = "ms"
    VOLT = "V"
    AMPERE = "A"
    WATT = "W"
    RPM = "rpm"
    PASCAL = "Pa"
    MILLILITRE = "mL"
    LITRE = "L"


class NumericRange(StrictModel):
    minimum: DecimalValue
    maximum: DecimalValue

    @model_validator(mode="after")
    def ordered(self) -> NumericRange:
        if self.minimum > self.maximum:
            raise ValueError("range minimum cannot exceed maximum")
        return self

    def contains(self, value: Decimal) -> bool:
        return self.minimum <= value <= self.maximum


class DeviceIdentity(StrictModel):
    device_id: Identifier
    manufacturer: Annotated[str, Field(min_length=1, max_length=128)]
    model: Annotated[str, Field(min_length=1, max_length=128)]
    serial_number: Annotated[str, Field(min_length=1, max_length=128)] | None = None


class ReadableChannel(StrictModel):
    channel_id: Identifier
    unit: UnitCode
    value_type: Literal["decimal", "integer", "boolean"]
    permitted_range: NumericRange | None = None
    freshness_seconds: PositiveDecimal


class CommandParameterSpec(StrictModel):
    parameter_id: Identifier
    unit: UnitCode
    permitted_range: NumericRange
    safe_value: DecimalValue
    required: bool = True

    @model_validator(mode="after")
    def safe_value_within_range(self) -> CommandParameterSpec:
        if not self.permitted_range.contains(self.safe_value):
            raise ValueError("safe value must be within the permitted range")
        return self


class WritableCommand(StrictModel):
    command_id: Identifier
    parameters: tuple[CommandParameterSpec, ...]
    max_duration_seconds: PositiveDecimal
    readback_channels: tuple[Identifier, ...]
    human_approval_required: bool

    @model_validator(mode="after")
    def command_shape(self) -> WritableCommand:
        parameter_ids = [parameter.parameter_id for parameter in self.parameters]
        if not self.parameters:
            raise ValueError("a writable command must declare at least one parameter")
        if len(parameter_ids) != len(set(parameter_ids)):
            raise ValueError("command parameter identifiers must be unique")
        if not self.readback_channels:
            raise ValueError("a writable command must declare readback")
        return self


class SafeState(StrictModel):
    command_id: Identifier
    description: Annotated[str, Field(min_length=1, max_length=512)]


class CapabilityManifest(CanonicalContract):
    schema_name: Literal["capability_manifest"] = "capability_manifest"
    manifest_id: Identifier
    manifest_version: SemanticVersion
    device: DeviceIdentity
    device_type: Identifier
    firmware_or_simulator_version: SemanticVersion
    readable_channels: tuple[ReadableChannel, ...]
    writable_commands: tuple[WritableCommand, ...]
    safe_state: SafeState
    fail_safe_behavior: Annotated[str, Field(min_length=1, max_length=512)]
    human_approval_required: bool

    @model_validator(mode="after")
    def manifest_shape(self) -> CapabilityManifest:
        channels = [channel.channel_id for channel in self.readable_channels]
        commands = [command.command_id for command in self.writable_commands]
        if not channels or not commands:
            raise ValueError("manifest must expose readable channels and writable commands")
        if len(channels) != len(set(channels)) or len(commands) != len(set(commands)):
            raise ValueError("channel and command identifiers must be unique")
        known_channels = set(channels)
        for command in self.writable_commands:
            if not set(command.readback_channels).issubset(known_channels):
                raise ValueError("command readback channels must be declared readable channels")
        if self.safe_state.command_id not in set(commands):
            raise ValueError("safe-state command must be declared writable")
        return self


class Condition(StrictModel):
    code: ReasonCode
    description: Annotated[str, Field(min_length=1, max_length=512)]


class ParameterAssignment(StrictModel):
    parameter_id: Identifier
    value: DecimalValue
    unit: UnitCode


class PlanStep(StrictModel):
    step_id: Identifier
    sequence: Annotated[int, Field(ge=1)]
    command_id: Identifier
    parameters: tuple[ParameterAssignment, ...]
    duration_seconds: PositiveDecimal


class ExpectedObservation(StrictModel):
    observation_id: Identifier
    channel_id: Identifier
    unit: UnitCode
    expected_range: NumericRange


class InvariantSpec(StrictModel):
    invariant_id: Identifier
    channel_id: Identifier
    operator: Literal["between", "at_or_below", "at_or_above", "equals"]
    expected_range: NumericRange
    unit: UnitCode
    violation_transition: Literal["DEFER", "QUARANTINE", "REJECT"]


class SafeStateAction(StrictModel):
    command_id: Identifier
    parameters: tuple[ParameterAssignment, ...]
    rationale: Annotated[str, Field(min_length=1, max_length=512)]


class TimeoutPolicy(StrictModel):
    timeout_seconds: PositiveDecimal
    transition: Literal["DEFER", "QUARANTINE", "REJECT"]


class ExperimentPlan(CanonicalContract):
    schema_name: Literal["experiment_plan"] = "experiment_plan"
    plan_id: Identifier
    plan_version: SemanticVersion
    objective: Annotated[str, Field(min_length=1, max_length=1024)]
    capability_manifest_digest: Digest
    steps: tuple[PlanStep, ...]
    preconditions: tuple[Condition, ...]
    expected_observations: tuple[ExpectedObservation, ...]
    invariants: tuple[InvariantSpec, ...]
    timeout: TimeoutPolicy
    compensation_and_safe_state: tuple[SafeStateAction, ...]
    required_evidence: tuple[Identifier, ...]

    @model_validator(mode="after")
    def ordered_steps_and_evidence(self) -> ExperimentPlan:
        if not self.steps:
            raise ValueError("plan must contain at least one step")
        sequences = [step.sequence for step in self.steps]
        if sequences != list(range(1, len(self.steps) + 1)):
            raise ValueError("steps must be stored in contiguous sequence order beginning at one")
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("plan step identifiers must be unique")
        if not self.preconditions or not self.expected_observations or not self.invariants:
            raise ValueError("plan must declare preconditions, observations, and invariants")
        if not self.compensation_and_safe_state or not self.required_evidence:
            raise ValueError("plan must declare compensation and required evidence")
        return self


class ActorType(StrEnum):
    HUMAN = "HUMAN"
    AI = "AI"
    DETERMINISTIC_SYSTEM = "DETERMINISTIC_SYSTEM"


class ActorRef(StrictModel):
    actor_id: Identifier
    actor_type: ActorType


class TargetRef(StrictModel):
    device_id: Identifier
    device_type: Identifier


class ValidatedParameter(StrictModel):
    parameter_id: Identifier
    value: DecimalValue
    unit: UnitCode
    permitted_range: NumericRange

    @model_validator(mode="after")
    def value_within_range(self) -> ValidatedParameter:
        if not self.permitted_range.contains(self.value):
            raise ValueError("parameter value is outside its declared permitted range")
        return self


class JustificationClaim(StrictModel):
    claim_code: ReasonCode
    statement: Annotated[str, Field(min_length=1, max_length=512)]
    evidence_digest: Digest


class ExecutionWindow(StrictModel):
    not_before: UtcTimestamp
    not_after: UtcTimestamp

    @model_validator(mode="after")
    def ordered(self) -> ExecutionWindow:
        if self.not_before >= self.not_after:
            raise ValueError("execution window must end after it begins")
        return self


class ActionProposal(CanonicalContract):
    schema_name: Literal["action_proposal"] = "action_proposal"
    proposal_id: Identifier
    actor: ActorRef
    experiment_plan_digest: Digest
    capability_manifest_digest: Digest
    target: TargetRef
    command_id: Identifier
    validated_parameters: tuple[ValidatedParameter, ...]
    frozen_sensor_digest: Digest
    rationale: Annotated[str, Field(min_length=1, max_length=1024)]
    structured_justification: tuple[JustificationClaim, ...]
    execution_window: ExecutionWindow
    required_readback_channels: tuple[Identifier, ...]

    @model_validator(mode="after")
    def proposal_shape(self) -> ActionProposal:
        parameter_ids = [parameter.parameter_id for parameter in self.validated_parameters]
        if not parameter_ids or len(parameter_ids) != len(set(parameter_ids)):
            raise ValueError("proposal parameters must be non-empty and uniquely identified")
        if not self.structured_justification:
            raise ValueError("proposal must include structured justification")
        if not self.required_readback_channels:
            raise ValueError("proposal must require readback")
        return self


class Observation(StrictModel):
    observation_id: Identifier
    channel_id: Identifier
    value: DecimalValue
    unit: UnitCode
    observed_at: UtcTimestamp
    source_digest: Digest


class InvariantResult(StrictModel):
    invariant_id: Identifier
    passed: bool
    observed_value: DecimalValue
    expected_range: NumericRange
    unit: UnitCode

    @model_validator(mode="after")
    def result_consistency(self) -> InvariantResult:
        if self.passed != self.expected_range.contains(self.observed_value):
            raise ValueError("invariant result must match its observed value and expected range")
        return self


class ArtifactRef(StrictModel):
    artifact_id: Identifier
    uri: Annotated[str, Field(min_length=1, max_length=1024)]
    media_type: Annotated[str, Field(min_length=3, max_length=128)]
    digest: Digest


class ProvenanceRef(StrictModel):
    source_id: Identifier
    source_type: Literal["fixture", "sensor_snapshot", "simulator", "plan", "manifest"]
    digest: Digest
    description: Annotated[str, Field(min_length=1, max_length=512)]


class EvidencePacket(CanonicalContract):
    schema_name: Literal["evidence_packet"] = "evidence_packet"
    evidence_id: Identifier
    proposal_digest: Digest
    experiment_plan_digest: Digest
    capability_manifest_digest: Digest
    input_digest: Digest
    policy_digest: Digest
    simulation_or_dry_run_version: SemanticVersion
    predicted_output_digest: Digest
    observations: tuple[Observation, ...]
    invariant_results: tuple[InvariantResult, ...]
    overall_passed: bool
    artifacts: tuple[ArtifactRef, ...]
    provenance: tuple[ProvenanceRef, ...]
    reproducibility_digest: Digest

    derived_digest_fields: ClassVar[frozenset[str]] = frozenset({"reproducibility_digest"})

    @model_validator(mode="after")
    def evidence_consistency(self) -> EvidencePacket:
        if not self.observations or not self.invariant_results or not self.provenance:
            raise ValueError(
                "evidence must contain observations, invariant results, and provenance"
            )
        if self.overall_passed != all(result.passed for result in self.invariant_results):
            raise ValueError("overall evidence result must match all invariant results")
        if self.reproducibility_digest != self.semantic_digest():
            raise ValueError("reproducibility_digest does not match semantic evidence content")
        return self


class PolicyStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    REQUIRE_HUMAN_APPROVAL = "REQUIRE_HUMAN_APPROVAL"
    DEFER = "DEFER"
    QUARANTINE = "QUARANTINE"
    REJECT = "REJECT"


class NextTransition(StrEnum):
    RELEASE_REVIEW = "RELEASE_REVIEW"
    AWAIT_OPERATOR_APPROVAL = "AWAIT_OPERATOR_APPROVAL"
    REFRESH_EVIDENCE = "REFRESH_EVIDENCE"
    INVESTIGATE_AND_CLEAR_QUARANTINE = "INVESTIGATE_AND_CLEAR_QUARANTINE"
    NO_TRANSITION = "NO_TRANSITION"


EXPECTED_TRANSITIONS: dict[PolicyStatus, NextTransition] = {
    PolicyStatus.ELIGIBLE: NextTransition.RELEASE_REVIEW,
    PolicyStatus.REQUIRE_HUMAN_APPROVAL: NextTransition.AWAIT_OPERATOR_APPROVAL,
    PolicyStatus.DEFER: NextTransition.REFRESH_EVIDENCE,
    PolicyStatus.QUARANTINE: NextTransition.INVESTIGATE_AND_CLEAR_QUARANTINE,
    PolicyStatus.REJECT: NextTransition.NO_TRANSITION,
}


class PolicyDecision(CanonicalContract):
    schema_name: Literal["policy_decision"] = "policy_decision"
    decision_id: Identifier
    status: PolicyStatus
    proposal_digest: Digest
    evidence_digest: Digest
    policy_name: Identifier
    policy_version: SemanticVersion
    policy_digest: Digest
    reason_codes: tuple[ReasonCode, ...]
    explanation: Annotated[str, Field(min_length=1, max_length=1024)]
    unmet_requirements: tuple[ReasonCode, ...]
    next_transition: NextTransition
    decided_at: UtcTimestamp
    decision_digest: Digest

    derived_digest_fields: ClassVar[frozenset[str]] = frozenset({"decision_digest"})

    @model_validator(mode="after")
    def decision_consistency(self) -> PolicyDecision:
        if not self.reason_codes:
            raise ValueError("decision must include at least one reason code")
        if self.next_transition != EXPECTED_TRANSITIONS[self.status]:
            raise ValueError("next transition does not match the policy status")
        if self.decision_digest != self.semantic_digest():
            raise ValueError("decision_digest does not match semantic decision content")
        return self
