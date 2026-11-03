"""Shapes for the community tab.

Every field here is either the app's own taxonomy or a first name. There is
no free-text field in this module and that is the point: while there is no
moderation pipeline, nothing a user wrote may cross to another account, and
the easiest way to keep that true is for the wire format to have nowhere to
put it.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field


class GuidelineOut(BaseModel):
    """One community guideline, in the words people are held to."""

    id: str
    title: str
    body: str
    #: True when somebody can pick it as a reason for reporting.
    reportable: bool = True


class GuidelinesOut(BaseModel):
    items: list[GuidelineOut] = Field(default_factory=list)
    #: Said once, above the list: these are enforced automatically on
    #: everything written here, and a person can report what the screen
    #: missed.
    note: str = (
        "Everything written here is checked automatically before other "
        "people see it. If something gets through, report it and it will "
        "be looked at."
    )


class FollowCountsOut(BaseModel):
    following: int
    followers: int


class MemberFitOut(BaseModel):
    """One tile on somebody's page: what to show, and what to open."""

    post_id: uuid.UUID
    #: Null when the fit has no readable photograph, which a client
    #: renders as a blank tile rather than omitting - the fit exists.
    cover_asset_id: uuid.UUID | None = None


class MemberOut(BaseModel):
    """One other person's page: who they are, and what they have made.

    The identity doctrine from the router holds: a first name, plus the
    handle and approved bio they chose to publish. No email, no last
    name, no face carried between accounts.

    **The following count is shown.** It used to be withheld on the
    reasoning that it was "a list of other people's names in numeric
    form", which does not survive examination: a count discloses no
    name, and the list behind it stays private and unreadable by
    anybody but its owner. Withholding it made the page say less than
    every comparable surface while protecting nothing.

    **Their published fits are not gated.** Putting an outfit in front
    of strangers is what publishing is, so a fit already on the board
    discloses nothing new on its author's page. What they *saved* is a
    different thing and stays behind `community_sharing`.
    """

    user_id: uuid.UUID
    name: str
    #: What they chose to be called publicly, when they have set one.
    handle: str | None = None
    #: The approved bio only. An unscreened one is unscreened text in
    #: front of a stranger.
    bio: str | None = None
    #: Platform to handle. The address is built at render time, so a
    #: link can only point where it says it does.
    links: dict[str, str] = Field(default_factory=dict)
    #: The picture across the top of their page, if the screen passed it.
    banner_asset_id: uuid.UUID | None = None
    followed: bool
    follows_you: bool
    follower_count: int
    following_count: int = 0
    shares: bool
    #: Fits they published, newest first. Each carries the picture to
    #: show for it: a grid needs the asset to render and the post to
    #: open, and returning only the post id drew grey boxes.
    posts: list[MemberFitOut] = Field(default_factory=list)
    #: How many in total, which is not how many this page returns.
    post_count: int = 0
    #: Fits by other people they kept, same shape. Empty unless
    #: `shares`.
    saved_posts: list[MemberFitOut] = Field(default_factory=list)
    blocked: bool
    #: They keep their fits and their two follow lists to themselves.
    #: The counts above are still true; the lists are empty, and a
    #: client says so rather than drawing an empty grid.
    private: bool = False


class BlockedPersonOut(BaseModel):
    user_id: uuid.UUID
    name: str


class BlockedListOut(BaseModel):
    items: list[BlockedPersonOut] = Field(default_factory=list)


class ReportIn(BaseModel):
    subject_kind: Literal["account", "post", "comment"]
    subject_user_id: uuid.UUID | None = None
    post_id: uuid.UUID | None = None
    comment_id: uuid.UUID | None = None
    #: The coarse bucket the moderation queue sorts by. Stable on
    #: purpose: it must not change every time a guideline is reworded.
    reason: Literal["impersonation", "inappropriate", "spam", "other"]
    #: The specific rule the reporter says was broken, from
    #: `GET /v1/community/guidelines`. Optional - a report with only a
    #: reason is still worth having, and refusing it would lose it.
    guideline_id: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=500)


class ReportOut(BaseModel):
    report_id: uuid.UUID


class FoundPersonOut(BaseModel):
    """A search hit: a first name, and the two numbers that justify a follow."""

    user_id: uuid.UUID
    name: str
    followed: bool
    follower_count: int
    #: Published fits. Also the reason this person is findable at all.
    fits: int


class PeopleSearchOut(BaseModel):
    items: list[FoundPersonOut] = Field(default_factory=list)
    #: The account whose list was asked for keeps it to itself. Empty
    #: items with a reason, rather than empty items meaning two things.
    private: bool = False
