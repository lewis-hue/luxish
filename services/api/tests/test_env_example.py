"""The committed example covers everything the API needs to start.

**A clean clone could not start the API.** The three `.env` files are
gitignored and no examples were committed, so a reviewer had none -
and `pin_host`, the one thing that touches those files, skips a file
that does not exist. The API raised on a missing `keycloak_issuer`
before serving a request.

Shipping an example fixed that and introduced a quieter version of
the same problem: an example that is missing one field fails in
exactly the same way, one field later. This is the test that keeps
the two in step, and it caught `keycloak_client_id` on the first
run.
"""

from __future__ import annotations

from pathlib import Path

from tests._repo import repo_root

from app.config import Settings

EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"


def _declared() -> set[str]:
    """The keys the example actually sets, comments and blanks aside."""
    found: set[str] = set()
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        found.add(line.split("=", 1)[0].strip())
    return found


def test_the_example_exists() -> None:
    assert EXAMPLE.is_file(), "a clean clone has nothing to copy from"


def test_every_required_setting_is_in_the_example() -> None:
    """A field with no default is a field the API refuses to start
    without, so the example has to carry it - even empty."""
    required = {
        f"LUXISH_{name.upper()}"
        for name, field in Settings.model_fields.items()
        if field.is_required()
    }
    missing = sorted(required - _declared())
    assert not missing, f"the example is missing {missing}"


def test_the_example_carries_no_secret() -> None:
    """It is committed. The model key is the one value that is the
    reviewer's own, and it ships empty on purpose."""
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        if line.startswith("LUXISH_META_API_KEY="):
            assert line.strip() == "LUXISH_META_API_KEY=", "a real key is committed in .env.example"
            return
    raise AssertionError("the model key is not mentioned at all")


def test_the_two_issuer_settings_are_spelled_the_same_way() -> None:
    """**They must agree or every call is a 401 `bad_issuer`.**

    Sign-in succeeds and then nothing works, which reads as a broken
    API rather than a config mismatch. `dev-stack.sh` rewrites both,
    so the examples only have to start consistent.
    """
    mobile = (repo_root() / "apps" / "mobile" / ".env.example").read_text(encoding="utf-8")
    api = EXAMPLE.read_text(encoding="utf-8")

    def value(text: str, key: str) -> str:
        for line in text.splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
        return ""

    assert value(api, "LUXISH_KEYCLOAK_ISSUER") == value(mobile, "EXPO_PUBLIC_KEYCLOAK_ISSUER")
