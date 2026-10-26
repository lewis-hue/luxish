"""The one SSRF-guarded fetcher (ADR-009).

Every server-side URL touch goes through here. The shape of the guard matters
more than any single rule, so it is stated plainly:

1. **Scheme allowlist.** ``http`` and ``https`` only, and no credentials in the
   URL.
2. **We resolve DNS ourselves** and require *every* returned address to be
   globally routable. Checking only the first address, or trusting the
   hostname, leaves DNS rebinding wide open.
3. **We connect to the validated address**, not to the name, and send the
   original ``Host`` (plus SNI for TLS). Resolving twice — once to check, once
   by the HTTP client — is the classic TOCTOU hole.
4. **Every redirect repeats steps 1-3.** A 200 on the first hop is not
   permission for the second; ``http://evil/`` → ``http://169.254.169.254/`` is
   the attack this closes.
5. **Hard ceilings**: at most ``MAX_REDIRECTS`` hops, a byte cap enforced while
   streaming (not after buffering), and a total timeout.
6. **The declared content type must be allowed *and* must agree with the
   sniffed bytes.** A header is a claim, not evidence.
"""

from __future__ import annotations

import ipaddress
import json
import socket
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpx

ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})
MAX_REDIRECTS = 3
DEFAULT_TIMEOUT_SECONDS = 5.0
#: How many bytes are enough to sniff every type we accept.
SNIFF_BYTES = 512

Resolver = Callable[[str, int], Sequence[str]]


class UnsafeUrl(Exception):
    """The URL, or something it led to, was refused.

    ``reason`` is a stable token for logs and tests; the message is for humans.
    """

    def __init__(self, message: str, *, reason: str = "unsafe_url") -> None:
        self.reason = reason
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class FetchResult:
    url: str
    final_url: str
    status_code: int
    content_type: str | None
    body: bytes = field(repr=False)
    redirect_count: int = 0

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------- #
# addresses
# --------------------------------------------------------------------------- #
def is_public_ip(address: str) -> bool:
    """True only for a globally routable unicast address.

    ``ip.is_global`` already excludes loopback, link-local (so
    ``169.254.169.254``), private, reserved, multicast and the unspecified
    address; the explicit checks below state the intent and cover v4-mapped v6.
    """
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_private
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return False
    return bool(ip.is_global)


def assert_public_ip(address: str) -> None:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError as exc:
        raise UnsafeUrl(f"{address!r} is not an IP address", reason="bad_address") from exc
    if ip.is_link_local or (
        isinstance(ip, ipaddress.IPv6Address)
        and ip.ipv4_mapped is not None
        and ip.ipv4_mapped.is_link_local
    ):
        # Named separately because this is the cloud metadata endpoint.
        raise UnsafeUrl(f"{address} is link-local", reason="link_local_address")
    if not is_public_ip(address):
        raise UnsafeUrl(f"{address} is not a public address", reason="private_address")


def default_resolver(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeUrl(f"{host!r} did not resolve", reason="dns_failure") from exc
    return [info[4][0] for info in infos]


# --------------------------------------------------------------------------- #
# content sniffing
# --------------------------------------------------------------------------- #
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"%PDF-", "application/pdf"),
)


def sniff_content_type(body: bytes) -> str | None:
    """Best-effort type of the actual bytes, or None if we cannot tell."""
    if not body:
        return None
    for magic, content_type in _MAGIC:
        if body.startswith(magic):
            return content_type
    if body[:12].startswith(b"RIFF") and body[8:12] == b"WEBP":
        return "image/webp"
    head = body[:SNIFF_BYTES].lstrip()
    lowered = head.lower()
    if lowered.startswith((b"<!doctype html", b"<html", b"<head", b"<body", b"<!-- ")):
        return "text/html"
    if head.startswith((b"{", b"[")):
        try:
            json.loads(body.decode("utf-8", errors="strict"))
        except (ValueError, UnicodeDecodeError):
            return None
        return "application/json"
    if lowered.startswith(b"<?xml"):
        return "application/xml"
    try:
        head.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None
    if b"\x00" in head:
        return None
    return "text/plain"


def _families_agree(declared: str, sniffed: str | None) -> bool:
    if sniffed is None:
        # Nothing recognisable: accept only for types where that is normal.
        return not declared.startswith(("text/", "application/json", "application/xml"))
    if declared == sniffed:
        return True
    # Text types are interchangeable enough that a mismatch is not evidence of
    # a lie; a declared text/* carrying a PNG is.
    text_like = {"text/html", "text/plain", "application/xml", "application/json"}
    return declared in text_like and sniffed in text_like


# --------------------------------------------------------------------------- #
# the fetch
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class _Target:
    scheme: str
    host: str
    port: int
    path_and_query: str
    address: str

    @property
    def dial_url(self) -> str:
        host = f"[{self.address}]" if ":" in self.address else self.address
        default_port = 80 if self.scheme == "http" else 443
        authority = host if self.port == default_port else f"{host}:{self.port}"
        return f"{self.scheme}://{authority}{self.path_and_query}"

    @property
    def display_url(self) -> str:
        default_port = 80 if self.scheme == "http" else 443
        authority = self.host if self.port == default_port else f"{self.host}:{self.port}"
        return f"{self.scheme}://{authority}{self.path_and_query}"

    @property
    def host_header(self) -> str:
        default_port = 80 if self.scheme == "http" else 443
        return self.host if self.port == default_port else f"{self.host}:{self.port}"


