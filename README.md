# Willhaben Bot

A Discord bot that watches [willhaben.at](https://www.willhaben.at) for GPU listings and posts new matches to your server in real time — including price history, average-price comparison, and a live stats board.

Built to catch cheap and defective graphics cards the moment they're listed, before anyone else sees them.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![discord.py](https://img.shields.io/badge/discord.py-2.x-5865F2)

## Features

- **Continuous scanning** — polls any number of willhaben search URLs on a configurable interval (default: every 60 seconds)
- **Keyword + price filtering** — matches listings against a keyword list (GPU models, brands, "defekt", "kein bild", …) and an optional price ceiling per channel. Matching is boundary-aware: acronyms like `RX` won't match inside words ("Marx"), while German inflections and compounds still match (`defekt` → "Defekte Grafikkarte")
- **Instant Discord notifications** — clean embeds with title, price, location, PayLivery status, and a direct link to the listing
- **Price tracking** — records matched GPU prices (rolling window of the last 100 per model) and shows how a new listing compares to the historical average (e.g. *"Ø 450 € (−12% unter Ø, 23 Inserate)"*)
- **Live stats board** — a self-updating message with average / min / max prices per GPU model, grouped by generation (10xx–50xx), refreshed hourly
- **Reaction workflow** — sort listings with a single click:
  - ✅ moves the listing to the **marked** thread (interesting, follow up later)
  - ❌ moves it to the **archive** thread (not interesting)
- **Auto-archiving** — listings older than 24 hours are moved to the archive thread automatically, keeping channels clean
- **Backfill** — on first start, optionally pulls listings from the last *N* days (without @here pings) so you don't start from zero
- **Multi-channel** — each Discord channel gets its own search URLs and price limit (e.g. one channel for bargains under 100 €, one for high-end cards)

## How it works

Willhaben renders its search results with Next.js and ships the full result set as JSON inside the page's `__NEXT_DATA__` script tag. The bot fetches the search page, extracts that JSON directly (no fragile HTML scraping), filters by your keywords and price limit, deduplicates against everything it has already seen, and posts the rest to Discord.

```
willhaben.at ──► scanner ──► keyword/price filter ──► dedup (seen.json)
                                                          │
        stats board ◄── price tracker ◄──────────────── new listings
        (hourly)        (prices.json)                     │
                                                          ▼
                                                  Discord embed + @here
                                                          │
                                            ✅ marked / ❌ archive / 24h auto-archive
```

## Project structure

| File | Purpose |
|---|---|
| `main.py` | Entry point: Discord client, per-channel scan loops, backfill, nightly restart |
| `scanner.py` | Fetches search pages and parses listings from the `__NEXT_DATA__` JSON |
| `notifier.py` | Builds and sends the Discord embeds |
| `archiver.py` | ❌-reaction archiving and the 24-hour auto-archive loop |
| `marker.py` | ✅-reaction handling (moves listings to the *marked* thread) |
| `commands.py` | `/clear` and `/archive` slash commands |
| `price_tracker.py` | Records GPU prices and computes historical averages |
| `stats_board.py` | The self-updating price overview message |
| `storage.py` | Atomic persistence for seen listing IDs |
| `colors.py` | ANSI colors for the terminal output |

## Setup

### 1. Requirements

- Python **3.10+**
- A Discord bot token ([Discord Developer Portal](https://discord.com/developers/applications)) with the bot invited to your server and permission to send messages, create threads, add reactions, and manage messages (plus *Mention @everyone* if you want @here pings)

### 2. Install

```bash
git clone https://github.com/grindig/Willhaben-Bot.git
cd Willhaben-Bot
pip install -r requirements.txt
```

### 3. Bot token

Copy `.env.example` to `.env` and paste your bot token:

```env
WILLHABEN_BOT_TOKEN=your-bot-token-here
```

### 4. Configuration

Copy `json/config.example.json` to `json/config.json` and fill in your channel IDs and search URLs:

```json
{
  "scan_interval_seconds": 60,
  "auto_archive_interval_minutes": 30,
  "backfill_days": 0,
  "stats_channel_id": "123456789012345678",
  "channels": [
    {
      "channel_id": "123456789012345678",
      "max_price": 150,
      "track_prices": true,
      "show_price_stats": true,
      "search_urls": [
        "https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz?keyword=grafikkarte+defekt"
      ]
    }
  ]
}
```

| Key | Description |
|---|---|
| `scan_interval_seconds` | Seconds between scans (default `60`) |
| `auto_archive_interval_minutes` | How often the auto-archiver checks for listings older than 24 h (default `30`) |
| `backfill_days` | On startup, fetch listings from the last *N* days (`0` = off — automatically reset to `0` after the backfill completes) |
| `stats_channel_id` | Channel for the live price stats board (optional, omit to disable) |
| `channels` | One entry per Discord channel to post into |
| `channels[].channel_id` | Discord channel ID |
| `channels[].max_price` | Price ceiling in EUR; `null` = no limit. Listings without a price always pass |
| `channels[].track_prices` | Record matched GPU prices in `prices.json` |
| `channels[].show_price_stats` | Add the Ø-price comparison field to embeds |
| `channels[].search_urls` | Willhaben search result URLs to poll — just build a search on willhaben.at and copy the URL |

Keywords live in `json/keywords.json`. A listing matches if its title contains **at least one** keyword (case-insensitive, boundary-aware). The `gpu_models` list is also used for price tracking — when a title contains a model like `RTX 3080 Ti`, its price is recorded under that model (longest match wins).

### 5. Run

```bash
python main.py
```

On startup the bot syncs its slash commands, runs the backfill (if configured), and starts one scan loop per channel. It restarts itself every night at midnight to stay fresh.

## Usage

### Notifications

Every new match is posted as an embed with an `@here` ping:

> **Zorac RTX 3080 Amp Holo**
> Preis: **399 €** · Standort: **Wien, Meidling** · PayLivery: ✅
> Ø-Preis: 450 € (−11% unter Ø, 23 Inserate)

### Reactions

| Reaction | Effect |
|---|---|
| ✅ | Listing moves to the **marked** thread |
| ❌ | Listing moves to the **archive** thread |

The threads are created automatically the first time they're needed. Anything left untouched for 24 hours is archived automatically.

### Slash commands

Both commands default to requiring the **Manage Messages** permission (adjustable per server under *Server Settings → Integrations*).

| Command | Description |
|---|---|
| `/clear [days] [hours] [minutes]` | Delete all bot notifications from the last *d* days, *h* hours, and/or *m* minutes in this channel (all optional, at least one required) |
| `/archive [days] [hours] [minutes]` | Move all bot notifications from the last *d* days, *h* hours, and/or *m* minutes to the archive thread (all optional, at least one required) |

### Hotkey

`Ctrl+R` restarts the bot. **Note:** the `keyboard` module hooks the key system-wide, not just in the bot's terminal — pressing Ctrl+R in any application (e.g. refreshing a browser tab) triggers the restart. The hotkey is optional; it requires the `keyboard` module to have the necessary OS permissions (on Linux typically root) and is skipped otherwise. Remove the `keyboard` entry from `requirements.txt` to disable it entirely.

## Data files

All state lives in `json/` and is git-ignored:

| File | Contents |
|---|---|
| `config.json` | Your configuration (see above) |
| `seen.json` | IDs of every listing already posted (prevents duplicates) |
| `prices.json` | Recorded price history per GPU model |
| `stats_state.json` | Message ID of the stats board, so it survives restarts |

## Tests

```bash
pip install pytest
python -m pytest tests/
```

## Notes

- The bot identifies as a regular browser and only polls public search pages at a modest rate. Be considerate with the scan interval and the number of search URLs.
- Console output is in German, matching the Austrian marketplace it watches. 🇦🇹
