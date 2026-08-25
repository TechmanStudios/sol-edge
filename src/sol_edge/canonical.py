"""Deterministic serialization and SHA-256 identities for SOL-Edge contracts."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel


def decimal_text(value: Decimal) -> str:
    """Return the Foundation 0.1 normalized decimal representation."""
    if not value.is_finite():
        raise ValueError("decimal values must be finite")
    if value.is_zero():
        return "0"
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def timestamp_text(value: datetime) -> str:
    """Return a timezone-aware datetime as normalized UTC RFC 3339."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must include a UTC offset")
    utc = value.astimezone(UTC)
    if utc.microsecond:
        fraction = f"{utc.microsecond:06d}".rstrip("0")
        return utc.strftime("%Y-%m-%dT%H:%M:%S") + f".{fraction}Z"
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize(value: Any) -> Any:
    if isinstance(value, BaseModel):
        semantic_payload = getattr(value, "semantic_payload", None)
        if callable(semantic_payload):
            return _normalize(semantic_payload())
        return _normalize(value.model_dump(mode="python"))
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Decimal):
        return decimal_text(value)
    if isinstance(value, datetime):
        return timestamp_text(value)
    if isinstance(value, Enum):
        return _normalize(value.value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("NaN and infinity are prohibited")
        raise TypeError(
            "binary floating-point values are prohibited; use Decimal or decimal strings"
        )
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical object keys must be strings")
            normalized[key] = _normalize(item)
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalize(item) for item in value]
    raise TypeError(f"unsupported canonical value type: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Serialize a value with the documented SOL-Edge canonical JSON profile."""
    normalized = _normalize(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_bytes(value: Any) -> bytes:
    """Return canonical UTF-8 bytes."""
    return canonical_json(value).encode("utf-8")


def digest_data(value: Any) -> str:
    """Return a lowercase, tagged SHA-256 digest of canonical bytes."""
    digest = hashlib.sha256(canonical_bytes(value)).hexdigest()
    return f"sha256:{digest}"
