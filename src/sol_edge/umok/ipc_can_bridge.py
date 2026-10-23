"""Zero-copy memoryview IPC ring buffer, 64B CAN-FD / ROS2 CDR framing, and SOL-Edge interlock."""

from __future__ import annotations

import struct
import zlib
from collections.abc import Sequence
from decimal import Decimal
from enum import StrEnum
from typing import Any, ClassVar, Literal

from pydantic import Field, model_validator

from sol_edge.canonical import digest_data
from sol_edge.contracts import DecimalValue, Digest, Identifier, ReasonCode, StrictModel
from sol_edge.runtime.events import RuntimeEvent
from sol_edge.runtime.replay import replay_events
from sol_edge.runtime.state import RuntimeState, RuntimeStatus
from sol_edge.umok.kernel import UMOKALUVerificationReport, UMOKGeodesicBatchResult, _dec

CAN_FD_STRUCT = struct.Struct("<IHH6dII")
CAN_FD_HEADER_BODY_STRUCT = struct.Struct("<IHH6dI")
CAN_FD_FRAME_BYTES = 64


class SafeStateAction(StrEnum):
    """Fail-closed actuator safe-state actions enforced by the UMOK interlock."""

    NONE = "NONE"
    HOLD_SAFE_POSITION = "HOLD_SAFE_POSITION"
    PASSIVE_DAMPING = "PASSIVE_DAMPING"
    EMERGENCY_TORQUE_ZERO = "EMERGENCY_TORQUE_ZERO"


SafeStateActionMode = SafeStateAction


class CANFDActuatorFrame(StrictModel):
    """Canonical 64-byte CAN-FD actuator frame with hardware CRC-32 verification."""

    schema_name: Literal["can_fd_actuator_frame"] = "can_fd_actuator_frame"
    can_id: int = Field(ge=0, le=0x1FFFFFFF)
    sequence_number: int = Field(ge=0, le=0xFFFF)
    status_flags: int = Field(ge=0, le=0xFFFF)
    joint_targets_rad: tuple[
        DecimalValue,
        DecimalValue,
        DecimalValue,
        DecimalValue,
        DecimalValue,
        DecimalValue,
    ]
    step_latency_ns: int = Field(ge=0, le=0xFFFFFFFF)
    crc32: int = Field(ge=0, le=0xFFFFFFFF)
    expected_crc32: int = Field(ge=0, le=0xFFFFFFFF)
    crc32_verified: bool
    payload_size_bytes: int = Field(default=CAN_FD_FRAME_BYTES)
    frame_hex_prefix: str = Field(min_length=8, max_length=128)
    frame_digest: Digest

    derived_digest_fields: ClassVar[frozenset[str]] = frozenset({"frame_digest"})

    def semantic_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="python", exclude=set(self.derived_digest_fields))

    def semantic_digest(self) -> str:
        return digest_data(self.semantic_payload())

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @model_validator(mode="after")
    def validate_frame(self) -> CANFDActuatorFrame:
        if self.payload_size_bytes != CAN_FD_FRAME_BYTES:
            raise ValueError("CAN-FD actuator payload must be exactly 64 bytes")
        if self.crc32_verified != (self.crc32 == self.expected_crc32):
            raise ValueError("crc32_verified must match crc32 == expected_crc32")
        if self.frame_digest != self.semantic_digest():
            raise ValueError("frame_digest does not match semantic payload")
        return self

    @classmethod
    def unpack(
        cls,
        buffer: bytes | bytearray | memoryview,
        offset: int = 0,
        *,
        strict_crc: bool = False,
    ) -> CANFDActuatorFrame:
        """Unpack a 64-byte CAN-FD frame from a zero-copy buffer or memoryview."""
        view = memoryview(buffer)[offset : offset + CAN_FD_FRAME_BYTES]
        if len(view) < CAN_FD_FRAME_BYTES:
            raise ValueError("buffer slice is smaller than 64 bytes")
        unpacked = CAN_FD_STRUCT.unpack_from(view, 0)
        can_id = int(unpacked[0])
        seq_num = int(unpacked[1])
        flags = int(unpacked[2])
        joints_f = tuple(float(x) for x in unpacked[3:9])
        latency_ns = int(unpacked[9])
        stored_crc = int(unpacked[10])

        expected_crc = zlib.crc32(view[:60]) & 0xFFFFFFFF
        crc_ok = stored_crc == expected_crc
        if strict_crc and not crc_ok:
            raise ValueError("CAN-FD CRC-32 mismatch during unpack")

        joints_dec = (
            _dec(joints_f[0], 6),
            _dec(joints_f[1], 6),
            _dec(joints_f[2], 6),
            _dec(joints_f[3], 6),
            _dec(joints_f[4], 6),
            _dec(joints_f[5], 6),
        )
        hex_prefix = bytes(view[:16]).hex()
        frame_payload: dict[str, Any] = {
            "schema_name": "can_fd_actuator_frame",
            "can_id": can_id,
            "sequence_number": seq_num,
            "status_flags": flags,
            "joint_targets_rad": joints_dec,
            "step_latency_ns": latency_ns,
            "crc32": stored_crc,
            "expected_crc32": expected_crc,
            "crc32_verified": crc_ok,
            "payload_size_bytes": CAN_FD_FRAME_BYTES,
            "frame_hex_prefix": hex_prefix,
        }
        frame_payload["frame_digest"] = digest_data(frame_payload)
        return cls(**frame_payload)


