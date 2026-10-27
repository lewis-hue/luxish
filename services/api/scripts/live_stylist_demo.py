"""One real styling run against the live Meta Model API.

Proves the thing the unit suite cannot: that the bounded loop, the tool phase,
the owned-id guard and the persistence all work against the *actual* model
rather than a scripted stub. The unit tests prove our logic; this proves our
logic matches the vendor's behaviour.

Costs a few cents. Run it deliberately:

    MODEL_API_KEY=LLM_... python scripts/live_stylist_demo.py

Uses an in-memory SQLite database seeded with a small wardrobe, so it touches
no real user data and leaves nothing behind.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

os.environ.setdefault("LUXISH_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("LUXISH_GCS_BUCKET", "local-demo")
os.environ.setdefault("LUXISH_KEYCLOAK_ISSUER", "http://localhost:8080/realms/luxish")
os.environ.setdefault("LUXISH_KEYCLOAK_CLIENT_ID", "luxish-mobile")
if key := os.environ.get("MODEL_API_KEY"):
    os.environ.setdefault("LUXISH_META_API_KEY", key)

from app.db.base import Base  # noqa: E402
from app.domain import stylist  # noqa: E402
from app.models import Consent, Garment, User  # noqa: E402
from app.models.ai_run import AIRun  # noqa: E402
from app.providers.base import AIRunRecorder  # noqa: E402
from app.providers.meta import MetaProvider  # noqa: E402
from app.providers.registry import default_registry  # noqa: E402

#: A wardrobe with a deliberate trap: it contains heels, and the request says
#: no heels. A model that simply returns plausible-looking clothes will fail.
WARDROBE = [
    ("Ivory silk shirt", "shirt", {"colour": "ivory", "formality": "business"}),
    ("Navy wool trousers", "trousers", {"colour": "navy", "formality": "business"}),
    ("Charcoal blazer", "blazer", {"colour": "charcoal", "formality": "business"}),
    ("Black leather heels", "heels", {"colour": "black", "formality": "business"}),
    ("Brown leather loafers", "loafers", {"colour": "brown", "formality": "smart_casual"}),
    ("White leather trainers", "trainers", {"colour": "white", "formality": "casual"}),
    ("Camel wool coat", "coat", {"colour": "camel", "formality": "business"}),
]

REQUEST = "Something for the office tomorrow. No heels, I'll be walking a lot."


async def main() -> int:
    if not os.environ.get("MODEL_API_KEY"):
        print("MODEL_API_KEY is not set. Refusing to pretend this ran.")
        return 2

    engine = create_async_engine(os.environ["LUXISH_DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async with maker() as session:
        user = User(id=uuid.uuid4(), email="demo@luxish.example", display_name="Demo")
        session.add(user)
        await session.flush()

        # Without this the registry refuses every provider with reason
        # "consent" and the run fails as provider_unavailable, which is the
        # correct behaviour: nothing is sent to a model until the user agrees.
        session.add(
            Consent(
                id=uuid.uuid4(),
                user_id=user.id,
                kind="ai_processing",
                granted_at=datetime.now(UTC),
                source="demo_script",
            )
        )

        for name, category, attrs in WARDROBE:
            session.add(
                Garment(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    name=name,
                    category=category,
                    availability="available",
                    confirmed_attributes=attrs,
                    inferred_attributes={},
                )
            )
        await session.commit()

        print(f"wardrobe: {len(WARDROBE)} garments")
        print(f'request:  "{REQUEST}"')
        print()

        run = await stylist.start_run(
            session, user_id=user.id, text=REQUEST, place="Nairobi", queue=False
        )
        print(f"run {run.id} created, state={run.state}")

        registry = default_registry(meta=MetaProvider(recorder=AIRunRecorder(session)))
        view = await stylist.execute_run(session, run.id, registry=registry)

        print(f"state:            {view.state}")
        print(f"explanation_code: {view.explanation_code}")
        print(f"tool calls used:  {getattr(view, 'tool_calls_used', 'n/a')}")
        detail = getattr(view, "detail", None)
        if detail:
            print(f"detail:           {detail}")
        print()

        for r in (await session.scalars(sa.select(AIRun))).all():
            print(
                f"  AIRun {r.model} purpose={r.purpose} outcome={r.outcome} "
                f"in={r.input_tokens} out={r.output_tokens} err={r.error_code!r}"
            )

        outfit = getattr(view, "outfit", None)
        if outfit is None:
            print("no outfit returned")
        else:
            print("OUTFIT")
            for item in outfit.items:
                owned = "owned" if getattr(item, "owned", False) else "not owned"
                label = getattr(item, "name", None) or getattr(item, "garment_id", "?")
                print(f"  - {label}  [{getattr(item, 'role', '?')}, {owned}]")
            why = getattr(outfit, "explanation", None) or getattr(outfit, "rationale", None)
            if why:
                print(f"\n  why: {why}")

        # The trap: assert the model's answer actually honoured the constraint.
        names = " ".join(
            str(getattr(i, "name", "") or "") for i in (outfit.items if outfit else [])
        ).lower()
        if "heel" in names:
            print("\nFAIL: a heel is in the outfit despite 'no heels'")
            return 1
        print("\nconstraint honoured: no heels in the outfit")

        runs = (await session.scalars(sa.select(AIRun))).all()
        total = sum(r.cost_micro_minor or 0 for r in runs) / 1_000_000 / 100
        print(f"\nAI runs recorded: {len(runs)}, cost ${total:.4f}")

    await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
