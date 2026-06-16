# Stats Board Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a live Discord embed that shows GPU price statistics (avg, min, max, count) per model, posted in a dedicated channel and edited hourly.

**Architecture:** A new `stats_board.py` module owns the embed builder and the async loop. `main.py` starts the loop in `on_ready` if `stats_channel_id` is configured. `price_tracker._load()` is called directly to read raw price data.

**Tech Stack:** Python 3.11+, discord.py, pytest, asyncio

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `stats_board.py` | Create | Embed builder + hourly update loop |
| `tests/test_stats_board.py` | Create | Unit tests for embed builder |
| `config.json` | Modify | Add `stats_channel_id` field |
| `main.py` | Modify | Import + start stats loop in `on_ready` |

---

### Task 1: Create `stats_board.py` with embed builder

**Files:**
- Create: `stats_board.py`
- Create: `tests/test_stats_board.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_stats_board.py`:

```python
"""Tests for the stats board embed builder."""

import discord
from stats_board import build_stats_embed


def test_empty_prices_shows_no_data():
    embed = build_stats_embed({})
    assert len(embed.fields) == 1
    assert "Noch keine Daten vorhanden" in embed.fields[0].value


def test_single_price_no_average():
    embed = build_stats_embed({"RTX 3060 Ti": [240.0]})
    field = embed.fields[0]
    assert field.name == "RTX 3060 Ti"
    assert "240 €" in field.value
    assert "1 Inserat" in field.value
    assert "Ø" not in field.value


def test_multi_price_shows_avg_min_max():
    embed = build_stats_embed({"RTX 3070": [249.0, 300.0, 550.0, 335.0, 330.0]})
    field = embed.fields[0]
    assert field.name == "RTX 3070"
    assert "Ø" in field.value
    assert "5 Inserate" in field.value
    assert "Min 249 €" in field.value
    assert "Max 550 €" in field.value


def test_models_sorted_alphabetically():
    prices = {"RTX 3080": [370.0, 350.0], "GTX 1060": [90.0, 80.0]}
    embed = build_stats_embed(prices)
    names = [f.name for f in embed.fields]
    assert names == sorted(names)


def test_embed_title_and_color():
    embed = build_stats_embed({})
    assert embed.title == "GPU Preisübersicht · Willhaben"
    assert embed.color.value == 0x19AFFF


def test_footer_contains_timestamp():
    embed = build_stats_embed({})
    assert embed.footer.text.startswith("Zuletzt aktualisiert:")
    assert "Uhr" in embed.footer.text


def test_fields_are_inline():
    embed = build_stats_embed({"RTX 3080": [370.0, 350.0]})
    assert embed.fields[0].inline is True


def test_price_with_cents():
    embed = build_stats_embed({"GTX 1060": [49.99, 50.0]})
    field = embed.fields[0]
    # avg = 49.995 → formatted with comma decimal
    assert "," in field.value or "€" in field.value
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd /path/to/Willhaben-Bot
pytest tests/test_stats_board.py -v
```

Expected: `ImportError: No module named 'stats_board'`

- [ ] **Step 3: Create `stats_board.py`**

```python
"""Live stats board: posts and hourly-edits a GPU price summary embed."""

import asyncio
from datetime import datetime

import discord

from price_tracker import _load, PRICES_PATH


def _fmt(price: float) -> str:
    """Format a price as integer or decimal euros, with comma decimal separator."""
    if price == int(price):
        return f"{int(price)} €"
    return f"{price:.2f} €".replace(".", ",")


def build_stats_embed(prices: dict) -> discord.Embed:
    """Build a Discord embed summarising all GPU prices in the given prices dict."""
    now = datetime.now()
    footer = f"Zuletzt aktualisiert: {now.strftime('%d.%m.%Y · %H:%M')} Uhr"

    embed = discord.Embed(title="GPU Preisübersicht · Willhaben", color=0x19AFFF)
    embed.set_footer(text=footer)

    if not prices:
        embed.add_field(name="Keine Daten", value="Noch keine Daten vorhanden", inline=False)
        return embed

    for model in sorted(prices.keys()):
        history = prices[model]
        if len(history) == 1:
            value = f"{_fmt(history[0])} · 1 Inserat"
        else:
            avg = sum(history) / len(history)
            value = (
                f"Ø {_fmt(avg)} · {len(history)} Inserate\n"
                f"Min {_fmt(min(history))} · Max {_fmt(max(history))}"
            )
        embed.add_field(name=model, value=value, inline=True)

    return embed


async def stats_loop(client: discord.Client, channel_id: str | None) -> None:
    """Post the stats embed once, then edit it every hour."""
    if not channel_id:
        return

    await client.wait_until_ready()

    channel = client.get_channel(int(channel_id))
    if channel is None:
        print(f"[STATS] Kanal {channel_id} nicht gefunden.")
        return

    prices = _load(PRICES_PATH)
    message = await channel.send(embed=build_stats_embed(prices))

    while True:
        await asyncio.sleep(3600)
        prices = _load(PRICES_PATH)
        embed = build_stats_embed(prices)
        try:
            await message.edit(embed=embed)
        except discord.NotFound:
            message = await channel.send(embed=embed)
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_stats_board.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add stats_board.py tests/test_stats_board.py
git commit -m "feat: add stats_board with hourly GPU price embed"
```

---

### Task 2: Wire stats loop into `main.py` and update `config.json`

**Files:**
- Modify: `main.py`
- Modify: `config.json`

- [ ] **Step 1: Add `stats_channel_id` to `config.json`**

Open `config.json` and add the field at the top level (replace `YOUR_STATS_CHANNEL_ID` with the actual Discord channel ID):

```json
{
  "scan_interval_seconds": 60,
  "bot_token": "...",
  "stats_channel_id": "YOUR_STATS_CHANNEL_ID",
  "channels": [ ... ]
}
```

- [ ] **Step 2: Import `stats_loop` in `main.py`**

Add to the imports at the top of `main.py`:

```python
from stats_board import stats_loop
```

- [ ] **Step 3: Start the loop in `on_ready`**

In `main.py`, inside the `on_ready` event, after the existing `create_task` calls:

```python
        for channel_cfg in config["channels"]:
            client.loop.create_task(scan_loop(client, config, channel_cfg, seen_ids))
        client.loop.create_task(midnight_restart())
        client.loop.create_task(stats_loop(client, config.get("stats_channel_id")))
```

- [ ] **Step 4: Run the full test suite**

```
pytest -v
```

Expected: all existing + new tests PASS.

- [ ] **Step 5: Commit**

```bash
git add main.py config.json
git commit -m "feat: wire stats_loop into bot startup"
```
