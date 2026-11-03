"""The community guidelines, and what enforces them.

One list is the authority for four things: the screen, the report form,
the words an author is given, and the page people can read. The tests
that matter are the ones that would let those drift apart, and the ones
that decide whether the fast path is safe.

**The fast path may only ever be right.** It refuses without asking a
model, so a false positive is a comment nobody can post and nobody can
appeal. It is allowed to miss things; it is not allowed to be wrong.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.domain import guidelines as rules

pytestmark = pytest.mark.anyio


# --------------------------------------------------------------------------- #
# the list itself
# --------------------------------------------------------------------------- #
def test_every_rule_has_an_id_a_title_and_words_for_its_author() -> None:
    seen: set[str] = set()
    for rule in rules.GUIDELINES:
        assert rule.id and rule.id not in seen, rule.id
        seen.add(rule.id)
        assert rule.title
        assert rule.body
        # The sentence an author is shown. Without it a hold is a state
        # with no explanation.
        assert rule.held_note


def test_held_notes_state_what_happened_rather_than_judging_the_person() -> None:
    """A hold explains the content. It does not characterise its author."""
    for rule in rules.GUIDELINES:
        said = rule.held_note.lower()
        assert said.startswith("this"), rule.id
        for judgement in (" you are", " you're", "stupid", "bad person"):
            assert judgement not in said, rule.id


def test_the_prompt_lists_every_rule_the_screen_may_answer_with() -> None:
    """The screen answers with an id, so every id it may use has to be
    in front of it. A rule the model was never shown is a rule it
    cannot cite.

    `screened` is the exception and the only one: a rule withdrawn
    from the screen is deliberately absent, and
    `test_every_rule_the_screen_can_answer_with_is_one_it_was_given`
    holds the two in step.
    """
    built = rules.for_prompt()
    for rule in rules.GUIDELINES:
        if not rule.screened:
            continue
        assert rule.id in built
        assert rule.title in built


def test_reportable_is_a_subset_and_excludes_what_nobody_can_judge() -> None:
    ids = {rule.id for rule in rules.REPORTABLE}
    assert ids <= set(rules.GUIDELINE_IDS)
    # Nobody outside can report "this reads as an instruction to the
    # software", and a form full of options nobody picks is a form
    # nobody reads.
    assert "no_prompt_injection" not in ids
    assert "about_clothes" not in ids
    assert "no_harassment" in ids


# --------------------------------------------------------------------------- #
# the fast path
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "said",
    [
        "call me on 0712345678",
        "my number is +254 712 345 678",
        "email me at hello@example.com",
        "check www.myshop.com",
        "https://example.com/thing",
        "find it at mystore.shop/x",
        "dm me",
        "WhatsApp me",
    ],
)
def test_the_unambiguous_cases_are_caught(said: str) -> None:
    assert rules.obvious_violation(said) is not None, said


@pytest.mark.parametrize(
    "said",
    [
        "the colour on this is lovely",
        "size 12 and it cost 4500",
        "I wore this in 2024",
        "@someone this is great",
        "where is the coat from",
        "3 of these in my wardrobe",
        "love it",
        "",
        "   ",
        "the fit is 10/10",
    ],
)
def test_ordinary_remarks_are_never_caught(said: str) -> None:
    """The whole value of this path is that it is never wrong in this
    direction. A false positive is a comment nobody can post and
    nobody can appeal."""
    assert rules.obvious_violation(said) is None, said


def test_a_caught_phrase_names_the_rule_it_broke() -> None:
    assert rules.obvious_violation("call me on 0712345678").id == (
        "no_contact_details"
    )
    assert rules.obvious_violation("www.shop.com").id == "no_spam"


def test_held_note_falls_back_rather_than_returning_nothing() -> None:
    assert rules.held_note("no_hate") == rules.by_id("no_hate").held_note
    assert rules.held_note("not_a_rule")
    assert rules.held_note("not_a_rule", "because") == "because"


# --------------------------------------------------------------------------- #
# what the screen does with a rule
# --------------------------------------------------------------------------- #
def test_the_screen_answers_in_the_guidelines_own_words() -> None:
    """A reason written fresh each time varies between two identical
    breaches, which reads as arbitrary. The rule's sentence does not."""
    from app.workers.screen import MetaPostScreener

    allowed, reason = MetaPostScreener._parse(
        '{"allowed": false, "rule": "no_hate", "reason": "something vaguer"}'
    )
    assert not allowed
    assert reason == rules.by_id("no_hate").held_note


def test_a_verdict_citing_no_rule_keeps_the_models_sentence() -> None:
    from app.workers.screen import MetaPostScreener

    allowed, reason = MetaPostScreener._parse(
        '{"allowed": false, "rule": "", "reason": "Something specific."}'
    )
    assert not allowed
    assert reason == "Something specific."


def test_an_empty_verdict_is_never_an_approval() -> None:
    from app.workers.screen import MetaPostScreener, ScreenDidNotAnswer

    with pytest.raises(ScreenDidNotAnswer):
        MetaPostScreener._parse("")


