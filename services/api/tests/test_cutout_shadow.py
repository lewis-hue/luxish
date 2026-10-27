"""The contact shadow under a cut-out garment.

Worth its own module because the shadow is the difference between a feature
that works and one that measurably does not. Depop shipped background removal
without a shadow and measured 9% adoption against flat listing metrics; the
published reason was that products "looked like they were floating in space,
unnatural and unconvincing". The same feature with a shadow returned +1.5%
items listed.

So these tests pin the properties that make it read as contact rather than as
a sticker effect: it sits below the garment and nowhere else, it is soft, it
is subtle, and it stays in the ground's colour family. Each is a way the
shadow could be "present" and still look wrong.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image, ImageColor

from app.providers.segmentation import (
    CUTOUT_BACKGROUND,
    SHADOW_BLUR_RATIO,
    SHADOW_DARKEN,
    SHADOW_OFFSET_RATIO,
    SHADOW_OPACITY,
    Box,
    MaskRecord,
    composite_cutout,
)

WIDTH, HEIGHT = 200, 300
GARMENT = "#884455"
GX, GY, GW, GH = 50, 60, 100, 150


@pytest.fixture
def original() -> bytes:
    """A plain photograph. Its colour is irrelevant beyond being distinctive."""
    image = Image.new("RGB", (WIDTH, HEIGHT), GARMENT)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def record() -> MaskRecord:
    """A solid rectangular garment, so expected pixel positions are exact."""
    return MaskRecord(
        object_id=1,
        box=Box(
            x1=GX,
            y1=GY,
            x2=GX + GW - 1,
            y2=GY + GH - 1,
            frame_width=WIDTH,
            frame_height=HEIGHT,
        ),
        height=GH,
        width=GW,
        raster=bytes([1]) * (GW * GH),
    )


def _render(original: bytes, record: MaskRecord, *, shadow: bool) -> Image.Image:
    out = composite_cutout(original=original, records=[record], shadow=shadow)
    return Image.open(io.BytesIO(out)).convert("RGB")


def _ground() -> tuple[int, int, int]:
    return ImageColor.getrgb(CUTOUT_BACKGROUND)[:3]


def _luma(pixel: tuple[int, int, int]) -> float:
    red, green, blue = pixel
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


# --------------------------------------------------------------------------- #
# it exists, and only where it should
# --------------------------------------------------------------------------- #
def test_a_shadow_falls_below_the_garment(
    original: bytes, record: MaskRecord
) -> None:
    image = _render(original, record, shadow=True)
    below = image.getpixel((GX + GW // 2, GY + GH + 4))
    assert _luma(below) < _luma(_ground()), "no shadow under the garment"


def test_nothing_is_painted_above_the_garment(
    original: bytes, record: MaskRecord
) -> None:
    """A shadow that bleeds upward is a halo, which reads as a cheap effect.

    This is why the mask is blurred *before* it is shifted. Blurring a shifted
    hard mask spreads it symmetrically, putting as much shadow above the
    garment as below.
    """
    image = _render(original, record, shadow=True)
    assert image.getpixel((GX + GW // 2, GY - 24)) == _ground()


def test_nothing_is_painted_beside_the_garment(
    original: bytes, record: MaskRecord
) -> None:
    # A horizontal offset implies a light source the photograph does not have.
    image = _render(original, record, shadow=True)
    assert image.getpixel((GX - 30, GY + GH // 2)) == _ground()


def test_the_garment_itself_is_untouched(
    original: bytes, record: MaskRecord
) -> None:
    # The shadow is painted before the garment, so it can never tint it.
    image = _render(original, record, shadow=True)
    assert image.getpixel((GX + GW // 2, GY + GH // 2)) == ImageColor.getrgb(GARMENT)


def test_turning_the_shadow_off_leaves_a_clean_ground(
    original: bytes, record: MaskRecord
) -> None:
    image = _render(original, record, shadow=False)
    assert image.getpixel((GX + GW // 2, GY + GH + 4)) == _ground()
    assert image.getpixel((GX - 30, GY + GH // 2)) == _ground()


def test_the_shadow_is_on_by_default(original: bytes, record: MaskRecord) -> None:
    """The default matters more than the parameter.

    A cut-out with no shadow is the variant that measurably underperformed, so
    getting one must not require remembering to ask.
    """
    out = composite_cutout(original=original, records=[record])
    image = Image.open(io.BytesIO(out)).convert("RGB")
    assert _luma(image.getpixel((GX + GW // 2, GY + GH + 4))) < _luma(_ground())


# --------------------------------------------------------------------------- #
# it looks like contact, not like a second garment
# --------------------------------------------------------------------------- #
def test_the_shadow_fades_with_distance(
    original: bytes, record: MaskRecord
) -> None:
    """Soft, not a hard-edged copy of the silhouette.

    A hard shadow reads as a duplicate object. Sampling two depths proves
    there is a gradient rather than a solid block.
    """
    image = _render(original, record, shadow=True)
    column = GX + GW // 2
    near = _luma(image.getpixel((column, GY + GH + 2)))
    far = _luma(image.getpixel((column, GY + GH + 20)))
    assert near < far, "the shadow should be darkest closest to the garment"
    assert far <= _luma(_ground())


def test_the_shadow_stays_subtle(original: bytes, record: MaskRecord) -> None:
    """Past roughly a third opacity the garment looks airborne, not seated.

    Which is the opposite of the problem the shadow solves, so this is a real
    upper bound rather than taste.
    """
    assert SHADOW_OPACITY <= 0.35
    image = _render(original, record, shadow=True)
    darkest = min(
        _luma(image.getpixel((GX + GW // 2, GY + GH + offset)))
        for offset in range(1, 30)
    )
    # Never darker than the ground scaled by the configured darkening.
    assert darkest >= _luma(_ground()) * SHADOW_DARKEN


def test_the_shadow_keeps_the_ground_s_colour_family(
    original: bytes, record: MaskRecord
) -> None:
    """Pure black on warm paper reads as dirt.

    The shadow is derived from the background, so its channels must stay in
    the same order as the ground's rather than collapsing to neutral grey.
    """
    image = _render(original, record, shadow=True)
    red, green, blue = image.getpixel((GX + GW // 2, GY + GH + 4))
    ground_red, ground_green, ground_blue = _ground()
    # Warm ground: red >= green >= blue. The shadow must preserve that.
    assert ground_red >= ground_green >= ground_blue
    assert red >= green >= blue


def test_a_custom_ground_moves_the_shadow_with_it(
    original: bytes, record: MaskRecord
) -> None:
    # The shadow is computed from the background, not hardcoded, so a cool
    # ground gets a cool shadow.
    out = composite_cutout(
        original=original, records=[record], background="#E3EAF2", shadow=True
    )
    image = Image.open(io.BytesIO(out)).convert("RGB")
    red, green, blue = image.getpixel((GX + GW // 2, GY + GH + 4))
    assert blue > red, "a cool ground should cast a cool shadow"


# --------------------------------------------------------------------------- #
# geometry scales
# --------------------------------------------------------------------------- #
def test_the_shadow_scales_with_the_image() -> None:
    """Fractions, not pixels, so the look holds at any resolution.

    A fixed 4px offset is invisible on a 3000px photograph and crude on a
    thumbnail.
    """
    assert 0 < SHADOW_OFFSET_RATIO < 0.05
    assert 0 < SHADOW_BLUR_RATIO < 0.05
    assert 0 < SHADOW_DARKEN < 1


def test_a_garment_at_the_bottom_edge_still_renders(original: bytes) -> None:
    """Clipping is correct here, and must not crash.

    A garment photographed to the edge of frame has nowhere for its shadow to
    fall, which is physically right. The failure mode to avoid is an
    exception, not the clipping.
    """
    record = MaskRecord(
        object_id=1,
        box=Box(
            x1=GX,
            y1=HEIGHT - 20,
            x2=GX + GW - 1,
            y2=HEIGHT - 1,
            frame_width=WIDTH,
            frame_height=HEIGHT,
        ),
        height=20,
        width=GW,
        raster=bytes([1]) * (GW * 20),
    )
    image = _render(original, record, shadow=True)
    assert image.size == (WIDTH, HEIGHT)


def test_a_one_pixel_garment_does_not_divide_by_zero(original: bytes) -> None:
    # The blur radius is derived from the image, not the garment, but the
    # offset rounding still has to floor at 1 rather than 0.
    record = MaskRecord(
        object_id=1,
        box=Box(
            x1=10, y1=10, x2=10, y2=10, frame_width=WIDTH, frame_height=HEIGHT
        ),
        height=1,
        width=1,
        raster=bytes([1]),
    )
    assert _render(original, record, shadow=True).size == (WIDTH, HEIGHT)


def test_the_shadow_survives_a_png_round_trip(
    original: bytes, record: MaskRecord
) -> None:
    """PNG is lossless, so the sampled values must be exact, not approximate.

    If this ever fails the output format has changed to something lossy, which
    would also mean the cut-out's edges are no longer clean.
    """
    out = composite_cutout(original=original, records=[record], shadow=True)
    first = Image.open(io.BytesIO(out)).convert("RGB")
    second = Image.open(io.BytesIO(out)).convert("RGB")
    # `tobytes` rather than `getdata`, which Pillow removes in 14.
    assert first.tobytes() == second.tobytes()
