"""Conversations, stylist runs, and the outfits a run produces.

Six tables, and the shape of them encodes three decisions.

**A run is a durable row, not a request.** Model work is queued, never awaited
in a handler (ADR-013), so ``POST /v1/stylist/runs`` has to answer with
something the client can poll. :class:`StylistRun` is that something: it carries
``state``, ``progress``, the resolved hard constraints, the tool-call audit
trail, and — when the answer is "no" — an ``explanation_code`` instead of an
outfit. A run that could not produce an outfit is a *recorded* outcome rather
than a gap.

**The run stores what Python decided, not what the model said.** ``excluded``
and ``required`` are the output of ``regional.apply_precedence``, re-derived on
every turn and re-applied after the model returns. A swap carries them forward
on ``parent_run_id`` and accumulates ``forbidden_garment_ids``, which is what
makes "no heels" survive three swaps: each swap re-resolves the same
constraints rather than inheriting a summary of them.

**An outfit item names a garment or a product, never both.** Owned garments are
foreign keys into ``garments`` and are re-validated at a single chokepoint
before they get here (ADR-010); a shopping suggestion is a text reference with
``owned = false``. A CHECK constraint keeps an item that identifies nothing out
of the table.

There is no coordinate column anywhere in this module. ``place`` is a name the
user typed (ADR, §7, and ``app.domain.regional``'s rule that only a *name*
reaches the styling layer).
"""

from __future__ import annotations

import uuid
from datetime import date as date_type
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.ai.schemas import OUTFIT_ROLES
from app.db.base import JSONB, Base, TimestampMixin, UTCDateTime, named_enum, uuid_fk, uuid_pk

#: Transcript roles. ``tool`` rows record what a tool returned, so a run can be
#: replayed without re-reading the provider's wire format.
CONVERSATION_MESSAGE_ROLES: tuple[str, ...] = ("system", "user", "assistant", "tool")

#: A run's lifecycle. ``completed`` means the loop finished and recorded an
#: answer — which may be "no feasible outfit". ``failed`` means an invariant was
#: broken (an unowned id, an unusable model response) and nothing is renderable.
STYLIST_RUN_STATES: tuple[str, ...] = (
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
)

#: Slot vocabulary, single-sourced from the structured-output contract so the
#: column, the schema the model is held to, and swap targeting cannot drift.
OUTFIT_ITEM_ROLES: tuple[str, ...] = tuple(OUTFIT_ROLES)

#: What a user can say about a finished outfit. ``wore`` is a stronger signal
#: than ``would_wear`` and they are deliberately separate values.
OUTFIT_FEEDBACK_KINDS: tuple[str, ...] = ("would_wear", "wore", "dislike")

message_role_enum = named_enum("conversation_message_role", *CONVERSATION_MESSAGE_ROLES)
stylist_run_state_enum = named_enum("stylist_run_state", *STYLIST_RUN_STATES)
outfit_item_role_enum = named_enum("outfit_item_role", *OUTFIT_ITEM_ROLES)
outfit_feedback_kind_enum = named_enum("outfit_feedback_kind", *OUTFIT_FEEDBACK_KINDS)

#: States from which a run will never move again.
TERMINAL_RUN_STATES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})


