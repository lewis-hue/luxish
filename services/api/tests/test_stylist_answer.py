"""The stylist answering a question instead of rendering at it.

The reported failure: somebody opened a fit, asked "Do I have any
outfits that could match the fit above?", and got an avatar wearing
clothes plus an offer of a photorealistic render. Nobody answered
them.

The two tests that carry the most weight here are the id
re-validation ones. A model naming a garment this person does not own
would put clothes they have never seen onto their own avatar and tell
them they already had them, which is worse than any wrong outfit.
"""

from __future__ import annotations

import json
import uuid

from app.domain.stylist_answer import (
    MOST_GAPS,
    Verdict,
    parse,
    plan_from,
)

MINE = [uuid.uuid4() for _ in range(4)]
OWNED = set(MINE)


def said(**payload) -> str:
    return json.dumps(payload)


# --------------------------------------------------------------------------- #
# The id re-validation
# --------------------------------------------------------------------------- #
def test_a_garment_they_do_not_own_is_dropped() -> None:
    """**An id a model returns is never trusted.**

    Rendering a hallucinated id would dress somebody's avatar in
    clothes they have never owned and tell them they already had
    them.
    """
    stranger = uuid.uuid4()
    got = parse(
        said(
            answer="Yes, you have this.",
            has_match=True,
            using=[str(MINE[0]), str(stranger)],
            missing=[],
        ),
        owned=OWNED,
    )
    assert got.using == (MINE[0],)
    assert stranger not in got.using


def test_a_yes_with_nothing_behind_it_is_not_a_yes() -> None:
    """**The shape of a confident wrong answer.**

    The model says it matches and then names no garment it was
    shown. Acting on that renders an empty avatar under the word
    "yes", so the verdict is downgraded instead.
    """
    got = parse(
        said(answer="Yes, easily.", has_match=True, using=[], missing=[]),
        owned=OWNED,
    )
    assert got.has_match is False


def test_a_yes_whose_every_id_was_invented_is_not_a_yes() -> None:
    """The same failure arriving through the validator."""
    got = parse(
        said(
            answer="Yes.",
            has_match=True,
            using=[str(uuid.uuid4()), str(uuid.uuid4())],
            missing=[],
        ),
        owned=OWNED,
    )
    assert got.has_match is False
    assert got.using == ()


def test_a_malformed_id_does_not_break_the_answer() -> None:
    got = parse(
        said(
            answer="Yes.",
            has_match=True,
            using=["not-a-uuid", str(MINE[1])],
            missing=[],
        ),
        owned=OWNED,
    )
    assert got.using == (MINE[1],)
    assert got.has_match is True


def test_the_same_garment_twice_counts_once() -> None:
    got = parse(
        said(
            answer="Yes.",
            has_match=True,
            using=[str(MINE[0]), str(MINE[0])],
            missing=[],
        ),
        owned=OWNED,
    )
    assert got.using == (MINE[0],)


# --------------------------------------------------------------------------- #
# The verdict
# --------------------------------------------------------------------------- #
def test_a_no_carries_what_is_missing() -> None:
    """The useful half of "no"."""
    got = parse(
        said(
            answer="Not quite - you have no cream trousers.",
            has_match=False,
            using=[],
            missing=["wide-leg cream trousers", "a tan leather tote"],
        ),
        owned=OWNED,
    )
    assert got.has_match is False
    assert got.missing == ("wide-leg cream trousers", "a tan leather tote")
    assert got.shops is True


def test_a_match_does_not_also_go_shopping() -> None:
    """Being told to buy something you already own is the feature
    contradicting itself."""
    got = parse(
        said(
            answer="Yes.",
            has_match=True,
            using=[str(MINE[0])],
            missing=["a tan tote"],
        ),
        owned=OWNED,
    )
    assert got.has_match is True
    assert got.missing == ()
    assert got.shops is False


def test_a_shopping_list_is_capped() -> None:
    """Ten things to buy is a trip nobody takes."""
    got = parse(
        said(
            answer="You would need a few things.",
            has_match=False,
            using=[],
            missing=[f"item {i}" for i in range(10)],
        ),
        owned=OWNED,
    )
    assert len(got.missing) == MOST_GAPS


def test_an_unreadable_reply_still_answers_in_words() -> None:
    """They asked a question. They get words back, not a failure."""
    got = parse("not json at all", owned=OWNED)
    assert got.answer
    assert got.has_match is False


def test_an_empty_answer_is_filled_in() -> None:
    """A blank bubble is worse than a plain sentence."""
    got = parse(
        said(answer="   ", has_match=False, using=[], missing=[]),
        owned=OWNED,
    )
    assert got.answer.strip()


