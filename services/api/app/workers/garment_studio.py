"""Turn a photograph of a real garment into the shots a shop would use.

**Every treatment here edits the owner's own photograph.** That is what
makes it worth having: the print, the logo, the weave, the exact colour and
the way that particular jumper has stretched at the elbow all survive,
because they are in the source pixels rather than in a description of them.
A generated picture of "a navy cable knit" is a different jumper; an edit of
*this* jumper is this jumper, somewhere else.

**One input image, no mask.** The vendor's edit endpoint takes a single
image and a prompt — ``mask`` and ``input_fidelity`` are verified 400s (see
``MetaProvider.edit_image``). Two consequences, and both shape what is
offered:

* The prompts have to carry "keep the garment exactly as it is" in words,
  since there is no mask to protect it. Every treatment below says so, at
  length, because an edit will cheerfully redraw a garment it was asked to
  reposition.
* Putting *this* garment on *that* chosen mannequin cannot be done, because
  that needs two source images in one call. :data:`TREATMENTS` therefore
  offers a model the edit invents around the garment, not one the user
  picked. `scripts/generate_mannequins.py` figures are a separate set and
  are not combined here.

**The prompts describe a photograph that was taken.** Named camera and
lens, a real lighting setup, and imperfections asked for by name — pores,
stray hairs, the creases a worn garment actually has. The words "perfect",
"flawless", "hyperrealistic" and "8k" appear nowhere: they pull hard toward
the airbrushed plastic look they seem to promise. :data:`REALISM` is shared
by every treatment so the set comes back looking like one shoot.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from app.errors import CapabilityUnavailable
from app.providers.base import AIRequest, GeneratedImage

#: Bumped when a prompt below changes, so a stored run says which wording
#: produced it.
STUDIO_PROMPT_VERSION = 1

STUDIO_PURPOSE = "garment.studio"

#: The same image model the avatar uses. Named here rather than read from
#: settings for the same reason `AVATAR_MODEL` is: it is the one model
#: verified to hold a source image through an edit, so swapping it is a
#: decision with a test behind it, not a config change.
STUDIO_MODEL = "muse-image-1.0"

#: The media kind studio results are stored under, which keeps them out of
#: the wardrobe's own photograph slot: a studio shot is a derivative, and
#: overwriting the source would make the treatment irreversible.
STUDIO_MEDIA_KIND = "garment_studio"

#: Shared by every treatment. See the module docstring for why each clause
#: is here rather than a shorter "photorealistic".
REALISM = (
    "Shot on a Sony a7R V with a 50mm lens at f/4, natural colour, fine "
    "photographic film grain, true-to-life contrast with no heavy "
    "retouching. Natural fabric wrinkles and creases where the cloth "
    "folds, the weave and stitching legible. "
    "No text, no logo overlay, no brand mark, no watermark, no border."
)

#: Asked for on every treatment that lays garments out.
#:
#: **The app draws every cover in one upright shell.** A packshot of
#: a shirt beside a pair of trousers came back landscape, because
#: that is how you lay two garments out on a floor, and the app then
#: had to letterbox or crop it - it was the only card in the feed
#: lying on its side.
#:
#: Asked for rather than imposed afterwards, because the model can
#: *compose* for the frame: told the frame is upright it stacks the
#: pieces instead of putting them side by side, which is a better
#: picture than the same landscape photograph padded out. The padding
#: in `workers/shell_fit` is still there for whatever comes back the
#: wrong shape anyway.
PORTRAIT_FRAME = (
    "Compose this as an upright portrait image, taller than it is wide, "
    "about nine units wide by sixteen tall. Arrange the garments to suit "
    "that shape - stacked one above another rather than side by side when "
    "there is more than one - and fill the frame with an even margin. "
    "Never letterbox, never add bars, and never rotate a garment onto its "
    "side to make it fit."
)

#: Said in every prompt. There is no mask on this endpoint, so the only
#: thing protecting the garment is the instruction.
KEEP_THE_GARMENT = (
    "Keep the garment itself exactly as it is in the photograph: the same "
    "colour, the same pattern and print, the same logos and labels in the "
    "same places, the same fabric texture and weave, the same cut, the "
    "same length, the same buttons and hardware. Do not restyle it, do not "
    "clean it up, do not change its shade, and do not invent detail that is "
    "not already there."
)


@dataclass(frozen=True)
class Treatment:
    """One shot the studio can produce from a garment photograph."""

    id: str
    label: str
    #: Said to the person before they spend a generation on it. Describes
    #: what comes back, not how good it will be.
    description: str = ""
    prompt: str = ""


TREATMENTS: tuple[Treatment, ...] = (
    Treatment(
        id="on_model",
        label="On a model",
        description=(
            "Your garment worn by a person, photographed in a studio. The "
            "model is invented by the edit; the clothes are yours."
        ),
        prompt=(
            "Photograph this exact garment being worn by a person, standing "
            "naturally and facing the camera, framed from the knees up. "
            f"{KEEP_THE_GARMENT} "
            "Plain warm off-white studio wall behind, soft diffuse daylight "
            "from one side with a gentle fill on the shadow side. "
            "Subtle skin texture with visible pores, a few stray hairs out "
            "of place, a relaxed and unposed expression, hands relaxed. "
            f"{REALISM}"
        ),
    ),
    Treatment(
        id="packshot",
        label="Packshot",
        description=(
            "A clean catalogue shot: the garment laid flat and lit evenly, "
            "the way a shop photographs stock."
        ),
        prompt=(
            "Photograph this exact garment as a flat catalogue packshot, "
            "laid out neatly and squared to the camera, shot from directly "
            "above, filling the frame with a small even margin. "
            f"{PORTRAIT_FRAME} "
            f"{KEEP_THE_GARMENT} "
            "Plain light grey seamless background, soft even studio light "
            "from above with a faint contact shadow beneath the cloth so it "
            "sits on a surface rather than floating. "
            f"{REALISM}"
        ),
    ),
    Treatment(
        id="cutout",
        label="Cutout",
        description=(
            "The garment alone on plain white, background removed. For a "
            "listing, or anywhere it needs no setting."
        ),
        prompt=(
            "Isolate this exact garment on a plain pure white background, "
            "removing everything else in the photograph: the surface it is "
            "on, any hanger, any hands, any props, any shadow cast on the "
            "old background. "
            f"{PORTRAIT_FRAME} "
            f"{KEEP_THE_GARMENT} "
            "Keep the garment's own edges crisp and complete, including "
            "straps, ties and sleeves, and keep its own form and shading so "
            "it reads as a solid object rather than a flat sticker. A very "
            "faint soft shadow directly beneath it. "
            f"{REALISM}"
        ),
    ),
    Treatment(
        id="campaign",
        label="In a scene",
        description=(
            "Your garment worn somewhere real: daylight, a street, a room. "
            "For seeing how it reads outside a studio."
        ),
        prompt=(
            "Photograph this exact garment being worn by a person out in the "
            "world: a quiet city street in late afternoon, the figure "
            "full-length and a little off-centre, walking or standing still. "
            f"{KEEP_THE_GARMENT} "
            "Warm low golden-hour daylight raking across the scene, long "
            "soft shadows, the background gently out of focus. "
            "Subtle skin texture, stray hairs moving in the air, an "
            "unposed candid expression. "
            f"{REALISM}"
        ),
    ),
)

TREATMENT_IDS: tuple[str, ...] = tuple(treatment.id for treatment in TREATMENTS)



def with_brief(treatment: Treatment, brief: str | None) -> str:
    """A treatment's wording plus somebody's own direction.

    **Order is the whole of this function.** There is no mask on the
    vendor's edit endpoint, so the clause protecting the source garment
    is the only thing keeping the product the product - and an edit
    follows its final instruction most closely. The brief therefore
    goes after the treatment and before that clause, never last.

    Returns the treatment's own prompt unchanged when there is no
    brief, so a shot nobody wrote a direction for runs exactly the
    wording it always did.
    """
    direction = (brief or "").strip()
    if not direction:
        return treatment.prompt
    return f"{treatment.prompt} {direction} {KEEP_THE_GARMENT}"


def treatment_by_id(treatment_id: str) -> Treatment | None:
    return next((t for t in TREATMENTS if t.id == treatment_id), None)


class GarmentStudio(Protocol):
    async def shoot(
        self,
        *,
        photo: bytes,
        treatment: Treatment,
        content_type: str = "image/jpeg",
        user_id: uuid.UUID | None = None,
        prompt: str | None = None,
    ) -> GeneratedImage: ...


class MetaGarmentStudio:
    """The studio, against the vendor's image-edit endpoint.

    Deliberately thin: it owns the call and the refusal, and nothing else.
    Which treatments exist, and what they say, is data above — so changing
    a prompt is a change to a constant rather than to a code path.
    """

    def __init__(self, provider: object, *, model: str = STUDIO_MODEL) -> None:
        self._provider = provider
        self._model = model

    async def shoot(
        self,
        *,
        photo: bytes,
        treatment: Treatment,
        content_type: str = "image/jpeg",
        user_id: uuid.UUID | None = None,
        prompt: str | None = None,
    ) -> GeneratedImage:
        """Run one edit over one photograph.

        `prompt` overrides the treatment's fixed wording. A brand frame
        composes its own from a scene, a cast, a reference and a brief;
        the four treatments here pass nothing and run as written.
        """
        edit = getattr(self._provider, "edit_image", None)
        if edit is None:
            raise CapabilityUnavailable(
                "This provider cannot edit images.",
                detail={"capability": "image_edit"},
            )
        response = await edit(
            AIRequest(
                prompt=prompt or treatment.prompt,
                model=self._model,
                purpose=STUDIO_PURPOSE,
                prompt_version=STUDIO_PROMPT_VERSION,
            ),
            image=photo,
            content_type=content_type,
            user_id=user_id,
        )
        if not response.image_data:
            # Never a silent fallback to the original photograph: handing
            # back the input as though it were the result is the one
            # failure mode a person cannot detect.
            raise CapabilityUnavailable(
                f"{self._model} returned no image data.",
                detail={"capability": "image_edit", "model": self._model},
            )
        return response.image_data[0]


__all__ = [
    "KEEP_THE_GARMENT",
    "REALISM",
    "with_brief",
    "STUDIO_MEDIA_KIND",
    "STUDIO_MODEL",
    "STUDIO_PROMPT_VERSION",
    "STUDIO_PURPOSE",
    "TREATMENTS",
    "TREATMENT_IDS",
    "GarmentStudio",
    "MetaGarmentStudio",
    "Treatment",
    "treatment_by_id",
]