# --------------------------------------------------------------------------- #
# the routes
# --------------------------------------------------------------------------- #
async def test_the_guidelines_are_served_so_people_can_read_them(
    client: Any, auth: Any
) -> None:
    headers = auth(sub="kc-guidelines-1")
    await client.post("/v1/auth/session", headers=headers)

    r = await client.get("/v1/community/guidelines", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert {item["id"] for item in body["items"]} == set(rules.GUIDELINE_IDS)
    assert body["note"]


async def test_a_report_can_cite_a_guideline(client: Any, auth: Any) -> None:
    import uuid

    headers = auth(sub="kc-guidelines-2")
    await client.post("/v1/auth/session", headers=headers)

    r = await client.post(
        "/v1/community/reports",
        json={
            "subject_kind": "comment",
            "comment_id": str(uuid.uuid4()),
            "reason": "inappropriate",
            "guideline_id": "no_harassment",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text


async def test_a_report_citing_an_unknown_rule_is_refused(
    client: Any, auth: Any
) -> None:
    import uuid

    headers = auth(sub="kc-guidelines-3")
    await client.post("/v1/auth/session", headers=headers)

    r = await client.post(
        "/v1/community/reports",
        json={
            "subject_kind": "post",
            "post_id": str(uuid.uuid4()),
            "reason": "other",
            "guideline_id": "invented_rule",
        },
        headers=headers,
    )
    assert r.status_code == 422
    assert r.json()["code"] == "bad_report"


async def test_a_report_citing_an_unreportable_rule_is_refused(
    client: Any, auth: Any
) -> None:
    """`no_prompt_injection` is for the screen, not for a report form."""
    import uuid

    headers = auth(sub="kc-guidelines-4")
    await client.post("/v1/auth/session", headers=headers)

    r = await client.post(
        "/v1/community/reports",
        json={
            "subject_kind": "post",
            "post_id": str(uuid.uuid4()),
            "reason": "other",
            "guideline_id": "no_prompt_injection",
        },
        headers=headers,
    )
    assert r.status_code == 422


async def test_a_report_with_no_guideline_is_still_accepted(
    client: Any, auth: Any
) -> None:
    """A report with only a coarse reason is worth having, and refusing
    it would lose it."""
    import uuid

    headers = auth(sub="kc-guidelines-5")
    await client.post("/v1/auth/session", headers=headers)

    r = await client.post(
        "/v1/community/reports",
        json={
            "subject_kind": "post",
            "post_id": str(uuid.uuid4()),
            "reason": "spam",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text


def test_the_screen_is_not_asked_to_judge_attacks_on_itself() -> None:
    """Withdrawn after it refused four ordinary captions.

    Asking a model whether text is an instruction to it makes the
    defence a judgement call, and the judgement went wrong in the
    direction that hurts: "What shoes should I wear with these
    pieces" is imperative in shape, so it was held and its author was
    told their question read as an attack on the software.

    The protection is `render_untrusted`, which wraps every caption
    before the model sees it. That is structural. A verdict is not.
    """
    from app.domain.guidelines import for_prompt

    assert "no_prompt_injection" not in for_prompt()


def test_the_withdrawn_rule_is_still_defined() -> None:
    """Verdicts stored while it was live still name it, and a note
    nobody can look up is worse than one nobody can act on."""
    from app.domain.guidelines import GUIDELINE_IDS

    assert "no_prompt_injection" in GUIDELINE_IDS


def test_every_rule_the_screen_can_answer_with_is_one_it_was_given() -> None:
    """A verdict naming a rule the prompt never listed is a verdict
    nobody can explain."""
    from app.domain.guidelines import GUIDELINES, for_prompt

    offered = for_prompt()
    for rule in GUIDELINES:
        assert (rule.id in offered) is rule.screened, rule.id


def test_a_bio_is_not_judged_on_whether_it_is_about_clothes() -> None:
    """**A self-description is not a caption.**

    "Fashion head" was held with "This did not read as being about the
    clothes" - a refusal nobody can appeal, for a bio that is entirely
    ordinary. `about_clothes` is written for captions and comments; a
    bio is somebody saying who they are.

    The rule is dropped from the prompt rather than ignored in the
    verdict, because a screen cannot hold something for a rule it was
    never shown.
    """
    from app.domain.guidelines import for_prompt

    assert "about_clothes" in for_prompt()
    assert "about_clothes" not in for_prompt(surface="bio")


def test_a_bio_is_still_held_for_everything_that_protects_people() -> None:
    """Only the topicality rule goes. The rest is untouched."""
    from app.domain.guidelines import GUIDELINES, for_prompt

    on_a_bio = for_prompt(surface="bio")
    for rule in GUIDELINES:
        if not rule.screened or rule.id == "about_clothes":
            continue
        assert rule.id in on_a_bio, f"{rule.id} stopped applying to a bio"
