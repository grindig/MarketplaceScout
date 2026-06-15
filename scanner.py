"""Willhaben listing scanner.

Fetches willhaben.at search result pages, extracts listing data from the
embedded __NEXT_DATA__ JSON, and filters by keywords and price.
"""

import json
import re
import threading
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Optional

import requests
from bs4 import BeautifulSoup, SoupStrainer

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-AT,de;q=0.9",
}

# One session per thread: each channel's scan runs in its own worker thread
# (asyncio.to_thread), and requests.Session is not thread-safe. Sessions still
# reuse TCP/TLS connections across the periodic scans of the same thread.
_thread_local = threading.local()

# Only the __NEXT_DATA__ script tag is needed; skip parsing the rest of the page.
_NEXT_DATA_ONLY = SoupStrainer("script", id="__NEXT_DATA__")

# Fast path: the __NEXT_DATA__ payload is a single self-contained JSON <script>
# (Next.js escapes any "<" inside it), so a regex slice avoids running the whole
# ~500 KB page through bs4's pure-Python tokenizer on every scan — ~5x faster.
# Anchored on the id alone so extra/reordered attributes still match; on a miss
# we fall back to BeautifulSoup so a Willhaben markup change degrades gracefully
# instead of silently dropping every listing.
_NEXT_DATA_RE = re.compile(
    r'<script[^>]*\bid="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)


def _get_session() -> requests.Session:
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update(HEADERS)
        _thread_local.session = session
    return session


def fetch_html(base_url: str) -> str:
    """GET the willhaben search page and return the raw HTML string."""
    response = _get_session().get(base_url, timeout=15)
    response.raise_for_status()
    return response.text


def _get_attribute(attributes: list[dict], name: str) -> Optional[str]:
    """Extract the first value of a named attribute from the attributes list.

    Each attribute is a dict like ``{"name": "HEADING", "values": ["..."]}``.
    Returns ``None`` if the attribute is not found or has no values.
    """
    for attr in attributes:
        if attr.get("name") == name:
            values = attr.get("values")
            if values:
                return values[0]
    return None


def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse a date value into a timezone-aware datetime. Returns None on failure.

    Supports Unix timestamps in milliseconds (Willhaben default) and ISO 8601 strings.
    """
    if not date_str:
        return None
    try:
        ms = int(date_str)
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    except (ValueError, TypeError):
        pass
    try:
        dt = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None


def parse_listings(html: str) -> list[dict]:
    """Parse the __NEXT_DATA__ JSON from the HTML and return a list of listing dicts.

    Each dict has keys: ``id``, ``title``, ``price``, ``url``, ``location``, ``published``.
    """
    match = _NEXT_DATA_RE.search(html)
    if match is not None:
        raw = match.group(1)
    else:
        # Regex missed (markup changed) — let bs4 locate the tag instead.
        soup = BeautifulSoup(html, "html.parser", parse_only=_NEXT_DATA_ONLY)
        script_tag = soup.find("script", id="__NEXT_DATA__")
        if script_tag is None:
            return []
        raw = script_tag.string

    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    try:
        items = (
            data["props"]["pageProps"]["searchResult"]
            ["advertSummaryList"]["advertSummary"]
        )
    except (KeyError, TypeError):
        return []

    listings: list[dict] = []
    for item in items:
        item_id = item.get("id")
        if item_id is None:
            continue

        attributes = item.get("attributes", {}).get("attribute", [])

        heading = _get_attribute(attributes, "HEADING")
        price_str = _get_attribute(attributes, "PRICE/AMOUNT")
        seo_url = _get_attribute(attributes, "SEO_URL")
        location = _get_attribute(attributes, "LOCATION")
        paylivery = _get_attribute(attributes, "p2penabled") == "true"

        published = _parse_date(_get_attribute(attributes, "PUBLISHED"))

        price: Optional[float] = None
        if price_str is not None:
            try:
                price = float(price_str)
            except (ValueError, TypeError):
                price = None

        url = ""
        if seo_url:
            url = "https://www.willhaben.at/iad/" + seo_url

        image_url = ""
        advert_image_list = item.get("advertImageList", {}).get("advertImage") or []
        if advert_image_list:
            image_url = advert_image_list[0].get("mainImageUrl") or ""

        listings.append(
            {
                "id": str(item_id),
                "title": heading or item.get("description", ""),
                "price": price,
                "url": url,
                "location": location or "",
                "published": published,
                "paylivery": paylivery,
                "image_url": image_url,
            }
        )

    return listings


# Letter-ended keywords up to this length get a strict right boundary
# (acronyms like RX/GPU/MSI); longer words may continue into German
# inflections and compounds ("defekt" → "defekte", "grafik" → "Grafikkarte").
_MAX_STRICT_SUFFIX_LEN = 4


@lru_cache(maxsize=None)
def _keyword_pattern(keyword: str) -> re.Pattern:
    """Compile a boundary-aware, case-insensitive pattern for one keyword.

    The keyword's start must sit on a word boundary of its character class,
    so "RX" no longer matches "Marx" while "3060" still matches "RTX3060"
    (letter/digit transition). Digit endings must not run into more digits
    ("3060" does not match "30600"); short letter endings allow only a
    plural "s" ("GPU" matches "GPUs" but not "GPUx").
    """
    first, last = keyword[0], keyword[-1]
    prefix = r"(?<!\d)" if first.isdigit() else r"(?<![^\W\d_])" if first.isalpha() else ""
    if last.isdigit():
        suffix = r"(?!\d)"
    elif last.isalpha() and len(keyword) <= _MAX_STRICT_SUFFIX_LEN:
        suffix = r"s?(?![^\W\d_])"
    else:
        suffix = ""
    return re.compile(prefix + re.escape(keyword) + suffix, re.IGNORECASE)


def filter_listings(
    listings: list[dict],
    keywords: list[str],
    max_price: Optional[float],
) -> list[dict]:
    """Filter listings by keyword (OR, case-insensitive, boundary-aware) and max price.

    A listing passes if:
    - Its title matches at least one keyword (see ``_keyword_pattern``), AND
    - Its price is ``<= max_price``, or its price is ``None``
      (e.g. "Verschenken" listings with no price).
    """
    results: list[dict] = []
    patterns = [_keyword_pattern(kw) for kw in keywords]

    for item in listings:
        title = item["title"]

        # Keyword match (OR): at least one keyword in title
        if not any(p.search(title) for p in patterns):
            continue

        # Price filter: skip if no limit (max_price is None), otherwise must be <= max_price
        if max_price is not None and item["price"] is not None and item["price"] > max_price:
            continue

        results.append(item)

    return results


def filter_new(listings: list[dict], seen_ids: set[str]) -> list[dict]:
    """Return only listings whose IDs have not been seen before."""
    return [item for item in listings if item["id"] not in seen_ids]


def fetch_listings_since(base_url: str, days_back: int, max_pages: int = 10) -> list[dict]:
    """Paginate through Willhaben results and return listings from the last ``days_back`` days.

    Listings older than the cutoff are skipped (promoted ads can put old listings
    at the top of a page); pagination stops once a whole page is older than the
    cutoff, or a page returns no results. If no dates are found in the API
    response, all pages up to ``max_pages`` are fetched.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    all_listings: list[dict] = []
    sep = "&" if "?" in base_url else "?"

    for page in range(1, max_pages + 1):
        url = f"{base_url}{sep}page={page}"
        try:
            html = fetch_html(url)
        except Exception as exc:
            print(f"[WARN] Backfill: Seite {page} konnte nicht geladen werden: {exc}")
            break

        listings = parse_listings(html)
        if not listings:
            break

        dated = [l for l in listings if l.get("published") is not None]
        all_listings.extend(
            l for l in listings
            if l.get("published") is None or l["published"] >= cutoff
        )

        if dated and all(l["published"] < cutoff for l in dated):
            break

    return all_listings
