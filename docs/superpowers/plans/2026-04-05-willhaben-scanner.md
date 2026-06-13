# Willhaben Defekte Grafikkarten Scanner — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Python bot that scans willhaben.at every minute for new defective graphics card listings matching configurable keywords and price filters, sending matches to Discord via webhook.

**Architecture:** Simple single-process Python script with a `time.sleep` loop. Three modules: `scanner.py` (fetch & parse willhaben), `notifier.py` (Discord webhook), `main.py` (orchestration). Config via `config.json`, persistence via `seen.json`.

**Tech Stack:** Python 3.13, requests, BeautifulSoup4

---

## File Structure

```
Willhaben-Bot/
├── main.py            # Entry point, scan loop, config loading
├── scanner.py         # Willhaben HTTP requests, HTML parsing, filtering
├── notifier.py        # Discord webhook integration
├── config.json        # User configuration (keywords, price, webhook, interval)
├── seen.json          # Auto-generated, tracks seen listing IDs
├── requirements.txt   # Python dependencies
└── tests/
    ├── test_scanner.py
    ├── test_notifier.py
    └── fixtures/
        └── sample_response.html  # Saved willhaben HTML for testing
```

---

### Task 1: Project Setup & Dependencies

**Files:**
- Create: `Willhaben-Bot/requirements.txt`
- Create: `Willhaben-Bot/config.json`

- [ ] **Step 1: Create requirements.txt**

```
requests
beautifulsoup4
```

- [ ] **Step 2: Create config.json with defaults**

```json
{
  "keywords": ["RTX", "4090", "5090", "defekt", "kaputt", "broken"],
  "max_price": 200,
  "scan_interval_seconds": 60,
  "discord_webhook_url": "",
  "willhaben_base_url": "https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz/elektronik-computer/computer-hardware/grafikkarten-2628"
}
```

- [ ] **Step 3: Install dependencies**

Run: `pip install requests beautifulsoup4`

- [ ] **Step 4: Commit**

```bash
git add Willhaben-Bot/requirements.txt Willhaben-Bot/config.json
git commit -m "feat: add project setup with requirements and config"
```

---

### Task 2: Scanner — Fetch Willhaben Listings

**Files:**
- Create: `Willhaben-Bot/scanner.py`
- Create: `Willhaben-Bot/tests/test_scanner.py`
- Create: `Willhaben-Bot/tests/fixtures/sample_response.html`

- [ ] **Step 1: Capture a real willhaben response for test fixtures**

Open a browser and save the HTML source of:
`https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz/elektronik-computer/computer-hardware/grafikkarten-2628`

Save as `Willhaben-Bot/tests/fixtures/sample_response.html`.

Alternatively, fetch it with Python:

```python
import requests

url = "https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz/elektronik-computer/computer-hardware/grafikkarten-2628"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "de-AT,de;q=0.9",
}
resp = requests.get(url, headers=headers)
with open("Willhaben-Bot/tests/fixtures/sample_response.html", "w", encoding="utf-8") as f:
    f.write(resp.text)
print(f"Status: {resp.status_code}, Length: {len(resp.text)}")
```

Run this and inspect the HTML to identify the correct CSS selectors for:
- Listing container elements
- Title
- Price
- Location
- Link/ID

**This step is critical.** The selectors below are based on research and may need adjustment after inspecting the actual HTML. Update the selectors in Step 3 and Step 5 accordingly.

- [ ] **Step 2: Write failing tests for `fetch_listings` and `parse_listings`**

Create `Willhaben-Bot/tests/test_scanner.py`:

