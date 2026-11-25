"""
Task 7-3: Dead Letter Queue Tests
Covers: record/retrieve, max_size eviction, file persistence, recent N retrieval.
"""

import os
import pytest
import tempfile
from schemas.dlq import DeadLetterQueue


@pytest.fixture
def dlq(tmp_path):
    path = str(tmp_path / "dlq.json")
    return DeadLetterQueue(max_size=5, persist_path=path)


@pytest.fixture
def sample_msg():
    return {
        "article_id": "a-1",
        "title": "Test",
        "body_md": "Body",
        "source_id": "s-1",
        "reliability_category": "official",
        "published_at": 100,
        "fetched_at": 200,
        "url": "http://x.com",
        "content_hash": "h",
        "metadata": {}
    }


def test_record_and_retrieve(dlq, sample_msg):
    dlq.record("NormalizedArticle", sample_msg, "validation failed", "trace-1")
    all_msgs = dlq.get_all()
    assert len(all_msgs) == 1
    assert all_msgs[0].msg_type == "NormalizedArticle"
    assert all_msgs[0].error_reason == "validation failed"
    assert all_msgs[0].trace_id == "trace-1"


def test_record_truncates_payload_snippet(dlq, sample_msg):
    dlq.record("NormalizedArticle", sample_msg, "test error", "trace-1")
    entry = dlq.get_all()[0]
    assert len(entry.payload_snippet) <= 100


def test_max_size_eviction(dlq, sample_msg):
    for i in range(10):
        dlq.record("NormalizedArticle", sample_msg, f"err-{i}", f"trace-{i}")
    assert dlq.get_stats()["count"] == 5
    all_msgs = dlq.get_all()
    trace_ids = [m.trace_id for m in all_msgs]
    assert "trace-0" not in trace_ids  # oldest evicted
    assert "trace-9" in trace_ids  # newest kept


def test_clear(dlq, sample_msg):
    dlq.record("NormalizedArticle", sample_msg, "err", "trace-1")
    dlq.record("SynthesisResult", {"insights": []}, "err2", "trace-2")
    dlq.clear()
    assert dlq.get_stats()["count"] == 0
    assert len(dlq.get_all()) == 0


def test_file_persistence(dlq, sample_msg):
    path = dlq._persist_path
    dlq.record("NormalizedArticle", sample_msg, "err", "trace-1")
    dlq.save_to_file()
    assert os.path.isfile(path)
    # Load from file
    fresh = DeadLetterQueue(max_size=5, persist_path=path)
    fresh.load_from_file()
    assert fresh.get_stats()["count"] == 1


def test_file_eviction_and_save(dlq, sample_msg):
    path = dlq._persist_path
    for i in range(5):
        dlq.record("NormalizedArticle", sample_msg, f"err-{i}", f"trace-{i}")
    dlq.save_to_file()
    # Reload and verify eviction is reflected
    fresh = DeadLetterQueue(max_size=5, persist_path=path)
    fresh.load_from_file()
    assert fresh.get_stats()["count"] == 5


def test_get_recent(dlq, sample_msg):
    for i in range(5):
        dlq.record("NormalizedArticle", sample_msg, f"err-{i}", f"trace-{i}")
    recent = dlq.get_recent(n=3)
    assert len(recent) == 3
    trace_ids = [m.trace_id for m in recent]
    assert "trace-4" in trace_ids
    assert "trace-3" in trace_ids
    assert "trace-2" in trace_ids
