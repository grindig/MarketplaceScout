# Design: Auto-Archive Stale Messages

**Date:** 2026-04-28  
**Status:** Approved

## Summary

Bot messages still sitting in #gebraucht or #defekt after 24 hours are automatically moved to the channel's `"archive"` thread. No reaction check — purely time-based. Messages already moved to archive or marked threads are unaffected (they are no longer in the main channel).

## Architecture

### Changes to `archiver.py`

New function: **`auto_archive_loop(client: discord.Client, channel_ids: list[int]) -> None`**

- Background coroutine, started once per bot session
- Runs every `auto_archive_interval_minutes` minutes (read from config, default 30)
- For each channel ID: resolves the `discord.TextChannel`, scans `channel.history(limit=None, oldest_first=True)` with `before=now - 24h`
- Filters for messages authored by the bot
- For each match: calls `find_or_create_archive_thread(channel)` then sends embeds and deletes the original — same pattern as the manual ❌ reaction flow
- One thread lookup per channel per sweep (reused across messages in that run)

### Changes to `main.py`

- Pass `auto_archive_interval_minutes` from config into `auto_archive_loop`
- Start `auto_archive_loop` in `on_ready` with the list of channel IDs from `config["channels"]`

### Changes to `config.json`

- Add optional key `"auto_archive_interval_minutes"` (default: 30)

## Data Flow

```
auto_archive_loop wakes every 30 min
  → for each channel:
      → channel.history(before=now - 24h)
          → filter: msg.author == bot
          → find_or_create_archive_thread()
          → archive_thread.send(embeds=msg.embeds)
          → msg.delete()
```

## Error Handling

Same rules as the existing archiver:

| Failure point | Behavior |
|---|---|
| Channel not found | Skip silently |
| History fetch fails | Log `[WARN]`, skip channel |
| Thread find/create fails | Log `[WARN]`, skip channel for this run |
| Archive post fails | Log `[WARN]`, do NOT delete original |
| Delete fails | Log `[WARN]`, message stays in channel |

## Testing

No automated tests — Discord-API-bound, same as existing archiver. Existing tests unaffected.
