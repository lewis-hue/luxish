"""Reading one string field out of JSON that is still arriving.

**Why this exists.** The stylist's reply is a structured object - the
prose, a yes/no, the garment ids, the gaps - because everything after
the prose has to be acted on rather than read. But the prose is what
somebody is sitting there waiting for, and holding it back until the
whole object has arrived turns a conversation into a spinner.

So the call streams, and this pulls the prose out of the half-written
JSON as it fills:

    {"answer":"You have almost ever        ->  You have almost ever
    {"answer":"You have almost everyth     ->  You have almost everyth

**Character by character, not by parsing.** A partial JSON document
is not JSON, so no parser will read it; and the obvious shortcut -
wait for a `}` and try `json.loads` - gets you the whole thing at
once, which is the behaviour being avoided. This walks the buffer and
tracks whether it is inside the string.

**Escapes are the only hard part.** `\\"` inside the answer must not
end it, and a buffer that stops mid-escape must not emit half of one:
`\\u00e9` arriving as `\\u00` would otherwise surface as literal
backslash-u. So a trailing incomplete escape is held back until the
rest of it arrives.
"""

from __future__ import annotations

#: The characters JSON escapes to a single other character.
SIMPLE_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}


def read_string_field(buffer: str, field: str) -> tuple[str, bool]:
    """The value of `field` so far, and whether it has finished.

    Returns `("", False)` until the field's opening quote has
    arrived, so a caller can emit whatever it gets without checking
    for `None`.

    `done` means the closing quote was seen; the value will not grow
    again and the caller can stop watching this field.
    """
    marker = f'"{field}"'
    at = buffer.find(marker)
    if at < 0:
        return "", False

    # Past the key, the colon and any whitespace, to the opening quote.
    cursor = at + len(marker)
    while cursor < len(buffer) and buffer[cursor] in ' \t\r\n':
        cursor += 1
    if cursor >= len(buffer) or buffer[cursor] != ":":
        return "", False
    cursor += 1
    while cursor < len(buffer) and buffer[cursor] in ' \t\r\n':
        cursor += 1
    if cursor >= len(buffer):
        return "", False
    if buffer[cursor] != '"':
        # A non-string value, or `null`. Not this function's business.
        return "", True
    cursor += 1

    out: list[str] = []
    while cursor < len(buffer):
        char = buffer[cursor]
        if char == '"':
            return "".join(out), True
        if char != "\\":
            out.append(char)
            cursor += 1
            continue

        # An escape. Held back entirely if the rest of it has not
        # arrived, so nobody ever sees half of one.
        if cursor + 1 >= len(buffer):
            break
        code = buffer[cursor + 1]
        if code == "u":
            if cursor + 6 > len(buffer):
                break
            digits = buffer[cursor + 2 : cursor + 6]
            try:
                out.append(chr(int(digits, 16)))
            except ValueError:
                # Malformed, and not worth failing a reply over.
                out.append(digits)
            cursor += 6
            continue
        out.append(SIMPLE_ESCAPES.get(code, code))
        cursor += 2

    return "".join(out), False


class FieldStream:
    """Emits only what is new, so a caller can append rather than redraw.

    A client that is handed the whole string each time has to work out
    the difference itself, and every implementation of that gets the
    escape handling wrong in its own way.
    """

    def __init__(self, field: str) -> None:
        self.field = field
        self._buffer = ""
        self._emitted = 0
        self.done = False

    def feed(self, chunk: str) -> str:
        """Add a chunk of raw response. Returns the new text, if any.

        **The buffer keeps growing after the field closes.** Returning
        early here was a real defect: everything after the prose -
        the verdict, the garment ids, the gaps - stopped being
        recorded, so `raw` was a truncated document and the final
        parse raised. The prose stops; the recording does not.
        """
        self._buffer += chunk
        if self.done:
            return ""
        value, finished = read_string_field(self._buffer, self.field)
        self.done = finished
        if len(value) <= self._emitted:
            # Can go backwards only if the buffer was malformed; not
            # emitting anything is the safe answer.
            return ""
        fresh = value[self._emitted :]
        self._emitted = len(value)
        return fresh

    @property
    def text(self) -> str:
        """Everything emitted so far."""
        value, _ = read_string_field(self._buffer, self.field)
        return value

    @property
    def raw(self) -> str:
        """The whole buffer, for parsing once the stream ends."""
        return self._buffer


__all__ = ["SIMPLE_ESCAPES", "FieldStream", "read_string_field"]
