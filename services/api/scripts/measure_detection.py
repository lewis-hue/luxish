"""What outfit detection actually spends, measured against the live model.

`OUTFIT_MAX_TOKENS` is a safe ceiling that was never measured. It is not a
budget the model tries to fill, but it is the number the service reserves
against the per-minute allowance, so a ceiling four times the real cost means
four times fewer uploads get through before the queue rate-limits itself. It
is also what stands between a prompt that has gone wrong and an expensive
loop.

Lowering it is only safe with a measurement, and the failure mode if it is set
too low is the one this codebase has already hit three times: reasoning tokens
count against the same budget, the model spends them all before emitting
anything, and the run comes back empty with ``finish_reason: length`` rather
than with an error that names the cause.

So: run every sample photograph through the real detector, record what each
one actually spent, and print the floor, the ceiling and what they imply.

    MODEL_API_KEY=LLM_... python scripts/measure_detection.py

Costs a few cents per run.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("LUXISH_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("LUXISH_GCS_BUCKET", "local-measure")
if key := os.environ.get("MODEL_API_KEY"):
    os.environ.setdefault("LUXISH_META_API_KEY", key)

import sqlalchemy as sa  # noqa: E402,F401
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.models import *  # noqa: E402,F401,F403  — registers every table
from app.providers.base import AIRunRecorder  # noqa: E402
from app.providers.meta import MetaProvider  # noqa: E402
from app.workers.outfit import (  # noqa: E402
    OUTFIT_MAX_TOKENS,
    MetaOutfitDetector,
)

IMAGES = (
    Path(__file__).resolve().parents[3] / "apps" / "mobile" / "assets" / "images"
)


def samples() -> list[Path]:
    """Real photographs, not fixtures: single garments and full outfits both."""
    wardrobe = sorted((IMAGES / "wardrobe").glob("*.webp"))
    styles = sorted((IMAGES / "styles").glob("*.webp"))[:6]
    return [*wardrobe[:8], *styles]


async def main() -> int:
    if not os.environ.get("LUXISH_META_API_KEY"):
        print("set MODEL_API_KEY to run this against the live model.")
        return 2

    # An in-memory database purely so the recorder has somewhere to write.
    # The provider refuses an unaccounted call, which is the correct rule and
    # applies to a measurement exactly as it does to a request.
    engine = create_async_engine(os.environ["LUXISH_DATABASE_URL"])
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    session = sessions()

    provider = MetaProvider(recorder=AIRunRecorder(session))
    detector = MetaOutfitDetector(provider)

    rows: list[tuple[str, int, int, int, float, str]] = []
    for path in samples():
        image = path.read_bytes()
        started = time.monotonic()
        try:
            response = await provider.complete(
                detector.build_request(image=image, content_type="image/webp")
            )
        except Exception as exc:  # noqa: BLE001 — a measurement, not a service
            print(f"{path.name:34} FAILED {exc}")
            continue
        elapsed = time.monotonic() - started
        usage = response.usage
        rows.append(
            (
                path.name,
                usage.input_tokens,
                usage.output_tokens,
                # Printed because it is almost all of the completion and
                # explains the latency, but *not* added: it is already
                # inside `output_tokens`.
                usage.reasoning_tokens,
                elapsed,
                response.finish_reason or "",
            )
        )
        print(
            f"{path.name:30} in={usage.input_tokens:6} out={usage.output_tokens:5} "
            f"reasoning={usage.reasoning_tokens:5} {elapsed:5.1f}s "
            f"{response.finish_reason or ''}"
        )

    if not rows:
        print("nothing measured.")
        return 1

    # `output_tokens` alone, because that is `completion_tokens` and the
    # vendor reports `reasoning_tokens` as a *breakdown* of it
    # (`completion_tokens_details.reasoning_tokens`), not as an addition.
    # Summing the two double-counts the reasoning and makes the ceiling look
    # half as generous as it is — verified against the adapter's mapping in
    # `providers/meta.py`, not assumed.
    out = [row[2] for row in rows]
    seconds = [row[4] for row in rows]
    truncated = [row[0] for row in rows if row[5] == "length"]

    print()
    print(f"runs           : {len(rows)}")
    print(f"completion     : min {min(out)}  max {max(out)}  mean {sum(out) / len(out):.0f}")
    print(f"latency        : min {min(seconds):.1f}s  max {max(seconds):.1f}s")
    print(f"current ceiling: {OUTFIT_MAX_TOKENS}")
    print(f"headroom at max: {OUTFIT_MAX_TOKENS / max(out):.1f}x")
    if truncated:
        print(f"TRUNCATED      : {', '.join(truncated)} — the ceiling is already too low")
    else:
        # Doubling the measured worst case is the convention this codebase
        # arrived at the hard way: reasoning tokens are invisible here and
        # vary with the photograph, so a tight ceiling fails silently.
        print(f"suggested      : {max(out) * 2} (2x the measured worst case)")
    await session.close()
    await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
