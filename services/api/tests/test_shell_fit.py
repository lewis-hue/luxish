"""A generated picture is the shape the app draws it in.

The app shows a cover at its own shape between 9:16 and 1.45 and
clamps anything outside that, which means cropping it. A photograph
off a phone is almost always inside those bounds. A picture the
studio made is not: an edit returns the shape it was handed, so a
full-length figure shot at about 0.47 comes back at 0.47 and the app
crops the shoes off it.
"""

from __future__ import annotations

import io

import pytest

from tests._repo import repo_root

from app.workers.shell_fit import (
    PORTRAIT_TARGET,
    TALLEST,
    WIDEST,
    fit_to_shell,
    needs_fitting,
    shell_ratio,
)


def png(width: int, height: int, colour: tuple[int, int, int] = (200, 180, 160)) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def shape_of(image: bytes) -> float:
    from PIL import Image

    with Image.open(io.BytesIO(image)) as opened:
        return opened.size[0] / opened.size[1]


def size_of(image: bytes) -> tuple[int, int]:
    from PIL import Image

    with Image.open(io.BytesIO(image)) as opened:
        return opened.size


# --------------------------------------------------------------------------- #
# the bounds, which have to be the app's
# --------------------------------------------------------------------------- #
def test_the_bounds_match_the_ones_the_app_clamps_to() -> None:
    """Two numbers in two languages, and only one of them is enforced.

    The server padding to one ratio while the client clamps to another
    is the bug this file exists to prevent, reintroduced from the
    other side: every generated picture would be padded *and* then
    cropped.
    """
    shape_ts = repo_root() / "apps" / "mobile" / "src" / "features" / "feed" / "shape.ts"
    if not shape_ts.is_file():  # pragma: no cover - API checked alone
        pytest.skip("mobile app not present in this checkout")

    source = shape_ts.read_text(encoding="utf-8")
    assert "tallest: 9 / 16" in source, source
    assert f"widest: {WIDEST}" in source, source
    assert TALLEST == 9 / 16


# --------------------------------------------------------------------------- #
# what gets touched
# --------------------------------------------------------------------------- #
def test_a_picture_already_in_the_shell_is_returned_untouched() -> None:
    """Byte-identical, not merely the same shape.

    Re-encoding every studio shot to change nothing would cost quality
    and size on the overwhelming majority of them.
    """
    original = png(900, 1200)  # 0.75
    assert needs_fitting(900, 1200) is False
    assert fit_to_shell(original) is original


def test_a_full_length_figure_is_widened_to_the_shell() -> None:
    # The picture that prompted this: about 0.47, taller than an
    # upright phone screen, so the app cropped it.
    tall = png(470, 1000)
    assert needs_fitting(470, 1000) is True

    fitted = fit_to_shell(tall)
    assert shape_of(fitted) == pytest.approx(TALLEST, abs=0.01)


def test_widening_keeps_every_pixel_of_the_original() -> None:
    """The argument for widening rather than cropping.

    Turning 0.47 into 0.5625 means either taking height off the top
    and bottom or adding width to the sides. The first removes the
    head or the shoes, which in a fashion app is the subject.
    """
    width, height = 470, 1000
    fitted = fit_to_shell(png(width, height))
    out_width, out_height = size_of(fitted)

    assert out_height == height, "no height was taken"
    assert out_width > width, "it was made wider instead"


