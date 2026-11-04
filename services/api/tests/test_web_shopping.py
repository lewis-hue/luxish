"""Where to buy a named piece, from the open web.

The lookup this replaces asked a map for clothes shops within a
radius, which answers a different question: somebody wants *this
jacket*, not *a jacket shop*. These pin the parts that make the new
one useful rather than merely different - the query carries the look,
magazines are not offered as shops, and a search that could not be
reached says so instead of reporting an empty high street.

Every test here is offline. The network path is exercised by hand;
what is pinned is the parsing and the shape of the answer, which is
what breaks silently.
"""

from __future__ import annotations

import pytest

from app.domain.web_shopping import (
    MOST_LINKS,
    Found,
    query_for,
    read_results,
    seller_of,
    where_to_buy,
)

pytestmark = pytest.mark.anyio


def result(url: str, title: str) -> str:
    """One anchor, in the shape the lite endpoint emits."""
    import urllib.parse

    return (
        f'<a rel="nofollow" href="//duckduckgo.com/l/?uddg='
        f'{urllib.parse.quote(url, safe="")}&amp;rut=abc" '
        f"class='result-link'>{title}</a>"
    )


# --------------------------------------------------------------------------- #
# The query
# --------------------------------------------------------------------------- #
def test_the_look_narrows_the_search() -> None:
    """**Why this beats a bare product search.**

    "cream trousers" returns every cream trouser ever made. The look
    beside it is what picks the right cut and weight.
    """
    asked = query_for("cream trousers", look="1970s flared streetwear")
    assert "cream trousers" in asked
    assert "1970s" in asked


def test_a_whole_caption_is_trimmed() -> None:
    """A sentence as a query matches nothing: no page contains it."""
    asked = query_for(
        "tan boots",
        look="Wore this out on Tuesday and nobody let me leave without asking",
    )
    assert len(asked.split()) <= 10


def test_the_gap_still_works_on_its_own() -> None:
    assert query_for("tan leather tote") == "tan leather tote buy"


# --------------------------------------------------------------------------- #
# Reading the page
# --------------------------------------------------------------------------- #
def test_results_come_back_with_their_seller() -> None:
    page = result("https://www.nordstrom.com/x", "Suede Jackets")
    [shop] = read_results(page)
    assert shop.seller == "nordstrom.com"
    assert shop.url == "https://www.nordstrom.com/x"
    assert shop.title == "Suede Jackets"


def test_entities_are_decoded() -> None:
    """Or a title arrives as "Coats &amp; Jackets"."""
    page = result("https://www.ebay.com/x", "Coats &amp; Jackets &#x27;70s")
    [shop] = read_results(page)
    assert shop.title == "Coats & Jackets '70s"


def test_magazines_are_not_offered_as_shops() -> None:
    """**A round-up is a dead end under "where to get them".**

    Searching a clothing phrase surfaces as much editorial as retail,
    and a link to an Esquire list is not somewhere to buy a jacket.
    """
    page = result("https://www.esquire.com/style/g1/suede-jackets/", "20 Best")
    page += result("https://thursdayboots.com/products/x", "Suede Trucker")
    shops = read_results(page)
    assert [s.seller for s in shops] == ["thursdayboots.com"]


def test_one_entry_per_seller() -> None:
    """Four Amazon links is one shop, shown four times."""
    page = "".join(
        result(f"https://www.amazon.com/x{n}", f"Jacket {n}") for n in range(5)
    )
    assert len(read_results(page)) == 1


def test_the_list_is_capped() -> None:
    page = "".join(
        result(f"https://shop{n}.com/x", f"Jacket {n}") for n in range(12)
    )
    assert len(read_results(page)) == MOST_LINKS


def test_a_link_with_no_title_keeps_its_seller_as_the_label() -> None:
    """**Tolerant on purpose.**

    A markup change that breaks the title pattern should cost the
    titles, not the results: a link labelled with its shop is still
    useful, and an exception here would take down the whole reply it
    is attached to.
    """
    page = result("https://thursdayboots.com/x", "")
    [shop] = read_results(page)
    assert shop.title == "thursdayboots.com"


