"""Rendering a garment that cannot be cut out of the photograph.

Segmentation can only remove what it can see. When something overlaps a
garment — a tote across a shirt, a desk across trousers — the mask comes back
as a fragment, and the wardrobe ends up showing a shirt with a bag-shaped hole
in it. There are three honest responses to that: show the fragment, show
nothing, or draw what the garment looks like from what was read off it.

This is the third. It is used **only** where the first two are worse, which the
detector decides by reporting how much of each garment the photograph actually
shows (:mod:`app.workers.outfit`). A garment that cuts out cleanly keeps its
real cut-out, because a picture of the user's own garment is worth more than a
good drawing of one like it.

Two rules hold everything here together:

* **A render is never passed off as a photograph.** It is stored under its own
  media kind, ``garment_render``, so nothing downstream can mistake it for
  evidence of what somebody owns.
* **A render claims only what was observed.** The prompt is built from the
  closed-vocabulary labels the detector returned — slot, category, colour,
  pattern, apparent material — and nothing else. It does not invent a brand, a
  logo, a size, or a fibre composition, because none of those were seen.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from app.errors import CapabilityUnavailable
from app.providers.base import AIRequest, GeneratedImage
from app.providers.segmentation import CUTOUT_BACKGROUND
from app.workers.categorise import CategorisationResult

#: The model that draws. Verified: ``/images/generations`` returns WEBP as
#: base64 in ``data[0].b64_json``, with ``url`` always null.
RENDER_MODEL = "muse-image-1.0"

#: Bumped whenever the prompt below changes, so a stored render can be traced
#: to the wording that produced it.
RENDER_PROMPT_VERSION = "garment_render.v1"

RENDER_PURPOSE = "wardrobe.render_garment"

#: What the stored row is labelled. Not ``garment_photo``, and the difference
#: is the point.
RENDER_MEDIA_KIND = "garment_render"

#: A render is only worth paying for where the alternative is unusable.
#: ``mostly_hidden`` is the detector's verdict that cutting this garment out
#: would produce something that does not read as the garment.
RENDER_WHEN_VISIBILITY = frozenset({"mostly_hidden"})


class GarmentRenderer(Protocol):
    """Draws one garment from what was read off it."""

    async def render(
        self,
        *,
        noun_phrase: str,
        classification: CategorisationResult,
        user_id: uuid.UUID | None = None,
    ) -> GeneratedImage: ...


def render_prompt(noun_phrase: str, classification: CategorisationResult) -> str:
    """Build the instruction that draws one garment.

    Deliberately a product shot and not a scene. The wardrobe grid is a grid of
    garments, so every tile has to sit on the same ground, at the same scale,
    with no person in it: a render with a model in it would be the one tile in
    the wardrobe that shows a body, and a render on a different backdrop would
    be the one tile that looks pasted in.

    The backdrop matches :data:`CUTOUT_BACKGROUND` for the same reason. A grid
    mixing real cut-outs and renders should read as one wardrobe, not as two
    sources of picture sitting next to each other.

    Only observed attributes appear. ``apparent_material`` is phrased as
    appearance rather than fact, because that is exactly what the classifier
    reports: what the surface looks like, never a fibre-composition claim.
    """
    descriptors: list[str] = []
    if classification.colour and classification.colour != "unknown":
        descriptors.append(classification.colour)
    if classification.pattern and classification.pattern not in {"unknown", "plain"}:
        descriptors.append(f"{classification.pattern}-patterned")

    described = " ".join(descriptors)
    subject = f"{described} {noun_phrase}".strip() if described else noun_phrase

    material = ""
    if classification.apparent_material and classification.apparent_material != "unknown":
        material = (
            f" The surface should look like {classification.apparent_material}."
        )

    return (
        f"A single {subject}, photographed on its own as a catalogue product "
        f"shot. Laid flat and centred, shown complete, filling most of the "
        f"frame.{material}\n"
        f"\n"
        f"No person, no model, no mannequin, no hands, no other garment. "
        f"Plain warm off-white backdrop the colour {CUTOUT_BACKGROUND}, even "
        f"soft studio lighting, a subtle contact shadow beneath the garment. "
        f"No text, no logo, no brand mark, no watermark, no border."
    )


class MetaGarmentRenderer:
    """:class:`GarmentRenderer` backed by the Meta image model."""

    def __init__(self, provider: object, *, model: str = RENDER_MODEL) -> None:
        self._provider = provider
        self._model = model

    async def render(
        self,
        *,
        noun_phrase: str,
        classification: CategorisationResult,
        user_id: uuid.UUID | None = None,
    ) -> GeneratedImage:
        generate = getattr(self._provider, "generate_image", None)
        if generate is None:
            raise CapabilityUnavailable(
                "This provider cannot generate images.",
                detail={"capability": "image_out"},
            )

        response = await generate(
            AIRequest(
                prompt=render_prompt(noun_phrase, classification),
                model=self._model,
                purpose=RENDER_PURPOSE,
                prompt_version=RENDER_PROMPT_VERSION,
            ),
            user_id=user_id,
            count=1,
        )
        if not response.image_data:
            # Charged for and got nothing usable back. Reported as a missing
            # capability rather than retried: a second identical call is as
            # likely to return nothing, and would be billed again.
            raise CapabilityUnavailable(
                f"{self._model} returned no image data.",
                detail={"capability": "image_out", "model": self._model},
            )
        return response.image_data[0]


__all__ = [
    "RENDER_MEDIA_KIND",
    "RENDER_MODEL",
    "RENDER_PROMPT_VERSION",
    "RENDER_PURPOSE",
    "RENDER_WHEN_VISIBILITY",
    "GarmentRenderer",
    "MetaGarmentRenderer",
    "render_prompt",
]