class ROS2CDRJointCommand(StrictModel):
    """Zero-copy ROS2 CDR encapsulated joint command mapped over a 64B CAN-FD slot."""

    schema_name: Literal["ros2_cdr_joint_command"] = "ros2_cdr_joint_command"
    topic_name: str = Field(min_length=1, max_length=128)
    cdr_encapsulation_header_hex: Literal["00010000"] = "00010000"
    sequence_number: int = Field(ge=0, le=0xFFFF)
    joint_names: tuple[str, str, str, str, str, str]
    joint_positions_rad: tuple[
        DecimalValue,
        DecimalValue,
        DecimalValue,
        DecimalValue,
        DecimalValue,
        DecimalValue,
    ]
    can_fd_frame_digest: Digest
    cdr_payload_bytes: int = Field(ge=64)
    zero_copy_slot_index: int = Field(ge=0)
    command_digest: Digest

    derived_digest_fields: ClassVar[frozenset[str]] = frozenset({"command_digest"})

    def semantic_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="python", exclude=set(self.derived_digest_fields))

    def semantic_digest(self) -> str:
        return digest_data(self.semantic_payload())

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @model_validator(mode="after")
    def validate_command(self) -> ROS2CDRJointCommand:
        if self.command_digest != self.semantic_digest():
            raise ValueError("command_digest does not match semantic payload")
        return self


