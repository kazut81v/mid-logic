"""
Phase 7: Engine Interface Contract Definitions (msgspec Structs)
Task: 7-1 Engine-1, 7-2 Engine-2, 7-3 Engine-3

All 9 data structures for the MID project pipeline.
"""

from __future__ import annotations

import msgspec


class NormalizedArticle(msgspec.Struct, frozen=True, order=True, eq=True):
    article_id: str
    title: str
    body_md: str
    source_id: str
    reliability_category: str = "unknown"
    published_at: int = 0
    fetched_at: int = 0
    url: str = ""
    content_hash: str = ""
    metadata: dict = msgspec.field(default_factory=dict)


class ActionableInsight(msgspec.Struct, frozen=True, order=True, eq=True):
    insight_id: str
    article_id: str
    insight_type: str
    text: str
    confidence: float = 0.0
    metadata: dict = msgspec.field(default_factory=dict)


class SynthesisResult(msgspec.Struct, frozen=True, order=True, eq=True):
    synthesis_id: str
    topic: str
    insights: list = msgspec.field(default_factory=list)
    summary_md: str = ""
    source_article_ids: list = msgspec.field(default_factory=list)
    metadata: dict = msgspec.field(default_factory=dict)


class DeliveryRecord(msgspec.Struct, frozen=True, order=True, eq=True):
    delivery_id: str
    target_type: str
    target_id: str
    status: str = "pending"
    payload_snapshot: dict = msgspec.field(default_factory=dict)
    delivered_at: int = 0
    error_reason: str = ""
    retry_count: int = 0


class Envelope(msgspec.Struct, frozen=True, order=True, eq=True):
    spec_version: str
    msg_type: str
    trace_id: str
    span_id: str
    timestamp_ns: int
    payload: dict | None = None


class FeedbackEvent(msgspec.Struct, frozen=True, order=True, eq=True):
    feedback_id: str
    source_engine: str
    target_engine: str
    article_id: str
    score: float = 0.0
    comment: str = ""
    timestamp_ns: int = 0


class HealthMetric(msgspec.Struct, frozen=True, order=True, eq=True):
    metric_name: str
    value: float
    unit: str = ""
    tags: dict = msgspec.field(default_factory=dict)
    timestamp_ns: int = 0
