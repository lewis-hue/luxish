"""Where to buy a piece, looked up on the open web.

**What this replaces.** "Find shops near me" asked a map which shops
within a radius sell clothes. That answers a different question from
the one somebody is asking: they do not want *a clothes shop*, they
want *this jacket*. A list of three boutiques in town, none of which
stock a brown suede trucker with a shearling collar, is the wrong
answer delivered confidently.

So the gap itself is the query, carrying what the stylist said was
missing and the look it was missing from.

**Why DuckDuckGo and not Google.** The instruction was plain web
search, no paid API, and that is what this is. Both were tried from
this machine: Google answers 200 and its markup carries no
extractable result links - consent-walled and obfuscated, and
anything that did parse would break on their next deploy.
DuckDuckGo's `lite` endpoint is a short, stable HTML document whose
results are ordinary anchors, and it indexes the same open web. No
key, no account, no quota to run out mid-demo.

**Three states, not two.** The lesson from the shops lookup that
cached a 502 as "there are no shops here": *could not ask* is not
*asked and found nothing*. `Found.reached` carries which it was, and
the caller says something different for each.

**Nothing is scraped beyond the result list.** Titles, links and the
retailer's own domain - the things a search page is for. No product
pages are fetched, no prices are claimed, and no images are copied.
What somebody gets is a link to a shop that appears to sell the
thing, which is what they asked for.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import urllib.parse
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

#: Named so the operators of a free service can see who is calling and
#: complain to somebody. A blank or spoofed agent on a public endpoint
#: is how an app gets the endpoint closed for everybody.
AGENT = (
    "LUXish/1.0 (wardrobe app; shopping lookup for a named garment; "
    "contact: support@luxish.app)"
)

ENDPOINT = "https://lite.duckduckgo.com/lite/"

#: Long enough for a slow search, short enough that the reply the user
#: is reading does not wait on it. The lookup is already a separate
#: round trip for exactly this reason.
TIMEOUT_S = 12.0

#: How many links are worth showing under one gap. Past about four a
#: shopping list stops being a suggestion and becomes homework.
MOST_LINKS = 4

#: Hosts that are never a place to buy a garment.
#:
#: Search results for a clothing phrase are full of magazine round-ups
#: and image boards. They are interesting and they are not shops, and
#: offering one under "where to get them" is a dead end.
NOT_SHOPS = frozenset(
    {
        "wikipedia.org", "reddit.com", "quora.com", "pinterest.com",
        "youtube.com", "tiktok.com", "instagram.com", "facebook.com",
        "x.com", "twitter.com", "esquire.com", "gq.com", "vogue.com",
        "harpersbazaar.com", "elle.com", "cosmopolitan.com",
        "buzzfeed.com", "medium.com", "blogspot.com", "wordpress.com",
    }
)


@dataclass(frozen=True)
class Shop:
    """One place that appears to sell the thing."""

    title: str
    url: str
    #: `thursdayboots.com`. Shown instead of the full URL, which is
    #: unreadable at the width of a chat bubble.
    seller: str


@dataclass
class Found:
    """What came back, and whether the question was asked at all."""

    #: What was searched for, so the caller can label the group.
    gap: str
    shops: list[Shop] = field(default_factory=list)
    #: False when the search could not be reached. Distinct from an
    #: empty list, which means it answered and found nothing.
    reached: bool = True


def query_for(gap: str, *, look: str | None = None) -> str:
    """The search text for one missing piece.

    The gap leads because it is the thing being bought. A few words of
    the look follow when there are any, which is what makes this
    better than a bare product search: "cream trousers" alone returns
    everything, while the look narrows it to the right cut and weight.

    "buy" rather than "shop" or "for sale": it is the word retail
    pages actually use, so it pulls product listings up and editorial
    down without an operator the engine may ignore.
    """
    words = [gap.strip()]
    if look:
        # Only a little of it. A whole caption as a query matches
        # nothing, because no page contains that sentence.
        trimmed = " ".join(look.split()[:6]).strip(" .,")
        if trimmed:
            words.append(trimmed)
    words.append("buy")
    return " ".join(w for w in words if w)


_unescape = html.unescape

#: `//duckduckgo.com/l/?uddg=<escaped target>&rut=...`
_LINK = re.compile(r'href="//duckduckgo\.com/l/\?uddg=([^"&]+)[^"]*"')
_TITLE = re.compile(r"class='result-link'>(.*?)</a>", re.S)
_TAGS = re.compile(r"<[^>]+>")


#: Titles that announce a guide rather than a shop.
#:
#: **A domain list was not enough.** `NOT_SHOPS` catches the big
#: magazines, and the long tail is endless - "How To Wear Brown Belt
#: Like A Pro", "25 Outfit Ideas On How to Wear a Brown Bag", "How to
#: Wear a Necklace With a Collared Shirt" all came back from real
#: searches on sites nobody would think to block by name. They are
#: articles about the garment, which is a dead end under "where to
#: get them", and they are recognisable from the title in a way the
#: domain cannot express.
_A_GUIDE = re.compile(
    r"^\s*(how to|\d+\s+(best|outfit|ways|styles))"
    r"|outfit ideas|styling (ideas|tips|guide)"
    r"|style guide|what to wear|how to wear",
    re.IGNORECASE,
)


def looks_like_a_guide(title: str) -> bool:
    """Whether a result is an article about the thing, not a shop."""
    return bool(_A_GUIDE.search(title or ""))


def seller_of(url: str) -> str:
    """`https://www.nordstrom.com/x` -> `nordstrom.com`."""
    host = urllib.parse.urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _is_a_shop(host: str) -> bool:
    return not any(host == bad or host.endswith(f".{bad}") for bad in NOT_SHOPS)


def read_results(html: str, *, limit: int = MOST_LINKS) -> list[Shop]:
    """Pull the result list out of a lite search page.

    Tolerant by construction: a markup change that breaks the title
    pattern yields links with their seller as the label rather than
    nothing at all, because a link with a plain name is still useful
    and an exception here would take the whole reply down.
    """
    links = _LINK.findall(html)
    # Unescaped, or a title arrives as "Coats &amp; Jackets". The
    # module is shadowed by the parameter name, hence the alias.
    titles = [
        _unescape(_TAGS.sub("", raw)).strip() for raw in _TITLE.findall(html)
    ]
    out: list[Shop] = []
    seen: set[str] = set()
    for at, escaped in enumerate(links):
        url = urllib.parse.unquote(escaped)
        if not url.startswith(("http://", "https://")):
            continue
        host = seller_of(url)
        if not host or not _is_a_shop(host) or host in seen:
            continue
        title = titles[at] if at < len(titles) and titles[at] else host
        # An article about the garment is not somewhere to buy it.
        if looks_like_a_guide(title):
            continue
        seen.add(host)
        out.append(Shop(title=title[:120], url=url, seller=host))
        if len(out) >= limit:
            break
    return out


async def where_to_buy(
    gaps: list[str],
    *,
    look: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[Found]:
    """Look each missing piece up, concurrently.

    One `Found` per gap and in the order asked, so the caller can pair
    them with the list the stylist produced without matching on text.
    A gap whose search failed comes back `reached=False` rather than
    empty, and never raises: a shopping list is an extra under an
    answer that has already arrived, and it must not be able to take
    that answer down.
    """
    if not gaps:
        return []

    owned = client is None
    http = client or httpx.AsyncClient(
        timeout=TIMEOUT_S,
        headers={"User-Agent": AGENT},
        follow_redirects=True,
    )

    async def one(gap: str) -> Found:
        try:
            response = await http.get(ENDPOINT, params={"q": query_for(gap, look=look)})
            if response.status_code != 200:
                logger.warning(
                    "shopping search for %r answered %s", gap, response.status_code
                )
                return Found(gap=gap, reached=False)
            return Found(gap=gap, shops=read_results(response.text))
        except Exception as caught:  # noqa: BLE001 - reported, never raised
            logger.warning("shopping search for %r failed: %s", gap, caught)
            return Found(gap=gap, reached=False)

    try:
        return list(await asyncio.gather(*(one(gap) for gap in gaps)))
    finally:
        if owned:
            await http.aclose()


__all__ = [
    "AGENT",
    "ENDPOINT",
    "MOST_LINKS",
    "NOT_SHOPS",
    "Found",
    "Shop",
    "query_for",
    "read_results",
    "looks_like_a_guide",
    "seller_of",
    "where_to_buy",
]
