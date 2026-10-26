"""Task 10 — the SSRF-guarded fetcher (Review Focus item 4).

The guard resolves DNS itself, asserts every resolved address is public,
connects to that address while preserving the ``Host`` header, and repeats the
whole check after every redirect. The first hop passing is not permission for
the second.

No live network is used: a resolver and an HTTP transport are injected, and the
transport asserts what the guard actually dialled.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.security.urlfetch import (
    MAX_REDIRECTS,
    UnsafeUrl,
    assert_public_ip,
    is_public_ip,
    safe_fetch,
    sniff_content_type,
)

HTML = b"<!doctype html><html><head><title>t</title></head><body>hi</body></html>"
PUBLIC_IP = "93.184.216.34"


def resolver(mapping: dict[str, list[str]]):
    """A stand-in for DNS. Unknown names fail to resolve, as they would live."""

    def _resolve(host: str, port: int) -> list[str]:
        try:
            return mapping[host]
        except KeyError:
            raise UnsafeUrl(f"{host} did not resolve", reason="dns_failure") from None

    return _resolve


def transport_for(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


# --------------------------------------------------------------------------- #
# refusals that happen before a single byte is read
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://127.0.0.1:8000/healthz",  # loopback
        "http://10.0.0.5/",  # private
        "http://192.168.1.1/",  # private
        "http://172.16.0.1/",  # private
        "http://[::1]/",  # v6 loopback
        "http://[fd00::1]/",  # v6 unique-local
        "http://[fe80::1]/",  # v6 link-local
        "http://0.0.0.0/",  # unspecified
        "http://metadata.google.internal/computeMetadata/v1/",  # GCP metadata
        "file:///etc/passwd",  # scheme
        "gopher://x/",  # scheme
        "ftp://example.com/x",  # scheme
        "http://user:pass@example.com/",  # credentials in URL
        "notaurl",
        "",
    ],
)
async def test_unsafe_targets_are_refused(url: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError(f"the fetcher must not dial {request.url}")

    with pytest.raises(UnsafeUrl):
        await safe_fetch(
            url,
            max_bytes=1024,
            allow_content_types=["text/html"],
            resolver=resolver({"metadata.google.internal": ["169.254.169.254"]}),
            transport=transport_for(handler),
        )


async def test_a_public_name_resolving_to_a_private_address_is_refused() -> None:
    """DNS rebinding: the name looks fine, the address does not."""

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("must not dial")

    with pytest.raises(UnsafeUrl) as exc:
        await safe_fetch(
            "http://inside.example.com/",
            max_bytes=1024,
            allow_content_types=["text/html"],
            resolver=resolver({"inside.example.com": ["10.1.2.3"]}),
            transport=transport_for(handler),
        )
    assert exc.value.reason == "private_address"


async def test_every_resolved_address_must_be_public_not_just_the_first() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("must not dial")

    with pytest.raises(UnsafeUrl):
        await safe_fetch(
            "http://split.example.com/",
            max_bytes=1024,
            allow_content_types=["text/html"],
            resolver=resolver({"split.example.com": [PUBLIC_IP, "127.0.0.1"]}),
            transport=transport_for(handler),
        )


# --------------------------------------------------------------------------- #
# the happy path, and how it dials
# --------------------------------------------------------------------------- #
async def test_the_request_goes_to_the_resolved_ip_with_the_original_host() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["host"] = request.headers.get("Host")
        return httpx.Response(200, content=HTML, headers={"Content-Type": "text/html"})

    result = await safe_fetch(
        "http://example.com/page",
        max_bytes=1024,
        allow_content_types=["text/html"],
        resolver=resolver({"example.com": [PUBLIC_IP]}),
        transport=transport_for(handler),
    )

    assert result.status_code == 200
    assert result.body == HTML
    # Pinned to the address we validated, with the name preserved for the server.
    assert seen["url"] == f"http://{PUBLIC_IP}/page"
    assert seen["host"] == "example.com"
    assert result.final_url == "http://example.com/page"


async def test_the_resolved_port_is_preserved() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, content=HTML, headers={"Content-Type": "text/html"})

    await safe_fetch(
        "http://example.com:8080/page",
        max_bytes=1024,
        allow_content_types=["text/html"],
        resolver=resolver({"example.com": [PUBLIC_IP]}),
        transport=transport_for(handler),
    )
    assert seen["url"] == f"http://{PUBLIC_IP}:8080/page"


# --------------------------------------------------------------------------- #
# redirects — re-checked every time
# --------------------------------------------------------------------------- #
async def test_redirect_into_private_range_is_refused_after_200() -> None:
    """The first hop passing is not permission for the second."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path == "/ok":
            return httpx.Response(200, content=HTML, headers={"Content-Type": "text/html"})
        if request.url.path == "/a":
            return httpx.Response(302, headers={"Location": "http://169.254.169.254/"})
        raise AssertionError(f"unexpected dial: {request.url}")

    fetch: dict[str, Any] = {
        "max_bytes": 1024,
        "allow_content_types": ["text/html"],
        "resolver": resolver({"example.com": [PUBLIC_IP]}),
        "transport": transport_for(handler),
    }

    # A clean 200 first, proving the transport works and the guard allows it.
    first = await safe_fetch("http://example.com/ok", **fetch)
    assert first.status_code == 200

    # Then the same host 302s into the metadata service.
    with pytest.raises(UnsafeUrl) as exc:
        await safe_fetch("http://example.com/a", **fetch)
    assert exc.value.reason in {"private_address", "link_local_address"}
    # The redirect target was never dialled.
    assert not any("169.254.169.254" in call for call in calls)


