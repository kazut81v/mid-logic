"""
Task 7-4: Dead Letter Queue (DLQ) Tests
Covers: basic record/retrieve, max_size eviction, file persistence, clear.
"""

import pytest
import json
import tempfile
import os
from schemas.dlq import DeadLetterQueue, DroppedMessage


class TestDeadLetterQueue:
    def test_record_and_retrieve(self):
        dlq = DeadLetterQueue(max_size=100)
        dlq.record("NormalizedArticle", {"article_id": "a-1", "title": "Test"}, "Payload validation failed", "trace-1")
        assert len(dlq.get_all()) == 1
        assert dlq.get_all()[0]["msg_type"] == "NormalizedArticle"
        assert dlq.get_all()[0]["error_reason"] == "Payload validation failed"

    def test_record_truncates_payload_snippet(self):
        dlq = DeadLetterQueue(max_size=100)
        payload = {"article_id": "a-1", "body_md": "X" * 1000, "title": "Test", "metadata": {"nested": {"deep": True}}}
        dlq.record("NormalizedArticle", payload, "Test error", "trace-2")
        snippet = dlq.get_all()[0]["payload_snippet"]
        assert "body_md" not in snippet
        assert "metadata" not in snippet
        assert "article_id" in snippet
        assert "title" in snippet

    def test_max_size_eviction(self):
        dlq = DeadLetterQueue(max_size=5)
        for i in range(10):
            dlq.record("TestMsg", {"id": i}, f"Error {i}", f"trace-{i}")
        assert len(dlq.get_all()) == 5
        assert dlq.get_all()[0]["msg_type"] == "TestMsg"
        assert dlq.get_recent(2)[0]["msg_type"] == "TestMsg"

    def test_clear(self):
        dlq = DeadLetterQueue(max_size=100)
        dlq.record("TestMsg", {}, "Error", "trace-3")
        dlq.clear()
        assert len(dlq.get_all()) == 0

    def test_file_persistence(self, tmp_path):
        dlq_path = tmp_path / "dlq.json"
        dlq = DeadLetterQueue(max_size=100, dump_path=str(dlq_path))
        dlq.record("TestMsg", {"id": "1"}, "Error", "trace-4")
        assert dlq_path.exists()
        
        # Simulate restart by loading into new instance
        dlq2 = DeadLetterQueue(max_size=100, dump_path=str(dlq_path))
        assert len(dlq2.get_all()) == 1
        assert dlq2.get_all()[0]["trace_id"] == "trace-4"

    def test_file_eviction_and_save(self, tmp_path):
        dlq_path = tmp_path / "dlq_evict.json"
        dlq = DeadLetterQueue(max_size=3, dump_path=str(dlq_path))
        for i in range(5):
            dlq.record("TestMsg", {"id": i}, f"Error {i}", f"trace-{i}")
        
        with open(dlq_path, "r") as f:
            data = json.load(f)
        assert len(data) == 3  # Only last 3 should remain
        
        # Also verify in-memory state matches
        assert len(dlq.get_all()) == 3
        assert dlq.get_all()[0]["trace_id"] == "trace-2"

    def test_get_recent(self):
        dlq = DeadLetterQueue(max_size=100)
        for i in range(10):
            dlq.record("TestMsg", {}, f"Error {i}", f"trace-{i}")
        recent = dlq.get_recent(3)
        assert len(recent) == 3
        assert recent[0]["trace_id"] == "trace-7"
