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


#: Words that describe a body rather than a garment.
#:
#: **These are why a try-on was refused outright.** A pin of toe
#: rings and anklets was read as "Bare feet with silver and gold toe
#: rings... around one ankle", and that sentence went into an image
#: edit that also says "keep the same person, the same body" - which
#: the vendor's content filter rejected with a 400, consistently. The
#: reading was accurate about the photograph and useless as an
#: instruction: nobody wears bare feet.
#:
#: Matched as whole words so "barefoot sandals" keeps its sandals and
#: a "shoulder bag" keeps its bag.
_NOT_CLOTHING = (
    "bare feet",
    "bare foot",
    "barefoot",
    "bare legs",
    "bare arms",
    "bare shoulders",
    "bare midriff",
    "bare skin",
    "nude",
    "naked",
    "topless",
    "shirtless",
)

#: What an accessory is worn with when it is the only thing in the pin.
#:
#: **A necklace alone is not an outfit.** A pin can legitimately be
#: one piece - a scarf, a pair of socks, a single chain - and asking
#: an edit to dress a figure in only that leaves it either unchanged
#: or undressed, and the second is what the filter objects to. A
#: plain base lets the piece be seen on a body without competing
#: with it, and is described as plain so the model does not invent
#: something louder than the thing being tried on.
#: **Renamed away from `BASE_OUTFIT`, which it was silently
#: overwriting.** That name was already taken, forty lines up, by
#: what the *base figure* wears - and because this assignment runs
#: later at import time it won, so the avatar and the likeness were
#: quietly drawn in this t-shirt instead of the grey set they ask
#: for. Two constants, two jobs, two names.
#:
#: **Described rather than dictated.** A fixed outfit under every
#: accessory means white trainers, a gold necklace and an ochre
#: scarf all arrive over the same white tee, and two of those three
#: look wrong. Naming the *character* of the outfit and leaving the
#: pieces to the model costs nothing - it is words in a prompt that
#: was being sent anyway - and the model is choosing clothes to go
#: with something it can see.
UNDER_AN_ACCESSORY = (
    "a simple, well-matched everyday outfit in plain neutral tones that "
    "suits it and does not compete with it"
)

#: Pieces that need a base outfit under them.
_ON_TOP_OF_SOMETHING = (
    "jewellery", "jewelry", "necklace", "chain", "bracelet", "anklet",
    "ring", "earring", "watch", "scarf", "belt", "hat", "cap", "bag",
    "sunglasses", "glasses", "sock", "socks", "tights", "gloves",
    "shoe", "shoes", "boot", "boots", "trainer", "trainers", "sneaker",
    "sneakers", "sandals", "heels", "loafers", "brogues", "mules",
    "pendant", "pumps", "clutch", "tote", "handbag", "backpack",
    "headband", "bandana", "tie", "bowtie", "brooch", "cufflinks",
)


#: Phrases that describe the *photograph*, not the clothes.
#:
#: **The reported failure, and it was not subtle.** Trying on a pin
#: of white trainers produced an empty concrete room with the
#: trainers sitting on the floor - no figure at all. The stored
#: description was "A pair of white leather trainers, side on, on
#: pale concrete", which is a caption for a photograph, and passing
#: it to an edit as the thing to wear asks the model for that
#: photograph: side on, on pale concrete, and nobody in it.
#:
#: These phrases also defeated the accessory rule below. "on pale
#: concrete" is not an accessory, so a description made entirely of
#: shoes plus scenery did not read as accessories-only and never got
#: the base outfit that would have put it on a person.
#:
#: Matched as whole comma-separated clauses as well as inline, since
#: the describing model writes them both ways.
_ABOUT_THE_SHOT = (
    "side on", "side-on", "front on", "front-on", "three quarter",
    "three-quarter", "from above", "from below", "overhead", "top down",
    "top-down", "close up", "close-up", "flat lay", "flat-lay",
    "laid flat", "on a hanger", "hanging", "in the box", "unworn",
    "on pale concrete", "on concrete", "on a wooden floor", "on the floor",
    "on a table", "on a bed", "on a chair", "on a shelf", "on a rail",
    "on a plain background", "on a white background", "on a grey background",
    "against a wall", "against a white wall", "studio lit", "studio-lit",
    "natural light", "soft light", "shot on", "photographed",
)


