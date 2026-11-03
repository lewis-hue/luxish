"""Consent, and the properties that make it worth the name.

Until these endpoints existed, consent could be read but never set: the
provider registry refuses to route anything without `ai_processing` consent,
and nothing in the product could grant it. The stylist therefore reported that
the styling service was unavailable while it was working perfectly and
correctly declining. A gate with no handle is a feature nobody can use.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import consents
from app.models.consent import CONSENT_KINDS


async def _sign_in(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    r = await client.post("/v1/auth/session", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["user_id"]


async def test_withdrawing_is_exactly_as_easy_as_granting(
    client: httpx.AsyncClient, auth: Any
) -> None:
    """Same endpoint, same shape, one boolean.

    A consent that takes more effort to withdraw than to give was not freely
    given, and the asymmetry is usually built in by accident — a grant button
    on the screen and a withdrawal buried in support.
    """
    await _sign_in(client, auth(sub="kc-consent-1"))

    granted = await client.put(
        "/v1/consents/ai_processing",
        headers=auth(sub="kc-consent-1"),
        json={"granted": True},
    )
    assert granted.status_code == 200, granted.text
    assert granted.json()["granted"] is True

    withdrawn = await client.put(
        "/v1/consents/ai_processing",
        headers=auth(sub="kc-consent-1"),
        json={"granted": False},
    )
    assert withdrawn.status_code == 200
    assert withdrawn.json()["granted"] is False
    assert withdrawn.json()["revoked_at"] is not None


async def test_granting_twice_does_not_move_the_date(
    client: httpx.AsyncClient, auth: Any
) -> None:
    """The date somebody first agreed is the date they agreed."""
    await _sign_in(client, auth(sub="kc-consent-2"))
    first = await client.put(
        "/v1/consents/ai_processing",
        headers=auth(sub="kc-consent-2"),
        json={"granted": True},
    )
    again = await client.put(
        "/v1/consents/ai_processing",
        headers=auth(sub="kc-consent-2"),
        json={"granted": True},
    )
    assert first.json()["granted_at"] == again.json()["granted_at"]


async def test_every_kind_is_reported_so_never_asked_is_visible(
    client: httpx.AsyncClient, auth: Any
) -> None:
    """"Never asked" and "declined" are different facts about a person."""
    await _sign_in(client, auth(sub="kc-consent-3"))
    body = (
        await client.get("/v1/consents", headers=auth(sub="kc-consent-3"))
    ).json()

    assert {item["kind"] for item in body["items"]} == set(CONSENT_KINDS)
    for item in body["items"]:
        assert item["granted"] is False
        # Never asked: no grant, and no withdrawal either.
        assert item["granted_at"] is None
        assert item["revoked_at"] is None


async def test_one_consent_does_not_imply_another(
    client: httpx.AsyncClient, auth: Any
) -> None:
    """Agreeing to be styled is not agreeing to be published."""
    await _sign_in(client, auth(sub="kc-consent-4"))
    await client.put(
        "/v1/consents/ai_processing",
        headers=auth(sub="kc-consent-4"),
        json={"granted": True},
    )

    body = (
        await client.get("/v1/consents", headers=auth(sub="kc-consent-4"))
    ).json()
    granted = {item["kind"] for item in body["items"] if item["granted"]}
    assert granted == {"ai_processing"}


async def test_an_unknown_kind_is_refused_rather_than_stored(
    client: httpx.AsyncClient, auth: Any
) -> None:
    """A consent nothing reads is a consent nobody is honouring."""
    await _sign_in(client, auth(sub="kc-consent-5"))
    r = await client.put(
        "/v1/consents/telepathy",
        headers=auth(sub="kc-consent-5"),
        json={"granted": True},
    )
    assert r.status_code == 422
    assert r.json()["code"] == "unknown_consent_kind"


async def test_setting_consent_requires_a_session(client: httpx.AsyncClient) -> None:
    r = await client.put("/v1/consents/ai_processing", json={"granted": True})
    assert r.status_code == 401


async def test_withdrawal_keeps_the_history(db: AsyncSession) -> None:
    """"Was this processed with consent at the time?" stays answerable.

    Withdrawal stamps the row rather than deleting it, so the record of
    having agreed survives the decision to stop.
    """
    import uuid

    from app.models import User

    user = User(id=uuid.uuid4(), email="history@example.test")
    db.add(user)
    await db.commit()

    await consents.set_consent(
        db, user_id=user.id, kind="ai_processing", granted=True, source="stylist"
    )
    record = await consents.set_consent(
        db, user_id=user.id, kind="ai_processing", granted=False
    )

    assert record.granted_at is not None, "the fact of having agreed was erased"
    assert record.revoked_at is not None
    assert record.is_granted is False


async def test_an_unknown_kind_raises_rather_than_silently_passing(
    db: AsyncSession,
) -> None:
    import uuid

    from app.models import User

    user = User(id=uuid.uuid4(), email="unknown-kind@example.test")
    db.add(user)
    await db.commit()

    with pytest.raises(consents.UnknownConsentKind):
        await consents.set_consent(
            db, user_id=user.id, kind="not-a-kind", granted=True
        )