def test_the_original_sits_centred_in_what_was_added() -> None:
    from PIL import Image

    width, height = 470, 1000
    subject = (10, 200, 40)
    fitted = fit_to_shell(png(width, height, subject))
    out_width, _ = size_of(fitted)

    with Image.open(io.BytesIO(fitted)) as opened:
        frame = opened.convert("RGB")
        middle = frame.getpixel((out_width // 2, height // 2))

    # The subject is still the subject, in the middle of the frame.
    assert middle == pytest.approx(subject, abs=4)


def test_a_panorama_is_heightened_by_the_same_argument() -> None:
    wide = png(2000, 500)  # 4.0, past the wide bound
    assert needs_fitting(2000, 500) is True

    fitted = fit_to_shell(wide)
    assert shape_of(fitted) == pytest.approx(WIDEST, abs=0.02)
    out_width, out_height = size_of(fitted)
    assert out_width == 2000, "no width was taken"
    assert out_height > 500


# --------------------------------------------------------------------------- #
# it is never worth the picture
# --------------------------------------------------------------------------- #
def test_something_that_is_not_an_image_comes_back_as_it_went_in() -> None:
    """The shape is an improvement on the result, not the result.

    A studio shot nobody can open is strictly worse than one the app
    has to crop, so nothing here raises.
    """
    rubbish = b"not a picture at all"
    assert fit_to_shell(rubbish) == rubbish


def test_an_empty_body_is_returned_rather_than_raising() -> None:
    assert fit_to_shell(b"") == b""


def test_a_webp_stays_a_webp() -> None:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (470, 1000), (120, 120, 120)).save(buffer, format="WEBP")
    fitted = fit_to_shell(buffer.getvalue(), content_type="image/webp")

    with Image.open(io.BytesIO(fitted)) as opened:
        assert opened.format == "WEBP"


def test_shell_ratio_survives_a_zero_sided_frame() -> None:
    # Guarded because this divides, and a corrupt header reporting a
    # zero height would otherwise take the whole job down.
    assert shell_ratio(100, 0) == TALLEST


# --------------------------------------------------------------------------- #
# upright, for the things that are photographed lying flat
# --------------------------------------------------------------------------- #
def test_a_landscape_packshot_is_stood_upright() -> None:
    """A shirt beside a pair of trousers is a wide arrangement.

    It came back landscape and was the only card in the feed lying on
    its side.
    """
    flat_lay = png(876, 600)  # 1.46
    fitted = fit_to_shell(flat_lay, portrait=True)
    assert shape_of(fitted) < 1, "it is upright now"


def test_a_landscape_picture_is_padded_and_never_turned() -> None:
    """**The quarter turn is gone, and this is the test that was it.**

    It went in on the product owner's instruction (2026-11-02) after
    the trade was put to them: a turn keeps every pixel, and the
    contents turn with the frame. They saw the consequence two days
    later - a sweatshirt lying diagonally across its wardrobe tile,
    and the same picture laid sideways onto a figure's torso by the
    composite - and called it what it looks like, which is broken.

    So an upright frame is still required and it is reached by
    adding ground. The garment stays the way up it was photographed,
    which is the only way up the composite can use.
    """
    width, height = 876, 600
    fitted = fit_to_shell(png(width, height), portrait=True)
    out_width, out_height = size_of(fitted)

    assert out_width == width, "no width was taken, and none was turned away"
    assert out_height > height, "height was added instead"
    assert shape_of(fitted) < 1, "upright, which was always the requirement"


def test_a_panorama_is_padded_to_upright_too() -> None:
    """The extreme case, where padding is most expensive.

    A 4:1 panorama needs a great deal of ground to stand up, and
    gets it: the rule is about the result, not about how much work
    it is. In practice nothing reaches here - the packshot prompt
    asks for the garment squared to the camera - and a garment on
    its side would be wrong at any aspect ratio.
    """
    fitted = fit_to_shell(png(2000, 500), portrait=True)
    assert shape_of(fitted) < 1, "upright"
    assert shape_of(fitted) == pytest.approx(PORTRAIT_TARGET, abs=0.01)


def test_a_square_is_padded_because_turning_it_does_nothing() -> None:
    # A quarter turn leaves a square exactly as it was, so the only
    # way to make one upright is to add height.
    fitted = fit_to_shell(png(800, 800), portrait=True)
    out_width, out_height = size_of(fitted)
    assert out_width == 800, "no width was taken"
    assert out_height > 800, "height was added"
    assert shape_of(fitted) < 1


def test_an_already_upright_picture_is_left_alone_in_portrait_mode() -> None:
    # Padding a picture that needs nothing costs quality and size.
    upright = png(600, 900)  # 0.667
    assert needs_fitting(600, 900, portrait=True) is False
    assert fit_to_shell(upright, portrait=True) is upright


def test_portrait_mode_still_widens_something_far_too_tall() -> None:
    # A cut-out pair of trousers is very tall and narrow. Upright is
    # not the only rule; the shell's floor still applies.
    trousers = png(300, 1200)  # 0.25
    fitted = fit_to_shell(trousers, portrait=True)
    assert shape_of(fitted) == pytest.approx(TALLEST, abs=0.01)


def test_a_square_counts_as_lying_down_when_upright_is_required() -> None:
    # 1.0 is not portrait. A wardrobe of square tiles beside upright
    # ones is the inconsistency this exists to remove.
    assert needs_fitting(800, 800, portrait=True) is True


def test_only_the_flat_lay_treatments_ask_for_upright() -> None:
    """A model shot and a scene already come back upright.

    Forcing those would pad a picture that needs nothing.
    """
    from app.domain.garment_studio import LAID_OUT_FLAT

    assert LAID_OUT_FLAT == frozenset({"packshot", "cutout"})


def test_both_flat_lay_prompts_ask_the_model_to_compose_upright() -> None:
    """Asked for, not only imposed afterwards.

    Told the frame is upright, the model stacks the pieces instead of
    putting them side by side - a better picture than the same
    landscape photograph padded out.
    """
    from app.workers.garment_studio import treatment_by_id

    for treatment_id in ("packshot", "cutout"):
        treatment = treatment_by_id(treatment_id)
        assert treatment is not None
        assert "upright portrait" in treatment.prompt, treatment_id
        # And told not to solve it the way that makes things sideways.
        assert "never rotate" in treatment.prompt.lower(), treatment_id


# --------------------------------------------------------------------------- #
# the size, which is what stops the card moving
# --------------------------------------------------------------------------- #
def test_a_picture_reports_its_size() -> None:
    from app.workers.shell_fit import measure

    assert measure(png(470, 1000)) == (470, 1000)


def test_the_size_reported_is_the_one_after_fitting() -> None:
    """The stored number has to describe the stored bytes.

    Recording the shape the picture arrived at and then widening it
    would lay the tile out at one ratio and fill it with another,
    which is the jump this was supposed to remove.
    """
    from app.workers.shell_fit import measure

    fitted = fit_to_shell(png(470, 1000))
    assert measure(fitted) == size_of(fitted)
    assert measure(fitted) != (470, 1000)


def test_measuring_something_unreadable_answers_none() -> None:
    # Null is what the column already means: a client measures those
    # on load, as it did for all of them before.
    from app.workers.shell_fit import measure

    assert measure(b"not a picture") is None
    assert measure(b"") is None
