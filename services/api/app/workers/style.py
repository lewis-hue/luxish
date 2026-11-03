"""Reading the *style* of a worn outfit, as opposed to the garments in it.

:mod:`app.workers.categorise` answers "what is this garment?" and
:mod:`app.workers.outfit` answers "what garments are in this photograph?".
Neither answers the question Discover is organised around: what *kind* of
outfit is this. That is what this does, against a closed set of styles.

**On the label set.** It is derived from a hand-labelled corpus whose folders
encoded style crossed with the wearer's identity: the same clothes appeared as
"MEN CASUAL", "WOMEN CASUAL" and "LGBT CASUAL WEAR". Those are one style, and
training on them as three would mean building something that claims to read
gender or sexual orientation off clothing. It cannot, and a fashion app has no
business attempting it — the outfit detector's own prompt already forbids
reporting anything about the person. So the identity prefixes are dropped and
the styles are kept, which is both the correct behaviour and the better
dataset: eight classes of 13 to 40 images rather than twenty of nought to 16.

**On "training".** The model behind this is hosted inference with no training
endpoint (ADR-006, ADR-007), so nothing here is fine-tuned. The corpus is used
for the two things it genuinely supports: measuring accuracy, which this
project had no way to do before, and grounding the prompt in the vocabulary a
human labeller actually used.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from app.config import get_settings
from app.providers.base import AIMessage, AIRequest, Capabilities, JsonSchemaFormat
from app.workers.categorise import data_uri, prepare_image

#: The styles this will report. Closed, so nothing outside it can reach the
#: wardrobe however the model phrases its answer.
#:
#: `occasion` and `elegant` are deliberately separate: a labeller used both,
#: and they differ in a way that matters to someone getting dressed. Elegant is
#: a register you can choose on a Tuesday; occasion is a dress code imposed by
#: an event.
STYLE_LABELS: tuple[str, ...] = (
    "casual",
    "streetwear",
    "sport",
    "elegant",
    "official",
    "occasion",
    "modest",
    "heritage",
)

STYLE_MODEL = "muse-spark-1.3"
STYLE_PROMPT_VERSION = "style.v2"
STYLE_PURPOSE = "wardrobe.classify_style"

#: Generous for the same reason every other cap in this service is: the
#: ceiling covers *reasoning* tokens, which this model spends before it emits
#: anything, and a cap sized to the JSON returns an empty string with
#: `finish_reason: length`.
#:
#: Measured rather than guessed. At 2048, ten of forty evaluation images came
#: back empty once the prompt grew to spell out the eight styles; the answer
#: itself is two fields. 4096 returned all forty.
STYLE_MAX_TOKENS = 4096

STYLE_SYSTEM = (
    "You name the style of an outfit in a photograph, for a wardrobe app.\n"
    "\n"
    "Judge the clothes and nothing else. Never report, imply, or take "
    "into account the wearer's body, age, gender, ethnicity, or "
    "appearance. Two people in the same clothes are wearing the same "
    "style.\n"
    "\n"
    "The styles, in the order to test them. Take the first that fits:\n"
    "\n"
    "- heritage: traditional or cultural dress. African print, Ankara, "
    "asoebi, kaftans, or tailoring in a regional tradition. The fabric or "
    "cut is the point.\n"
    "- modest: coverage is the defining choice. Long sleeves and long "
    "hems together, loose silhouettes, layering that deliberately covers. "
    "Judge this on coverage alone, not on how refined the outfit is.\n"
    "- sport: sportswear. Tracksuits, sweatsuits, hoodies and joggers as "
    "a set, gym and training kit, technical or jersey fabric, performance "
    "trainers. Counts whether worn to train or worn as everyday clothes.\n"
    "- occasion: dressed for a specific event. Gowns, cocktail dresses, "
    "wedding and party wear, clothes that would be conspicuous on an "
    "ordinary day.\n"
    "- official: a workplace dress code. Matched suiting, blazer with "
    "tailored trousers, shirting, polished leather shoes. Clothes worn "
    "because work requires them.\n"
    "- elegant: refined, but freely chosen rather than required. "
    "Considered proportion, draping, fine knit, quiet tailoring worn "
    "outside work.\n"
    "- streetwear: fashion-led casual with a subcultural edge. Oversized "
    "silhouettes, graphics and logos, cargo trousers, statement trainers, "
    "baggy denim. Not simply any casual outfit, and not a tracksuit, "
    "which is sport.\n"
    "- casual: ordinary everyday clothes with no particular edge. Plain "
    "denim, knitwear, simple tops, unremarkable trainers.\n"
    "\n"
    "The order matters: a kaftan is heritage rather than modest, a "
    "covered outfit is modest rather than elegant, and a tracksuit is "
    "sport rather than streetwear.\n"
    "\n"
    "Report low confidence rather than guessing when the photograph does "
    "not show enough of the outfit to tell."
)

STYLE_USER_TEXT = "Name the style of the outfit in this photograph."

STYLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["style", "confidence"],
    "properties": {
        "style": {
            "type": "string",
            "enum": list(STYLE_LABELS),
            "description": "The single closest style, from the closed list.",
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": (
                "How clearly the photograph shows this. Low when the outfit "
                "is cropped, obscured, or could as easily be another style."
            ),
        },
    },
}

STYLE_RESPONSE_FORMAT = JsonSchemaFormat(
    name="outfit_style", json_schema=STYLE_SCHEMA, strict=True
)


class MalformedStyle(RuntimeError):
    """The model answered with something outside the contract."""


@dataclass(frozen=True, slots=True)
class StyleResult:
    style: str
    confidence: float
    model: str
    prompt_version: str

    def __post_init__(self) -> None:
        if self.style not in STYLE_LABELS:
            raise MalformedStyle(f"{self.style!r} is not one of {STYLE_LABELS}")


class StyleClassifier(Protocol):
    async def classify_style(
        self, *, image: bytes, content_type: str, user_id: uuid.UUID | None = None
    ) -> StyleResult: ...


class MetaStyleClassifier:
    """:class:`StyleClassifier` backed by the Meta chat model."""

    def __init__(
        self,
        provider: Any,
        *,
        model: str = STYLE_MODEL,
        prompt_version: str = STYLE_PROMPT_VERSION,
    ) -> None:
        self._provider = provider
        self._model = model
        self._prompt_version = prompt_version

    async def classify_style(
        self, *, image: bytes, content_type: str, user_id: uuid.UUID | None = None
    ) -> StyleResult:
        # Built the same way the garment classifier builds its request, down
        # to `prepare_image`: that is where downscaling and the content-type
        # correction live, and a second hand-rolled encoder here would be a
        # second place for the vendor's limits to be got wrong.
        sent, sent_type = prepare_image(image, content_type=content_type)
        response = await self._provider.complete(
            AIRequest(
                model=self._model,
                system=STYLE_SYSTEM,
                messages=(
                    AIMessage(
                        "user",
                        [
                            {"type": "text", "text": STYLE_USER_TEXT},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": data_uri(sent, content_type=sent_type)
                                },
                            },
                        ],
                    ),
                ),
                needs=Capabilities(
                    text_in=True, image_in=True, text_out=True, structured_output=True
                ),
                response_format=STYLE_RESPONSE_FORMAT,
                max_completion_tokens=STYLE_MAX_TOKENS,
                reasoning_effort=get_settings().model_reasoning_effort,
                prompt_version=self._prompt_version,
                purpose=STYLE_PURPOSE,
            ),
            user_id=user_id,
        )

        text = (response.text or "").strip()
        if not text:
            raise MalformedStyle(
                f"{self._model} returned no text "
                f"(finish_reason={response.finish_reason!r})"
            )
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise MalformedStyle(f"not JSON: {text[:160]}") from exc

        return StyleResult(
            style=str(payload.get("style") or ""),
            confidence=float(payload.get("confidence") or 0.0),
            model=self._model,
            prompt_version=self._prompt_version,
        )


__all__ = [
    "STYLE_LABELS",
    "STYLE_MAX_TOKENS",
    "STYLE_MODEL",
    "STYLE_PROMPT_VERSION",
    "STYLE_PURPOSE",
    "STYLE_SCHEMA",
    "STYLE_SYSTEM",
    "MalformedStyle",
    "MetaStyleClassifier",
    "StyleClassifier",
    "StyleResult",
]
