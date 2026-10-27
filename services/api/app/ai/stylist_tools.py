"""The tools the stylist may actually call.

Each one is deliberately narrow. A broad "query the database" tool would be easier to
write and impossible to reason about; these answer specific questions, return bounded
results, and are individually reviewable.

None of them accepts a user id. The owner comes from :class:`ToolContext`, built from
the authenticated session, so there is no parameter through which a model could
request someone else's wardrobe — that is the enforcement §6 asks for, expressed as a
shape rather than a check.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from app.ai.tools import MAX_RESULTS, ToolContext, ToolRefused, ToolSpec
from app.domain.wardrobe_guard import UnownedGarment, validate_owned_ids
from app.models.garment import STYLEABLE_AVAILABILITY, Garment


def _garment_view(garment: Garment) -> dict[str, Any]:
    """What the model sees of one garment.

    Only what styling needs. No media URLs (nothing for the model to fetch), no
    purchase links, no timestamps — every extra field costs tokens on a payload sent
    once per turn, and the capacity model shows input dominating cost.
    """
    attributes = garment.effective_attributes
    return {
        "id": str(garment.id),
        "name": garment.name,
        "category": garment.category,
        "colour": attributes.get("colour"),
        "formality": attributes.get("formality"),
        "seasons": attributes.get("seasons"),
        "material": attributes.get("material"),
        "available": garment.availability in STYLEABLE_AVAILABILITY,
    }


async def search_wardrobe(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Owner-scoped retrieval over garment attributes.

    Deterministic SQL rather than vector similarity (ADR-004): the Meta Model API has
    no embeddings endpoint, and a few hundred garments filtered on indexed attributes
    is both cheaper and explainable.
    """
    limit = min(int(args.get("limit") or 20), MAX_RESULTS)

    query = sa.select(Garment).where(
        Garment.user_id == context.user_id,
        Garment.deleted_at.is_(None),
    )

    # Unavailable items are excluded by default. A model that cannot see the garment
    # in the wash cannot suggest it, which is more reliable than asking it not to.
    if not args.get("include_unavailable"):
        query = query.where(Garment.availability.in_(STYLEABLE_AVAILABILITY))

    categories = args.get("categories")
    if isinstance(categories, list) and categories:
        query = query.where(Garment.category.in_([str(c)[:64] for c in categories[:12]]))

    rows = list((await context.session.scalars(query.limit(limit))).all())

    # Hard constraints are applied here as well as in the prompt, so an excluded
    # category never even reaches the model.
    if context.excluded:
        rows = [
            row
            for row in rows
            if (row.category or "").lower() not in context.excluded
            and str(row.effective_attributes.get("colour", "")).lower() not in context.excluded
        ]

    return {
        "garments": [_garment_view(row) for row in rows],
        "count": len(rows),
        "truncated": len(rows) >= limit,
    }


async def validate_outfit(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Check a proposed outfit before it is shown to anyone.

    The model may call this to check its own work, and the loop calls it regardless
    before persisting — ADR-010 requires validation that does not depend on the model
    having asked for it.
    """
    raw_ids = args.get("garment_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        raise ToolRefused("invalid_arguments", "garment_ids must be a non-empty array")

    try:
        garments = await validate_owned_ids(context.session, context.user_id, raw_ids)
    except UnownedGarment as rejection:
        # Reported back to the model so it can choose again, rather than failing the
        # run. The ids are echoed without saying *why* each was rejected — "that id
        # belongs to someone else" is not something to confirm.
        return {
            "valid": False,
            "reason": rejection.code,
            "message": "One or more garments are not available in this wardrobe.",
            "rejected": [str(value) for value in rejection.ids]
            if hasattr(rejection, "ids")
            else [],
        }

    violations: list[str] = []
    for garment in garments:
        category = (garment.category or "").lower()
        colour = str(garment.effective_attributes.get("colour", "")).lower()
        if category in context.excluded or colour in context.excluded:
            violations.append(str(garment.id))

    if violations:
        return {
            "valid": False,
            "reason": "hard_constraint_violated",
            "message": "Some garments break a constraint the user set.",
            "rejected": violations,
        }

    return {"valid": True, "garments": [_garment_view(garment) for garment in garments]}


SEARCH_WARDROBE = ToolSpec(
    name="search_wardrobe",
    description=(
        "Find garments in the user's own wardrobe. Returns only garments that exist "
        "and are available. Call this before building an outfit; you cannot use any "
        "garment that this has not returned."
    ),
    parameters={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "categories": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional category filter, e.g. ['shirt','trousers'].",
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": MAX_RESULTS},
            "include_unavailable": {
                "type": "boolean",
                "description": (
                    "Include garments that are in the wash or marked unavailable. "
                    "They must not appear in the final outfit."
                ),
            },
        },
    },
    handler=search_wardrobe,
)

VALIDATE_OUTFIT = ToolSpec(
    name="validate_outfit",
    description=(
        "Check that a set of garment ids is real, owned, available and does not break "
        "a constraint. Use it before you commit to an outfit."
    ),
    parameters={
        "type": "object",
        "additionalProperties": False,
        "required": ["garment_ids"],
        "properties": {
            "garment_ids": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": "Garment ids returned by search_wardrobe.",
            }
        },
    },
    handler=validate_outfit,
)

#: The read-only set. A revision turn gets exactly this and no persistence tool —
#: not offering an action is stronger than instructing against it.
STYLIST_TOOLS: tuple[ToolSpec, ...] = (SEARCH_WARDROBE, VALIDATE_OUTFIT)



__all__ = [
    "SEARCH_WARDROBE",
    "STYLIST_TOOLS",
    "VALIDATE_OUTFIT",
    "search_wardrobe",
    "validate_outfit",
]
