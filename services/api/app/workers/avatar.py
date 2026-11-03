"""The avatar: seeing an outfit on someone who looks like you.

Two operations, and they use different endpoints for a reason.

**Generating** the avatar is text to image: there is no source photograph,
only what the person told us about themselves. **Trying an outfit on** is
image to image, because the whole point is that it is the *same* person in the
same pose against the same wall, wearing something else. Verified against the
live endpoint: an edit preserves identity, pose, backdrop and even the shoes
that were not mentioned, changing only what the prompt names.

**Appearance is stated, never inferred.** Every other prompt in this service
forbids reading identity off clothing, and a feature that guessed somebody's
presentation from their wardrobe would contradict all of them. So it comes
from :class:`app.models.preference.Preference`, whose own rule is that a
preference is a user statement and always wins over an inference. Every field
is optional and defaults to unspecified; an avatar with nothing stated is
still generated, just without those details fixed.

**A photograph is pixels to edit, never a source of facts about a person.**
:func:`likeness_prompt` builds an avatar from a picture somebody uploaded of
themselves, and that is the one way to get a figure that genuinely looks like
them - because it *is* them, cleaned up, rather than a description rendered.
What it must never become is a way around the rule above: nothing reads
presentation, age, body or skin tone off the picture and writes it down. The
model is told to keep the person it can see; it is not asked what they are,
and no field of :class:`Appearance` is ever populated from an image. The
person's own words ride alongside as a note, because those are theirs.

**A likeness is consented to separately.** `likeness` is its own consent
kind. Somebody can reasonably want the stylist and not want their face sent
to a model, and `ai_processing` standing in for that would make the
distinction impossible to express.

**It is a drawing, and is stored as one.** Media kind ``avatar``, never
``garment_photo``. Nobody should be able to mistake it for a photograph of the
user, including a future feature that treats stored media as evidence.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from app.errors import ApiError, CapabilityUnavailable
from app.providers.base import AIRequest, GeneratedImage

#: The key the stated appearance lives under in `preferences`.
APPEARANCE_KEY = "appearance"

AVATAR_MODEL = "muse-image-1.0"
#: Bumped to v2 on 2026-10-29: height was added to the vocabulary and
#: `describe()` was reordered to put adjectives before the noun. Both
#: change the prompt text, and this is what attributes a change in the
#: pictures to a change in what was asked for.
AVATAR_PROMPT_VERSION = "avatar.v2"
AVATAR_PURPOSE = "avatar.generate"
TRY_ON_PURPOSE = "avatar.try_on"
LIKENESS_PURPOSE = "avatar.from_photo"

#: What an uploaded photograph of the person is stored as. Never
#: `garment_photo`, and never `avatar`: it is neither a garment nor a
#: drawing, and the difference is what keeps it out of pipelines that
#: were looking for clothes.
AVATAR_SOURCE_MEDIA_KIND = "avatar_source"

#: The longest note accepted alongside the photograph.
MAX_LIKENESS_NOTE = 400

#: What the avatar is stored as. Not `garment_photo`, and the difference is
#: the point.
AVATAR_MEDIA_KIND = "avatar"

#: Closed vocabularies, each with an explicit "did not say".
#:
#: Small on purpose. This exists to render someone who feels like the person
#: looking at it, not to build a profile: anything not needed to draw a figure
#: is not asked for.
PRESENTATIONS = ("feminine", "masculine", "androgynous", "unspecified")
BODY_TYPES = ("slim", "average", "athletic", "curvy", "plus", "unspecified")
AGE_BANDS = ("20s", "30s", "40s", "50s", "60s_plus", "unspecified")
#: Height, as three bands rather than a measurement.
#:
#: Bands because a number would be a measurement of a person held on a
#: server, and because the prompt can only act on the difference anyway: an
#: image model draws "tall" and "short", not 174cm. Same closed shape as every
#: other field here, with the same way to say nothing.
HEIGHTS = ("tall", "average", "short", "unspecified")
SKIN_TONES = (
    "very_fair",
    "fair",
    "medium",
    "olive",
    "brown",
    "dark_brown",
    "deep",
    "unspecified",
)

_PHRASES: dict[str, dict[str, str]] = {
    "presentation": {
        "feminine": "woman",
        "masculine": "man",
        "androgynous": "androgynous person",
    },
    "body_type": {
        "slim": "slim",
        "athletic": "athletic",
        "curvy": "curvy",
        "plus": "plus size",
    },
    # No entry for "average", here or in `body_type`, and that is deliberate
    # rather than an omission. An image model handed "a person" already draws
    # an average build at an average height; "of average build" adds words to
    # the prompt without adding information to the picture, and it does not
    # compose into a sentence ("an of average height of average build
    # person"). It is still *stored* when somebody says it - what they stated
    # and what the prompt needs are different questions.
    "height": {
        "tall": "tall",
        "short": "short",
    },
    "age_band": {
        "20s": "in their twenties",
        "30s": "in their thirties",
        "40s": "in their forties",
        "50s": "in their fifties",
        "60s_plus": "in their sixties",
    },
    "skin_tone": {
        "very_fair": "with very fair skin",
        "fair": "with fair skin",
        "medium": "with medium skin",
        "olive": "with olive skin",
        "brown": "with brown skin",
        "dark_brown": "with dark brown skin",
        "deep": "with deep brown skin",
    },
}


class UnknownAppearance(ApiError):
    status_code = 422
    code = "unknown_appearance"
    default_message = "That is not something this service records."


@dataclass(frozen=True, slots=True)
class Appearance:
    """What someone said about how they look. Every field optional."""

    presentation: str = "unspecified"
    body_type: str = "unspecified"
    height: str = "unspecified"
    age_band: str = "unspecified"
    skin_tone: str = "unspecified"

    def __post_init__(self) -> None:
        for field, allowed in (
            ("presentation", PRESENTATIONS),
            ("body_type", BODY_TYPES),
            ("height", HEIGHTS),
            ("age_band", AGE_BANDS),
            ("skin_tone", SKIN_TONES),
        ):
            value = getattr(self, field)
            if value not in allowed:
                raise UnknownAppearance(
                    f"{field} must be one of {', '.join(allowed)}, got {value!r}."
                )

    @classmethod
    def from_stored(cls, value: Any) -> Appearance:
        """Read a stored preference, tolerating anything written before now."""
        if not isinstance(value, dict):
            return cls()
        allowed = {
            "presentation": PRESENTATIONS,
            "body_type": BODY_TYPES,
            "height": HEIGHTS,
            "age_band": AGE_BANDS,
            "skin_tone": SKIN_TONES,
        }
        return cls(
            **{
                field: value.get(field)
                if value.get(field) in options
                else "unspecified"
                for field, options in allowed.items()
            }
        )

    def as_stored(self) -> dict[str, str]:
        return {
            "presentation": self.presentation,
            "body_type": self.body_type,
            "height": self.height,
            "age_band": self.age_band,
            "skin_tone": self.skin_tone,
        }

    def describe(self) -> str:
        """The subject of the prompt, from what was actually said.

        Assembled rather than templated so an unspecified field simply does
        not appear. Describing somebody as "a person of unspecified build"
        would put the gap in the picture.

        **Adjectives before the noun**, which is where English puts them: "a
        tall athletic woman in their thirties", not "a woman athletic tall in
        their thirties". The naive concatenation produced the second, and an
        image model handed a sentence that reads as broken draws accordingly.
        """
        height = _PHRASES["height"].get(self.height)
        build = _PHRASES["body_type"].get(self.body_type)
        noun = _PHRASES["presentation"].get(self.presentation, "person")

        described = " ".join(
            part for part in (height, build, noun) if part
        )
        # "an athletic man", not "a athletic man".
        article = "an" if described[:1].lower() in "aeiou" else "a"

        trailing = [
            part
            for part in (
                _PHRASES["age_band"].get(self.age_band),
                _PHRASES["skin_tone"].get(self.skin_tone),
            )
            if part
        ]
        return " ".join([f"{article} {described}", *trailing])


#: The backdrop every avatar and every try-on shares.
#:
#: Identical to the Discover covers, so an outfit tried on sits in the same
#: world as the collection it came from. A try-on shot against a different
#: wall would read as a different app.
AVATAR_SCENE = (
    "Full-length fashion photograph, head to feet in frame, facing the "
    "camera, standing naturally with arms relaxed at the sides. Plain warm "
    "off-white plaster wall behind, soft diffused daylight from one side, a "
    "soft natural shadow on the pale concrete floor. Shot on medium format "
    "film, natural grain, muted warm colour. "
    "No text, no logo, no brand mark, no watermark, no border, no props."
)

#: What the avatar wears before any outfit is tried on it.
#:
#: Deliberately plain and deliberately covered. A base figure in underwear
#: would be a worse thing to have generated and a worse thing to show.
BASE_OUTFIT = (
    "a plain mid-grey long-sleeved top and plain mid-grey straight "
    "trousers, with simple white trainers, all unbranded"
)


def avatar_prompt(appearance: Appearance) -> str:
    return f"{AVATAR_SCENE}\n\nIn frame: {appearance.describe()}, wearing {BASE_OUTFIT}."


def likeness_prompt(note: str | None = None) -> str:
    """Turn a photograph of somebody into their avatar.

    An edit rather than a generation, which is the whole reason this
    looks like the person: the face, the build and the hair are in the
    source pixels rather than in an adjective. Verified behaviour of this
    endpoint is that an edit preserves identity and changes only what the
    prompt names, so what the prompt names is the *setting* - the pose,
    the backdrop, the light and the clothes - and everything about the
    person is explicitly held.

    The note is the person's own description of themselves, quoted as
    theirs and placed after the clauses that protect their likeness. It
    can ask for a different pose or a plainer background; it is not in a
    position to ask the model to change who is in the picture, because
    the instruction not to is both before it and repeated at the end.
    """
    said = (note or "").strip()[:MAX_LIKENESS_NOTE]
    asked = (
        f"\nWhat they said about how they would like it: {said}\n" if said else "\n"
    )
    return (
        "Redraw this photograph as a clean, full-length standing portrait "
        "of the same person, for use as a personal avatar.\n\n"
        "Keep the person exactly as they are: the same face and features, "
        "the same skin tone, the same hair, the same build and proportions, "
        "the same apparent age. This has to be recognisably them. Do not "
        "slim them, do not smooth or lighten their skin, do not change "
        "their hair, and do not make them look younger or older.\n\n"
        "Change only the setting: stand them squarely facing the camera "
        "with arms relaxed at their sides and both feet visible, against a "
        "plain warm off-white studio wall on a plain floor, lit by soft "
        "even daylight from one side with a gentle fill opposite. Remove "
        "anything else in the original frame: other people, furniture, "
        "props and clutter. Dress them in "
        f"{BASE_OUTFIT}.\n"
        f"{asked}\n"
        "Natural skin texture with visible pores and the odd stray hair, "
        "true-to-life colour, fine photographic grain, no heavy retouching. "
        "No text, no logo, no brand mark, no watermark, no border.\n\n"
        "Above all: it must still be the same person."
    )


def try_on_prompt(outfit: str) -> str:
    """Instruct an edit that changes the clothes and nothing else.

    Every clause after the first exists because an image edit will happily
    redraw the person given the chance, and an avatar that changes face
    between outfits is not an avatar.
    """
    return (
        f"Change only the clothing to: {outfit}.\n"
        "Keep the same person, the same face, the same body, the same pose, "
        "the same hair, the same background wall, the same floor, the same "
        "lighting and the same framing, all completely unchanged. "
        "Do not add text, a logo, a brand mark or a watermark."
    )


class AvatarRenderer(Protocol):
    async def generate(
        self, *, appearance: Appearance, user_id: uuid.UUID | None = None
    ) -> GeneratedImage: ...

    async def from_photo(
        self,
        *,
        photo: bytes,
        note: str | None = None,
        content_type: str = "image/jpeg",
        user_id: uuid.UUID | None = None,
    ) -> GeneratedImage: ...

    async def try_on(
        self,
        *,
        avatar: bytes,
        outfit: str,
        content_type: str = "image/png",
        user_id: uuid.UUID | None = None,
    ) -> GeneratedImage: ...


class MetaAvatarRenderer:
    """:class:`AvatarRenderer` backed by the Meta image model."""

    def __init__(self, provider: Any, *, model: str = AVATAR_MODEL) -> None:
        self._provider = provider
        self._model = model

    async def generate(
        self, *, appearance: Appearance, user_id: uuid.UUID | None = None
    ) -> GeneratedImage:
        generate = getattr(self._provider, "generate_image", None)
        if generate is None:
            raise CapabilityUnavailable(
                "This provider cannot generate images.",
                detail={"capability": "image_out"},
            )
        response = await generate(
            AIRequest(
                prompt=avatar_prompt(appearance),
                model=self._model,
                purpose=AVATAR_PURPOSE,
                prompt_version=AVATAR_PROMPT_VERSION,
            ),
            user_id=user_id,
            count=1,
        )
        if not response.image_data:
            raise CapabilityUnavailable(
                f"{self._model} returned no image data.",
                detail={"capability": "image_out", "model": self._model},
            )
        return response.image_data[0]

    async def from_photo(
        self,
        *,
        photo: bytes,
        note: str | None = None,
        content_type: str = "image/jpeg",
        user_id: uuid.UUID | None = None,
    ) -> GeneratedImage:
        """Build the avatar out of a photograph of the person.

        The same edit endpoint the try-on uses, for the same reason:
        identity survives an edit, and that is exactly what is wanted
        here. Nothing is read *out* of the picture - no attribute is
        inferred and stored - it is only edited.
        """
        edit = getattr(self._provider, "edit_image", None)
        if edit is None:
            raise CapabilityUnavailable(
                "This provider cannot edit images.",
                detail={"capability": "image_edit"},
            )
        response = await edit(
            AIRequest(
                prompt=likeness_prompt(note),
                model=self._model,
                purpose=LIKENESS_PURPOSE,
                prompt_version=AVATAR_PROMPT_VERSION,
            ),
            image=photo,
            content_type=content_type,
            user_id=user_id,
        )
        if not response.image_data:
            # Never a silent fallback to the source photograph: handing
            # back somebody's own photo as though it were a generated
            # avatar is the one failure they cannot detect.
            raise CapabilityUnavailable(
                f"{self._model} returned no image data.",
                detail={"capability": "image_out", "model": self._model},
            )
        return response.image_data[0]

    async def try_on(
        self,
        *,
        avatar: bytes,
        outfit: str,
        content_type: str = "image/png",
        user_id: uuid.UUID | None = None,
    ) -> GeneratedImage:
        edit = getattr(self._provider, "edit_image", None)
        if edit is None:
            raise CapabilityUnavailable(
                "This provider cannot edit images.",
                detail={"capability": "image_edit"},
            )
        response = await edit(
            AIRequest(
                prompt=try_on_prompt(outfit),
                model=self._model,
                purpose=TRY_ON_PURPOSE,
                prompt_version=AVATAR_PROMPT_VERSION,
            ),
            image=avatar,
            content_type=content_type,
            user_id=user_id,
        )
        if not response.image_data:
            raise CapabilityUnavailable(
                f"{self._model} returned no image data.",
                detail={"capability": "image_edit", "model": self._model},
            )
        return response.image_data[0]


__all__ = [
    "AGE_BANDS",
    "APPEARANCE_KEY",
    "AVATAR_MEDIA_KIND",
    "AVATAR_MODEL",
    "AVATAR_PROMPT_VERSION",
    "BODY_TYPES",
    "HEIGHTS",
    "PRESENTATIONS",
    "SKIN_TONES",
    "Appearance",
    "AvatarRenderer",
    "MetaAvatarRenderer",
    "UnknownAppearance",
    "avatar_prompt",
    "try_on_prompt",
]
