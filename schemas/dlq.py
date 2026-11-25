"""
Task 7-3: Dead Letter Queue (dlq.py)
In-memory queue with optional JSON persistence.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DLQEntry:
    msg_type: str
    payload_snippet: str
    error_reason: str
    trace_id: str
    timestamp_ns: int = field(default_factory=time.time_ns)


class DeadLetterQueue:
    def __init__(self, max_size: int = 10000, persist_path: str | None = None):
        self._entries: list[DLQEntry] = []
        self._max_size = max_size
        self._persist_path = persist_path

    def record(
        self,
        msg_type: str,
        payload: dict[str, Any] | None = None,
        error_reason: str = "",
        trace_id: str = "",
    ) -> None:
        snippet = json.dumps(payload, ensure_ascii=False) if payload else ""
        if len(snippet) > 97:
            snippet = snippet[:97] + "..."
        entry = DLQEntry(
            msg_type=msg_type,
            payload_snippet=snippet,
            error_reason=error_reason,
            trace_id=trace_id,
        )
        self._entries.append(entry)
        if len(self._entries) > self._max_size:
            self._entries = self._entries[-self._max_size:]

    def get_all(self) -> list[DLQEntry]:
        return list(self._entries)

    def get_recent(self, n: int = 10) -> list[DLQEntry]:
        return list(self._entries[-n:])

    def clear(self) -> None:
        self._entries.clear()

    def get_stats(self) -> dict[str, Any]:
        return {"count": len(self._entries), "max_size": self._max_size}

    def save_to_file(self) -> None:
        if not self._persist_path:
            return
        Path(self._persist_path).parent.mkdir(parents=True, exist_ok=True)
        data = [
            {
                "msg_type": e.msg_type,
                "payload_snippet": e.payload_snippet,
                "error_reason": e.error_reason,
                "trace_id": e.trace_id,
                "timestamp_ns": e.timestamp_ns,
            }
            for e in self._entries
        ]
        with open(self._persist_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_from_file(self) -> None:
        path = self._persist_path
        if not path or not Path(path).exists():
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._entries = [
            DLQEntry(
                msg_type=e["msg_type"],
                payload_snippet=e["payload_snippet"],
                error_reason=e["error_reason"],
                trace_id=e["trace_id"],
                timestamp_ns=e["timestamp_ns"],
            )
            for e in data
        ]
        if len(self._entries) > self._max_size:
            self._entries = self._entries[-self._max_size:]
