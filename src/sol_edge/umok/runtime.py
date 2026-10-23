"""Unified Manifold Operating Kernel (UMOK) runtime module for SOL-Edge.

Provides the lock-free C-buffer symplectic Velocity-Verlet geodesic kernel,
Riemannian attractor ALU verifier, zero-copy memoryview IPC ring buffer, and
SOL-Edge eligibility interlock under the `sol_edge.umok.runtime` namespace.
"""

from __future__ import annotations

from sol_edge.umok.ipc_can_bridge import (
    CAN_FD_FRAME_BYTES,
    CAN_FD_STRUCT,
    CANFDActuatorFrame,
    ROS2CDRJointCommand,
    ROS2CDRSharedMemoryRing,
    SafeStateAction,
    SafeStateActionMode,
    UMOKEdgeEligibilityInterlock,
    UMOKInterlockEvaluation,
    UMOKStagedFrameEnvelope,
    ZeroCopyIPCRingBuffer,
)
from sol_edge.umok.kernel import (
    RiemannianHardwareALU,
    UMOKALUGateCaseResult,
    UMOKALUVerificationReport,
    UMOKGeodesicBatchResult,
    UMOKGeodesicStepMetrics,
    UMOKGeodesicVerletKernel,
    UMOKNativeGeodesicKernel,
)

__all__ = [
    "CAN_FD_FRAME_BYTES",
    "CAN_FD_STRUCT",
    "CANFDActuatorFrame",
    "ROS2CDRJointCommand",
    "ROS2CDRSharedMemoryRing",
    "RiemannianHardwareALU",
    "SafeStateAction",
    "SafeStateActionMode",
    "UMOKALUGateCaseResult",
    "UMOKALUVerificationReport",
    "UMOKEdgeEligibilityInterlock",
    "UMOKGeodesicBatchResult",
    "UMOKGeodesicStepMetrics",
    "UMOKGeodesicVerletKernel",
    "UMOKInterlockEvaluation",
    "UMOKNativeGeodesicKernel",
    "UMOKStagedFrameEnvelope",
    "ZeroCopyIPCRingBuffer",
]
