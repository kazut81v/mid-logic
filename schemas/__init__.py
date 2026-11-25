"""
Phase 7: Engine Interface Spec (schemas package)
Task: 7-1 Engine-1, 7-2 Engine-2, 7-3 Engine-3
"""

from .contract import (
    NormalizedArticle, ActionableInsight, SynthesisResult,
    DeliveryRecord, Envelope, FeedbackEvent, HealthMetric
)
from .verify import verify_envelope
from .dlq import DeadLetterQueue
from .queue import MessageBroker

__all__ = [
    "NormalizedArticle",
    "ActionableInsight",
    "SynthesisResult",
    "DeliveryRecord",
    "Envelope",
    "FeedbackEvent",
    "HealthMetric",
    "verify_envelope",
    "DeadLetterQueue",
    "MessageBroker",
]
