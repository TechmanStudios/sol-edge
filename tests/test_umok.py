from __future__ import annotations

from decimal import Decimal

import pytest

from sol_edge.canonical import digest_data
from sol_edge.runtime.fixtures import runtime_event_stream
from sol_edge.runtime.state import RuntimeStatus, new_runtime_state
from sol_edge.umok import (
    CAN_FD_FRAME_BYTES,
    CAN_FD_STRUCT,
    CANFDActuatorFrame,
    ROS2CDRSharedMemoryRing,
    SafeStateAction,
    UMOKEdgeEligibilityInterlock,
    UMOKGeodesicVerletKernel,
    UMOKNativeGeodesicKernel,
    ZeroCopyIPCRingBuffer,
)


def test_umok_native_geodesic_kernel_lock_free_sub_microsecond() -> None:
    kernel = UMOKNativeGeodesicKernel(kernel_id="umok-c-buffer-kernel-v1", deadline_us=1.0)
    assert kernel.verify_zero_copy_buffers() is True

    batch = kernel.step_geodesic_verlet_batch(
        steps=2048,
        dt=0.0005,
        damping_gamma=0.15,
        coupling_a=0.32,
        coupling_b=0.24,
        simulate_unbuffered_fault=False,
    )
    assert batch.steps_executed == 2048
    assert batch.lock_free_c_buffer is True
    assert batch.zero_heap_allocations_verified is True
    assert batch.mean_step_latency_us <= Decimal("1.0")
    assert batch.deadline_met is True
    assert batch.min_metric_eigenvalue > Decimal("0")
    assert batch.max_condition_number <= Decimal("100")
    assert batch.carnot_dissipation_j >= Decimal("0")
    assert batch.carnot_bound_satisfied is True
    assert batch.result_digest == batch.semantic_digest()
    assert digest_data(batch).startswith("sha256:")

    # Re-running with identical parameters yields the exact same trajectory_digest
    batch2 = kernel.step_geodesic_verlet_batch(
        steps=2048,
        dt=0.0005,
        damping_gamma=0.15,
        coupling_a=0.32,
        coupling_b=0.24,
        simulate_unbuffered_fault=False,
    )
    assert batch.trajectory_digest == batch2.trajectory_digest


def test_umok_native_geodesic_kernel_unbuffered_fault_exceeds_deadline() -> None:
    kernel = UMOKNativeGeodesicKernel(kernel_id="umok-c-buffer-kernel-v1", deadline_us=1.0)
    batch_fault = kernel.step_geodesic_verlet_batch(
        steps=512,
        dt=0.0005,
        damping_gamma=0.15,
        simulate_unbuffered_fault=True,
    )
    assert batch_fault.lock_free_c_buffer is False
    assert batch_fault.zero_heap_allocations_verified is False
    assert batch_fault.mean_step_latency_us > Decimal("1.0")
    assert batch_fault.deadline_met is False


def test_umok_kernel_parameter_validation() -> None:
    with pytest.raises(ValueError, match="deadline_us must be positive"):
        UMOKNativeGeodesicKernel(deadline_us=0.0)

    kernel = UMOKNativeGeodesicKernel()
    with pytest.raises(ValueError, match="steps must be >= 1"):
        kernel.step_geodesic_verlet_batch(steps=0)
    with pytest.raises(ValueError, match="dt must be > 0"):
        kernel.step_geodesic_verlet_batch(dt=0.0)
    with pytest.raises(ValueError, match="damping_gamma must be >= 0"):
        kernel.step_geodesic_verlet_batch(damping_gamma=-0.1)


def test_umok_riemannian_alu_truth_tables() -> None:
    kernel = UMOKNativeGeodesicKernel()
    report = kernel.verify_riemannian_alu_truth_tables()
    assert report.total_cases == 20
    assert report.passed_cases == 20
    assert report.mismatch_count == 0
    assert report.all_gates_passed is True
    assert report.ripple_carry_4bit_verified is True
    assert report.gates_verified == (
        "AND",
        "OR",
        "XOR",
        "NAND",
        "HALF_ADDER",
        "RIPPLE_ADD_4BIT",
    )
    assert report.report_digest == report.semantic_digest()


