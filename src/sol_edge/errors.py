"""Stable, machine-readable projections of Pydantic validation failures."""

from __future__ import annotations

from typing import TypeAlias

from pydantic import BaseModel, ConfigDict, ValidationError

ErrorLocation: TypeAlias = str | int


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: tuple[ErrorLocation, ...]
    code: str
    message: str


def structured_errors(error: ValidationError) -> tuple[ValidationIssue, ...]:
    """Remove unstable help URLs and raw inputs from a validation error."""
    return tuple(
        ValidationIssue(
            path=tuple(item["loc"]),
            code=str(item["type"]),
            message=str(item["msg"]),
        )
        for item in error.errors(include_url=False, include_context=False, include_input=False)
    )
