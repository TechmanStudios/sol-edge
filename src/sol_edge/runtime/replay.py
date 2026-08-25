"""Side-effect-free replay of a complete recorded runtime stream."""

from __future__ import annotations

from collections.abc import Sequence

from sol_edge.runtime.events import RuntimeEvent
from sol_edge.runtime.reducer import (
    RuntimeErrorCode,
    RuntimeIssue,
    RuntimeTransitionError,
    reduce_event,
)
from sol_edge.runtime.state import RuntimeState, new_runtime_state


def replay_events(events: Sequence[RuntimeEvent]) -> RuntimeState:
    """Replay events exactly as provided; sequence, never wall-clock time, defines order."""
    if not events:
        raise RuntimeTransitionError(
            RuntimeIssue(
                code=RuntimeErrorCode.EMPTY_STREAM,
                message="a runtime stream must contain at least RUN_OPENED",
            )
        )
    state = new_runtime_state()
    for event in events:
        state = reduce_event(state, event)
    return state
