"""SOL-Edge public contract API; the Foundation 0.2 runtime is in sol_edge.runtime."""

from sol_edge.canonical import canonical_bytes, canonical_json, digest_data
from sol_edge.contracts import (
    ActionProposal,
    CapabilityManifest,
    EvidencePacket,
    ExperimentPlan,
    PolicyDecision,
    PolicyStatus,
)
from sol_edge.errors import ValidationIssue, structured_errors

__all__ = [
    "ActionProposal",
    "CapabilityManifest",
    "EvidencePacket",
    "ExperimentPlan",
    "PolicyDecision",
    "PolicyStatus",
    "ValidationIssue",
    "canonical_bytes",
    "canonical_json",
    "digest_data",
    "structured_errors",
]

__version__ = "0.2.0"
