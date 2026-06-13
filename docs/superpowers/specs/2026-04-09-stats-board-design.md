# Stats Board — Design Spec

**Date:** 2026-04-09
**Status:** Approved

## Summary

A live Discord embed that displays GPU price statistics from `prices.json`, posted in a dedicated channel and edited hourly.

## Config

`config.json` gets one new top-level field:

```json
"stats_channel_id": "<channel_id>"
```

If the field is absent, the stats board does not start (no crash).

## Architecture

**New file:** `stats_board.py`
- `build_stats_embed(prices: dict) -> discord.Embed` — builds the embed from raw price data
- `async def stats_loop(client, channel_id: str)` — waits for bot ready, posts the first message, then edits it every hour

**`main.py`** — one new line in `on_ready`:
```python
client.loop.create_task(stats_loop(client, config.get("stats_channel_id")))
```

**`price_tracker.py`** — unchanged. `stats_board.py` calls `_load()` directly.

## Embed Structure

- **Title:** `GPU Preisübersicht · Willhaben`
- **Color:** `0x19AFFF` (matches existing embeds)
- **Fields:** One inline field per GPU model (2 per row), alphabetically sorted:
  ```
  RTX 3070
  Ø 353 € · 5 Inserate
  Min 249 € · Max 550 €
  ```
  Models with only 1 entry: show the single price + `1 Inserat`, no Ø line.
- **Empty state:** Single field `Noch keine Daten vorhanden` if `prices.json` is empty.
- **Footer:** `Zuletzt aktualisiert: 09.04.2026 · 14:00 Uhr` (local time, 24h format)

## Loop Behavior

- On startup: post first message, store `Message` object in memory (no file persistence).
- Every hour: call `message.edit(embed=...)`.
- If the stored message was deleted: catch `discord.NotFound`, post a new message, store new reference.
- If `stats_channel_id` missing from config: skip silently.

## Files Changed

| File | Change |
|------|--------|
| `stats_board.py` | New — all stats board logic |
| `config.json` | Add `stats_channel_id` field |
| `main.py` | One import + one `create_task` call in `on_ready` |