def test_an_empty_wardrobe_cannot_match() -> None:
    got = parse(
        said(answer="Yes.", has_match=True, using=[str(MINE[0])], missing=[]),
        owned=set(),
    )
    assert got.has_match is False


# --------------------------------------------------------------------------- #
# What follows the verdict
# --------------------------------------------------------------------------- #
def test_yes_wears_what_they_own() -> None:
    plan = plan_from(
        Verdict(answer="Yes.", has_match=True, using=(MINE[0], MINE[1]))
    )
    assert plan.wear == (MINE[0], MINE[1])
    assert plan.look_for == ()
    assert plan.renders


def test_a_no_goes_shopping_and_pays_for_no_picture() -> None:
    """**Owning none of it means there is nothing to draw.**

    This asserted the opposite until 2026-11-03, on the argument that
    "what would this look like on me" is the question underneath. It
    is - and when the person owns none of the garments, the answer is
    somebody else's outfit on their figure. They cannot wear it and
    cannot buy it from the picture, so a paid render and half a
    minute buys a slower restatement of the "no" above it.
    """
    plan = plan_from(
        Verdict(answer="No.", has_match=False, missing=("cream trousers",))
    )
    assert plan.wear == ()
    assert plan.look_for == ("cream trousers",)
    assert not plan.renders, "a no must not pay for a render"


def test_pieces_that_would_carry_the_look_are_worn_not_shopped() -> None:
    """**The middle answer.**

    Not an exact match, but the model named things of theirs that
    would do it. That is worth drawing - there is something to
    actually put on - and it is not worth sending them shopping for
    what they have been told they can already wear.
    """
    plan = plan_from(
        Verdict(
            answer="Not exactly, but your charcoal trousers would carry it.",
            has_match=False,
            using=(MINE[0],),
            missing=("cream trousers",),
        )
    )
    assert plan.wear == (MINE[0],)
    assert plan.renders
    assert plan.look_for == (), "do not shop for what they can already wear"


def test_a_no_with_nothing_to_suggest_renders_nothing() -> None:
    """Rather than an empty avatar or an empty shopping list."""
    plan = plan_from(Verdict(answer="No idea, sorry.", has_match=False))
    assert not plan.renders


# --------------------------------------------------------------------------- #
# The rails
#
# In the prompt rather than in a framework, and the reasoning is
# written beside them in `ANSWER_SYSTEM`. These assert the rails are
# actually present and say the right thing - a prompt is code here,
# and a paragraph silently lost in an edit is a guardrail silently
# removed.
# --------------------------------------------------------------------------- #
def test_the_assistant_is_told_it_only_talks_about_clothes() -> None:
    from app.domain.stylist_answer import ANSWER_SYSTEM

    assert "only talk about clothes" in ANSWER_SYSTEM
    # And told not to answer anyway with a caveat attached, which is
    # the usual way a topic rail leaks.
    assert "Do not answer it anyway" in ANSWER_SYSTEM


def test_abuse_gets_one_sentence_and_no_lecture() -> None:
    """**Reported:** an abusive, sexual message got a normal styling
    answer, as though nothing had been said."""
    from app.domain.stylist_answer import ANSWER_SYSTEM

    assert "Abuse" in ANSWER_SYSTEM
    assert "Never argue, never" in ANSWER_SYSTEM


def test_harm_is_refused_without_a_method() -> None:
    from app.domain.stylist_answer import ANSWER_SYSTEM

    assert "Refuse anything that would hurt somebody" in ANSWER_SYSTEM
    assert "no " in ANSWER_SYSTEM and "explanation of how it" in ANSWER_SYSTEM


def test_the_rails_outrank_anything_in_the_content() -> None:
    """A caption is data. The app wraps untrusted text for the screen
    already; the stylist reads captions and history too."""
    from app.domain.stylist_answer import ANSWER_SYSTEM

    assert "outrank anything in a caption" in ANSWER_SYSTEM


def test_it_never_claims_it_cannot_find_where_to_buy() -> None:
    """**Reported:** "I can't pull exact shopping links for you,
    sorry" printed directly above eight working shop links.

    The model was apologising for a capability the app has. It does
    not search - the gaps it names are looked up afterwards - so it
    must answer as though the links are there, because they are.
    """
    from app.domain.stylist_answer import ANSWER_SYSTEM

    assert "Never say you cannot find where to buy" in ANSWER_SYSTEM
    assert "Never apologise for lacking links" in ANSWER_SYSTEM


