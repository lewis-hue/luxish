#!/usr/bin/env python3
"""Fail if anything credential-shaped is committed.

A cheap backstop, not a replacement for a real secret scanner. It looks for the
specific shapes this project uses, and asserts the positive property for realm
config — that every secret is a `${VAR}` placeholder resolved at import — rather
than trying to pattern-match what a leaked secret looks like.

Run locally:  python scripts/check_no_committed_secrets.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Meta Model API keys are prefixed `LLM_` followed by a long numeric team id.
META_KEY = re.compile(r"LLM_\d{6,}")
#: A GCP service-account JSON always carries this key.
SERVICE_ACCOUNT_KEY = re.compile(r'"private_key"\s*:')

#: Paths where these strings are legitimately discussed rather than used.
DOC_SUFFIXES = {".md", ".mdx"}
ALLOWED_DIRS = {".github", "scripts", "docs"}


def tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [REPO_ROOT / name for name in out.split("\0") if name]


def is_prose(path: Path) -> bool:
    if path.suffix.lower() in DOC_SUFFIXES:
        return True
    relative = path.relative_to(REPO_ROOT)
    return bool(relative.parts) and relative.parts[0] in ALLOWED_DIRS


def scan_contents(findings: list[str]) -> None:
    for path in tracked_files():
        if is_prose(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary asset or unreadable; nothing to match
        relative = path.relative_to(REPO_ROOT)
        if META_KEY.search(text):
            findings.append(f"{relative}: looks like a committed Meta Model API key")
        if SERVICE_ACCOUNT_KEY.search(text):
            findings.append(f"{relative}: looks like a committed service-account key")


def scan_realm_placeholders(findings: list[str]) -> None:
    """Every secret in a Keycloak realm export must be a `${VAR}` placeholder."""
    import_dir = REPO_ROOT / "infra" / "keycloak" / "import"
    for path in sorted(import_dir.glob("*.json")):
        realm = json.loads(path.read_text(encoding="utf-8"))
        relative = path.relative_to(REPO_ROOT)

        def check(secret: object, what: str) -> None:
            if secret is None:
                return
            if not (
                isinstance(secret, str) and secret.startswith("${") and secret.endswith("}")
            ):
                findings.append(f"{relative}: {what} is a literal, not a ${{VAR}} placeholder")

        for client in realm.get("clients", []):
            check(client.get("secret"), f"client {client.get('clientId')!r} secret")
        for provider in realm.get("identityProviders", []):
            check(
                provider.get("config", {}).get("clientSecret"),
                f"identity provider {provider.get('alias')!r} clientSecret",
            )


def main() -> int:
    findings: list[str] = []
    scan_contents(findings)
    scan_realm_placeholders(findings)

    for finding in findings:
        # GitHub Actions annotation format; harmless locally.
        print(f"::error::{finding}")

    if findings:
        print(f"\n{len(findings)} potential credential issue(s) found.", file=sys.stderr)
        return 1

    print("No committed credentials found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