def test_zero_copy_ipc_ring_buffer_and_can_fd_framing() -> None:
    assert CAN_FD_STRUCT.size == CAN_FD_FRAME_BYTES == 64
    ring = ZeroCopyIPCRingBuffer(capacity_slots=8)
    assert ring.verify_zero_copy_identity() is True

    joints = (0.12, -0.24, 0.36, -0.48, 0.60, -0.72)
    slot_view, frame, cmd = ring.write_frame_zero_copy(
        can_id=0x1A0,
        sequence_number=1,
        status_flags=0x0001,
        joint_targets_rad=joints,
        step_latency_ns=420,
    )
    assert slot_view.obj is ring.root_view.obj
    assert len(slot_view) == 64
    assert frame.crc32_verified is True
    assert frame.payload_size_bytes == 64
    assert cmd.can_fd_frame_digest == frame.frame_digest
    assert cmd.cdr_encapsulation_header_hex == "00010000"

    read_view, read_frame = ring.read_frame_zero_copy(0)
    assert read_view.obj is ring.root_view.obj
    assert read_frame.frame_digest == frame.frame_digest
    assert read_frame.crc32_verified is True

    with pytest.raises(IndexError):
        ring.read_frame_zero_copy(99)
    with pytest.raises(ValueError, match="exactly 6 joint targets"):
        ring.write_frame_zero_copy(
            can_id=0x1A0,
            sequence_number=2,
            status_flags=1,
            joint_targets_rad=(0.1, 0.2),
            step_latency_ns=400,
        )


def test_umok_edge_eligibility_interlock_cycle0_quarantine_and_cycle1_eligible() -> None:
    kernel = UMOKNativeGeodesicKernel(deadline_us=1.0)
    alu_report = kernel.verify_riemannian_alu_truth_tables()
    interlock = UMOKEdgeEligibilityInterlock()

    # Cycle 0: Uncalibrated kernel + CAN-FD CRC/sequence fault + QUARANTINED event stream
    batch_c0 = kernel.step_geodesic_verlet_batch(steps=512, simulate_unbuffered_fault=True)
    ring_c0 = ZeroCopyIPCRingBuffer(capacity_slots=8)
    ring_c0.write_frame_zero_copy(
        can_id=0x1A0,
        sequence_number=1,
        status_flags=0x0001,
        joint_targets_rad=(0.1, -0.1, 0.2, -0.2, 0.3, -0.3),
        step_latency_ns=3850,
        inject_crc_fault=True,
    )
    ring_c0.write_frame_zero_copy(
        can_id=0x1A0,
        sequence_number=2,
        status_flags=0x0001,
        joint_targets_rad=(0.1, -0.1, 0.2, -0.2, 0.3, -0.3),
        step_latency_ns=3850,
        inject_sequence_fault=True,
    )

    eval_c0 = interlock.evaluate(
        runtime_state_or_events=runtime_event_stream("quarantined"),
        geodesic_batch=batch_c0,
        alu_report=alu_report,
        ring_buffer=ring_c0,
    )
    assert eval_c0.runtime_status is RuntimeStatus.QUARANTINED
    assert eval_c0.interlock_engaged is True
    assert eval_c0.safe_state_triggered is True
    assert eval_c0.safe_state_action is SafeStateAction.HOLD_SAFE_POSITION
    assert eval_c0.staged_frames_count == 0
    assert eval_c0.crc_or_seq_fault_detected is True
    assert eval_c0.release_gate_status == "QUARANTINED_SAFE_STATE_HOLD"
    assert eval_c0.authorized_claimed is False
    assert "RUNTIME_STATE_QUARANTINED" in eval_c0.reason_codes
    assert "UMOK_STEP_DEADLINE_EXCEEDED" in eval_c0.reason_codes
    assert "CAN_FD_CRC32_INTEGRITY_FAULT" in eval_c0.reason_codes

    # Cycle 1: Calibrated lock-free C-buffer kernel + clean CAN-FD frames + ELIGIBLE event stream
    batch_c1 = kernel.step_geodesic_verlet_batch(steps=2048, simulate_unbuffered_fault=False)
    ring_c1 = ZeroCopyIPCRingBuffer(capacity_slots=8)
    for seq in (1, 2, 3):
        ring_c1.write_frame_zero_copy(
            can_id=0x1A0,
            sequence_number=seq,
            status_flags=0x0001,
            joint_targets_rad=(0.15 * seq, -0.12 * seq, 0.22, -0.18, 0.31, -0.25),
            step_latency_ns=420,
        )

    eval_c1 = interlock.evaluate(
        runtime_state_or_events=runtime_event_stream("eligible"),
        geodesic_batch=batch_c1,
        alu_report=alu_report,
        ring_buffer=ring_c1,
    )
    assert eval_c1.runtime_status is RuntimeStatus.ELIGIBLE
    assert eval_c1.interlock_engaged is False
    assert eval_c1.safe_state_triggered is False
    assert eval_c1.safe_state_action is SafeStateAction.NONE
    assert eval_c1.staged_frames_count == 3
    assert eval_c1.zero_copy_verified is True
    assert eval_c1.crc32_verified is True
    assert eval_c1.sequence_monotonic is True
    assert eval_c1.crc_or_seq_fault_detected is False
    assert eval_c1.release_gate_status == "ELIGIBLE_AWAITING_RELEASE_AUTHORITY"
    assert eval_c1.authorized_claimed is False
    assert eval_c1.evaluation_digest == eval_c1.semantic_digest()

    with pytest.raises(ValueError, match="terminal RuntimeState"):
        interlock.evaluate(
            runtime_state_or_events=new_runtime_state(),
            geodesic_batch=batch_c1,
            alu_report=alu_report,
            ring_buffer=ring_c1,
        )


