"""
MID Project Phase 7 - Engine Interface Contracts
Single Source of Truth: msgspec.Struct
"""

import msgspec
from typing import Literal


class NormalizedArticle(msgspec.Struct):
    article_id: str
    source_id: str
    reliability_category: Literal["official", "major_media", "tech_journal", "specialized"]
    title: str
    body_md: str
    published_at: int
    fetched_at: int
    url: str
    content_hash: str
    metadata: dict


class ActionableInsight(msgspec.Struct):
    decision_point: str
    recommended_action: str
    confidence: Literal["High", "Medium", "Low"]
    confidence_gaps: list[str]
    residual_risks: list[str]


class SynthesisResult(msgspec.Struct):
    cluster_id: str
    articles: list[str]
    summary_md: str
    insight: ActionableInsight
    weight_snapshot: dict
    generated_at: int


class DeliveryRecord(msgspec.Struct):
    synthesis_id: str
    channels: list[Literal["obsidian", "email", "webhook", "cli"]]
    status_per_channel: dict[str, Literal["ok", "failed", "retrying"]]
    delivered_at: int
    retry_count: int


class Envelope(msgspec.Struct):
    spec_version: Literal["v1"]
    msg_type: Literal["NormalizedArticle", "SynthesisResult", "DeliveryRecord", "HealthMetric", "FeedbackEvent"]
    trace_id: str
    span_id: str
    timestamp_ns: int
    payload: dict | None = None


class FeedbackEvent(msgspec.Struct):
    event_id: str
    synthesis_id: str
    article_ids: list[str]
    label: Literal["useful", "inappropriate", "fix_requested"]
    comment: str | None
    engine_version: str
    created_at: int


class HealthMetric(msgspec.Struct):
    engine_name: str
    metric_name: str
    value: float
    labels: dict
    recorded_at: int
