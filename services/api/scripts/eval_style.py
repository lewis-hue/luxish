"""Measure the style classifier against hand-labelled photographs.

This exists because nothing in the project measured accuracy. Every claim
about classification so far rested on looking at one result and deciding it
seemed right, which is how a model that is 60% correct passes review.

The corpus is `datasets/style/`, whose folders a human labelled. Those folders
encode style crossed with the wearer's identity — the same clothes appear as
"MEN CASUAL", "WOMEN CASUAL" and "LGBT CASUAL WEAR" — so they are collapsed to
style here. Keeping them apart would mean scoring the model on whether it can
read gender or orientation off clothing, which it cannot and should not.

    MODEL_API_KEY=LLM_... python scripts/eval_style.py            # 5 per class
    MODEL_API_KEY=LLM_... python scripts/eval_style.py --all      # everything

Costs roughly $0.002 per image. The default sample keeps a full run to a few
cents; `--all` is 227 images and should be run deliberately.
"""

from __future__ import annotations

import asyncio
import os
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Windows consoles default to cp1252, and the corpus filenames are scraped
# from the web: em dashes, curly quotes, emoji. Without this the run dies on
# a `print` after the model calls are already paid for, which is the most
# expensive possible place to hit an encoding bug.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CORPUS = REPO / "datasets" / "style"

#: Every answer, written as it arrives.
#:
#: A full run is 227 paid calls, and before this existed a crash after image
#: 66 threw away everything it had already bought. It also makes the run
#: re-analysable — the confusion table can be recomputed, or a boundary
#: re-examined, without paying for the images again.
RESULTS = REPO / "datasets" / "style-eval.jsonl"

_results_handle = None


def record(row: dict) -> None:
    global _results_handle
    if _results_handle is None:
        _results_handle = RESULTS.open("w", encoding="utf-8")
    import json

    _results_handle.write(json.dumps(row) + chr(10))
    _results_handle.flush()

#: Folder name to style. The identity prefixes a labeller used are dropped on
#: purpose; see the module docstring.
FOLDER_TO_STYLE: dict[str, str] = {
    "LGBT CASUAL WEAR": "casual",
    "MEN CASUAL": "casual",
    "WOMEN CASUAL": "casual",
    "LGBT STREET WEAR": "streetwear",
    "MEN STREETWEAR": "streetwear",
    "WOMEN STREETWEAR": "streetwear",
    "LGBT SPORT WEAR": "sport",
    "MEN SPORT WEAR": "sport",
    "WOMEN SPORT WEAR": "sport",
    "LGBT ELEGANT WEAR": "elegant",
    "MEN ELEGANT": "elegant",
    "WOMEN ELEGANT": "elegant",
    "LGBT OFFICIAL WEAR": "official",
    "MEN OFFICIAL": "official",
    "WOMEN OFFICIAL": "official",
    "OCCASIONS OUTFIT FOR WOMEN": "occasion",
    "OCCATION OUTFITS": "occasion",
    "MODEST OUTFITS": "modest",
    "AFRICAN WEAR FOR BOTH MEN AND WOMEN": "heritage",
    # Deliberately unmapped: a colour-pairing reference, not a style of dress.
    # Scoring a style classifier on it would measure nothing.
    # "COLORS YOU CAN MATCH": excluded
}

SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def labelled() -> list[tuple[Path, str]]:
    items: list[tuple[Path, str]] = []
    for folder, style in FOLDER_TO_STYLE.items():
        directory = CORPUS / folder
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if path.suffix.lower() in SUFFIXES:
                items.append((path, style))
    return items


def sample(items: list[tuple[Path, str]], per_class: int) -> list[tuple[Path, str]]:
    by_style: dict[str, list[tuple[Path, str]]] = defaultdict(list)
    for item in items:
        by_style[item[1]].append(item)
    # Seeded, so two runs of the same size score the same photographs and a
    # prompt change is measured against a moved prompt rather than a moved set.
    rng = random.Random(20261029)
    chosen: list[tuple[Path, str]] = []
    for style in sorted(by_style):
        pool = by_style[style]
        rng.shuffle(pool)
        chosen.extend(pool[:per_class])
    return chosen


async def main() -> int:
    if key := os.environ.get("MODEL_API_KEY"):
        os.environ.setdefault("LUXISH_META_API_KEY", key)
    if not os.environ.get("LUXISH_META_API_KEY"):
        print("MODEL_API_KEY is not set. Refusing to pretend this ran.")
        return 2

    if not CORPUS.is_dir():
        print(f"No corpus at {CORPUS}")
        return 2

    items = labelled()
    if "--all" not in sys.argv:
        items = sample(items, per_class=5)
    print(f"corpus : {CORPUS}")
    print(f"scoring: {len(items)} photographs\n")

    from app.db.session import session_scope
    from app.providers.base import AIRunRecorder
    from app.providers.meta import MetaProvider
    from app.workers.style import STYLE_LABELS, MetaStyleClassifier

    confusion: dict[tuple[str, str], int] = Counter()
    failures: list[tuple[Path, str]] = []
    low_confidence = 0

    async with session_scope() as session:
        classifier = MetaStyleClassifier(MetaProvider(recorder=AIRunRecorder(session)))
        for index, (path, truth) in enumerate(items, start=1):
            content_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
            try:
                result = await classifier.classify_style(
                    image=path.read_bytes(), content_type=content_type
                )
            except Exception as exc:  # noqa: BLE001 - a failure is a result
                failures.append((path, f"{type(exc).__name__}: {exc}"))
                record(
                    {
                        "file": str(path.relative_to(CORPUS)),
                        "truth": truth,
                        "error": f"{type(exc).__name__}: {exc}"[:200],
                    }
                )
                print(
                    f"  [{index:>3}/{len(items)}] {truth:<11} FAILED  "
                    f"{type(exc).__name__}: {str(exc)[:110]}"
                )
                continue
            record(
                {
                    "file": str(path.relative_to(CORPUS)),
                    "truth": truth,
                    "got": result.style,
                    "confidence": result.confidence,
                }
            )
            confusion[(truth, result.style)] += 1
            if result.confidence < 0.5:
                low_confidence += 1
            mark = "ok " if result.style == truth else "MISS"
            print(
                f"  [{index:>3}/{len(items)}] {truth:<11} -> {result.style:<11} "
                f"{mark} {result.confidence:.2f}  {path.name[:34]}"
            )

    scored = sum(confusion.values())
    if not scored:
        print("\nNothing was scored.")
        return 1
    correct = sum(count for (truth, got), count in confusion.items() if truth == got)

    print(f"\n{'=' * 62}")
    print(f"accuracy        : {correct}/{scored} = {correct / scored:.1%}")
    print(f"low confidence  : {low_confidence}/{scored}")
    if failures:
        print(f"failed outright : {len(failures)}")

    print("\nper style (recall):")
    for style in STYLE_LABELS:
        total = sum(c for (truth, _), c in confusion.items() if truth == style)
        if not total:
            continue
        hit = confusion.get((style, style), 0)
        print(f"  {style:<12} {hit:>3}/{total:<3} {hit / total:>6.0%}")

    print("\nwhere it goes wrong (truth -> predicted, 2 or more):")
    for (truth, got), count in sorted(confusion.items(), key=lambda kv: -kv[1]):
        if truth != got and count >= 2:
            print(f"  {truth:<12} -> {got:<12} {count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
