"""How recent attention is weighed, in one place.

Three screens make a claim about what is being reached for — the
inbox's "other people kept this too", the stylist's sense of what
somebody is drawn to, and anything ranking fits by attention. They
have to agree: two different notions of "recent" or "enough people" in
one service disagree visibly, on two screens, about the same taps.

These constants used to live in a `trending` module built on a table of
taps against the catalogue of curated looks. The catalogue is gone and
so is that table; what people actually touch is a published fit, so the
weights below are over fit signals and the thresholds came across
unchanged — they were never about looks, only about time and crowd
size.
"""

from __future__ import annotations

from datetime import datetime

#: How much intent each signal demonstrates.
#:
#: Keeping a fit is a filing decision and the strongest thing short of
#: asking for it to be styled; a reaction is a remark in passing. The
#: ratio matters more than the numbers: a save must not be outvoted by
#: a handful of reactions.
WEIGHTS: dict[str, float] = {
    "reaction": 2.0,
    "save": 8.0,
}

#: Nothing older than this counts. A claim about attention is a claim
#: about now.
WINDOW_DAYS = 14

#: How many distinct people must have touched something before this app
#: will say so.
#:
#: Three is low because the alternative is worse: a threshold high
#: enough to be statistically respectable would leave the notice silent
#: for months, and silence teaches people a feature is broken. Three is
#: the smallest number that cannot be one person, and the claim stays
#: honest because nothing is shown at all rather than falling back to
#: one device's taps.
MIN_DISTINCT_USERS = 3

#: Most recent events win, but not by so much that a day-old fit is
#: invisible. A half-life of a week over a fortnight's window means the
#: oldest event counted is worth a quarter of a fresh one.
HALF_LIFE_DAYS = 7.0


def decay(occurred_at: datetime, now: datetime) -> float:
    """Weight for an event's age. 1.0 when fresh, halving every half-life."""
    age_days = max(0.0, (now - occurred_at).total_seconds() / 86_400)
    return 0.5 ** (age_days / HALF_LIFE_DAYS)
