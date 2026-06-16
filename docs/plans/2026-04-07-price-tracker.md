# Price Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Track historical prices per GPU model from "gebraucht" listings and show average + deviation in the Discord embed.

**Architecture:** A new `price_tracker.py` module handles all price logic (model detection, storage, stats). `scan_loop` in `main.py` calls it per listing when `track_prices` is enabled on the channel. The embed in `notifier.py` shows stats when `show_price_stats` is enabled and data is available.

**Tech Stack:** Python 3.11, discord.py, JSON file storage (`prices.json`)

---

### Task 1: Restructure keywords.json and update main.py loader

**Files:**
- Modify: `keywords.json`
- Modify: `main.py` (the `load_config` function)

- [ ] **Step 1: Restructure keywords.json**

Replace the flat array with an object:

```json
{
  "general": [
    "defekt", "kaputt", "broken", "defective", "bastler",
    "bastelware", "reparatur", "ersatzteile", "geht nicht",
    "startet nicht", "kein bild", "no display", "artifact",
    "artefakte", "überhitzt", "fan defekt", "lüfter kaputt",
    "RTX", "GTX", "nvidia",
    "1060", "1070", "1080",
    "2060", "2070", "2080",
    "3060", "3070", "3080", "3090",
    "4060", "4070", "4080", "4090",
    "5060", "5070", "5080", "5090",
    "RX", "radeon",
    "RX 580", "RX 6600", "RX 6700", "RX 6800", "RX 6900",
    "RX 7600", "RX 7700", "RX 7800", "RX 7900",
    "Quadro", "Tesla",
    "MSI", "ASUS", "Gigabyte", "EVGA", "Zotac", "Sapphire",
    "PowerColor", "XFX",
    "grafikkarte", "GPU", "Grafik"
  ],
  "gpu_models": [
    "GTX 1060", "GTX 1070", "GTX 1080",
    "RTX 2060", "RTX 2070", "RTX 2080",
    "RTX 3060", "RTX 3070", "RTX 3080", "RTX 3090",
    "RTX 4060", "RTX 4070", "RTX 4080", "RTX 4090",
    "RTX 5060", "RTX 5070", "RTX 5080", "RTX 5090"
  ]
}
```

- [ ] **Step 2: Update load_config in main.py**

Replace the current keywords loading block:

```python
def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
    with open(KEYWORDS_PATH, "r", encoding="utf-8") as f:
        kw = json.load(f)
    config["keywords"] = kw["general"] + kw["gpu_models"]
    config["gpu_models"] = kw["gpu_models"]
    return config
```

- [ ] **Step 3: Commit**

```bash
git add keywords.json main.py
git commit -m "refactor: split keywords.json into general + gpu_models"
```

---

### Task 2: Create price_tracker.py

**Files:**
- Create: `price_tracker.py`
- Create: `tests/test_price_tracker.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_price_tracker.py`:

```python
"""Tests for price_tracker module."""

import json
import pytest

from price_tracker import find_gpu_model, record_price, get_stats

GPU_MODELS = [
    "GTX 1060", "GTX 1070", "GTX 1080",
    "RTX 2060", "RTX 2070", "RTX 2080",
    "RTX 3060", "RTX 3070", "RTX 3080", "RTX 3090",
]


def test_find_gpu_model_match(tmp_path):
    assert find_gpu_model("RTX 3080 defekt", GPU_MODELS) == "RTX 3080"


def test_find_gpu_model_case_insensitive(tmp_path):
    assert find_gpu_model("rtx 3080 Grafikkarte", GPU_MODELS) == "RTX 3080"


def test_find_gpu_model_longest_match(tmp_path):
    # "RTX 3080" and a hypothetical "RTX 3080 Ti" — longest wins
    models = GPU_MODELS + ["RTX 3080 Ti"]
    assert find_gpu_model("RTX 3080 Ti kaputt", models) == "RTX 3080 Ti"


def test_find_gpu_model_no_match(tmp_path):
    assert find_gpu_model("Mainboard defekt", GPU_MODELS) is None


def test_record_and_get_stats(tmp_path):
    p = str(tmp_path / "prices.json")
    record_price("RTX 3080", 150.0, p)
    record_price("RTX 3080", 170.0, p)
    stats = get_stats("RTX 3080", p)
    assert stats["avg"] == 160.0
    assert stats["count"] == 2


def test_get_stats_insufficient_data(tmp_path):
    p = str(tmp_path / "prices.json")
    record_price("RTX 3080", 150.0, p)
    assert get_stats("RTX 3080", p) is None  # need at least 2 entries


def test_get_stats_unknown_model(tmp_path):
    p = str(tmp_path / "prices.json")
    assert get_stats("RTX 9999", p) is None


def test_record_price_persists(tmp_path):
    p = str(tmp_path / "prices.json")
    record_price("GTX 1080", 80.0, p)
    with open(p) as f:
        data = json.load(f)
    assert data["GTX 1080"] == [80.0]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /path/to/Willhaben-Bot
pytest tests/test_price_tracker.py -v
```

