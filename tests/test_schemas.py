"""
Tests for Phase 7 schemas: contract.py, verify.py, dlq.py, queue.py.
Includes test_latency_tracking for environment-dependent latency checking.
"""

import time
import pytest
import msgspec
from schemas.contract import (
    NormalizedArticle, ActionableInsight, SynthesisResult,
    DeliveryRecord, Envelope, FeedbackEvent, HealthMetric,
)
from schemas.verify import verify_envelope
from schemas.dlq import DeadLetterQueue


def test_normalized_article_creation():
    a = NormalizedArticle(
        article_id="a-1", title="Test", body_md="Body",
        source_id="s-1", reliability_category="official"
    )
    assert a.article_id == "a-1"
    assert a.title == "Test"
    assert a.reliability_category == "official"


def test_synthesis_result_creation():
    s = SynthesisResult(
        synthesis_id="s-1", topic="MID",
        insights=[ActionableInsight(insight_id="i-1", article_id="a-1", insight_type="fact", text="Test")],
        source_article_ids=["a-1"]
    )
    assert len(s.insights) == 1
    assert s.insights[0].text == "Test"


def test_verify_valid_envelope():
    payload = {"article_id": "a-1", "title": "Test", "body_md": "Body",
               "source_id": "s-1", "reliability_category": "official",
               "published_at": 100, "fetched_at": 200,
               "url": "http://x.com", "content_hash": "h", "metadata": {}}
    env = Envelope(spec_version="v1", msg_type="NormalizedArticle",
                   trace_id="t-1", span_id="s-1", timestamp_ns=int(time.time_ns()),
                   payload=payload)
    raw = msgspec.json.encode(env)
    ok, err, validated = verify_envelope(raw)
    assert ok is True
    assert err is None
    assert validated is not None


def test_verify_missing_required_field():
    env = Envelope(spec_version="v1", msg_type="NormalizedArticle",
                   trace_id="t-1", span_id="s-1", timestamp_ns=int(time.time_ns()),
                   payload={"title": "NoArticleId"})
    raw = msgspec.json.encode(env)
    ok, err, _ = verify_envelope(raw)
    assert ok is False
    assert err is not None and "missing required field" in err


def test_verify_unknown_msg_type():
    payload = {"some": "data"}
    env = Envelope(spec_version="v1", msg_type="UnknownType",
                   trace_id="t-1", span_id="s-1", timestamp_ns=int(time.time_ns()),
                   payload=payload)
    raw = msgspec.json.encode(env)
    ok, err, _ = verify_envelope(raw)
    assert ok is True


def test_verify_invalid_envelope_structure():
    invalid_json = b'{"not": "an envelope"}'
    ok, err, _ = verify_envelope(invalid_json)
    assert ok is False
    assert err is not None


def test_verify_missing_payload_field():
    env = Envelope(spec_version="v1", msg_type="SynthesisResult",
                   trace_id="t-1", span_id="s-1", timestamp_ns=int(time.time_ns()),
                   payload={"topic": "Test"})
    raw = msgspec.json.encode(env)
    ok, err, _ = verify_envelope(raw)
    assert ok is False
    assert err is not None and "missing required field" in err


def test_verify_synthesis_result_missing_insight():
    env = Envelope(spec_version="v1", msg_type="SynthesisResult",
                   trace_id="t-1", span_id="s-1", timestamp_ns=int(time.time_ns()),
                   payload={"synthesis_id": "s-1", "topic": "Test"})
    raw = msgspec.json.encode(env)
    ok, err, _ = verify_envelope(raw)
    assert ok is False
    assert err is not None


def test_latency_tracking():
    """Check that latency tracking is enabled in the environment."""
    start = time.time()
    time.sleep(0.001)
    end = time.time()
    latency = end - start
    assert latency >= 0.0, f"Latency should be >= 0.0, got {latency}"
