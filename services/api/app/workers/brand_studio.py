"""Brand visuals: a label's own product, photographed into a campaign.

The garment studio answers "what does this jumper look like on a person".
This answers the question a small label actually has: *give me a week of
content for this product.* Same pipeline, same billing, same storage - what
changes is that the prompt is composed rather than chosen from a fixed four.

**One source image, still.** The vendor's edit endpoint takes a single
image and no mask (verified 400s; see ``MetaProvider.edit_image``). Three
consequences shape everything below:

* The product in the frame is the *real* product, because it is the source
  pixels. That is the whole value: a generated picture of "a linen shirt"
  is a different shirt.
* A reference photograph cannot be a second input. So an inspiration fit
  from Discover is **read into words** by the text model and travels as a
  style note. The frame is composed in the spirit of the reference, not
  composited from it, and the API says so rather than implying otherwise.
* The instruction to leave the garment alone has to be in the prompt, and
  it goes last, where it is least likely to be overridden by the brief.

**A cast is asked for, never inferred.** Who is wearing the product is a
set of explicit choices a brand makes. Nothing here reads appearance off a
garment, a photograph or a prompt: unanswered means unspecified, and
unspecified means the edit decides, which is said out loud.

**Video is blocked, not planned-and-pretended.** Every model this service
can reach takes video *in* (``video_in=True``) and none emits it, so there
is no honest way to return a clip. :data:`VIDEO_STATUS` is returned by the
capability endpoint so a client renders the real answer instead of a button
that fails. A story is therefore a set of stills, which is what the
posting surfaces these are for actually take.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.workers.garment_studio import KEEP_THE_GARMENT, REALISM

#: Bumped when any wording below changes, so a stored frame records which
#: version produced it.
BRAND_PROMPT_VERSION = 1

#: What the capability endpoint says about moving pictures. Named here so
#: the wording lives with the reason rather than in a route handler.
VIDEO_STATUS = "blocked"
VIDEO_REASON = (
    "Video is not available. The image models this app can reach accept "
    "video as input and never produce it, so there is nothing to generate "
    "a clip with. A story comes back as a set of stills."
)

#: The longest brief accepted. Long enough for a real direction, short
#: enough that it cannot bury the clause protecting the product.
MAX_BRIEF = 600

#: The longest style note derived from a reference fit.
MAX_STYLE_NOTE = 400


@dataclass(frozen=True)
class Scene:
    """One frame a brand story can contain."""

    id: str
    label: str
    #: Said before a generation is spent on it.
    description: str
    #: The setting, framing and light. Never mentions the product: that
    #: clause is shared and goes last.
    setting: str
    #: What the frame is shaped for, so a client can group by use.
    use: str = "feed"
    #: Portrait for a story frame, square for a listing. Advisory: the
    #: model is asked for it in words, and the result is not cropped.
    aspect: str = "4:5"
    #: True when a person appears, which is when a cast means anything.
    wears: bool = False


SCENES: tuple[Scene, ...] = (
    Scene(
        id="lookbook",
        label="Lookbook",
        description="The product worn against a plain wall, lit like a studio.",
        setting=(
            "Photograph this exact garment worn by a person standing "
            "naturally against a plain warm off-white studio wall, framed "
            "from the knees up, weight on one leg, arms relaxed. Soft "
            "diffuse daylight from one side with a gentle fill opposite, a "
            "soft shadow falling to the floor behind."
        ),
        use="feed",
        aspect="4:5",
        wears=True,
    ),
    Scene(
        id="editorial",
        label="Editorial",
        description="A magazine frame: strong light, an unposed moment.",
        setting=(
            "Photograph this exact garment worn by a person in an editorial "
            "frame: the figure full length and placed off-centre with room "
            "above the head, caught mid-movement rather than posed. Hard "
            "late-afternoon sun through a window casting a sharp-edged "
            "shadow across a bare plaster wall."
        ),
        use="feed",
        aspect="4:5",
        wears=True,
    ),
    Scene(
        id="story_frame",
        label="Story frame",
        description="Tall and close, cropped for a full-screen story.",
        setting=(
            "Photograph this exact garment worn by a person in a tall "
            "vertical frame, cropped from the chest to mid-thigh so the "
            "garment fills most of the picture, the figure turning slightly "
            "away from the camera. Even soft window light, a plain muted "
            "wall a step behind."
        ),
        use="story",
        aspect="9:16",
        wears=True,
    ),
    Scene(
        id="flat_lay",
        label="Flat lay",
        description="The product laid out from above, styled with nothing else.",
        setting=(
            "Photograph this exact garment laid flat and squared to the "
            "camera, shot from directly overhead, filling the frame with a "
            "small even margin on every side. A plain paper-grey surface, "
            "soft even light from above, a faint contact shadow beneath the "
            "cloth so it rests on the surface rather than floating."
        ),
        use="catalogue",
        aspect="1:1",
    ),
    Scene(
        id="detail",
        label="Detail",
        description="Close on the cloth: the weave, a seam, a button.",
        setting=(
            "Photograph a close detail of this exact garment, filling the "
            "frame with cloth so the weave, the stitching and the hardware "
            "are legible at life size, shot at a slight angle so the "
            "surface catches a raking light. Shallow depth of field with "
            "the far side of the fold falling gently out of focus."
        ),
        use="catalogue",
        aspect="1:1",
    ),
    Scene(
        id="street",
        label="On the street",
        description="The product out in the world, in real daylight.",
        setting=(
            "Photograph this exact garment worn by a person walking on a "
            "quiet city street in late afternoon, full length and a little "
            "off-centre, mid-stride. Warm low golden-hour daylight raking "
            "down the street, long soft shadows, the background gently out "
            "of focus with legible but unreadable signage."
        ),
        use="feed",
        aspect="4:5",
        wears=True,
    ),
    Scene(
        id="cutout",
        label="Cutout",
        description="The product alone on white, for a listing.",
        setting=(
            "Isolate this exact garment on a plain pure white background, "
            "removing everything else in the photograph: the surface it "
            "rests on, any hanger, any hands, any props and any shadow cast "
            "on the old background. Keep its own edges crisp and complete "
            "including straps, ties and sleeves, and keep its own form and "
            "shading so it reads as a solid object rather than a flat "
            "sticker. A very faint soft shadow directly beneath it."
        ),
        use="catalogue",
        aspect="1:1",
    ),
)

SCENE_IDS: tuple[str, ...] = tuple(scene.id for scene in SCENES)


def scene_by_id(scene_id: str) -> Scene | None:
    return next((s for s in SCENES if s.id == scene_id), None)


@dataclass(frozen=True)
class StoryKind:
    """A ready-made set of frames.

    A brand picking "Launch a product" should not have to know that a
    launch wants a cutout, a flat lay and two worn frames. That knowledge
    is what this feature is for.
    """

    id: str
    label: str
    description: str
    scenes: tuple[str, ...]


STORY_KINDS: tuple[StoryKind, ...] = (
    StoryKind(
        id="launch",
        label="Launch a product",
        description=(
            "Everything a drop needs: the listing shot, the flat lay, and "
            "two frames of it being worn."
        ),
        scenes=("cutout", "flat_lay", "lookbook", "street"),
    ),
    StoryKind(
        id="campaign",
        label="Campaign",
        description="Three editorial frames that read as one shoot.",
        scenes=("editorial", "street", "detail"),
    ),
    StoryKind(
        id="stories",
        label="Stories",
        description="Tall frames for the full-screen slots, plus a detail.",
        scenes=("story_frame", "detail", "street"),
    ),
    StoryKind(
        id="catalogue",
        label="Catalogue",
        description="The three shots a shop listing wants, and nothing else.",
        scenes=("cutout", "flat_lay", "detail"),
    ),
)

STORY_KIND_IDS: tuple[str, ...] = tuple(kind.id for kind in STORY_KINDS)


def story_kind_by_id(kind_id: str) -> StoryKind | None:
    return next((k for k in STORY_KINDS if k.id == kind_id), None)


#: The cast fields, each a closed set of plain words. Closed rather than
#: free text because these go into a prompt: "whatever the brand typed" in
#: the clause that describes a person is how a generation feature ends up
#: producing something nobody would stand behind.
CAST_OPTIONS: dict[str, tuple[str, ...]] = {
    "age": ("20s", "30s", "40s", "50s", "60s or older"),
    "build": ("slim", "straight", "curve", "plus", "tall", "petite"),
    "skin": ("deep", "dark brown", "medium brown", "light brown", "olive", "fair"),
    "hair": (
        "short natural",
        "braids",
        "locs",
        "afro",
        "buzz cut",
        "shoulder length",
        "long straight",
        "headwrap",
        "hijab",
    ),
    "presentation": ("womenswear", "menswear", "unisex"),
}


@dataclass(frozen=True)
class Cast:
    """Who is wearing the product, as the brand chose.

    Every field is optional and nothing is guessed. An empty cast is a
    legitimate answer and means the edit decides, which the API says.
    """

    age: str | None = None
    build: str | None = None
    skin: str | None = None
    hair: str | None = None
    presentation: str | None = None

    @classmethod
    def from_choices(cls, raw: dict[str, str] | None) -> Cast:
        """Keep only recognised values.

        An unknown one is dropped rather than passed through: a prompt is
        not a place to echo client input.
        """
        picked = raw or {}
        clean: dict[str, str] = {}
        for field, allowed in CAST_OPTIONS.items():
            value = str(picked.get(field, "") or "").strip().lower()
            if value in allowed:
                clean[field] = value
        return cls(**clean)  # type: ignore[arg-type]

    def sentence(self) -> str:
        """The cast as a clause, or empty when nothing was chosen."""
        parts: list[str] = []
        if self.age:
            parts.append(f"in their {self.age}")
        if self.build:
            parts.append(f"a {self.build} build")
        if self.skin:
            parts.append(f"{self.skin} skin")
        if self.hair:
            parts.append(f"{self.hair} hair")
        if self.presentation and self.presentation != "unisex":
            parts.append(f"styled for {self.presentation}")
        if not parts:
            return ""
        return (
            "The person wearing it: "
            + ", ".join(parts)
            + ". Natural skin texture with visible pores, a few hairs out of "
            "place, an unposed expression."
        )


def clean_brief(raw: str | None) -> str:
    """The brand's own direction, trimmed to something that fits a prompt."""
    return (raw or "").strip()[:MAX_BRIEF]