```python
import json
import os
import pytest

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def load_fixture(name):
    path = os.path.join(FIXTURES_DIR, name)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def test_parse_listings_returns_list():
    from scanner import parse_listings

    html = load_fixture("sample_response.html")
    listings = parse_listings(html)
    assert isinstance(listings, list)
    assert len(listings) > 0


def test_parse_listings_has_required_fields():
    from scanner import parse_listings

    html = load_fixture("sample_response.html")
    listings = parse_listings(html)
    listing = listings[0]
    assert "id" in listing
    assert "title" in listing
    assert "price" in listing
    assert "url" in listing
    assert "location" in listing


def test_parse_listings_id_is_string():
    from scanner import parse_listings

    html = load_fixture("sample_response.html")
    listings = parse_listings(html)
    for listing in listings:
        assert isinstance(listing["id"], str)
        assert len(listing["id"]) > 0


def test_filter_listings_by_keywords():
    from scanner import filter_listings

    listings = [
        {"id": "1", "title": "RTX 4090 defekt", "price": 150, "url": "", "location": ""},
        {"id": "2", "title": "AMD Monitor", "price": 50, "url": "", "location": ""},
    ]
    result = filter_listings(listings, keywords=["RTX", "defekt"], max_price=200)
    assert len(result) == 1
    assert result[0]["id"] == "1"


def test_filter_listings_keyword_case_insensitive():
    from scanner import filter_listings

    listings = [
        {"id": "1", "title": "rtx 4090 DEFEKT", "price": 100, "url": "", "location": ""},
    ]
    result = filter_listings(listings, keywords=["RTX"], max_price=200)
    assert len(result) == 1


def test_filter_listings_by_max_price():
    from scanner import filter_listings

    listings = [
        {"id": "1", "title": "RTX 4090 defekt", "price": 300, "url": "", "location": ""},
        {"id": "2", "title": "RTX 3070 defekt", "price": 100, "url": "", "location": ""},
    ]
    result = filter_listings(listings, keywords=["RTX"], max_price=200)
    assert len(result) == 1
    assert result[0]["id"] == "2"


def test_filter_listings_no_price_included():
    from scanner import filter_listings

    listings = [
        {"id": "1", "title": "RTX 4090 defekt", "price": None, "url": "", "location": ""},
    ]
    result = filter_listings(listings, keywords=["RTX"], max_price=200)
    assert len(result) == 1


def test_filter_new_only():
    from scanner import filter_new

    listings = [
        {"id": "1", "title": "A", "price": 10, "url": "", "location": ""},
        {"id": "2", "title": "B", "price": 20, "url": "", "location": ""},
        {"id": "3", "title": "C", "price": 30, "url": "", "location": ""},
    ]
    seen_ids = {"1", "3"}
    result = filter_new(listings, seen_ids)
    assert len(result) == 1
    assert result[0]["id"] == "2"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd Willhaben-Bot && python -m pytest tests/test_scanner.py -v`
Expected: FAIL — `scanner` module does not exist yet.

- [ ] **Step 4: Implement `scanner.py`**

Create `Willhaben-Bot/scanner.py`:

```python
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "de-AT,de;q=0.9",
}


def fetch_html(base_url: str) -> str:
    """Fetch the willhaben search results page HTML."""
    resp = requests.get(base_url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.text


def parse_listings(html: str) -> list[dict]:
    """Parse willhaben HTML and extract listing data.

    NOTE: The CSS selectors below are based on research of willhaben's HTML
    structure. If parsing returns empty results, inspect the actual HTML
    (saved in tests/fixtures/sample_response.html) and update the selectors.
    """
    soup = BeautifulSoup(html, "html.parser")
    listings = []

    # Willhaben uses search-result-entry articles or similar containers.
    # Adjust this selector after inspecting the real HTML.
    articles = soup.select("a[data-testid='search-result-entry-header']")

    # Fallback: try other common willhaben patterns
    if not articles:
        articles = soup.select("article.search-result-entry")
    if not articles:
        articles = soup.select("[itemtype='http://schema.org/Product']")

    for article in articles:
        listing = _extract_listing(article)
        if listing:
            listings.append(listing)

    return listings


def _extract_listing(article) -> dict | None:
    """Extract a single listing's data from an HTML element."""
    # Extract link and ID
    link_tag = article if article.name == "a" else article.find("a", href=True)
    if not link_tag or not link_tag.get("href"):
        return None

    href = link_tag["href"]
    if not href.startswith("http"):
        href = "https://www.willhaben.at" + href

    # Extract ID from URL (willhaben URLs end with -NUMERIC_ID/)
    listing_id = href.rstrip("/").split("-")[-1]
    if not listing_id.isdigit():
        # Try to extract from data attributes
        listing_id = article.get("data-ad-id", "") or article.get("id", "") or href
    listing_id = str(listing_id)

    # Extract title
    title_tag = article.find("span", itemprop="name") or article.find("h2") or article.find("h3")
    title = title_tag.get_text(strip=True) if title_tag else ""

    # Extract price
    price = _extract_price(article)

    # Extract location
    location_tag = article.find("div", class_=lambda c: c and "address" in c) or article.find("span", class_=lambda c: c and "location" in str(c).lower())
    location = location_tag.get_text(strip=True) if location_tag else ""

    if not title and not listing_id:
        return None

    return {
        "id": listing_id,
        "title": title,
        "price": price,
        "url": href,
        "location": location,
    }


def _extract_price(article) -> float | None:
    """Extract price as a float from a listing element."""
    price_tag = article.find(class_=lambda c: c and "price" in str(c).lower())
    if not price_tag:
        price_tag = article.find("span", itemprop="price")
    if not price_tag:
        return None

    price_text = price_tag.get_text(strip=True)
    # Remove currency symbols, dots (thousands), replace comma with dot
    cleaned = price_text.replace("€", "").replace(".", "").replace(",", ".").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def filter_listings(
    listings: list[dict],
    keywords: list[str],
    max_price: float,
) -> list[dict]:
    """Filter listings: at least one keyword must match (OR, case-insensitive)
    and price must be <= max_price (or price is unknown)."""
    result = []
    for listing in listings:
        title_lower = listing["title"].lower()
        keyword_match = any(kw.lower() in title_lower for kw in keywords)
        if not keyword_match:
            continue

        price = listing["price"]
        if price is not None and price > max_price:
            continue

        result.append(listing)
    return result


def filter_new(listings: list[dict], seen_ids: set[str]) -> list[dict]:
    """Return only listings whose ID is not in the seen set."""
    return [l for l in listings if l["id"] not in seen_ids]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd Willhaben-Bot && python -m pytest tests/test_scanner.py -v`
