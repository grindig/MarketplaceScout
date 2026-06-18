# Image Thumbnails Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to execute this plan task-by-task with two-stage review per task.

**Goal:** Add the listing's image to the Discord notification embed as a thumbnail, sourced from the `mainImageUrl` field in the `__NEXT_DATA__` payload that the scanner already parses.

**Architecture:** Two changes — `scanner.py` extracts the image URL into the listing dict (so it's available where every other field is), and `notifier.py` reads it and calls `embed.set_thumbnail(url=...)`. No new files, no new deps.

**Tech Stack:** discord.py 2.x (existing), `parse_listings` (existing), no new libraries.

---

## Discovery (already done by parent)

Confirmed by reading the live fixture in `tests/fixtures/sample_response.html` and a HEAD request to Willhaben's CDN:

- Every item in the search result has `advertImageList.advertImage[0].mainImageUrl` (full URL on `cache.willhaben.at`, returns 200).
- Two older attributes exist (`ALL_IMAGE_URLS`, `MMO`) but they hold only the relative path and require URL composition. The new field is the canonical, full-URL form. Use it.
- Some listings may have `advertImageList` missing or empty (rare but possible — older/edge listings). Code must not crash; just leave the field empty and the notifier will skip the thumbnail.

---

## Task 1: Extract `image_url` in the scanner

**Objective:** Add `image_url` to every listing dict, sourced from `advertImageList.advertImage[0].mainImageUrl`. Empty string when missing.

**Files:**
- Modify: `scanner.py:124-163` (the listing-build loop in `parse_listings`)
- Modify: `tests/test_scanner.py:51-55` (the `test_parse_listings_has_required_fields` required-keys set)
- Add: `tests/test_scanner.py` — 2 new tests at the end of the parse_listings section (around line 63)

**Step 1: Write failing tests** (append to `tests/test_scanner.py` after `test_parse_listings_id_is_string`)

```python
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
```

**Step 2: Run new tests to verify they fail**

```bash
cd C:\Users\grindig\MarketplaceScout
/c/Users/grindig/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/test_scanner.py::test_parse_listings_extracts_image_url tests/test_scanner.py::test_parse_listings_no_image_url_when_missing -v
```

Expected: both FAIL — `image_url` not yet in listing dicts.

**Step 3: Update `test_parse_listings_has_required_fields` required-keys set**

Change line 53 of `tests/test_scanner.py` from:
```python
required = {"id", "title", "price", "url", "location"}
```
to:
```python
required = {"id", "title", "price", "url", "location", "image_url"}
```

**Step 4: Implement extraction in `scanner.py`**

Replace the `listings.append({...})` block (lines 151-161) with:

```python
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
```

**Step 5: Run all scanner tests to verify pass**

```bash
cd C:\Users\grindig\MarketplaceScout
/c/Users/grindig/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/test_scanner.py -v
```

Expected: all pass (existing tests + the 2 new ones + the updated required-fields test).

**Step 6: Commit**

```bash
cd C:\Users\grindig\MarketplaceScout
git add scanner.py tests/test_scanner.py
git commit -m "feat(scanner): extract image_url from advertImageList.mainImageUrl"
```

---

## Task 2: Add thumbnail to the embed

**Objective:** When the listing has an `image_url`, call `embed.set_thumbnail(url=...)` in `notifier.build_embed`. Skip silently when empty.

**Files:**
- Modify: `notifier.py:21-26` (the `discord.Embed(...)` constructor block) and add one line after it
- Add: `tests/test_notifier.py` — 2 new tests at end of file (after `test_send_notification_returns_true_when_only_reactions_fail`)

**Step 1: Write failing tests** (append to `tests/test_notifier.py`)

```python
def test_build_embed_thumbnail_set_when_image_url_present():
    listing = make_listing(image_url="https://cache.willhaben.at/mmo/x.jpg")
    embed = build_embed(listing)
    assert embed.thumbnail is not None
    assert embed.thumbnail.url == "https://cache.willhaben.at/mmo/x.jpg"


def test_build_embed_no_thumbnail_when_image_url_empty():
    listing = make_listing(image_url="")
    embed = build_embed(listing)
    # discord.py leaves thumbnail.url = None when never set
    assert embed.thumbnail is None or embed.thumbnail.url is None
```

**Step 2: Run new tests to verify they fail**

```bash
cd C:\Users\grindig\MarketplaceScout
/c/Users/grindig/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/test_notifier.py::test_build_embed_thumbnail_set_when_image_url_present tests/test_notifier.py::test_build_embed_no_thumbnail_when_image_url_empty -v
```

Expected: both FAIL.

**Step 3: Implement in `notifier.py`**

Replace the `discord.Embed(...)` block (lines 21-26) with:

```python
    embed = discord.Embed(
        title=listing["title"],
        url=listing["url"],
        color=0x19AFFF,
        timestamp=listing.get("published") or datetime.now(timezone.utc),
    )
    image_url = listing.get("image_url")
    if image_url:
        embed.set_thumbnail(url=image_url)
```

**Step 4: Run all notifier tests to verify pass**

```bash
cd C:\Users\grindig\MarketplaceScout
/c/Users/grindig/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/test_notifier.py -v
```

Expected: all pass (existing 11 + 2 new).

**Step 5: Run the full suite**

```bash
cd C:\Users\grindig\MarketplaceScout
/c/Users/grindig/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/ -q
```

Expected: **73 passed** (was 71, +2 from scanner, +2 from notifier, –0 from breaking).

**Step 6: Commit**

```bash
cd C:\Users\grindig\MarketplaceScout
git add notifier.py tests/test_notifier.py
git commit -m "feat(notifier): show listing image as embed thumbnail"
```

---

## Task 3: Update README

**Objective:** Keep README honest. The "68 tests" badge is already stale; bump to 73 and add a one-liner under "Notifications" mentioning the thumbnail.

**Files:**
- Modify: `README.md:11` (tests badge)
- Modify: `README.md:148-152` (the blockquote under "Notifications")

**Step 1: Bump the badge**

Change line 11 of `README.md` from:
```
![tests](https://img.shields.io/badge/tests-68%20passing-brightgreen)
```
to:
```
![tests](https://img.shields.io/badge/tests-73%20passing-brightgreen)
```

**Step 2: Add thumbnail mention under the "Notifications" example blockquote**

After line 146 (the `> Ø-Preis: ...` line), add a new line:

```
> 🖼️ Thumbnail of the listing photo.
```

**Step 3: Commit**

```bash
cd C:\Users\grindig\MarketplaceScout
git add README.md
git commit -m "docs: bump test count and mention embed thumbnail"
```

---

## Verification

After all 3 tasks:

```bash
cd C:\Users\grindig\MarketplaceScout
/c/Users/grindig/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/ -q
```

Expected: **73 passed in < 1s**.

```bash
cd C:\Users\grindig\MarketplaceScout
git log --oneline -5
```

Expected: 3 new commits on top of `1cd405d` (the negative-input fix from the previous turn).

---

## Risks / tradeoffs

- **Discord thumbnail size limit:** 8 MB, but we always link to Willhaben's CDN, not upload. Safe.
- **External image hotlink reliability:** Willhaben could in theory change CDN paths. Mitigation: the field is sourced at scan time; if the URL 404s at view time, Discord will show a broken-image placeholder. We don't need to handle that — the listing still has its full URL and title.
- **No fallback when only `ALL_IMAGE_URLS` is set (older payloads):** I checked the fixture and `advertImageList` is present. If Willhaben ever ships a page without it, those listings just won't have a thumbnail. That's a graceful degradation, not a regression.
- **Embed char limit:** `set_thumbnail` doesn't count against the embed body char limit (6000), it counts against embed payload size. A 6000-char body + thumbnail is well under Discord's 6000-byte embed limit. No risk.

---

## Out of scope (deliberately)

- Multiple images (gallery). Willhaben listings can have 1-10; we only show the first. Adding a gallery would need a follow-up embed or buttons — YAGNI.
- Image pre-cache / proxy through the bot. Network-cost increase is negligible (one CDN GET per view, not per scan).
- `embed.set_image(url=...)` (the larger "main" image). Different visual treatment; thumbnail is the right default for a Linktree-style notification channel.