def test_rubbish_does_not_raise() -> None:
    assert read_results("<html>nothing here</html>") == []
    assert read_results("") == []


def test_www_is_not_part_of_the_name() -> None:
    assert seller_of("https://www.nordstrom.com/a/b") == "nordstrom.com"
    assert seller_of("https://thursdayboots.com/a") == "thursdayboots.com"


# --------------------------------------------------------------------------- #
# Asking
# --------------------------------------------------------------------------- #
async def test_nothing_asked_for_means_nothing_asked() -> None:
    assert await where_to_buy([]) == []


async def test_a_search_that_cannot_be_reached_says_so() -> None:
    """**The distinction the old shops lookup got wrong.**

    It cached a 502 as "there are no shops here", which tells
    somebody something false about their own high street. Not reached
    and found nothing are different answers and the caller says
    different things for each.
    """
    import httpx

    def refuse(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(refuse)
    ) as client:
        [found] = await where_to_buy(["cream trousers"], client=client)

    assert found.reached is False
    assert found.shops == []


async def test_an_answer_with_no_results_is_reached_and_empty() -> None:
    import httpx

    def nothing(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html></html>")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(nothing)
    ) as client:
        [found] = await where_to_buy(["cream trousers"], client=client)

    assert found.reached is True
    assert found.shops == []


async def test_a_network_failure_never_escapes() -> None:
    """A shopping list is an extra under an answer that has already
    arrived. It must not be able to take that answer down."""
    import httpx

    def explode(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(explode)
    ) as client:
        found = await where_to_buy(["a", "b"], client=client)

    assert [f.reached for f in found] == [False, False]


async def test_the_answers_pair_with_the_gaps_in_order() -> None:
    """So the caller never has to match them back up on text."""
    import httpx

    def answer(request: httpx.Request) -> httpx.Response:
        asked = request.url.params.get("q", "")
        host = "trousers.com" if "trousers" in asked else "boots.com"
        return httpx.Response(200, text=result(f"https://{host}/x", host))

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(answer)
    ) as client:
        found = await where_to_buy(["cream trousers", "tan boots"], client=client)

    assert [f.gap for f in found] == ["cream trousers", "tan boots"]
    assert found[0].shops[0].seller == "trousers.com"
    assert found[1].shops[0].seller == "boots.com"


def test_found_defaults_to_reached() -> None:
    """Because the common case is that it worked."""
    assert Found(gap="x").reached is True


# --------------------------------------------------------------------------- #
# Getting a web result to the screen intact
#
# The lookup worked and the rows arrived unusable: the serialiser read
# `retailer` and `url` from a nested `product`, which is the shape a
# catalogue row has and not the shape a web result has. Both came back
# null, so the shop name never showed and the row could not be tapped -
# the client disables a link with no URL. A list of shops nobody can
# open is a worse answer than no list.
# --------------------------------------------------------------------------- #
def test_a_web_result_keeps_its_link_and_its_shop_name() -> None:
    from app.domain.stylist_ask import _WebOffer
    from app.routers.stylist import _offer

    out = _offer(
        _WebOffer(
            product_id="https://thursdayboots.com/p",
            title="Suede Trucker Jacket",
            retailer="thursdayboots.com",
            url="https://thursdayboots.com/p",
            match_label="brown suede trucker jacket",
        )
    )

    assert out["url"] == "https://thursdayboots.com/p", "a row with no url cannot be tapped"
    assert out["retailer"] == "thursdayboots.com"
    assert out["title"] == "Suede Trucker Jacket"


def test_a_catalogue_row_still_serialises_the_way_it_did() -> None:
    """The fallback must not cost the shape it was written for."""
    from app.routers.stylist import _offer

    class Product:
        title = "Wool Overcoat"
        retailer = "Zara"
        url = "https://zara.com/overcoat"

    class Match:
        product = Product()
        product_id = "cat-1"
        match_label = "overcoat"
        title = None
        retailer = None
        url = None

    out = _offer(Match())
    assert out["retailer"] == "Zara"
    assert out["url"] == "https://zara.com/overcoat"
    assert out["product_id"] == "cat-1"