Expected: All tests PASS. The `parse_listings` tests depend on the fixture HTML — if selectors don't match, adjust the selectors in `scanner.py` based on the actual HTML structure.

- [ ] **Step 6: Commit**

```bash
git add Willhaben-Bot/scanner.py Willhaben-Bot/tests/
git commit -m "feat: add scanner with HTML parsing, keyword filtering, and seen tracking"
```

---

### Task 3: Notifier — Discord Webhook

**Files:**
- Create: `Willhaben-Bot/notifier.py`
- Create: `Willhaben-Bot/tests/test_notifier.py`

- [ ] **Step 1: Write failing tests for notifier**

Create `Willhaben-Bot/tests/test_notifier.py`:

```python
from unittest.mock import patch, MagicMock
from notifier import build_embed, send_notification


def test_build_embed_has_required_fields():
    listing = {
        "id": "12345",
        "title": "RTX 4090 defekt",
        "price": 150.0,
        "url": "https://www.willhaben.at/iad/kaufen-und-verkaufen/d/rtx-4090-defekt-12345/",
        "location": "Wien",
    }
    embed = build_embed(listing)
    assert embed["title"] == "RTX 4090 defekt"
    assert embed["url"] == listing["url"]
    assert any("150" in f["value"] for f in embed["fields"])
    assert any("Wien" in f["value"] for f in embed["fields"])


def test_build_embed_no_price():
    listing = {
        "id": "12345",
        "title": "GPU kaputt",
        "price": None,
        "url": "https://www.willhaben.at/iad/d/gpu-kaputt-12345/",
        "location": "Graz",
    }
    embed = build_embed(listing)
    assert any("Kein Preis" in f["value"] for f in embed["fields"])


@patch("notifier.requests.post")
def test_send_notification_calls_webhook(mock_post):
    mock_post.return_value = MagicMock(status_code=204)
    listing = {
        "id": "99",
        "title": "Test GPU",
        "price": 50.0,
        "url": "https://example.com",
        "location": "Linz",
    }
    send_notification("https://discord.com/api/webhooks/test", listing)
    mock_post.assert_called_once()
    call_args = mock_post.call_args
    payload = call_args[1]["json"]
    assert "embeds" in payload
    assert len(payload["embeds"]) == 1


@patch("notifier.requests.post")
def test_send_notification_handles_error(mock_post):
    mock_post.side_effect = Exception("Connection error")
    listing = {
        "id": "99",
        "title": "Test GPU",
        "price": 50.0,
        "url": "https://example.com",
        "location": "Linz",
    }
    # Should not raise — just log and continue
    send_notification("https://discord.com/api/webhooks/test", listing)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd Willhaben-Bot && python -m pytest tests/test_notifier.py -v`
Expected: FAIL — `notifier` module does not exist yet.

- [ ] **Step 3: Implement `notifier.py`**

Create `Willhaben-Bot/notifier.py`:

```python
from datetime import datetime, timezone

import requests


def build_embed(listing: dict) -> dict:
    """Build a Discord embed dict for a listing."""
    price = listing["price"]
    price_str = f"{price:.2f} EUR" if price is not None else "Kein Preis"

    return {
        "title": listing["title"],
        "url": listing["url"],
        "color": 0x2ECC71,
        "fields": [
            {"name": "Preis", "value": price_str, "inline": True},
            {"name": "Standort", "value": listing["location"] or "Unbekannt", "inline": True},
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def send_notification(webhook_url: str, listing: dict) -> None:
    """Send a single listing to Discord via webhook."""
    if not webhook_url:
        return

    embed = build_embed(listing)
    payload = {"embeds": [embed]}

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"[WARN] Discord notification failed: {e}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd Willhaben-Bot && python -m pytest tests/test_notifier.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add Willhaben-Bot/notifier.py Willhaben-Bot/tests/test_notifier.py
git commit -m "feat: add Discord webhook notifier with embed formatting"
```

