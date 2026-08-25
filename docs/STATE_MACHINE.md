# Foundation 0.2 State Machine

Foundation 0.2 models one pre-execution experiment attempt as a strict, immutable event stream and a
purely derived state. It is an evidence interpretation boundary, not an execution engine.

## Event envelope

Every `RuntimeEvent` contains:

- `schema_name` and semantic `schema_version`;
- unique `event_id` and one `run_id`;
- positive `sequence_number`;
- one of the four supported `event_type` values;
- normalized UTC `occurred_at` evidence;
- the matching typed payload;
- `previous_event_digest`, which is null only for sequence one;
- derived `event_digest`.

The event digest uses the Foundation 0.1 canonical JSON profile and SHA-256. It binds the schema,
stream identity, sequence, type, timestamp, typed payload, and previous digest. The derived
`event_digest` field itself is excluded to avoid self-reference.

Only these events exist in 0.2:

| Event | Typed facts recorded |
| --- | --- |
| `RUN_OPENED` | Experiment-plan and capability-manifest digests |
| `PROPOSAL_RECORDED` | Proposal, plan, and capability-manifest digests |
| `EVIDENCE_RECORDED` | Evidence, proposal, plan, and capability-manifest digests |
| `POLICY_DECISION_RECORDED` | Decision, policy status, proposal, and evidence digests |

There are no execution, approval, checkpoint, rollback, or adapter events.

## Transition table

| Prior state | Required event | Derived state |
| --- | --- | --- |
| `NEW` | `RUN_OPENED` | `OPEN` |
| `OPEN` | `PROPOSAL_RECORDED` | `PROPOSED` |
| `PROPOSED` | `EVIDENCE_RECORDED` | `EVIDENCED` |
| `EVIDENCED` | decision status `ELIGIBLE` | `ELIGIBLE` |
| `EVIDENCED` | decision status `REQUIRE_HUMAN_APPROVAL` | `AWAITING_HUMAN_APPROVAL` |
| `EVIDENCED` | decision status `DEFER` | `DEFERRED` |
| `EVIDENCED` | decision status `QUARANTINE` | `QUARANTINED` |
| `EVIDENCED` | decision status `REJECT` | `REJECTED` |

The five policy-derived states are terminal. An event after any terminal state is rejected.

## Replay and digest chaining

Replay always starts from the same empty `NEW` state. Events are consumed exactly in the order
provided. Each sequence number must be the previous accepted number plus one, and each
`previous_event_digest` must match the accepted chain head. The reducer also retains accepted event
IDs, so duplicates are rejected even when their other fields are changed.

Sequence numbers determine order because wall clocks can drift, be corrected, or report equal times.
Timestamps remain digest-bound evidence but never select or sort events. Altering, removing,
inserting, reordering, or duplicating an event therefore breaks sequence, identity, or digest-chain
validation.

The derived `RuntimeState` is also canonicalized and hashed. Identical accepted streams produce the
same final state bytes and state digest without consulting current time or external state.

## Authority and retry boundaries

`ELIGIBLE` means only that policy checks permit release review. It is not operator approval and does
not authorize physical action. `AWAITING_HUMAN_APPROVAL` records that a separate release authority is
required; the reducer has no event or credential that could satisfy or fabricate that approval.

Foundation 0.2 cannot perform physical execution because it contains no device adapter, actuator,
network client, execution event, approval token, or output side effect. Replay is an in-memory pure
function over supplied event objects.

A retry uses a new run ID because a terminal attempt is immutable evidence. Reusing the old run would
blur the rejected or incomplete history with a materially new attempt and weaken auditability.