def test_zero_copy_post_write_bit_flip_detected_by_unpack_and_interlock() -> None:
    kernel = UMOKGeodesicVerletKernel(deadline_us=1.0)
    batch = kernel.step_geodesic_verlet_batch(steps=512, simulate_unbuffered_fault=False)
    alu_report = kernel.verify_riemannian_alu_truth_tables()
    interlock = UMOKEdgeEligibilityInterlock()

    ring = ROS2CDRSharedMemoryRing(capacity_slots=4)
    slot_view, _, _ = ring.write_frame_zero_copy(
        can_id=0x1A0,
        sequence_number=1,
        status_flags=0x0001,
        joint_targets_rad=(0.15, -0.12, 0.22, -0.18, 0.31, -0.25),
        step_latency_ns=420,
    )
    assert ring.crc_fault_detected is False

    # Mutate a single bit in the zero-copy slot memoryview after publication
    slot_view[20] ^= 0x01
    unpacked_corrupt = CANFDActuatorFrame.unpack(slot_view, 0)
    assert unpacked_corrupt.crc32_verified is False
    with pytest.raises(ValueError, match="CAN-FD CRC-32 mismatch"):
        CANFDActuatorFrame.unpack(slot_view, 0, strict_crc=True)

    _, read_corrupt = ring.read_frame_zero_copy(0)
    assert read_corrupt.crc32_verified is False
    assert ring.crc_fault_detected is True

    eval_tampered = interlock.evaluate(
        runtime_state_or_events=runtime_event_stream("eligible"),
        geodesic_batch=batch,
        alu_report=alu_report,
        ring_buffer=ring,
    )
    assert eval_tampered.crc32_verified is False
    assert eval_tampered.crc_or_seq_fault_detected is True
    assert eval_tampered.interlock_engaged is True
    assert eval_tampered.safe_state_triggered is True
    assert eval_tampered.safe_state_action is SafeStateAction.HOLD_SAFE_POSITION
    assert eval_tampered.staged_frames_count == 0
    assert eval_tampered.release_gate_status == "QUARANTINED_SAFE_STATE_HOLD"
    assert eval_tampered.authorized_claimed is False
    assert "CAN_FD_CRC32_INTEGRITY_FAULT" in eval_tampered.reason_codes


def test_umok_interlock_non_eligible_runtime_statuses_never_stage_or_claim_authorized() -> None:
    kernel = UMOKNativeGeodesicKernel(deadline_us=1.0)
    batch = kernel.step_geodesic_verlet_batch(steps=512, simulate_unbuffered_fault=False)
    alu_report = kernel.verify_riemannian_alu_truth_tables()
    interlock = UMOKEdgeEligibilityInterlock()

    ring = ZeroCopyIPCRingBuffer(capacity_slots=4)
    ring.write_frame_zero_copy(
        can_id=0x1A0,
        sequence_number=1,
        status_flags=0x0001,
        joint_targets_rad=(0.15, -0.12, 0.22, -0.18, 0.31, -0.25),
        step_latency_ns=420,
    )

    for fixture_name, expected_status in (
        ("requires_human_approval", RuntimeStatus.AWAITING_HUMAN_APPROVAL),
        ("deferred", RuntimeStatus.DEFERRED),
        ("rejected", RuntimeStatus.REJECTED),
    ):
        eval_res = interlock.evaluate(
            runtime_state_or_events=runtime_event_stream(fixture_name),
            geodesic_batch=batch,
            alu_report=alu_report,
            ring_buffer=ring,
        )
        assert eval_res.runtime_status is expected_status
        assert eval_res.staged_frames_count == 0
        assert eval_res.interlock_engaged is True
        assert eval_res.safe_state_triggered is True
        assert eval_res.safe_state_action is SafeStateAction.HOLD_SAFE_POSITION
        assert eval_res.release_gate_status == "BLOCKED_NON_ELIGIBLE_STATE"
        assert eval_res.authorized_claimed is False
        assert "RUNTIME_STATE_NOT_ELIGIBLE" in eval_res.reason_codes


def test_umok_runtime_module_imports() -> None:
    import sol_edge.umok.runtime as umok_runtime

    assert umok_runtime.UMOKNativeGeodesicKernel is UMOKNativeGeodesicKernel
    assert umok_runtime.UMOKGeodesicVerletKernel is UMOKGeodesicVerletKernel
    assert umok_runtime.RiemannianHardwareALU is UMOKNativeGeodesicKernel
    assert umok_runtime.UMOKEdgeEligibilityInterlock is UMOKEdgeEligibilityInterlock
    assert umok_runtime.ZeroCopyIPCRingBuffer is ZeroCopyIPCRingBuffer



