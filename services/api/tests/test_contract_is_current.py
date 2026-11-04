"""The committed contract has to describe the code that is committed.

`packages/contracts/openapi.json` is the source the mobile client's
types are generated from, and it is a file in the repository rather
than something fetched at build time. That is deliberate - a clone
should typecheck without a backend running - but it means the file
can fall behind the code, and nothing noticed when it did.

**Nothing noticed when it did.** Four schemas were out of step for a
session: `TasteIn.occasions` capped at six when the service had
raised it, `TasteOptions.max_occasions` absent, and `NotificationOut`
missing `studio_ready` and `render_ready`. The two bugs those changes
fixed were a save that failed validation and an inbox that answered
500, so a stale contract hands a reviewer back the exact faults the
code no longer has.

Checked in-process, against `app.openapi()`, so the guard needs no
running server and no network. `packages/contracts` regenerates the
TypeScript from this same file, and its own `check` script compares
that output, so the chain is: code -> this file -> schema.d.ts, with
a test on each link.
"""

from __future__ import annotations

import json

from app.main import app

from tests._repo import repo_root

CONTRACT = repo_root() / "packages" / "contracts" / "openapi.json"

REGENERATE = (
    "Restart the API so it serves the current code, then from "
    "packages/contracts: `npm run fetch-spec && npm run generate`. "
    "Commit both openapi.json and src/schema.d.ts."
)


def _committed() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def _operations(spec: dict) -> set[str]:
    verbs = {"get", "post", "put", "patch", "delete"}
    return {
        f"{verb.upper()} {path}"
        for path, item in spec.get("paths", {}).items()
        for verb in item
        if verb in verbs
    }


def test_the_contract_file_exists_in_a_clone() -> None:
    """A clone typechecks without a backend, which is why this is committed."""
    assert CONTRACT.is_file(), f"{CONTRACT} is missing; the mobile types come from it"


def test_every_endpoint_is_in_the_contract() -> None:
    """The direction that breaks a client at runtime.

    An endpoint the contract does not know about has no generated
    type, so the screen calling it either does not compile or calls it
    untyped.
    """
    missing = sorted(_operations(app.openapi()) - _operations(_committed()))
    assert not missing, f"endpoints absent from the contract: {missing}. {REGENERATE}"


def test_the_contract_promises_nothing_the_api_does_not_serve() -> None:
    """The direction that produces a 404 a reviewer reads as a broken feature."""
    extra = sorted(_operations(_committed()) - _operations(app.openapi()))
    assert not extra, f"the contract describes endpoints that do not exist: {extra}. {REGENERATE}"


def test_no_schema_has_drifted() -> None:
    """Shapes, not just paths.

    Paths matching is not enough: the four schemas that went stale
    had the right paths and the wrong fields, which is the kind of
    drift that only shows up as a validation failure in the reviewer's
    hands.
    """
    generated = app.openapi().get("components", {}).get("schemas", {})
    committed = _committed().get("components", {}).get("schemas", {})

    absent = sorted(set(generated) - set(committed))
    stale = sorted(set(committed) - set(generated))
    differing = sorted(k for k in set(generated) & set(committed) if generated[k] != committed[k])

    assert not absent, f"schemas the contract has never seen: {absent}. {REGENERATE}"
    assert not stale, f"schemas the code no longer defines: {stale}. {REGENERATE}"
    assert not differing, f"schemas whose shape has changed: {differing}. {REGENERATE}"


def test_the_contract_matches_the_code_exactly() -> None:
    """The whole document, so nothing drifts in a corner no other test reads.

    Titles, descriptions, security schemes and response codes all end
    up in the generated types. Comparing the whole thing costs one
    equality check and removes the question of which parts matter.
    """
    assert app.openapi() == _committed(), (
        "the committed contract is not what this code generates. " + REGENERATE
    )
