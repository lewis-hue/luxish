"""Entitlement and subscription shapes."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class EntitlementsOut(BaseModel):
    plan: Literal["free", "plus"]
    #: ``ending`` is active with renewal off: "expires on" is a different
    #: sentence from "renews on" and the client must know which to say.
    state: Literal["free", "active", "ending"]
    #: Where the subscription came from. ``simulated`` until real store
    #: credentials exist; null on the free plan.
    store: Literal["simulated", "app_store", "play_billing"] | None = None
    period_end: datetime | None = None
    auto_renew: bool
    #: Stylist runs per calendar month on this plan, and where the count
    #: stands. Derived from the run history, never stored.
    allowance: int
    used: int
    remaining: int
    resets_at: datetime
    #: True whenever the subscription is a development fixture. A client
    #: must surface this; a fixture must never read as a live integration.
    simulated: bool


class SimulatedSubscribeIn(BaseModel):
    plan: Literal["plus"] = "plus"


class AutoRenewIn(BaseModel):
    auto_renew: bool
