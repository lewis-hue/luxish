"""Making a generated picture the shape the app draws it in.

**The app has one shell and generated pictures kept missing it.** A
cover is shown at its own shape between 9:16 and 1.45, and anything
outside that is brought to the nearest bound - which means cropped.
A photograph off a phone is almost always inside those bounds
already. A picture the studio made is not: it inherits the shape of
whatever was handed to it, so a full-length figure shot on a phone
at about 0.47 comes back at 0.47, and the app then crops it to fit.

Cropping a full-length fashion photograph takes the shoes, and the
reshaping is also visible on the way in: the card is laid out at one
guess, then at another when the real shape arrives.

So the shape is settled here, once, at the moment the bytes are
made - the only point where it can be fixed rather than worked
around. A picture stored at the shell's own ratio is never clamped,
never cropped and never relaid out.

**It widens rather than crops, and that is the whole argument.** To
turn 0.47 into 0.5625 you either take height off the top and bottom
or add width to the sides. Taking height off a full-length figure
removes the head or the shoes, which in a fashion app is the
subject. Adding width adds ground - and these are studio pictures
against a plain wall or a seamless backdrop, so ground extended from
the edge pixels is the same ground. Nothing of the garment is lost.

A picture already inside the bounds is returned untouched.
"""

from __future__ import annotations

import io
from typing import Any

#: The shape the app draws a cover in, matching `SHAPE` in the mobile
#: app's `features/feed/shape.ts`. The two are asserted against each
#: other in `tests/test_shell_fit.py`: a server padding to one ratio
#: while the client clamps to another is the bug this file exists to
#: stop, reintroduced from the other side.
TALLEST = 9 / 16
WIDEST = 1.45

#: The shape a picture that must be upright is brought to.
#:
#: **Not `TALLEST`.** Taking a landscape flat-lay all the way to 9:16
#: means roughly two and a half times its own height in added ground,
#: and the garments then sit in a thin band across the middle. 3:4 is
#: upright, well inside the shell, and asks for about half as much.
#: The model is asked to compose upright in the first place
#: (`PORTRAIT_FRAME` in `workers/garment_studio`); this is the
#: fallback for what comes back the wrong way round anyway.
PORTRAIT_TARGET = 3 / 4

#: How much of the edge is sampled to extend it. A thin strip, because
#: it is standing in for ground immediately beside it.
EDGE_STRIP = 0.04


def measure(image: bytes) -> tuple[int, int] | None:
    """The picture's size, or None if it cannot be read.

    **Recording this is what stops the card moving.** A tile is laid
    out from the stored width and height before a single byte of the
    photograph arrives; without them the app guesses a shape and
    re-lays the column out when the picture decodes, which is the
    jump people read as the app glitching. Every studio asset was
    stored without them.
    """
    try:
        from PIL import Image

        with Image.open(io.BytesIO(image)) as opened:
            width, height = opened.size
            return (width, height) if width and height else None
    except Exception:  # noqa: BLE001 - a shape is never worth the picture
        return None


def shell_ratio(width: int, height: int) -> float:
    """Width over height, guarded against a zero-sized frame."""
    return width / height if height else TALLEST


def needs_fitting(width: int, height: int, *, portrait: bool = False) -> bool:
    """Whether this picture would be clamped by the app, or is lying down."""
    ratio = shell_ratio(width, height)
    if ratio < TALLEST:
        return True
    return ratio > (PORTRAIT_TARGET if portrait else WIDEST)


