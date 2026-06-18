# 🛰️ MarketplaceScout

> **Snipe cheap & defective GPUs on [willhaben.at](https://www.willhaben.at) before anyone else even hits refresh.**

A Discord bot that watches Austria's biggest marketplace for graphics-card listings and fires them into your server the second they go live — with price history, average-price comparison, and a self-updating stats board.

Built for one job: catch the underpriced and the broken-but-fixable **first**.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![discord.py](https://img.shields.io/badge/discord.py-2.x-5865F2)
![tests](https://img.shields.io/badge/tests-138%20passing-brightgreen)
![made in](https://img.shields.io/badge/made%20for-🇦🇹%20willhaben-red)

---

## ✨ What it does

| | |
|---|---|
| 🔁 **Never stops looking** | Polls any number of willhaben search URLs on your interval (default: every 60s). |
| 🎯 **Smart matching** | Keyword **+** price filtering that's boundary-aware: `RX` won't match *"Marx"*, but `defekt` still catches *"Defekte Grafikkarte"* and `3060` catches *"RTX3060"*. |
| ⚡ **Instant alerts** | Clean Discord embeds: title, price, location, PayLivery status, direct link — with an `@here` ping. |
| 📈 **Price intelligence** | Records matched prices (rolling last-100 per model) and tells you how a new listing stacks up: *"Ø 450 € (−12% unter Ø, 23 Inserate)"*. |
| 📊 **Live stats board** | A self-editing message with avg/min/max per model, grouped by GPU generation (10xx → 50xx), refreshed hourly. |
| 🗂️ **One-click triage** | React ✅ to keep (→ *marked* thread) or ❌ to dismiss (→ *archive* thread). |
| 🧹 **Self-cleaning** | Listings older than 24h auto-archive. Channels stay tidy on their own. |
| ⏪ **Backfill** | On first boot, optionally pull the last *N* days — no pings, no zero-state. |
| 🔀 **Multi-channel** | Each channel gets its own URLs and price ceiling. Bargain-bin under 100 €? High-end flagships? Both. |

---

## 🧠 How it works

Willhaben renders its search results with Next.js and ships the **entire result set as JSON** inside the page's `__NEXT_DATA__` script tag. So instead of fragile HTML scraping, the bot grabs that JSON straight from the source, filters it, dedupes against everything it's already seen, and posts the rest.

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

---

## 🗺️ The map

| File | What it owns |
|---|---|
| `main.py` | Entry point: Discord client, per-channel scan loops, backfill, nightly restart |
| `scanner.py` | Fetches search pages, parses listings from `__NEXT_DATA__`, does the matching |
| `notifier.py` | Builds & sends the Discord embeds |
| `archiver.py` | ❌-reaction archiving + the 24h auto-archive loop |
| `marker.py` | ✅-reaction handling (→ *marked* thread) |
| `commands.py` | `/clear` and `/archive` slash commands |
| `price_tracker.py` | Records prices, computes historical averages |
| `stats_board.py` | The self-updating price overview |
| `storage.py` | Atomic persistence for seen listing IDs |
| `colors.py` | ANSI colors for the terminal output |

---

## 🚀 Get it running

### 1. You'll need

- **Python 3.10+**
- A Discord bot token from the [Developer Portal](https://discord.com/developers/applications), invited to your server with permission to **send messages, create threads, add reactions, and manage messages** (+ *Mention @everyone* if you want `@here` pings).

### 2. Install

Clone the repo first:

```bash
git clone https://github.com/grindig/MarketplaceScout.git
cd MarketplaceScout
```

The recommended production path is **Docker Compose**. It gives you a pinned
Python runtime, automatic container restarts, persistent state files, graceful
shutdowns, and bounded Docker logs without installing Python packages on the
host.

If you prefer a local Python process for development, the classic
`pip install -r requirements.txt && python main.py` flow still works.

### 3. Drop in your token

Copy `.env.example` → `.env`:

```env
DISCORD_BOT_TOKEN=your-bot-token-here
```

### 4. Configure

Copy `cfg/config.example.json` → `cfg/config.json` and fill in your channel IDs and search URLs:

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
| `seen_ttl_days` | Days to remember seen listing IDs (default `52`). Older IDs are pruned on load/save. |
| `language` | UI language: `en` (default) or `de`. Requires a restart to apply. |
| `auto_archive_interval_minutes` | How often the auto-archiver checks for >24h-old listings (default `30`) |
| `backfill_days` | On startup, fetch the last *N* days (`0` = off — auto-reset to `0` once done) |
| `stats_channel_id` | Channel for the live stats board (omit to disable) |
| `channels` | One entry per Discord channel to post into |
| `channels[].channel_id` | Discord channel ID |
| `channels[].max_price` | Price ceiling in EUR; `null` = no limit. No-price listings always pass |
| `channels[].track_prices` | Record matched GPU prices in `prices.json` |
| `channels[].show_price_stats` | Add the Ø-price comparison field to embeds |
| `channels[].search_urls` | willhaben search URLs to poll — just build a search on the site and copy the URL |

> 💡 Keywords live in `cfg/keywords.json`. A listing matches if its title contains **at least one** keyword (case-insensitive, boundary-aware). The `gpu_models` list doubles as the price-tracking key — a title with `RTX 3080 Ti` records under that model (longest match wins).

### 5. Run with Docker Compose

Build and start the bot in the background:

```bash
docker compose up -d --build
```

Watch logs:

```bash
docker compose logs -f marketplacescout
```

Stop it cleanly:

```bash
docker compose down
```

The Compose file bind-mounts `./json` into the container, so your
`config.json`, `seen.json`, `prices.json`, `stats_state.json`, and custom
`keywords.json` stay on the host and survive rebuilds/recreates. The container
uses `SIGINT` on stop so the bot follows its normal graceful shutdown path and
flushes pending seen IDs.

On Linux hosts with a non-`1000:1000` user, set `MARKETPLACESCOUT_UID` and
`MARKETPLACESCOUT_GID` in `.env` to the output of `id -u` and `id -g` so the
container can write to the bind-mounted `cfg/` directory.

### 6. Update a Docker deployment

For source-based deployments:

```bash
git pull
docker compose up -d --build
```

That rebuilds the image from the current checkout and recreates only the bot
container. Your `.env` and `cfg/` runtime state remain untouched.

Before larger upgrades, back up local state:

```bash
tar -czf marketplacescout-state-$(date +%F).tar.gz .env cfg/config.json cfg/seen.json cfg/prices.json cfg/stats_state.json
```

### 7. Run without Docker

```bash
pip install -r requirements.txt
python main.py
```

On startup it syncs slash commands, runs the backfill (if set), and spins up one scan loop per channel. It restarts itself nightly at midnight to stay fresh.

---

## 🎮 Using it

### Notifications

Every new match lands as an embed with an `@here`:

> **Zorac RTX 3080 Amp Holo**
> Preis: **399 €** · Standort: **Wien, Meidling** · PayLivery: ✅
> Ø-Preis: 450 € (−11% unter Ø, 23 Inserate)
> 🖼️ Thumbnail of the listing photo.

### Reactions

| React | Effect |
|:-:|---|
| ✅ | → **marked** thread (interesting, follow up) |
| ❌ | → **archive** thread (not for you) |

Threads are created automatically the first time they're needed. Anything left untouched for 24h archives itself.

### Slash commands

Both default to requiring **Manage Messages** (tweak per server under *Server Settings → Integrations*).

| Command | Description |
|---|---|
| `/clear [days] [hours] [minutes]` | Delete all bot notifications from the last *d*/*h*/*m* in this channel (all optional, ≥1 required) |
| `/archive [days] [hours] [minutes]` | Move all bot notifications from the last *d*/*h*/*m* to the archive thread (all optional, ≥1 required) |

The bot also restarts itself nightly at midnight to stay fresh. To restart manually, stop the process (`Ctrl+C`) and run `python main.py` again.

## Languages

The bot's console output, embed field names, and slash-command descriptions are
fully translatable. Set `language` in `cfg/config.json` to one of the available
codes (currently `en` and `de`) and restart the bot.

Adding a new language is two steps:
1. Copy `locales/en.json` to `locales/<code>.json` and translate the values.
2. Add the code to `AVAILABLE_LANGUAGES` in `i18n.py`.

---

## 💾 State files

All runtime state lives in `cfg/` and is git-ignored:

| File | Holds |
|---|---|
| `config.json` | Your config (above) |
| `seen.json` | IDs of every listing already posted (dedup) |
| `prices.json` | Recorded price history per model |
| `stats_state.json` | The stats board's message ID, so it survives restarts |

---

## 🧪 Tests

```bash
pip install pytest
python -m pytest tests/
```

138 tests covering parsing, the boundary-aware matcher, backfill pagination, dedup, atomic writes, the in-memory seen-ID writer, the price tracker, scanner fast-path import hygiene, and the i18n layer.

---

## 📌 Notes

- The bot identifies as a regular browser and only polls public search pages at a modest rate. **Be considerate** with your scan interval and URL count.
- Console output is in the configured language (`en` by default).