class ZeroCopyIPCRingBuffer:
    """Lock-free, zero-copy memoryview ring buffer for 64-byte CAN-FD / ROS2 CDR frames."""

    DEFAULT_JOINT_NAMES: tuple[str, str, str, str, str, str] = (
        "shoulder_pan_joint",
        "shoulder_lift_joint",
        "elbow_joint",
        "wrist_1_joint",
        "wrist_2_joint",
        "wrist_3_joint",
    )

    def __init__(
        self,
        capacity_slots: int = 16,
        topic_name: str = "/sol/umok/joint_command",
    ) -> None:
        if capacity_slots < 1:
            raise ValueError("capacity_slots must be >= 1")
        if CAN_FD_STRUCT.size != CAN_FD_FRAME_BYTES:
            raise RuntimeError("CAN_FD_STRUCT size must be 64 bytes")
        self.capacity_slots: int = capacity_slots
        self.topic_name: str = topic_name
        self._buffer: bytearray = bytearray(capacity_slots * CAN_FD_FRAME_BYTES)
        self._root_view: memoryview = memoryview(self._buffer)
        self._slot_views: tuple[memoryview, ...] = tuple(
            self._root_view[i * CAN_FD_FRAME_BYTES : (i + 1) * CAN_FD_FRAME_BYTES]
            for i in range(capacity_slots)
        )
        self._write_cursor: int = 0
        self._frames_written: int = 0
        self._last_sequence_number: int | None = None
        self._sequence_fault_detected: bool = False
        self._crc_fault_detected: bool = False
        self._written_frames: list[CANFDActuatorFrame] = []
        self._written_commands: list[ROS2CDRJointCommand] = []

    @property
    def root_view(self) -> memoryview:
        return self._root_view

    @property
    def frames_written(self) -> int:
        return self._frames_written

    @property
    def crc_fault_detected(self) -> bool:
        return self._crc_fault_detected or (not self.verify_live_slots_integrity())

    @property
    def sequence_fault_detected(self) -> bool:
        return self._sequence_fault_detected

    @property
    def written_frames(self) -> tuple[CANFDActuatorFrame, ...]:
        return tuple(self._written_frames)

    @property
    def written_commands(self) -> tuple[ROS2CDRJointCommand, ...]:
        return tuple(self._written_commands)

    def verify_zero_copy_identity(self) -> bool:
        """Verify that every slot memoryview directly aliases the pre-allocated bytearray."""
        return (
            self._root_view.obj is self._buffer
            and len(self._buffer) == self.capacity_slots * CAN_FD_FRAME_BYTES
            and all(
                slot.obj is self._buffer and len(slot) == CAN_FD_FRAME_BYTES
                for slot in self._slot_views
            )
        )

    def verify_live_slots_integrity(self) -> bool:
        """Re-read active zero-copy slots to detect post-write bit flips or tampering."""
        active_frames = self._written_frames[-self.capacity_slots :]
        active_commands = self._written_commands[-self.capacity_slots :]
        for recorded_frame, cmd in zip(active_frames, active_commands, strict=True):
            _, live_frame = self.read_frame_zero_copy(cmd.zero_copy_slot_index)
            if not live_frame.crc32_verified:
                return False
            if live_frame.frame_digest != recorded_frame.frame_digest:
                return False
        return True

    def write_frame_zero_copy(
        self,
        can_id: int,
        sequence_number: int,
        status_flags: int,
        joint_targets_rad: Sequence[float | Decimal],
        step_latency_ns: int,
        *,
        inject_crc_fault: bool = False,
        inject_sequence_fault: bool = False,
    ) -> tuple[memoryview, CANFDActuatorFrame, ROS2CDRJointCommand]:
        """Pack a 64-byte CAN-FD frame directly into the ring buffer slot via struct.pack_into."""
        if len(joint_targets_rad) != 6:
            raise ValueError("joint_targets_rad must contain exactly 6 joint targets")

        slot_index = self._write_cursor % self.capacity_slots
        slot_view = self._slot_views[slot_index]

        effective_seq = sequence_number
        if inject_sequence_fault and self._last_sequence_number is not None:
            effective_seq = self._last_sequence_number  # Non-monotonic duplicate sequence fault

        if (
            self._last_sequence_number is not None
            and effective_seq <= self._last_sequence_number
        ):
            self._sequence_fault_detected = True
        self._last_sequence_number = effective_seq

        joints_f = tuple(float(v) for v in joint_targets_rad)
        header_body = CAN_FD_HEADER_BODY_STRUCT.pack(
            can_id & 0x1FFFFFFF,
            effective_seq & 0xFFFF,
            status_flags & 0xFFFF,
            joints_f[0],
            joints_f[1],
            joints_f[2],
            joints_f[3],
            joints_f[4],
            joints_f[5],
            step_latency_ns & 0xFFFFFFFF,
        )
        expected_crc = zlib.crc32(header_body) & 0xFFFFFFFF
        written_crc = (expected_crc ^ 0xDEADCAFE) & 0xFFFFFFFF if inject_crc_fault else expected_crc
        if written_crc != expected_crc:
            self._crc_fault_detected = True

        CAN_FD_STRUCT.pack_into(
            slot_view,
            0,
            can_id & 0x1FFFFFFF,
            effective_seq & 0xFFFF,
            status_flags & 0xFFFF,
            joints_f[0],
            joints_f[1],
            joints_f[2],
            joints_f[3],
            joints_f[4],
            joints_f[5],
            step_latency_ns & 0xFFFFFFFF,
            written_crc,
        )

        self._write_cursor += 1
        self._frames_written += 1

        frame = CANFDActuatorFrame.unpack(slot_view, 0)
        joints_dec = frame.joint_targets_rad

        cmd_payload: dict[str, Any] = {
            "schema_name": "ros2_cdr_joint_command",
            "topic_name": self.topic_name,
            "cdr_encapsulation_header_hex": "00010000",
            "sequence_number": effective_seq & 0xFFFF,
            "joint_names": self.DEFAULT_JOINT_NAMES,
            "joint_positions_rad": joints_dec,
            "can_fd_frame_digest": frame.frame_digest,
            "cdr_payload_bytes": CAN_FD_FRAME_BYTES + 4,
            "zero_copy_slot_index": slot_index,
        }
        cmd_payload["command_digest"] = digest_data(cmd_payload)
        cmd = ROS2CDRJointCommand(**cmd_payload)

        self._written_frames.append(frame)
        self._written_commands.append(cmd)
        return slot_view, frame, cmd

    def read_frame_zero_copy(
        self, slot_index: int
    ) -> tuple[memoryview, CANFDActuatorFrame]:
        """Unpack and verify a 64-byte CAN-FD frame directly from the slot memoryview."""
        if slot_index < 0 or slot_index >= self.capacity_slots:
            raise IndexError("slot_index out of bounds")
        slot_view = self._slot_views[slot_index]
        return slot_view, CANFDActuatorFrame.unpack(slot_view, 0)