async def test_a_redirect_to_a_rebound_hostname_is_re_resolved() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/a":
            return httpx.Response(302, headers={"Location": "http://inside.example.com/"})
        raise AssertionError(f"unexpected dial: {request.url}")

    with pytest.raises(UnsafeUrl):
        await safe_fetch(
            "http://example.com/a",
            max_bytes=1024,
            allow_content_types=["text/html"],
            resolver=resolver(
                {"example.com": [PUBLIC_IP], "inside.example.com": ["192.168.0.9"]}
            ),
            transport=transport_for(handler),
        )


async def test_a_redirect_to_a_forbidden_scheme_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "file:///etc/passwd"})

    with pytest.raises(UnsafeUrl) as exc:
        await safe_fetch(
            "http://example.com/a",
            max_bytes=1024,
            allow_content_types=["text/html"],
            resolver=resolver({"example.com": [PUBLIC_IP]}),
            transport=transport_for(handler),
        )
    assert exc.value.reason == "scheme_not_allowed"


async def test_redirects_are_capped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        index = int(request.url.params.get("i", "0"))
        return httpx.Response(
            302, headers={"Location": f"http://example.com/hop?i={index + 1}"}
        )

    with pytest.raises(UnsafeUrl) as exc:
        await safe_fetch(
            "http://example.com/hop?i=0",
            max_bytes=1024,
            allow_content_types=["text/html"],
            resolver=resolver({"example.com": [PUBLIC_IP]}),
            transport=transport_for(handler),
        )
    assert exc.value.reason == "too_many_redirects"
    assert MAX_REDIRECTS == 3


async def test_a_redirect_without_a_location_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302)

    with pytest.raises(UnsafeUrl):
        await safe_fetch(
            "http://example.com/a",
            max_bytes=1024,
            allow_content_types=["text/html"],
            resolver=resolver({"example.com": [PUBLIC_IP]}),
            transport=transport_for(handler),
        )


async def test_a_relative_redirect_is_followed_and_still_checked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/a":
            return httpx.Response(302, headers={"Location": "/b"})
        return httpx.Response(200, content=HTML, headers={"Content-Type": "text/html"})

    result = await safe_fetch(
        "http://example.com/a",
        max_bytes=1024,
        allow_content_types=["text/html"],
        resolver=resolver({"example.com": [PUBLIC_IP]}),
        transport=transport_for(handler),
    )
    assert result.final_url == "http://example.com/b"
    assert result.redirect_count == 1