Expected: `ModuleNotFoundError: No module named 'price_tracker'`

- [ ] **Step 3: Create price_tracker.py**

```python
"""Price tracker: records GPU listing prices and computes historical averages."""

import json
import os
from typing import Optional

PRICES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prices.json")


def find_gpu_model(title: str, gpu_models: list[str]) -> Optional[str]:
    """Return the longest GPU model keyword found in title (case-insensitive), or None."""
    title_lower = title.lower()
    matches = [m for m in gpu_models if m.lower() in title_lower]
    return max(matches, key=len) if matches else None


def _load(prices_path: str) -> dict:
    if not os.path.exists(prices_path):
        return {}
    with open(prices_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(prices: dict, prices_path: str) -> None:
    with open(prices_path, "w", encoding="utf-8") as f:
        json.dump(prices, f, indent=2)


def record_price(model: str, price: float, prices_path: str = PRICES_PATH) -> None:
    """Append a price entry for the given GPU model."""
    prices = _load(prices_path)
    prices.setdefault(model, []).append(price)
    _save(prices, prices_path)


def get_stats(model: str, prices_path: str = PRICES_PATH) -> Optional[dict]:
    """Return {avg, count} for the model if at least 2 prices recorded, else None."""
    history = _load(prices_path).get(model, [])
    if len(history) < 2:
        return None
    avg = sum(history) / len(history)
    return {"avg": avg, "count": len(history)}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_price_tracker.py -v
```

Expected: all 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add price_tracker.py tests/test_price_tracker.py
git commit -m "feat: add price_tracker module with model detection and stats"
```

---

### Task 3: Update config.json

**Files:**
- Modify: `config.json`

- [ ] **Step 1: Add track_prices and show_price_stats to each channel**

The defekt channel does not track prices. The gebraucht channel tracks and shows stats:

```json
{
  "scan_interval_seconds": 60,
  "bot_token": "...",
  "channels": [
    {
      "channel_id": "123456789012345678",
      "max_price": 200,
      "track_prices": false,
      "show_price_stats": false,
      "search_urls": [
        "https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz/pc-komponenten-5878/a/zustand-defekt-24?rows=30&isNavigation=true"
      ]
    },
    {
      "channel_id": "234567890123456789",
      "max_price": 0,
      "track_prices": true,
      "show_price_stats": true,
      "search_urls": [
        "https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz/pc-komponenten-5878/a/zustand-gebraucht-23?rows=30&isNavigation=true"
      ]
    }
  ]
}
```

- [ ] **Step 2: Commit**

```bash
git add config.json
git commit -m "feat: add track_prices and show_price_stats flags to channel config"
```

---

### Task 4: Integrate price tracker into scan_loop (main.py)

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add import at top of main.py**

Add after the existing imports:

```python
from price_tracker import find_gpu_model, record_price, get_stats
```

- [ ] **Step 2: Update the listing notification block inside scan_loop**

Replace the existing `for listing in new_listings:` block:

```python
for listing in new_listings:
    price_str = f"{listing['price']:.2f} EUR" if listing["price"] else "N/A"
    print(f"  {YELLOW}->{RESET} {listing['title']} | {price_str} | {listing['location']}")

    if channel_cfg.get("track_prices") and listing.get("price") is not None:
        model = find_gpu_model(listing["title"], config["gpu_models"])
        if model:
            stats = get_stats(model)  # fetch BEFORE recording so current price isn't in avg
            record_price(model, listing["price"])
            if channel_cfg.get("show_price_stats") and stats:
                pct = ((listing["price"] - stats["avg"]) / stats["avg"]) * 100
                listing["price_stats"] = {
                    "avg": stats["avg"],
                    "count": stats["count"],
                    "pct": pct,
                }

    await send_notification(channel, listing)
```

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: call price tracker in scan_loop for channels with track_prices enabled"
```

---

### Task 5: Show price stats in Discord embed (notifier.py)

**Files:**
- Modify: `notifier.py`

- [ ] **Step 1: Add price stats field to build_embed**

Add after the existing `embed.add_field` calls, before `return embed`:

```python
stats = listing.get("price_stats")
if stats:
    avg = stats["avg"]
    pct = stats["pct"]
    if avg == int(avg):
        avg_str = f"{int(avg)} €"
    else:
        avg_str = f"{avg:.2f} €".replace(".", ",")
    direction = "über" if pct >= 0 else "unter"
    embed.add_field(
        name="Ø-Preis",
        value=f"{avg_str} ({pct:+.0f}% {direction} Ø, {stats['count']} Inserate)",
        inline=False,
    )
```

- [ ] **Step 2: Commit**

```bash
git add notifier.py
git commit -m "feat: show GPU price average and deviation in gebraucht embed"
```
