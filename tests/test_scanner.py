"""Tests for the willhaben listing scanner."""

import os
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone

import pytest

import scanner
from scanner import parse_listings, filter_listings, filter_new, fetch_listings_since

FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "fixtures", "sample_response.html"
)


@pytest.fixture
def sample_html():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def listings(sample_html):
    return parse_listings(sample_html)


# ---------------------------------------------------------------------------
# parse_listings
# ---------------------------------------------------------------------------

def test_parse_listings_no_next_data():
    """Returns empty list when HTML has no __NEXT_DATA__."""
    from scanner import parse_listings
    assert parse_listings("<html><body>No data</body></html>") == []


def test_parse_listings_malformed_json():
    """Returns empty list when JSON structure is unexpected."""
    from scanner import parse_listings
    html = '<html><script id="__NEXT_DATA__">{"props":{}}</script></html>'
    assert parse_listings(html) == []


def test_parse_listings_returns_list(listings):
    """parse_listings returns a non-empty list."""
    assert isinstance(listings, list)
    assert len(listings) > 0


def test_parse_listings_has_required_fields(listings):
    """Every listing dict contains id, title, price, url, location."""
    required = {"id", "title", "price", "url", "location", "image_url"}
    for item in listings:
        assert required.issubset(item.keys()), f"Missing keys in {item}"


def test_parse_listings_id_is_string(listings):
    """All listing IDs are strings."""
    for item in listings:
        assert isinstance(item["id"], str), f"ID is not a string: {item['id']}"


def test_parse_listings_extracts_image_url(listings):
    """Every parsed listing with an image has a non-empty image_url string."""
    for item in listings:
        assert "image_url" in item, f"Missing image_url in {item}"
    with_images = [i for i in listings if i["image_url"]]
    assert with_images, "Fixture should contain at least one listing with an image"


def test_parse_listings_no_image_url_when_missing():
    """An item without advertImageList still parses, with image_url=''."""
    html = (
        '<html><script id="__NEXT_DATA__">'
        '{"props":{"pageProps":{"searchResult":'
        '{"advertSummaryList":{"advertSummary":'
        '[{"id":"1","description":"x","attributes":{"attribute":[]}}]}}}}}'
        '</script></html>'
    )
    result = parse_listings(html)
    assert result == [{"id": "1", "title": "x", "price": None, "url": "",
                       "location": "", "published": None, "paylivery": False,
                       "image_url": ""}]


def test_scanner_fast_path_does_not_import_bs4():
    """The normal __NEXT_DATA__ regex path must not pay BeautifulSoup's import cost."""
    code = r'''
import builtins
from pathlib import Path

real_import = builtins.__import__

def guarded_import(name, *args, **kwargs):
    if name == "bs4" or name.startswith("bs4."):
        raise AssertionError("bs4 imported on scanner fast path")
    return real_import(name, *args, **kwargs)

builtins.__import__ = guarded_import

import scanner

html = Path("tests/fixtures/sample_response.html").read_text(encoding="utf-8")
assert scanner.parse_listings(html)
'''
    repo = os.path.dirname(os.path.dirname(__file__))
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


# ---------------------------------------------------------------------------
# filter_listings
# ---------------------------------------------------------------------------

def test_filter_listings_by_keywords():
    """OR keyword matching: listing matches if title contains any keyword."""
    listings = [
        {"id": "1", "title": "RTX 4090 cheap", "price": 100.0, "url": "", "location": ""},
        {"id": "2", "title": "Old sofa", "price": 50.0, "url": "", "location": ""},
        {"id": "3", "title": "Broken GPU 5090", "price": 30.0, "url": "", "location": ""},
    ]
    result = filter_listings(listings, keywords=["RTX", "5090"], max_price=200)
    ids = {item["id"] for item in result}
    assert ids == {"1", "3"}


def test_filter_listings_keyword_case_insensitive():
    """Keywords match regardless of case."""
    listings = [
        {"id": "1", "title": "rtx 4090 CHEAP", "price": 100.0, "url": "", "location": ""},
        {"id": "2", "title": "Old sofa", "price": 50.0, "url": "", "location": ""},
    ]
    result = filter_listings(listings, keywords=["RTX"], max_price=200)
    assert len(result) == 1
    assert result[0]["id"] == "1"


def test_filter_listings_by_max_price():
    """Listings above max_price are excluded."""
    listings = [
        {"id": "1", "title": "RTX 4090", "price": 100.0, "url": "", "location": ""},
        {"id": "2", "title": "RTX 4090 expensive", "price": 500.0, "url": "", "location": ""},
    ]
    result = filter_listings(listings, keywords=["RTX"], max_price=200)
    assert len(result) == 1
    assert result[0]["id"] == "1"


def test_filter_listings_no_price_included():
    """Listings with price=None pass the price filter (e.g. 'Verschenken')."""
    listings = [
        {"id": "1", "title": "RTX 4090 free", "price": None, "url": "", "location": ""},
        {"id": "2", "title": "RTX 4090 expensive", "price": 500.0, "url": "", "location": ""},
    ]
    result = filter_listings(listings, keywords=["RTX"], max_price=200)
    assert len(result) == 1
    assert result[0]["id"] == "1"


def _titled(title):
    return [{"id": "1", "title": title, "price": 10.0, "url": "", "location": ""}]


def test_filter_listings_keyword_word_boundary():
    """Letter-edged keywords must not match inside other words ('RX' vs 'Marx')."""
    assert filter_listings(_titled("Marx Buch zu verkaufen"), ["RX"], None) == []
    assert filter_listings(_titled("RX 580 defekt"), ["RX"], None) != []