class UMOKStagedFrameEnvelope(StrictModel):
    """Envelope binding a verified CAN-FD frame and ROS2 CDR command to a runtime state digest."""

    slot_index: int = Field(ge=0)
    can_fd_frame: CANFDActuatorFrame
    ros2_cdr_command: ROS2CDRJointCommand
    runtime_state_digest: Digest
    policy_decision_digest: Digest


class UMOKInterlockEvaluation(StrictModel):
    """Canonical evaluation of the SOL-Edge UMOK eligibility interlock."""

    schema_name: Literal["umok_interlock_evaluation"] = "umok_interlock_evaluation"
    interlock_id: Identifier
    run_id: Identifier
    runtime_status: RuntimeStatus
    runtime_state_digest: Digest
    policy_decision_digest: Digest
    geodesic_result_digest: Digest
    alu_report_digest: Digest
    deadline_met: bool
    alu_all_gates_passed: bool
    zero_copy_verified: bool
    crc32_verified: bool
    sequence_monotonic: bool
    crc_or_seq_fault_detected: bool
    interlock_engaged: bool
    safe_state_triggered: bool
    safe_state_action: SafeStateAction
    reason_codes: tuple[ReasonCode, ...]
    staged_frames_count: int = Field(ge=0)
    staged_frames: tuple[UMOKStagedFrameEnvelope, ...]
    release_gate_status: Literal[
        "ELIGIBLE_AWAITING_RELEASE_AUTHORITY",
        "QUARANTINED_SAFE_STATE_HOLD",
        "BLOCKED_NON_ELIGIBLE_STATE",
    ]
    authorized_claimed: Literal[False] = False
    evaluation_digest: Digest

    derived_digest_fields: ClassVar[frozenset[str]] = frozenset({"evaluation_digest"})

    def semantic_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="python", exclude=set(self.derived_digest_fields))

    def semantic_digest(self) -> str:
        return digest_data(self.semantic_payload())

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @model_validator(mode="after")
    def validate_interlock_invariants(self) -> UMOKInterlockEvaluation:
        if self.authorized_claimed is not False:
            raise ValueError("SOL-Edge UMOK interlock must never claim AUTHORIZED")
        if self.staged_frames_count != len(self.staged_frames):
            raise ValueError("staged_frames_count must match len(staged_frames)")
        if self.safe_state_triggered:
            if self.staged_frames_count != 0:
                raise ValueError("safe_state_triggered requires staged_frames_count == 0")
            if self.safe_state_action == SafeStateAction.NONE:
                raise ValueError("safe_state_triggered requires a non-NONE SafeStateAction")
        else:
            if self.runtime_status != RuntimeStatus.ELIGIBLE:
                raise ValueError("unstaged interlock release requires RuntimeStatus.ELIGIBLE")
            if self.release_gate_status != "ELIGIBLE_AWAITING_RELEASE_AUTHORITY":
                raise ValueError(
                    "ELIGIBLE state must report ELIGIBLE_AWAITING_RELEASE_AUTHORITY"
                )
        if self.evaluation_digest != self.semantic_digest():
            raise ValueError("evaluation_digest does not match semantic payload")
        return self


