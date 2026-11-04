"""The sign-in page, checked as a stylesheet rather than by eye.

Keycloak's login screen is the one surface in this product nobody
can unit-test by rendering, so it gets looked at by hand and the
same two faults keep coming back. Both are the parent theme winning
a fight our sheet did not know it was in, and both were reported by
the product owner from a screenshot:

* the fields looked like glass - PatternFly paints its edges with
  two absolutely positioned pseudo-elements, not with `border`, so
  our hairline box and its overlay stacked a pixel apart;
* the wordmark was clipped - `keycloak.v2` gives the header the
  `pf-v5-c-brand` class, which is a *logo image* component that
  sizes and crops itself.

These assert the overrides exist. They cannot prove the page looks
right, and they are not pretending to: they catch the regression
where somebody tidies the stylesheet and removes the odd-looking
declarations that are load-bearing.
"""

from __future__ import annotations


import pytest

from tests._repo import repo_root

THEME = (
    repo_root()
    / "infra"
    / "keycloak"
    / "themes"
    / "luxish"
    / "login"
    / "resources"
    / "css"
    / "luxish.css"
)


@pytest.fixture(scope="module")
def sheet() -> str:
    assert THEME.is_file(), f"the login theme has moved: {THEME}"
    return THEME.read_text(encoding="utf-8")


def test_the_fields_edge_overlays_are_turned_off(sheet: str) -> None:
    """**The glass.**

    `.pf-v5-c-form-control:before` and `:after` are `inset: 0`
    absolutely positioned boxes carrying their own borders. Setting
    `--pf-v5-c-form-control--BorderBottomColor`, which the previous
    version did, changes nothing: the overlays read `--before--` and
    `--after--` names.
    """
    assert "--pf-v5-c-form-control--before--BorderStyle: none" in sheet
    assert "--pf-v5-c-form-control--after--BorderStyle: none" in sheet


def test_the_overlays_are_also_flattened_directly(sheet: str) -> None:
    """Belt and braces, for a PatternFly upgrade that moves the
    drawing somewhere other than those variables."""
    assert "::before" in sheet and "::after" in sheet
    assert "border: 0 !important" in sheet


def test_the_wordmark_is_not_sized_like_a_logo_image(sheet: str) -> None:
    """**The clipping.**

    `pf-v5-c-brand` is PatternFly's component for a logo image: it
    takes its height from a variable and crops what overflows. A
    wordmark set in Bodoni at up to 4rem inside that box loses its
    top and its tail.
    """
    block = sheet.split("#kc-header-wrapper {", 1)[1].split("}", 1)[0]
    assert "height: auto" in block
    assert "max-height: none" in block
    assert "overflow: visible" in block


def test_the_wordmark_stays_visible_against_the_paper(sheet: str) -> None:
    """The oldest fault here, kept because it is a one-character
    deletion away from returning: the parent sets a near-white
    colour with `!important`, correct for a dark PatternFly header
    band and invisible on this theme's cream."""
    block = sheet.split("#kc-header-wrapper {", 1)[1].split("}", 1)[0]
    assert "color: var(--luxish-ink) !important" in block


def test_the_header_does_not_clip_its_own_contents(sheet: str) -> None:
    block = sheet.split("#kc-header {", 1)[1].split("}", 1)[0]
    assert "overflow: visible" in block


def test_the_wordmark_is_not_pushed_beside_the_card(sheet: str) -> None:
    """**The third way the header went wrong, and the widest one.**

    PatternFly's login container is a grid, and at 1200px and above
    it becomes

        grid-template-areas: "main header" "main footer" "main .";

    which takes the name out of the space above the card and puts it
    in a second column next to it. Right for a small logo and a
    language picker; wrong for a wordmark set in Bodoni at 4rem,
    which wraps in a narrow column and collides with the card.

    Everything else in this sheet assumes a masthead above the card.
    This is what makes that true at every width rather than only
    below 1200px, where it was true by accident.
    """
    assert "grid-template-areas: 'header' 'main' 'footer'" in sheet
