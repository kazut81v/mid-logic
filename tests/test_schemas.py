"""
Phase 7 Schema & Envelope Verification Tests
Covers: Normal cases, SchemaViolation, BusinessReject, Unknown msg_type
"""

import json
import msgspec
import pytest
from schemas.contract import Envelope, NormalizedArticle, SynthesisResult, ActionableInsight
from schemas.verify import verify_envelope


class TestSchemaDefinitions:
    def test_normalized_article_creation(self):
        article = NormalizedArticle(
            article_id="test-001",
            source_id="src-1",
            reliability_category="official",
            title="Test Title",
            body_md="Test body",
            published_at=1000000,
            fetched_at=1000001,
            url="https://example.com",
            content_hash="abc123",
            metadata={}
        )
        assert isinstance(article, msgspec.Struct)

    def test_synthesis_result_creation(self):
        insight = ActionableInsight(
            decision_point="DP1",
            recommended_action="Do X",
            confidence="High",
            confidence_gaps=[],
            residual_risks=[]
        )
        result = SynthesisResult(
            cluster_id="cl-1",
            articles=["a-1"],
            summary_md="Summary",
            insight=insight,
            weight_snapshot={"w": 1.0},
            generated_at=2000000
        )
        assert result.insight.confidence == "High"


class TestEnvelopeVerification:
    def _wrap_payload(self, payload_dict, msg_type="NormalizedArticle"):
        """Helper to create a valid envelope JSON"""
        return json.dumps({
            "spec_version": "v1",
            "msg_type": msg_type,
            "trace_id": "trace-1",
            "span_id": "span-1",
            "timestamp_ns": 123456789,
            "payload": payload_dict
        })

    def test_verify_valid_envelope(self):
        article = {
            "article_id": "a-1",
            "source_id": "s-1",
            "reliability_category": "tech_journal",
            "title": "Valid",
            "body_md": "Body",
            "published_at": 100,
            "fetched_at": 200,
            "url": "https://ex.com",
            "content_hash": "hash",
            "metadata": {}
        }
        success, err, data = verify_envelope(self._wrap_payload(article).encode())
        assert success is True
        assert err is None
        assert data is not None
        assert data["msg_type"] == "NormalizedArticle"

    def test_verify_missing_required_field(self):
        article = {
            "source_id": "s-1",  # missing article_id
            "reliability_category": "official",
            "title": "Invalid",
            "body_md": "Body",
            "published_at": 100,
            "fetched_at": 200,
            "url": "https://ex.com",
            "content_hash": "hash",
            "metadata": {}
        }
        success, err, data = verify_envelope(self._wrap_payload(article).encode())
        assert success is False
        assert "validation failed" in str(err).lower()

    def test_verify_unknown_msg_type(self):
        payload = self._wrap_payload({}, "UnknownType")
        success, err, data = verify_envelope(payload.encode())
        assert success is False
        assert "msg_type" in err

    def test_verify_invalid_enum_value(self):
        article = {
            "article_id": "a-1",
            "source_id": "s-1",
            "reliability_category": "invalid_category",
            "title": "Invalid",
            "body_md": "Body",
            "published_at": 100,
            "fetched_at": 200,
            "url": "https://ex.com",
            "content_hash": "hash",
            "metadata": {}
        }
        success, err, data = verify_envelope(self._wrap_payload(article).encode())
        assert success is False
        assert "validation failed" in str(err).lower()

    def test_verify_missing_payload_field(self):
        # Missing 'payload' field entirely should pass (it's optional in Envelope)
        raw = json.dumps({
            "spec_version": "v1",
            "msg_type": "NormalizedArticle",
            "trace_id": "t-1",
            "span_id": "s-1",
            "timestamp_ns": 999
        })
        success, err, data = verify_envelope(raw.encode())
        assert success is True

    def test_verify_synthesis_result_missing_insight(self):
        # insight is required for SynthesisResult
        payload = {
            "cluster_id": "c-1",
            "articles": ["a-1"],
            "summary_md": "Summary",
            # missing 'insight'
            "weight_snapshot": {},
            "generated_at": 123
        }
        success, err, data = verify_envelope(self._wrap_payload(payload, "SynthesisResult").encode())
        assert success is False
        assert "validation failed" in str(err).lower()