def _validate(url: str, *, resolver: Resolver) -> _Target:
    """Apply every pre-connection check and pin the address to dial."""
    if not url or not url.strip():
        raise UnsafeUrl("empty URL", reason="malformed_url")
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrl(f"scheme {scheme!r} is not allowed", reason="scheme_not_allowed")
    if parts.username or parts.password:
        raise UnsafeUrl("credentials in URL are not allowed", reason="credentials_in_url")
    host = (parts.hostname or "").strip()
    if not host:
        raise UnsafeUrl("URL has no host", reason="malformed_url")
    try:
        port = parts.port or (80 if scheme == "http" else 443)
    except ValueError as exc:
        raise UnsafeUrl("URL has an invalid port", reason="malformed_url") from exc

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None

    if literal is not None:
        assert_public_ip(host)
        addresses = [host]
    else:
        addresses = list(resolver(host, port))
        if not addresses:
            raise UnsafeUrl(f"{host!r} did not resolve", reason="dns_failure")
        # Every address, not just the first: one private answer poisons the name.
        for address in addresses:
            assert_public_ip(address)

    path_and_query = parts.path or "/"
    if parts.query:
        path_and_query = f"{path_and_query}?{parts.query}"

    return _Target(
        scheme=scheme,
        host=host,
        port=port,
        path_and_query=path_and_query,
        address=addresses[0],
    )


async def safe_fetch(
    url: str,
    *,
    max_bytes: int,
    allow_content_types: Sequence[str],
    max_redirects: int = MAX_REDIRECTS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    resolver: Resolver = default_resolver,
    transport: httpx.AsyncBaseTransport | None = None,
    headers: dict[str, str] | None = None,
) -> FetchResult:
    """Fetch ``url`` under every guard in the module docstring.

    Raises :class:`UnsafeUrl` for anything refused. An HTTP error status is a
    result, not a refusal — the caller decides what a 404 means.
    """
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    allowed = {ct.split(";", 1)[0].strip().lower() for ct in allow_content_types}

    current = url
    redirects = 0
    async with httpx.AsyncClient(
        transport=transport,
        timeout=timeout_seconds,
        follow_redirects=False,  # we follow by hand so every hop is re-checked
        max_redirects=0,
    ) as client:
        while True:
            target = _validate(current, resolver=resolver)
            request_headers = {
                "Host": target.host_header,
                "Accept-Encoding": "identity",
                "User-Agent": "Atelier-LinkPreview/0.1",
                **(headers or {}),
            }
            request = client.build_request(
                "GET",
                target.dial_url,
                headers=request_headers,
                extensions={"sni_hostname": target.host},
            )
            response = await client.send(request, stream=True)
            try:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location")
                    if not location:
                        raise UnsafeUrl("redirect without a Location", reason="bad_redirect")
                    redirects += 1
                    if redirects > max_redirects:
                        raise UnsafeUrl(
                            f"more than {max_redirects} redirects", reason="too_many_redirects"
                        )
                    # Resolve relative to the *display* URL so the hostname, not
                    # the pinned address, is what a relative Location joins to.
                    current = urljoin(target.display_url, location)
                    continue

                declared = (response.headers.get("Content-Type") or "").split(";", 1)[0]
                declared = declared.strip().lower()
                if declared not in allowed:
                    raise UnsafeUrl(
                        f"content type {declared!r} is not allowed",
                        reason="content_type_not_allowed",
                    )

                length = response.headers.get("Content-Length")
                if length and length.isdigit() and int(length) > max_bytes:
                    raise UnsafeUrl(
                        f"declared {length} bytes exceeds the {max_bytes} cap",
                        reason="too_large",
                    )

                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        # Stop reading rather than buffering the rest.
                        raise UnsafeUrl(
                            f"body exceeds the {max_bytes} byte cap", reason="too_large"
                        )
            finally:
                await response.aclose()

            sniffed = sniff_content_type(bytes(body))
            if not _families_agree(declared, sniffed):
                raise UnsafeUrl(
                    f"declared {declared!r} but the bytes look like {sniffed!r}",
                    reason="content_type_mismatch",
                )

            return FetchResult(
                url=url,
                final_url=target.display_url,
                status_code=response.status_code,
                content_type=declared or None,
                body=bytes(body),
                redirect_count=redirects,
            )


__all__ = [
    "ALLOWED_SCHEMES",
    "DEFAULT_TIMEOUT_SECONDS",
    "MAX_REDIRECTS",
    "FetchResult",
    "UnsafeUrl",
    "assert_public_ip",
    "default_resolver",
    "is_public_ip",
    "safe_fetch",
    "sniff_content_type",
]