def test_filter_listings_digit_keyword_letter_transition():
    """Digit keywords match across a letter/digit transition ('RTX3060') but not inside numbers."""
    assert filter_listings(_titled("RTX3060 kein Bild"), ["3060"], None) != []
    assert filter_listings(_titled("Artikel 13060"), ["3060"], None) == []


def test_filter_listings_umlaut_keyword():
    """Unicode letters count as word characters at keyword edges."""
    assert filter_listings(_titled("GPU überhitzt sofort"), ["überhitzt"], None) != []
    assert filter_listings(_titled("Marxismus Buch"), ["RX"], None) == []


def test_filter_listings_german_inflections_and_compounds():
    """Long keywords may continue into inflections/compounds; short acronyms may only pluralize."""
    assert filter_listings(_titled("Defekte Grafikkarte"), ["defekt"], None) != []
    assert filter_listings(_titled("Grafikkarten Bundle"), ["grafikkarte"], None) != []
    assert filter_listings(_titled("2 GPUs abzugeben"), ["GPU"], None) != []
    assert filter_listings(_titled("GPUx Adapter"), ["GPU"], None) == []


def test_filter_listings_phrase_keyword():
    """Multi-word keywords still match as phrases."""
    assert filter_listings(_titled("PC geht nicht an"), ["geht nicht"], None) != []


# ---------------------------------------------------------------------------
# filter_new
# ---------------------------------------------------------------------------

def test_filter_new_only():
    """Only listings whose IDs are not in seen_ids are returned."""
    listings = [
        {"id": "1", "title": "A", "price": 10.0, "url": "", "location": ""},
        {"id": "2", "title": "B", "price": 20.0, "url": "", "location": ""},
        {"id": "3", "title": "C", "price": 30.0, "url": "", "location": ""},
    ]
    seen = {"1", "3"}
    result = filter_new(listings, seen)
    assert len(result) == 1
    assert result[0]["id"] == "2"


# ---------------------------------------------------------------------------
# fetch_listings_since
# ---------------------------------------------------------------------------

def _listing_aged(listing_id: str, days_ago: float | None):
    published = (
        datetime.now(timezone.utc) - timedelta(days=days_ago)
        if days_ago is not None
        else None
    )
    return {"id": listing_id, "title": "x", "price": 1.0, "url": "", "location": "", "published": published}


def _fake_pages(monkeypatch, pages: dict[int, list[dict]]):
    """Route fetch_listings_since's page fetches to canned listings; track fetched pages."""
    fetched: list[int] = []

    def fake_fetch_html(url):
        page = int(url.rsplit("page=", 1)[1])
        fetched.append(page)
        return str(page)

    monkeypatch.setattr(scanner, "fetch_html", fake_fetch_html)
    monkeypatch.setattr(scanner, "parse_listings", lambda html: pages.get(int(html), []))
    return fetched


def test_fetch_listings_since_skips_promoted_old_listing(monkeypatch):
    """An old promoted listing at the top of a page must not abort the backfill."""
    pages = {1: [_listing_aged("old", days_ago=10), _listing_aged("fresh", days_ago=1)]}
    _fake_pages(monkeypatch, pages)

    result = fetch_listings_since("https://example.test/search", days_back=2)

    assert [l["id"] for l in result] == ["fresh"]


def test_fetch_listings_since_stops_after_all_old_page(monkeypatch):
    """Pagination stops once every dated listing on a page is older than the cutoff."""
    pages = {
        1: [_listing_aged("a", days_ago=1)],
        2: [_listing_aged("b", days_ago=10), _listing_aged("c", days_ago=11)],
        3: [_listing_aged("d", days_ago=1)],  # must never be fetched
    }
    fetched = _fake_pages(monkeypatch, pages)

    result = fetch_listings_since("https://example.test/search", days_back=2)

    assert [l["id"] for l in result] == ["a"]
    assert fetched == [1, 2]


def test_fetch_listings_since_keeps_undated_listings(monkeypatch):
    """Listings without a published date are kept (no date to filter on)."""
    pages = {1: [_listing_aged("undated", days_ago=None), _listing_aged("fresh", days_ago=1)]}
    _fake_pages(monkeypatch, pages)

    result = fetch_listings_since("https://example.test/search", days_back=2)

    assert [l["id"] for l in result] == ["undated", "fresh"]


def test_fetch_listings_since_logs_translated_error_on_page_failure(monkeypatch, capsys):
    """A failing page must log via t() so the message is translated, not a hardcoded literal."""
    def boom(_url):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(scanner, "fetch_html", boom)

    from i18n import set_language
    set_language("en")
    fetch_listings_since("https://example.test/search", days_back=2)
    captured = capsys.readouterr()
    assert "could not be loaded" in captured.out
    assert "Seite" not in captured.out  # the old hardcoded German is gone

    set_language("de")
    fetch_listings_since("https://example.test/search", days_back=2)
    captured = capsys.readouterr()
    assert "Seite" in captured.out
    set_language("en")


# ---------------------------------------------------------------------------
# per-thread sessions
# ---------------------------------------------------------------------------

def test_get_session_is_per_thread():
    """Each thread gets its own requests.Session; the same thread reuses one."""
    assert scanner._get_session() is scanner._get_session()

    other: list = []
    t = threading.Thread(target=lambda: other.append(scanner._get_session()))
    t.start()
    t.join()

    assert other[0] is not scanner._get_session()
    assert other[0].headers["User-Agent"] == scanner.HEADERS["User-Agent"]