class UMOKEdgeEligibilityInterlock:
    """Pure SOL-Edge eligibility interlock gating zero-copy CAN-FD / ROS2 CDR staging."""

    def __init__(self, interlock_id: str = "umok-edge-interlock-v1") -> None:
        self.interlock_id: str = interlock_id

    def evaluate(
        self,
        *,
        runtime_state_or_events: RuntimeState | Sequence[RuntimeEvent],
        geodesic_batch: UMOKGeodesicBatchResult,
        alu_report: UMOKALUVerificationReport,
        ring_buffer: ZeroCopyIPCRingBuffer,
    ) -> UMOKInterlockEvaluation:
        """Evaluate runtime replay state, geodesic latency, ALU parity, and CAN-FD CRC health."""
        state = (
            runtime_state_or_events
            if isinstance(runtime_state_or_events, RuntimeState)
            else replay_events(list(runtime_state_or_events))
        )
        if state.run_id is None or state.policy_decision_digest is None:
            raise ValueError("UMOKEdgeEligibilityInterlock requires a terminal RuntimeState")

        zero_copy_ok = (
            ring_buffer.verify_zero_copy_identity()
            and geodesic_batch.zero_heap_allocations_verified
        )
        crc_ok = (not ring_buffer.crc_fault_detected) and all(
            f.crc32_verified for f in ring_buffer.written_frames
        )
        seq_ok = not ring_buffer.sequence_fault_detected
        fault_detected = (not crc_ok) or (not seq_ok)

        reasons: list[str] = []
        if state.status == RuntimeStatus.QUARANTINED:
            reasons.append("RUNTIME_STATE_QUARANTINED")
        elif state.status != RuntimeStatus.ELIGIBLE:
            reasons.append("RUNTIME_STATE_NOT_ELIGIBLE")

        if not geodesic_batch.deadline_met:
            reasons.append("UMOK_STEP_DEADLINE_EXCEEDED")
        if not geodesic_batch.zero_heap_allocations_verified:
            reasons.append("UMOK_DYNAMIC_HEAP_ALLOCATION_DETECTED")
        if not alu_report.all_gates_passed:
            reasons.append("UMOK_ALU_TRUTH_TABLE_MISMATCH")
        if not crc_ok:
            reasons.append("CAN_FD_CRC32_INTEGRITY_FAULT")
        if not seq_ok:
            reasons.append("CAN_FD_SEQUENCE_MONOTONICITY_FAULT")

        can_stage = (
            state.status == RuntimeStatus.ELIGIBLE
            and geodesic_batch.deadline_met
            and alu_report.all_gates_passed
            and zero_copy_ok
            and crc_ok
            and seq_ok
        )

        if can_stage:
            reasons.append("UMOK_SUB_MICROSECOND_ELIGIBLE_VERIFIED")
            staged_envelopes = tuple(
                UMOKStagedFrameEnvelope(
                    slot_index=cmd.zero_copy_slot_index,
                    can_fd_frame=frame,
                    ros2_cdr_command=cmd,
                    runtime_state_digest=state.state_digest,
                    policy_decision_digest=state.policy_decision_digest,
                )
                for frame, cmd in zip(
                    ring_buffer.written_frames, ring_buffer.written_commands, strict=True
                )
            )
            interlock_engaged = False
            safe_state_triggered = False
            safe_action = SafeStateAction.NONE
            gate_status: Literal[
                "ELIGIBLE_AWAITING_RELEASE_AUTHORITY",
                "QUARANTINED_SAFE_STATE_HOLD",
                "BLOCKED_NON_ELIGIBLE_STATE",
            ] = "ELIGIBLE_AWAITING_RELEASE_AUTHORITY"
        else:
            staged_envelopes = ()
            interlock_engaged = True
            safe_state_triggered = True
            safe_action = SafeStateAction.HOLD_SAFE_POSITION
            gate_status = (
                "QUARANTINED_SAFE_STATE_HOLD"
                if state.status == RuntimeStatus.QUARANTINED or fault_detected
                else "BLOCKED_NON_ELIGIBLE_STATE"
            )

        payload: dict[str, Any] = {
            "schema_name": "umok_interlock_evaluation",
            "interlock_id": self.interlock_id,
            "run_id": state.run_id,
            "runtime_status": state.status,
            "runtime_state_digest": state.state_digest,
            "policy_decision_digest": state.policy_decision_digest,
            "geodesic_result_digest": geodesic_batch.result_digest,
            "alu_report_digest": alu_report.report_digest,
            "deadline_met": geodesic_batch.deadline_met,
            "alu_all_gates_passed": alu_report.all_gates_passed,
            "zero_copy_verified": zero_copy_ok,
            "crc32_verified": crc_ok,
            "sequence_monotonic": seq_ok,
            "crc_or_seq_fault_detected": fault_detected,
            "interlock_engaged": interlock_engaged,
            "safe_state_triggered": safe_state_triggered,
            "safe_state_action": safe_action,
            "reason_codes": tuple(reasons),
            "staged_frames_count": len(staged_envelopes),
            "staged_frames": staged_envelopes,
            "release_gate_status": gate_status,
            "authorized_claimed": False,
        }
        payload["evaluation_digest"] = digest_data(payload)
        return UMOKInterlockEvaluation(**payload)


ROS2CDRSharedMemoryRing = ZeroCopyIPCRingBuffer
