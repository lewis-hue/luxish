"""Task 3 — the logging redaction filter."""

from __future__ import annotations

import json
import logging

from app.middleware import JsonLogFormatter, RedactionFilter

REDACTED_KEYS = (
    "authorization",
    "access_token",
    "refresh_token",
    "latitude",
    "longitude",
)


def _record(**extra: object) -> logging.LogRecord:
    rec = logging.LogRecord("app", logging.INFO, __file__, 1, "msg", None, None)
    for k, v in extra.items():
        setattr(rec, k, v)
    return rec


def test_filter_drops_every_sensitive_key_at_the_top_level() -> None:
    rec = _record(
        authorization="Bearer sk-live-1",
        access_token="at",
        refresh_token="rt",
        latitude=-1.2921,
        longitude=36.8219,
        user_id="u1",
    )
    assert RedactionFilter().filter(rec) is True
    for key in REDACTED_KEYS:
        assert not hasattr(rec, key), f"{key} survived redaction"
    assert rec.user_id == "u1"
    assert set(rec.redacted) == set(REDACTED_KEYS)


def test_filter_drops_sensitive_keys_nested_in_dicts() -> None:
    rec = _record(context={"headers": {"Authorization": "Bearer x"}, "place": {"latitude": 1.0}})
    RedactionFilter().filter(rec)
    assert rec.context == {"headers": {}, "place": {}}


def test_filter_replaces_image_bytes_with_a_descriptor() -> None:
    rec = _record(image=b"\xff\xd8\xff\xe0" + b"0" * 5000)
    RedactionFilter().filter(rec)
    assert rec.image == "<bytes len=5004>"


def test_formatter_emits_json_including_the_request_id() -> None:
    rec = _record(request_id="rid-1")
    line = JsonLogFormatter().format(rec)
    payload = json.loads(line)
    assert payload["request_id"] == "rid-1"
    assert payload["message"] == "msg"
    assert payload["level"] == "INFO"


def test_sensitive_values_never_reach_the_formatted_line() -> None:
    rec = _record(authorization="Bearer sk-live-1", longitude=36.8219)
    RedactionFilter().filter(rec)
    assert "sk-live-1" not in JsonLogFormatter().format(rec)
    assert "36.8219" not in JsonLogFormatter().format(rec)