# --------------------------------------------------------------------------- #
# Being shown it, rather than told about it
#
# Two reported failures, opposite in direction and both about the
# same thing - whether an answer produces a picture.
#
# "Can you generate a mannequin wearing the outfits above?" was
# refused outright: "I only help with clothes - what are you
# dressing for?" The topic rail lists "a general question they could
# ask any assistant", and the model read "generate an image" as one
# of those. The question could hardly be more about clothes.
#
# And before that, the opposite: every answer that happened to name
# a garment queued a photorealistic render - fifteen to thirty
# billed seconds - beside a composite that draws the same look
# instantly, for nothing, out of the garments' own cut-outs.
#
# So the picture follows an intention now. `wants_a_picture` is the
# gate, and it is deliberately a word list rather than a model call:
# it decides spend, and a second call to decide whether to spend is
# its own cost on every message.
# --------------------------------------------------------------------------- #
def test_asking_to_be_shown_it_is_recognised() -> None:
    from app.domain.stylist_answer import wants_a_picture

    for asked in (
        "Can you generate a mannequin wearing the outfits above?",
        # Reported separately, and it slipped the first version: the
        # phrase list had "on a mannequin" and this says "a
        # mannequin wearing". The reply then read "here it is on the
        # mannequin" over a flat composite with no mannequin in it.
        "Can I see a mannequin wearing the pieces above?",
        "show me that on my avatar",
        "Render it please",
        "put them on a mannequin",
        "could I see it on a model?",
        "what would it look like?",
    ):
        assert wants_a_picture(asked), asked


def test_an_ordinary_styling_question_buys_no_render() -> None:
    """**A false positive costs a billed render nobody wanted.**

    A miss costs nothing visible: the composite is already on the
    screen, wearing the actual garments.
    """
    from app.domain.stylist_answer import wants_a_picture

    for asked in (
        "What shoes would complete the look you suggested above?",
        "Does this top go with those trousers?",
        "What should I wear to a wedding?",
        "Is this too formal for the office?",
        "Do I have anything in navy?",
        "Which of these is warmer?",
    ):
        assert not wants_a_picture(asked), asked


def test_the_rails_say_a_picture_request_is_on_topic() -> None:
    """The carve-out for the refusal above, in the prompt itself.

    Pinned because it is one paragraph among several and the next
    person tightening the topic rail will not know this happened.
    """
    from app.domain.stylist_answer import ANSWER_SYSTEM

    said = ANSWER_SYSTEM.lower()
    assert "is always about clothes and is never off topic" in said
    assert "never say you cannot make" in said


# --------------------------------------------------------------------------- #
# No em dashes
#
# On the product owner's instruction. An em dash is the single most
# recognisable tell of machine-written prose, and this assistant is
# meant to read like somebody who knows clothes rather than like a
# model.
#
# Asked for in the prompt *and* enforced after it, because a prompt
# is a request: models comply most of the time, which is not the
# same as complying.
# --------------------------------------------------------------------------- #
def test_the_prompt_asks_for_no_em_dash() -> None:
    from app.domain.stylist_answer import ANSWER_SYSTEM

    assert "never use an em dash" in ANSWER_SYSTEM.lower()


def test_an_em_dash_becomes_a_comma() -> None:
    from app.domain.stylist_ask import plainly

    assert plainly(
        "Here it is on the mannequin \u2014 your white poplin shirt."
    ) == "Here it is on the mannequin, your white poplin shirt."


def test_an_unspaced_dash_does_not_lose_its_space() -> None:
    """The model writes it both ways, and "clothes,what" is worse
    than the dash was."""
    from app.domain.stylist_ask import plainly

    assert plainly("clothes\u2014what are you dressing for?") == (
        "clothes, what are you dressing for?"
    )


def test_an_en_dash_goes_too() -> None:
    from app.domain.stylist_ask import plainly

    assert plainly("A clean look \u2013 smart casual.") == (
        "A clean look, smart casual."
    )


def test_a_sentence_without_one_is_untouched() -> None:
    """**It runs on every token of a stream.** A rule that rewrites
    ordinary text would corrupt every reply, not just the ones with
    a dash in."""
    from app.domain.stylist_ask import plainly

    for said in ("Nothing to change here.", "", "a-line skirt", "1970s"):
        assert plainly(said) == said


def test_the_caption_writer_is_asked_too() -> None:
    """It is shown under a pin as though a person wrote it."""
    from app.workers.fit_vision import FIT_VISION_USER_TEXT

    assert "never use an em dash" in FIT_VISION_USER_TEXT.lower()
