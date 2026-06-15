# Production Readiness & Review Fixes — Design

**Date:** 2026-06-12
**Goal:** Make the repo deployable by third parties (clone → configure → run) and fix all
issues found in the 2026-06-12 code review.

## Problems addressed

1. Fresh clone crashes: `requirements.txt` missing `discord.py`; `keyboard` imported
   unconditionally but never listed.
2. No README, no example config, no `.env` template — `load_config()` dies with
   `FileNotFoundError` and no documentation of the expected shape.
3. `.gitignore` excludes `tests/` (never published) while `docs/` is ignored yet tracked.
4. Race: each channel's `scan_loop` mutates the shared `seen_ids` set inside
   `asyncio.to_thread` while another loop may serialize it (`sorted(seen_ids)`).
5. `save_seen` writes `seen.json` in place — a crash mid-write corrupts it and every
   known listing re-notifies with `@here`.
6. `save_seen(load_seen())` on KeyboardInterrupt is a no-op.
7. `stats_loop` only catches `discord.NotFound`; any other error kills the task silently.
8. `restart()` (os.execv) is invoked from the keyboard hotkey's background thread.
9. Substring keyword matching ("RX" matches "Marx"; brands match unrelated hardware).
10. Price history is unbounded and all-time; old prices skew the Ø signal.
11. Backfill pings `@here` once per listing; `backfill_days` must be reset by hand and
    re-runs after every midnight restart.
12. `_generation()` would misclassify "RX 580" as 50xx; `_GEN_COLORS` is five copies of
    one value.
13. `/clear` and `/archive` have no permission gate.
14. Archiver retries embed-less messages forever (`send(embeds=[])` raises).
15. Two per-channel spinners fight over one terminal line.

## Design

### Deployability
- **README.md**: features, requirements, setup (venv, pip, .env, config), config key
  reference, slash commands and reactions, operational notes.
- **`.env.example`** with `DISCORD_BOT_TOKEN=`.
- **`json/config.example.json`** with placeholder channel IDs mirroring the real shape.
- **`.gitignore`**: stop ignoring `tests/` and `docs/`; keep ignoring `.env`,
  `json/config.json`, `json/seen.json`, `json/prices.json`, `json/stats_state.json`,
  caches, `temp/`.
- Commit the pending local fixes (optional `keyboard` import, `discord.py` in
  requirements).

### Correctness
- **`storage.py`** (new): `load_seen(path)` / `save_seen(seen, path)` with atomic
  tmp-file + `os.replace` writes (same pattern as `price_tracker._save`). Unit-testable.
- **`scan_once`** no longer mutates state: it receives a *snapshot* of seen IDs and
  returns new listings. The event loop (single-threaded) does `seen_ids.update(...)` and
  `save_seen`. No cross-thread mutation → no lock needed.
- **KeyboardInterrupt handler**: drop the no-op save (per-cycle saves already persist).
- **`stats_loop`**: wrap each cycle in broad try/except; keep the NotFound repost path.
- **Restart**: hotkey callback marshals onto the event loop via
  `loop.call_soon_threadsafe(restart)` so `os.execv` runs on the main thread.
- **`_generation`**: extract the model number with a digit-boundary regex
  (`(?<!\d)([1-5])0\d0(?!\d)`); anything else → "other". Single `_EMBED_COLOR` constant.
- **Archiver/commands**: messages without embeds are deleted without forwarding
  (forwarding an empty embed list raises and the message is retried forever).

### Behavior
- **Keyword matching**: per-keyword compiled regex with character-class boundaries —
  a keyword edge that is a letter must not be adjacent to another letter, a digit edge
  must not be adjacent to another digit. "RX" no longer matches "Marx"; "3060" still
  matches "RTX3060" but not "13060". Unicode-aware (umlauts).
- **Price history cap**: keep the most recent 100 entries per model (rolling window).
- **Backfill**: notifications sent with `mention=False` (no `@here`);
  `backfill_days` is reset to 0 in `json/config.json` automatically (atomic write).
- **Notifier**: `send_notification(channel, listing, mention=True)`; explicit
  `AllowedMentions(everyone=True)` only when mentioning.
- **Slash commands**: `@app_commands.default_permissions(manage_messages=True)`.
- **Spinner**: one shared spinner object with `pause()`/`resume()`; loops pause around
  their prints. Double-start/double-pause safe.

### Testing
- New `tests/test_storage.py` (roundtrip, atomicity, missing file).
- Scanner tests for boundary matching (Marx/RX, RTX3060/3060, umlauts).
- Price tracker test for the history cap.
- Stats board tests for `_generation` (RX 580 → other, 1080 Ti → 10xx).
- Full suite must pass with `python -m pytest tests/`.

### Out of scope
- LICENSE choice (legal decision left to the repo owner).
- The parent home-directory git repo tracking stale copies of these files.
- Time-based (rather than count-based) price windows.