def compose(
    *,
    scene: Scene,
    brief: str | None = None,
    cast: Cast | None = None,
    style_note: str | None = None,
) -> str:
    """Build one frame's prompt.

    Order is deliberate and is the only protection the product has:
    setting, then the cast, then the reference's spirit, then the brand's
    own words, and **last** the instruction to leave the garment exactly
    as it is. An edit follows its final instruction most closely, and the
    one thing that must survive is the product.
    """
    parts: list[str] = [scene.setting]

    if scene.wears and cast is not None:
        clause = cast.sentence()
        if clause:
            parts.append(clause)

    if style_note:
        parts.append(
            "Take the mood, light and styling in the spirit of this "
            f"reference: {style_note.strip()[:MAX_STYLE_NOTE]}"
        )

    direction = clean_brief(brief)
    if direction:
        parts.append(f"The brand's direction for this frame: {direction}")

    parts.append(f"Frame it roughly {scene.aspect}.")
    parts.append(REALISM)
    # Last, and deliberately so.
    parts.append(KEEP_THE_GARMENT)
    return " ".join(part.strip() for part in parts if part.strip())


#: What the text model is asked when a Discover fit is used as a reference.
#: It describes *light, colour and styling* and is told not to describe the
#: person: the output rides into an image prompt, and a description of
#: somebody's face and body would be a way to generate a likeness of a
#: person who posted a photograph for a different purpose.
STYLE_NOTE_INSTRUCTION = (
    "Describe this outfit photograph as a styling reference for a "
    "photographer, in at most three sentences. Cover only the light, the "
    "colour palette, the mood, the setting and how the clothes are styled "
    "and layered. Do not describe the person: not their face, body, skin, "
    "hair, age or identity. Do not name a brand. Do not mention any text or "
    "logo visible in the picture. Write plainly, with no preamble."
)


__all__ = [
    "BRAND_PROMPT_VERSION",
    "CAST_OPTIONS",
    "MAX_BRIEF",
    "MAX_STYLE_NOTE",
    "SCENES",
    "SCENE_IDS",
    "STORY_KINDS",
    "STORY_KIND_IDS",
    "STYLE_NOTE_INSTRUCTION",
    "VIDEO_REASON",
    "VIDEO_STATUS",
    "Cast",
    "Scene",
    "StoryKind",
    "clean_brief",
    "compose",
    "scene_by_id",
    "story_kind_by_id",
]
