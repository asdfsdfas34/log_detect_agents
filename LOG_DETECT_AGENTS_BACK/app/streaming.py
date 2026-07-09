"""Lightweight in-process event stream for analysis progress."""

from __future__ import annotations

import json
import queue
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

_current_stream_id: ContextVar[str | None] = ContextVar(
    "current_stream_id", default=None
)
_streams: dict[str, queue.Queue[dict[str, Any] | None]] = {}
_streams_lock = threading.Lock()


def ensure_stream(stream_id: str) -> queue.Queue[dict[str, Any] | None]:
    """Return the queue for a stream, creating it if needed."""

    with _streams_lock:
        return _streams.setdefault(stream_id, queue.Queue())


def close_stream(stream_id: str) -> None:
    """Signal stream completion and remove the queue from the registry."""

    with _streams_lock:
        stream = _streams.pop(stream_id, None)
    if stream is not None:
        stream.put(None)


@contextmanager
def analysis_stream(stream_id: str | None) -> Iterator[None]:
    """Bind emitted events in this execution context to a stream id."""

    token = _current_stream_id.set(stream_id)
    try:
        yield
    finally:
        _current_stream_id.reset(token)
        if stream_id:
            close_stream(stream_id)


def emit_event(event: str, data: Any) -> None:
    """Publish an event to the active analysis stream, if any."""

    stream_id = _current_stream_id.get()
    if not stream_id:
        return
    stream = ensure_stream(stream_id)
    stream.put({"event": event, "data": data})


def sse_lines(stream_id: str) -> Iterator[str]:
    """Yield server-sent-event formatted lines for one stream."""

    stream = ensure_stream(stream_id)
    try:
        while True:
            item = stream.get()
            if item is None:
                yield "event: done\ndata: {}\n\n"
                break
            event = str(item.get("event") or "message")
            data = json.dumps(item.get("data"), ensure_ascii=False, default=str)
            yield f"event: {event}\ndata: {data}\n\n"
    finally:
        with _streams_lock:
            if _streams.get(stream_id) is stream:
                _streams.pop(stream_id, None)