def _only_the_clothes(said: str) -> str:
    """Strip what the photograph did, keeping what is being worn.

    Clause-first, because "A pair of trainers, side on, on pale
    concrete" is three clauses and two of them are about the camera
    and the floor. Whole clauses that are *only* scenery go; a clause
    that mentions scenery alongside a garment keeps the garment and
    loses the phrase.
    """
    kept: list[str] = []
    for clause in said.split(","):
        bit = clause.strip()
        if not bit:
            continue
        lowered = bit.lower()
        if any(phrase in lowered for phrase in _ABOUT_THE_SHOT) and not any(
            word in lowered for word in _WEARABLE_HINT
        ):
            continue
        for phrase in _ABOUT_THE_SHOT:
            lowered = lowered.replace(phrase, " ")
        tidied = " ".join(lowered.split()).strip(" ,.")
        if tidied:
            kept.append(tidied)
    return ", ".join(kept)


#: Enough of a garment word to save a clause from the scenery filter.
#:
#: Without this, "a white shirt against a white wall" is dropped
#: whole - losing the shirt to save us from the wall.
_WEARABLE_HINT = (
    "wear", "worn", "shirt", "tee", "t-shirt", "top", "blouse", "dress",
    "skirt", "trouser", "jean", "short", "jacket", "coat", "knit",
    "jumper", "sweater", "hoodie", "suit", "trainer", "sneaker", "shoe",
    "boot", "loafer", "sandal", "heel", "sock", "scarf", "bag", "belt",
    "hat", "cap", "necklace", "bracelet", "earring", "ring", "glove",
)


def wearable_words(outfit: str) -> str:
    """The clothes in a description, without the body wearing them.

    Two jobs, both learned from one refusal.

    **Body-part phrases are removed**, because an edit prompt that
    says "change the clothing to: bare feet with toe rings" is both
    an instruction nobody can follow and a prompt the vendor filters.

    **An accessory gets something to sit on.** If what is left is
    only jewellery, shoes or a scarf, a plain base outfit is added -
    a necklace on an otherwise undressed figure is the same refusal
    arriving a different way, and is not what anybody meant by "try
    it on" either.
    """
    said = (outfit or "").strip()
    if not said:
        return said

    # The scenery first. A caption describing where the photograph
    # was taken is the loudest instruction in the prompt, and it is
    # an instruction to draw the room rather than the person.
    said = _only_the_clothes(said) or said

    lowered = said.lower()
    for phrase in _NOT_CLOTHING:
        lowered = lowered.replace(phrase, "")
    # Tidy what removal left behind: doubled spaces, and a sentence
    # that now opens with "with" or a stray conjunction.
    cleaned = " ".join(lowered.split())
    for lead in ("with ", "and ", ", "):
        while cleaned.startswith(lead):
            cleaned = cleaned[len(lead) :].strip()
    cleaned = cleaned.strip(" ,.")
    if not cleaned:
        return UNDER_AN_ACCESSORY

    # Does anything here cover a body, or is it all worn *on* one?
    only_extras = all(
        any(word in part for word in _ON_TOP_OF_SOMETHING)
        for part in (bit.strip() for bit in cleaned.split(",") if bit.strip())
    )
    if only_extras:
        return f"{cleaned}, worn with {UNDER_AN_ACCESSORY}"
    return cleaned


def try_on_prompt(outfit: str) -> str:
    """Instruct an edit that changes the clothes and nothing else.

    Every clause after the first exists because an image edit will happily
    redraw the person given the chance, and an avatar that changes face
    between outfits is not an avatar.
    """
    return (
        # Cleaned here rather than at the call sites: every path that
        # reaches a try-on goes through this function, and a body-part
        # phrase slipping in from a new one would be the same 400
        # again.
        f"Change only the clothing to: {wearable_words(outfit)}.\n"
        # **Said outright, because the failure was the figure
        # vanishing.** A pin of white trainers came back as an empty
        # concrete room with the trainers on the floor: the stored
        # description was a caption for a photograph - "side on, on
        # pale concrete" - and the edit faithfully drew that
        # photograph. `wearable_words` now strips the scenery, and
        # this is the second lock, because the answer to "try it on"
        # is always somebody wearing it.
        "The person must stay in the picture, standing and fully dressed, "
        "wearing every piece named above. Never show the clothing on its "
        "own, laid out, on a surface, or in an empty room.\n"
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
