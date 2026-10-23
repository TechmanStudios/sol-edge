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
from sol_edge.umok import (
    CANFDActuatorFrame,
    ROS2CDRJointCommand,
    UMOKALUVerificationReport,
    UMOKEdgeEligibilityInterlock,
    UMOKGeodesicBatchResult,
    UMOKInterlockEvaluation,
    UMOKNativeGeodesicKernel,
    ZeroCopyIPCRingBuffer,
)

__all__ = [
    "ActionProposal",
    "CANFDActuatorFrame",
    "CapabilityManifest",
    "EvidencePacket",
    "ExperimentPlan",
    "PolicyDecision",
    "PolicyStatus",
    "ROS2CDRJointCommand",
    "UMOKALUVerificationReport",
    "UMOKEdgeEligibilityInterlock",
    "UMOKGeodesicBatchResult",
    "UMOKInterlockEvaluation",
    "UMOKNativeGeodesicKernel",
    "ValidationIssue",
    "ZeroCopyIPCRingBuffer",
    "canonical_bytes",
    "canonical_json",
    "digest_data",
    "structured_errors",
]

__version__ = "0.2.0"