def fit_to_shell(
    image: bytes, *, content_type: str = "image/png", portrait: bool = False
) -> bytes:
    """Bring a picture inside the shell. Bytes unchanged if it is already there.

    `portrait` additionally requires the result to be upright, for the
    two treatments that lay garments out flat. A packshot of a shirt
    beside a pair of trousers is naturally landscape, and it was the
    only card in the feed lying on its side.

    **A landscape picture is turned upright, then padded if it
    still needs it.** On the product owner's instruction
    (2026-11-02), reaffirmed after the trade was put to them: a
    picture wider than it is tall is rotated a quarter turn so it
    becomes portrait, rather than having ground added to the top and
    bottom until it is.

    The cost is the obvious one and is worth stating plainly, because
    it is not a bug when somebody meets it: the contents turn with
    the frame. A flat-lay ends up on its side, and so does anybody
    standing in the photograph. Nothing here can know which way up
    the subject was - there is no orientation in the pixels and the
    camera's own is long gone by the time a studio edit comes back -
    so this is a rule about frames, not about subjects.

    Padding is still what happens to a picture that is merely too
    tall, and to a square: a quarter turn does nothing for either.

    Never raises. A picture that cannot be read or cannot be written
    is returned exactly as it arrived: the shape is an improvement on
    the result, not the result, and a studio shot nobody can open is
    strictly worse than one the app has to crop.
    """
    try:
        from PIL import Image, ImageFilter
    except ImportError:  # pragma: no cover - Pillow is a hard dependency
        return image

    try:
        with Image.open(io.BytesIO(image)) as opened:
            frame = opened.convert("RGB")
            width, height = frame.size
            if not width or not height or not needs_fitting(
                width, height, portrait=portrait
            ):
                return image

            # **No quarter turn. Reversed on the product owner's
            # report (2026-11-04), having been added on their
            # instruction two days earlier.**
            #
            # The trade was stated plainly when it went in - "the
            # contents turn with the frame, a flat-lay ends up on
            # its side" - and seeing it decided it: a wardrobe tile
            # and a composite figure both showed a sweatshirt lying
            # diagonally across the frame, which reads as the app
            # being broken rather than as a framing choice.
            #
            # An upright *frame* is worth having; an upright frame
            # with the garment on its side is not, because the
            # composite lays that picture onto a figure's torso and
            # a sideways top is simply wrong there. Padding to
            # `PORTRAIT_TARGET` below gives both, and 3:4 is why the
            # rotation was arguable in the first place: it asks for
            # about half the ground 9:16 would.
            #
            # The deeper fix is upstream and already in: the packshot
            # prompt asks for the garment squared to the camera, so
            # new pictures arrive upright and never reach this
            # branch at all.
            ratio = shell_ratio(width, height)
            if ratio < TALLEST:
                # Too tall. Widen it.
                target = max(width + 1, int(round(height * TALLEST)))
                canvas = _widened(Image, ImageFilter, frame, target, height)
            else:
                # Too wide and not turnable - a square under the
                # portrait rule. Heighten it, by the argument that
                # taking width off a picture takes the sides of
                # whatever is in it.
                bound = PORTRAIT_TARGET if portrait else WIDEST
                target = max(height + 1, int(round(width / bound)))
                canvas = _heightened(Image, ImageFilter, frame, width, target)

            return _encoded(canvas, content_type)
    except Exception:  # noqa: BLE001 - the shape is never worth the picture
        return image


def _encoded(frame: Any, content_type: str) -> bytes:
    """The frame as bytes, in the format it arrived as."""
    buffer = io.BytesIO()
    if "webp" in content_type:
        frame.save(buffer, format="WEBP", quality=90, method=4)
    else:
        frame.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()

def _widened(Image: Any, ImageFilter: Any, frame: Any, target: int, height: int) -> Any:
    """The picture centred on a wider ground taken from its own edges."""
    pad = target - frame.size[0]
    left_pad = pad // 2
    right_pad = pad - left_pad
    strip = max(1, int(frame.size[0] * EDGE_STRIP))

    canvas = Image.new("RGB", (target, height))
    if left_pad:
        # The leftmost strip, stretched out to the left. Blurred,
        # because a stretched strip of a textured wall repeats its
        # texture in visible bars otherwise.
        left = frame.crop((0, 0, strip, height)).resize((left_pad, height))
        canvas.paste(left.filter(ImageFilter.GaussianBlur(radius=max(1, left_pad // 8))), (0, 0))
    if right_pad:
        right = frame.crop((frame.size[0] - strip, 0, frame.size[0], height)).resize(
            (right_pad, height)
        )
        canvas.paste(
            right.filter(ImageFilter.GaussianBlur(radius=max(1, right_pad // 8))),
            (left_pad + frame.size[0], 0),
        )
    canvas.paste(frame, (left_pad, 0))
    return canvas


def _heightened(Image: Any, ImageFilter: Any, frame: Any, width: int, target: int) -> Any:
    """The same, for a picture that is too wide rather than too tall."""
    pad = target - frame.size[1]
    top_pad = pad // 2
    bottom_pad = pad - top_pad
    strip = max(1, int(frame.size[1] * EDGE_STRIP))

    canvas = Image.new("RGB", (width, target))
    if top_pad:
        top = frame.crop((0, 0, width, strip)).resize((width, top_pad))
        canvas.paste(top.filter(ImageFilter.GaussianBlur(radius=max(1, top_pad // 8))), (0, 0))
    if bottom_pad:
        bottom = frame.crop((0, frame.size[1] - strip, width, frame.size[1])).resize(
            (width, bottom_pad)
        )
        canvas.paste(
            bottom.filter(ImageFilter.GaussianBlur(radius=max(1, bottom_pad // 8))),
            (0, top_pad + frame.size[1]),
        )
    canvas.paste(frame, (0, top_pad))
    return canvas


__all__ = [
    "EDGE_STRIP",
    "measure",
    "PORTRAIT_TARGET",
    "TALLEST",
    "WIDEST",
    "fit_to_shell",
    "needs_fitting",
    "shell_ratio",
]
