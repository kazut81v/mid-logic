"""
Task 7-2: Envelope verification middleware (verify.py)
Validates Envelope structure and required fields per msg_type.
"""

from __future__ import annotations

from typing import Any

import msgspec
from schemas.contract import Envelope


# Required fields per message type
_REQUIRED_PAYLOAD_FIELDS: dict[str, list[str]] = {
    "NormalizedArticle": [
        "article_id", "title", "body_md", "source_id"
    ],
    "SynthesisResult": [
        "synthesis_id", "topic"
    ],
    "DeliveryRecord": [
        "delivery_id", "target_type", "target_id"
    ],
}


def verify_envelope(raw_bytes: bytes) -> tuple[bool, str | None, dict[str, Any] | None]:
    """
    Parse and validate an Envelope from JSON bytes.

    Returns:
        (ok, error_reason_or_none, validated_dict_or_none)
    """
    try:
        data = msgspec.json.decode(raw_bytes, type=Envelope)
    except Exception as e:
        return False, f"Envelope parse failed: {e}", None

    try:
        _validate_envelope(data)
    except Exception as e:
        return False, f"Envelope validation failed: {e}", None

    # Validate payload required fields
    if data.payload is not None:
        required = _REQUIRED_PAYLOAD_FIELDS.get(data.msg_type, [])
        for field_name in required:
            if field_name not in data.payload:
                return (
                    False,
                    f"Payload missing required field: {field_name}",
                    None,
                )
        # Type-specific deeper validation (only for known types)
        if data.msg_type in _REQUIRED_PAYLOAD_FIELDS:
            try:
                payload_obj = msgspec.convert(data.payload, type=_get_struct_type(data.msg_type))
                _deep_validate(data.msg_type, payload_obj)
            except Exception as e:
                return False, f"Payload validation failed for {data.msg_type}: {e}", None

    return True, None, msgspec.convert(data.payload, type=dict)


def _validate_envelope(env: Envelope) -> None:
    if not env.spec_version or not env.spec_version.startswith("v"):
        raise ValueError("Invalid spec_version")
    if not env.msg_type:
        raise ValueError("Missing msg_type")
    if not env.trace_id:
        raise ValueError("Missing trace_id")
    if not env.span_id:
        raise ValueError("Missing span_id")
    if env.timestamp_ns <= 0:
        raise ValueError("Invalid timestamp_ns")


def _get_struct_type(msg_type: str) -> type:
    if msg_type == "NormalizedArticle":
        from schemas.contract import NormalizedArticle
        return NormalizedArticle
    if msg_type == "SynthesisResult":
        from schemas.contract import SynthesisResult
        return SynthesisResult
    if msg_type == "DeliveryRecord":
        from schemas.contract import DeliveryRecord
        return DeliveryRecord
    from schemas.contract import Envelope
    return Envelope


def _deep_validate(msg_type: str, obj: Any) -> None:
    if msg_type == "SynthesisResult":
        if not isinstance(obj.insights, list) or len(obj.insights) == 0:
            raise ValueError("SynthesisResult.insights must be a non-empty list")
