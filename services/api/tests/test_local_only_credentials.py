"""The demo password cannot reach anything that is not this laptop.

`infra/keycloak/import/luxish-realm.json` ships a reviewer account,
`me@luxish.local` / `admin123`, so that a clean clone can be signed
into without a setup step. An automated review flagged it, correctly,
as a hardcoded credential.

It stays, because it is what the account is for and because the
blast radius is one container on the reviewer's own machine: the
import is mounted by `infra/docker-compose.yml` and by nothing else,
and the deployed stack provisions Keycloak through Terraform with
generated passwords.

That last sentence is the whole safety argument, so it is a test
rather than a comment. If the import ever becomes reachable from a
deployment path, this fails and the password has to go.
"""

from __future__ import annotations

import json
from tests._repo import repo_root

REPO = repo_root()
REALM = REPO / "infra" / "keycloak" / "import" / "luxish-realm.json"

#: The one file allowed to mount the import directory.
LOCAL_ONLY = "infra/docker-compose.yml"


def _mounts() -> list[str]:
    """Every tracked file that mounts the realm import directory."""
    found: list[str] = []
    for path in REPO.rglob("*"):
        if not path.is_file() or path.suffix not in {".yml", ".yaml", ".tf"}:
            continue
        rel = path.relative_to(REPO).as_posix()
        if "node_modules" in rel or ".venv" in rel:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:  # pragma: no cover - unreadable file
            continue
        if "keycloak/import" in text or "data/import" in text:
            found.append(rel)
    return sorted(found)


def test_the_realm_import_is_mounted_only_by_the_local_stack() -> None:
    assert _mounts() == [LOCAL_ONLY], (
        f"the realm import is reachable from {_mounts()}. It carries a "
        "known password; it may only be mounted by the local stack."
    )


def test_the_deployed_stack_does_not_read_the_import() -> None:
    """Terraform provisions Keycloak itself, with generated
    passwords. If it ever imported this realm the demo account would
    exist in a deployed environment."""
    terraform = REPO / "infra" / "terraform"
    for path in terraform.rglob("*.tf"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert "luxish-realm" not in text, f"{path.name} reads the realm import"


def test_the_account_says_what_it_is_for() -> None:
    """So the next person to find it knows the argument above exists
    rather than assuming it was an oversight."""
    users = json.loads(REALM.read_text(encoding="utf-8")).get("users") or []
    assert len(users) == 1, "only the one review account belongs here"
    purpose = " ".join(users[0].get("attributes", {}).get("luxish:purpose", []))
    assert "local" in purpose.lower()
    assert "docker-compose" in purpose


def test_no_other_account_is_shipped_with_a_password() -> None:
    """One known credential is a documented demo. Two is a habit."""
    users = json.loads(REALM.read_text(encoding="utf-8")).get("users") or []
    with_passwords = [
        u["username"]
        for u in users
        if any(c.get("type") == "password" for c in u.get("credentials", []))
    ]
    assert with_passwords == ["me@luxish.local"]
