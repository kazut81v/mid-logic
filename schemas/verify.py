"""
Envelope Verification Middleware
Validates incoming messages against the Phase 7 contract.
Rejects invalid messages -> DLQ routing.
"""

import msgspec
from schemas.contract import (
    Envelope, NormalizedArticle, SynthesisResult,
    DeliveryRecord, FeedbackEvent, HealthMetric
)

# Map msg_type to Struct type for payload validation
VALID_PAYLOAD_TYPES = {
    "NormalizedArticle": NormalizedArticle,
    "SynthesisResult": SynthesisResult,
    "DeliveryRecord": DeliveryRecord,
    "HealthMetric": HealthMetric,
    "FeedbackEvent": FeedbackEvent,
}


def verify_envelope(raw: bytes) -> tuple[bool, str | None, dict | None]:
    """
    Validate envelope structure and payload schema.
    
    Returns:
        (success: bool, error_msg: str | None, validated_dict: dict | None)
    """
    # 1. Parse Envelope
    try:
        env = msgspec.convert(msgspec.json.decode(raw), Envelope)
    except msgspec.ValidationError as e:
        return False, f"Envelope validation failed: {e}", None
    except Exception as e:
        return False, f"Envelope parse failed: {e}", None

    # 2. Validate Envelope fields
    if env.spec_version != "v1":
        return False, "Unsupported spec_version", None
    if env.msg_type not in VALID_PAYLOAD_TYPES:
        return False, f"Unknown msg_type: {env.msg_type}", None

    # 3. Validate Payload (if present)
    if env.payload is not None:
        try:
            msgspec.convert(env.payload, VALID_PAYLOAD_TYPES[env.msg_type])
        except msgspec.ValidationError as e:
            return False, f"Payload validation failed for {env.msg_type}: {e}", None

    # 4. Success
    return True, None, {
        "spec_version": env.spec_version,
        "msg_type": env.msg_type,
        "trace_id": env.trace_id,
        "span_id": env.span_id,
        "timestamp_ns": env.timestamp_ns,
        "payload": env.payload
    }