class Conversation(Base, TimestampMixin):
    """One styling thread. Private by default; publication is a separate act."""

    __tablename__ = "conversations"
    __table_args__ = (
        sa.Index("ix_conversations_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    title: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)


class Message(Base, TimestampMixin):
    """One turn of a conversation, with its trust level recorded.

    ``untrusted`` is a column rather than a convention. A caption the user
    imported and a sentence the user typed read identically once they are both
    text, and the difference decides whether the content may be rendered into
    the instruction space of a later prompt (it may not — see
    ``app.ai.untrusted``). Storing it means a replay cannot lose the
    distinction.
    """

    __tablename__ = "conversation_messages"
    __table_args__ = (
        sa.Index("ix_conversation_messages_conversation_id_position", "conversation_id", "position"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    conversation_id: Mapped[uuid.UUID] = uuid_fk("conversations.id")
    #: The run this message belongs to, when it was produced by one.
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("stylist_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    role: Mapped[str] = mapped_column(message_role_enum, nullable=False)
    content: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    #: True for anything that came from outside our trust boundary.
    untrusted: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    #: The sanitised source label (``instagram_caption``, ``retailer_page``).
    source: Mapped[str | None] = mapped_column(sa.String(40), nullable=True)
    #: Kept for the audit trail. Never rendered into a prompt.
    origin_url: Mapped[str | None] = mapped_column(sa.String(2048), nullable=True)
    position: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    #: Tool name for a ``tool`` row; null otherwise.
    tool_name: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)


class StylistRun(Base, TimestampMixin):
    """One bounded agent loop, start to finish.

    Deliberately *not* ``AIRun``: that table is one row per provider call and
    exists for cost attribution. A stylist run makes several provider calls and
    is the unit the user polls, so the two are separate and joined by
    ``prompt_version`` plus the recorded ``ai_run_ids``.
    """

    __tablename__ = "stylist_runs"
    __table_args__ = (
        sa.Index("ix_stylist_runs_user_id_created_at", "user_id", "created_at"),
        sa.Index("ix_stylist_runs_state_created_at", "state", "created_at"),
        sa.CheckConstraint("progress >= 0 AND progress <= 1", name="progress_range"),
        sa.CheckConstraint("tool_calls_used >= 0", name="tool_calls_used_non_negative"),
        sa.CheckConstraint("model_attempts >= 0", name="model_attempts_non_negative"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    conversation_id: Mapped[uuid.UUID] = uuid_fk("conversations.id")
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    #: The run this one revises. A swap is a new run, not a mutation of the old
    #: one, so the history of what was rejected stays readable.
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("stylist_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    state: Mapped[str] = mapped_column(
        stylist_run_state_enum, nullable=False, default="queued", server_default="queued"
    )
    progress: Mapped[float] = mapped_column(
        sa.Float, nullable=False, default=0.0, server_default=sa.text("0")
    )

    # -- the request ------------------------------------------------------- #
    request_text: Mapped[str | None] = mapped_column(sa.String(2000), nullable=True)
    occasion: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    #: A place NAME the user typed. There is no coordinate column here.
    place: Mapped[str | None] = mapped_column(sa.String(160), nullable=True)
    styled_for: Mapped[date_type | None] = mapped_column(sa.Date, nullable=True)

    # -- what the request is *about* --------------------------------------- #
    # The assistant is the one surface where somebody already has a picture
    # in hand, and what they can ask depends on which kind it is. These are
    # ids, re-validated against the asker before anything is read: a client
    # naming an asset is making a claim, not granting itself access.
    #: A garment out of their own wardrobe.
    subject_garment_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("garments.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: A photograph they uploaded, which may have no wardrobe row behind it.
    subject_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("media_assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: A fit somebody else published, used as inspiration or tried on.
    subject_post_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("posts.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: What the asker turned out to be asking for, decided on the worker.
    #: Null until the run has been read. ``style`` is the ordinary case.
    intent: Mapped[str | None] = mapped_column(sa.String(24), nullable=True)
    #: The answer when a run did something other than build an outfit:
    #: started a shoot, a story or a try-on. In plain words, because that
    #: is what the thread shows.
    reply: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)

    # -- what Python decided, re-derived on every turn --------------------- #
    #: ``ResolvedGuidance.excluded`` — hard constraints, re-applied after the
    #: model returns rather than trusted to have been obeyed.
    excluded: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sa.text("'[]'")
    )
    required: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sa.text("'[]'")
    )
    #: Slot being swapped on a revision turn; null on a first turn.
    swap_slot: Mapped[str | None] = mapped_column(outfit_item_role_enum, nullable=True)
    #: ``role -> garment id`` the revision must keep. Enforced in Python.
    locked_items: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa.text("'{}'")
    )
    #: Garments previous turns already rejected, accumulated across swaps.
    forbidden_garment_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sa.text("'[]'")
    )

    # -- what happened ----------------------------------------------------- #
    prompt_version: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    provider: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    tool_calls_used: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    model_attempts: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    #: Every dispatch attempt, in order: ``{name, ok, error_code}``. A refused
    #: call is recorded too — "the model asked for save_outfit and was told no"
    #: is the interesting half of the audit trail.
    tool_executions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sa.text("'[]'")
    )
    #: The ``AIRun`` ids this loop produced, so spend joins back to the turn.
    ai_run_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sa.text("'[]'")
    )

    explanation: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    #: Why there is no outfit, from a closed vocabulary the app can branch on.
    explanation_code: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(sa.String(96), nullable=True)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    #: Set when a cancellation is requested; the loop checks it between steps.
    cancel_requested_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_RUN_STATES

    @property
    def executed_tool_names(self) -> tuple[str, ...]:
        """Tools that actually ran. A refused call is not in here.

        The distinction is the point: a model persuaded by an injected caption
        can *ask* for a tool, and the audit trail records that it asked, but
        only this list represents something that happened.
        """
        return tuple(
            str(entry.get("name"))
            for entry in (self.tool_executions or [])
            if entry.get("ok")
        )

    @property
    def refused_tool_names(self) -> tuple[str, ...]:
        return tuple(
            str(entry.get("name"))
            for entry in (self.tool_executions or [])
            if not entry.get("ok")
        )


class Outfit(Base, TimestampMixin):
    """A validated plan. Nothing reaches this table unvalidated (ADR-010)."""

    __tablename__ = "outfits"
    __table_args__ = (
        sa.Index("ix_outfits_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    #: The run that produced it. ``SET NULL`` so pruning run history does not
    #: delete a saved outfit the user still has.
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("stylist_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    #: The model's own words about why this works. Capped by the output schema.
    rationale: Mapped[str | None] = mapped_column(sa.String(600), nullable=True)
    occasion: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    place: Mapped[str | None] = mapped_column(sa.String(160), nullable=True)
    styled_for: Mapped[date_type | None] = mapped_column(sa.Date, nullable=True)
    #: Roles the wardrobe could not fill. Drives shopping suggestions; a slot
    #: listed here is honest about a gap rather than filled with a substitute.
    missing_slots: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sa.text("'[]'")
    )
    #: False for a superseded plan a swap replaced.
    saved: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=True, server_default=sa.true()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)


class OutfitItem(Base):
    """One slot of an outfit: an owned garment, or a product suggestion."""

    __tablename__ = "outfit_items"
    __table_args__ = (
        sa.UniqueConstraint("outfit_id", "garment_id", name="uq_outfit_items_outfit_id_garment_id"),
        sa.Index("ix_outfit_items_outfit_id_position", "outfit_id", "position"),
        sa.CheckConstraint(
            "garment_id IS NOT NULL OR product_ref IS NOT NULL",
            name="identifies_something",
        ),
        # An owned item must name a garment. A product suggestion must not claim
        # to be owned. The invariant lives in the schema because the renderer
        # branches on `owned` to decide whether to show a buy path.
        sa.CheckConstraint(
            "(owned AND garment_id IS NOT NULL) OR (NOT owned AND product_ref IS NOT NULL)",
            name="owned_means_garment",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    outfit_id: Mapped[uuid.UUID] = uuid_fk("outfits.id")
    #: ``SET NULL`` rather than cascade: a hard-deleted garment leaves a visible
    #: hole in the history instead of silently shrinking a past outfit.
    garment_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("garments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    #: A shopping reference for an unowned suggestion. Never a garment id.
    product_ref: Mapped[str | None] = mapped_column(sa.String(300), nullable=True)
    role: Mapped[str] = mapped_column(outfit_item_role_enum, nullable=False)
    owned: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=True, server_default=sa.true()
    )
    position: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )


class OutfitFeedback(Base, TimestampMixin):
    """What the user said about an outfit. One row per user per kind."""

    __tablename__ = "outfit_feedback"
    __table_args__ = (
        sa.UniqueConstraint(
            "outfit_id", "user_id", "kind", name="uq_outfit_feedback_outfit_id_user_id_kind"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    outfit_id: Mapped[uuid.UUID] = uuid_fk("outfits.id")
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    kind: Mapped[str] = mapped_column(outfit_feedback_kind_enum, nullable=False)
    note: Mapped[str | None] = mapped_column(sa.String(500), nullable=True)


__all__ = [
    "CONVERSATION_MESSAGE_ROLES",
    "OUTFIT_FEEDBACK_KINDS",
    "OUTFIT_ITEM_ROLES",
    "STYLIST_RUN_STATES",
    "TERMINAL_RUN_STATES",
    "Conversation",
    "Message",
    "Outfit",
    "OutfitFeedback",
    "OutfitItem",
    "StylistRun",
]