# --------------------------------------------------------------------------- #
# byte ceiling and content type
# --------------------------------------------------------------------------- #
async def test_oversized_body_is_refused_not_buffered() -> None:
    chunks_served = 0

    def handler(request: httpx.Request) -> httpx.Response:
        async def stream():
            nonlocal chunks_served
            for _ in range(100):
                chunks_served += 1
                yield b"x" * 1024

        return httpx.Response(
            200, content=stream(), headers={"Content-Type": "text/html"}
        )

    with pytest.raises(UnsafeUrl) as exc:
        await safe_fetch(
            "http://example.com/10mb",
            max_bytes=1024,
            allow_content_types=["text/html"],
            resolver=resolver({"example.com": [PUBLIC_IP]}),
            transport=transport_for(handler),
        )
    assert exc.value.reason == "too_large"
    # It stopped early rather than buffering the whole body.
    assert chunks_served < 100


async def test_a_declared_content_length_over_the_cap_is_refused_before_reading() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=HTML,
            headers={"Content-Type": "text/html", "Content-Length": "999999"},
        )

    with pytest.raises(UnsafeUrl) as exc:
        await safe_fetch(
            "http://example.com/big",
            max_bytes=1024,
            allow_content_types=["text/html"],
            resolver=resolver({"example.com": [PUBLIC_IP]}),
            transport=transport_for(handler),
        )
    assert exc.value.reason == "too_large"


async def test_an_undeclared_content_type_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=HTML, headers={"Content-Type": "application/pdf"})

    with pytest.raises(UnsafeUrl) as exc:
        await safe_fetch(
            "http://example.com/x",
            max_bytes=1024,
            allow_content_types=["text/html"],
            resolver=resolver({"example.com": [PUBLIC_IP]}),
            transport=transport_for(handler),
        )
    assert exc.value.reason == "content_type_not_allowed"


async def test_sniffed_bytes_must_agree_with_the_declared_type() -> None:
    """A declared text/html carrying a PNG is a lie worth refusing."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"\x89PNG\r\n\x1a\n" + b"\x00" * 64,
            headers={"Content-Type": "text/html"},
        )

    with pytest.raises(UnsafeUrl) as exc:
        await safe_fetch(
            "http://example.com/x",
            max_bytes=4096,
            allow_content_types=["text/html"],
            resolver=resolver({"example.com": [PUBLIC_IP]}),
            transport=transport_for(handler),
        )
    assert exc.value.reason == "content_type_mismatch"


async def test_a_genuine_image_is_accepted_when_allowed() -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=png, headers={"Content-Type": "image/png"})

    result = await safe_fetch(
        "http://example.com/i.png",
        max_bytes=4096,
        allow_content_types=["image/png"],
        resolver=resolver({"example.com": [PUBLIC_IP]}),
        transport=transport_for(handler),
    )
    assert result.content_type == "image/png"
    assert result.body == png


async def test_an_error_status_is_returned_not_raised() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, content=b"gone", headers={"Content-Type": "text/html"})

    result = await safe_fetch(
        "http://example.com/missing",
        max_bytes=1024,
        allow_content_types=["text/html"],
        resolver=resolver({"example.com": [PUBLIC_IP]}),
        transport=transport_for(handler),
    )
    assert result.status_code == 404


# --------------------------------------------------------------------------- #
# the address predicate, directly
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.5.4",
        "192.168.0.1",
        "169.254.169.254",
        "0.0.0.0",
        "255.255.255.255",
        "224.0.0.1",
        "100.64.0.1",  # carrier-grade NAT
        "::1",
        "fe80::1",
        "fd00::1",
        "::ffff:127.0.0.1",  # v4-mapped loopback
        "::",
    ],
)
def test_non_public_addresses_are_rejected(address: str) -> None:
    assert is_public_ip(address) is False
    with pytest.raises(UnsafeUrl):
        assert_public_ip(address)


@pytest.mark.parametrize("address", ["93.184.216.34", "1.1.1.1", "2606:4700::1111"])
def test_public_addresses_are_accepted(address: str) -> None:
    assert is_public_ip(address) is True
    assert_public_ip(address)


def test_sniffing_recognises_the_shapes_we_accept() -> None:
    assert sniff_content_type(HTML) == "text/html"
    assert sniff_content_type(b"\x89PNG\r\n\x1a\n") == "image/png"
    assert sniff_content_type(b"\xff\xd8\xff\xe0") == "image/jpeg"
    assert sniff_content_type(b"GIF89a") == "image/gif"
    assert sniff_content_type(b'{"a": 1}') == "application/json"
    assert sniff_content_type(b"\x00\x01\x02binary") is None
