"""Pulling the prose out of JSON that has not finished arriving.

Every test feeds the document one character at a time, because that
is the worst case and the one a real stream produces: a chunk
boundary can land anywhere, including inside an escape sequence.
"""

from __future__ import annotations

import json

from app.domain.partial_json import FieldStream, read_string_field


def drip(document: str, field: str = "answer") -> tuple[str, list[str]]:
    """Feed one character at a time. Returns the text and the deltas."""
    stream = FieldStream(field)
    deltas = [stream.feed(char) for char in document]
    return stream.text, [d for d in deltas if d]


def test_the_prose_arrives_before_the_object_is_closed() -> None:
    """**The whole point.** Nobody waits for the closing brace."""
    half = '{"answer":"You have almost ever'
    value, done = read_string_field(half, "answer")
    assert value == "You have almost ever"
    assert not done


def test_it_knows_when_the_field_has_finished() -> None:
    whole = '{"answer":"Yes, you do.","has_match":true}'
    value, done = read_string_field(whole, "answer")
    assert value == "Yes, you do."
    assert done


def test_nothing_comes_out_before_the_field_appears() -> None:
    for prefix in ("", "{", '{"has', '{"has_match":true,'):
        assert read_string_field(prefix, "answer") == ("", False)


def test_an_escaped_quote_does_not_end_the_string() -> None:
    """The commonest way a naive reader truncates a reply."""
    document = json.dumps({"answer": 'She said "yes" to it.'})
    value, done = read_string_field(document, "answer")
    assert value == 'She said "yes" to it.'
    assert done


def test_a_half_arrived_escape_is_held_back() -> None:
    """**Nobody ever sees half an escape.**

    `\\u00e9` arriving as `\\u00` would surface as a literal
    backslash-u in somebody's chat bubble.
    """
    value, done = read_string_field('{"answer":"caf\\u00', "answer")
    assert value == "caf"
    assert not done
    value, done = read_string_field('{"answer":"caf\\u00e9', "answer")
    assert value == "café"


def test_a_lone_trailing_backslash_emits_nothing_extra() -> None:
    value, _ = read_string_field('{"answer":"a line\\', "answer")
    assert value == "a line"


def test_newlines_and_tabs_decode() -> None:
    document = json.dumps({"answer": "one\ntwo\tthree"})
    value, done = read_string_field(document, "answer")
    assert value == "one\ntwo\tthree"
    assert done


def test_character_by_character_matches_the_whole_thing() -> None:
    """The real test: a chunk boundary can land anywhere."""
    original = 'Yes — the "cream" ones work.\nTry the tote too. café'
    document = json.dumps(
        {"answer": original, "has_match": True, "using": ["a"], "missing": []}
    )
    text, deltas = drip(document)
    assert text == original
    assert "".join(deltas) == original


def test_deltas_never_repeat_what_was_already_sent() -> None:
    """A client appends; it must not be handed the whole string again."""
    document = json.dumps({"answer": "abcdef"})
    _, deltas = drip(document)
    assert "".join(deltas) == "abcdef"
    assert all(len(d) >= 1 for d in deltas)


def test_a_stream_stops_emitting_once_the_field_closes() -> None:
    stream = FieldStream("answer")
    stream.feed('{"answer":"done."')
    assert stream.feed(',"has_match":true}') == ""
    assert stream.done


def test_whitespace_around_the_colon_is_tolerated() -> None:
    value, done = read_string_field('{"answer"  :  "spaced"}', "answer")
    assert value == "spaced"
    assert done


def test_a_null_field_is_finished_rather_than_pending() -> None:
    """Otherwise a caller waits forever for a value that never comes."""
    value, done = read_string_field('{"answer": null}', "answer")
    assert value == ""
    assert done


def test_the_raw_buffer_is_kept_for_the_final_parse() -> None:
    """The structured half is parsed normally once the stream ends."""
    document = json.dumps(
        {"answer": "Yes.", "has_match": True, "using": [], "missing": []}
    )
    stream = FieldStream("answer")
    for char in document:
        stream.feed(char)
    assert json.loads(stream.raw)["has_match"] is True


def test_another_field_is_not_mistaken_for_this_one() -> None:
    document = json.dumps({"note": "wrong", "answer": "right"})
    value, _ = read_string_field(document, "answer")
    assert value == "right"
