"""Structured-output contracts for the stylist.

These are the shapes the model is *required* to return. They are deliberately
narrow: every field the model can fill is a field that can be wrong, so anything the
server already knows (garment names, colours, prices, availability) is looked up
afterwards rather than asked for. The model chooses ids and explains itself; it does
not restate our own data back to us.

Strict mode is on, which the vendor requires to mean a root object with
``additionalProperties: false`` — enforced at construction by ``JsonSchemaFormat``.
"""

from __future__ import annotations

from typing import Any, Final

#: Where a garment sits in an outfit. Closed on purpose: a free-text role would make
#: "shoes" and "footwear" two different slots and break swap targeting.
OUTFIT_ROLES: Final = (
    "top",
    "bottom",
    "dress",
    "outer",
    "shoes",
    "bag",
    "accessory",
)

#: Why a plan could not be produced. The model picks one rather than writing prose,
#: so the app can respond differently to "you own nothing suitable" (suggest
#: shopping) and "your constraints conflict" (suggest relaxing one).
INFEASIBLE_REASONS: Final = (
    "no_suitable_garments",
    "constraints_conflict",
    "everything_unavailable",
    "occasion_unclear",
)

OUTFIT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["feasible", "items", "rationale", "infeasible_reason", "missing_slots"],
    "properties": {
        "feasible": {
            "type": "boolean",
            "description": (
                "True only if every item below comes from the supplied wardrobe and "
                "every hard constraint is satisfied. If you cannot do both, set this "
                "false and explain — never return a partial or invented outfit."
            ),
        },
        "items": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["garment_id", "role"],
                "properties": {
                    "garment_id": {
                        "type": "string",
                        "description": (
                            "Must be one of the garment ids supplied in the wardrobe "
                            "block. Do not invent, modify or guess an id."
                        ),
                    },
                    "role": {"type": "string", "enum": list(OUTFIT_ROLES)},
                },
            },
        },
        "rationale": {
            "type": "string",
            "maxLength": 400,
            "description": (
                "One or two sentences on why this works for the occasion, weather and "
                "place. Mention the constraint you respected if there was one."
            ),
        },
        "infeasible_reason": {
            # Nullable rather than optional: strict mode requires every property to
            # be present, so "no reason" has to be expressible as a value.
            "type": ["string", "null"],
            "enum": [*INFEASIBLE_REASONS, None],
            "description": "Set only when feasible is false. Otherwise null.",
        },
        "missing_slots": {
            "type": "array",
            "maxItems": 6,
            "items": {"type": "string", "enum": list(OUTFIT_ROLES)},
            "description": (
                "Roles the wardrobe could not fill. Drives the shopping suggestions, "
                "so list a slot here instead of substituting something unsuitable."
            ),
        },
    },
}