---

### Task 4: Main Loop — Orchestration

**Files:**
- Create: `Willhaben-Bot/main.py`

- [ ] **Step 1: Implement `main.py`**

Create `Willhaben-Bot/main.py`:

```python
import json
import os
import sys
import time

from scanner import fetch_html, parse_listings, filter_listings, filter_new
from notifier import send_notification

BOT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BOT_DIR, "config.json")
SEEN_PATH = os.path.join(BOT_DIR, "seen.json")


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_seen() -> set[str]:
    if not os.path.exists(SEEN_PATH):
        return set()
    with open(SEEN_PATH, "r", encoding="utf-8") as f:
        return set(json.load(f))


def save_seen(seen_ids: set[str]) -> None:
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(seen_ids), f)


def scan_once(config: dict, seen_ids: set[str]) -> list[dict]:
    """Run one scan cycle. Returns list of new matching listings."""
    html = fetch_html(config["willhaben_base_url"])
    all_listings = parse_listings(html)
    filtered = filter_listings(all_listings, config["keywords"], config["max_price"])
    new_listings = filter_new(filtered, seen_ids)

    for listing in new_listings:
        seen_ids.add(listing["id"])

    return new_listings


def main():
    config = load_config()

    if not config.get("discord_webhook_url"):
        print("[WARN] No discord_webhook_url set in config.json — running in log-only mode.")

    seen_ids = load_seen()
    scan_count = 0
    interval = config.get("scan_interval_seconds", 60)

    print("=" * 50)
    print("[BOOT] Willhaben Scanner gestartet")
    print(f"[BOOT] Keywords: {config['keywords']}")
    print(f"[BOOT] Max Preis: {config['max_price']} EUR")
    print(f"[BOOT] Intervall: {interval}s")
    print(f"[BOOT] Stoppen mit: Ctrl+C")
    print("=" * 50)

    try:
        while True:
            scan_count += 1
            try:
                new_listings = scan_once(config, seen_ids)
                save_seen(seen_ids)

                if new_listings:
                    print(f"[SCAN #{scan_count}] {len(new_listings)} neue Treffer!")
                    for listing in new_listings:
                        price_str = f"{listing['price']:.2f} EUR" if listing['price'] else "N/A"
                        print(f"  -> {listing['title']} | {price_str} | {listing['location']}")
                        send_notification(config.get("discord_webhook_url", ""), listing)
                else:
                    print(f"[SCAN #{scan_count}] Keine neuen Treffer.")

            except Exception as e:
                print(f"[WARN] Scan #{scan_count} fehlgeschlagen: {e}")

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n[STOP] Scanner gestoppt.")
        save_seen(seen_ids)
        sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the bot manually to test**

Run: `cd Willhaben-Bot && python main.py`

Expected: The bot starts, shows the boot message, runs the first scan, and either finds listings or logs "Keine neuen Treffer." Press Ctrl+C to stop.

If parsing returns 0 results, inspect the saved fixture HTML and adjust selectors in `scanner.py`.

- [ ] **Step 3: Commit**

```bash
git add Willhaben-Bot/main.py
git commit -m "feat: add main loop with scan orchestration, seen tracking, and console output"
```

---

### Task 5: End-to-End Verification

- [ ] **Step 1: Run all tests**

Run: `cd Willhaben-Bot && python -m pytest tests/ -v`
Expected: All tests PASS.

- [ ] **Step 2: Test live scan**

1. Set your Discord webhook URL in `config.json`
2. Run: `cd Willhaben-Bot && python main.py`
3. Verify:
   - Console shows scan results
   - Discord receives embed messages for new matches
   - `seen.json` gets created with IDs
4. Stop with Ctrl+C, restart — verify no duplicate notifications

- [ ] **Step 3: Adjust selectors if needed**

If `parse_listings` returns empty results from the live site:
1. Open `tests/fixtures/sample_response.html` in a browser
2. Inspect listing elements (right-click -> Inspect)
3. Update CSS selectors in `scanner.py:parse_listings` and `_extract_listing`
4. Re-run tests

- [ ] **Step 4: Final commit**

```bash
git add -A Willhaben-Bot/
git commit -m "feat: willhaben scanner complete — live-tested and verified"
```
