1|# Production Readiness & Review Fixes — Design
2|
3|**Date:** 2026-06-12
4|**Goal:** Make the repo deployable by third parties (clone → configure → run) and fix all
5|issues found in the 2026-06-12 code review.
6|
7|## Problems addressed
8|
9|1. Fresh clone crashes: `requirements.txt` missing `discord.py`; `keyboard` imported
10|   unconditionally but never listed.
11|2. No README, no example config, no `.env` template — `load_config()` dies with
12|   `FileNotFoundError` and no documentation of the expected shape.
13|3. `.gitignore` excludes `tests/` (never published) while `docs/` is ignored yet tracked.
14|4. Race: each channel's `scan_loop` mutates the shared `seen_ids` set inside
15|   `asyncio.to_thread` while another loop may serialize it (`sorted(seen_ids)`).
16|5. `save_seen` writes `seen.json` in place — a crash mid-write corrupts it and every
17|   known listing re-notifies with `@here`.
18|6. `save_seen(load_seen())` on KeyboardInterrupt is a no-op.
19|7. `stats_loop` only catches `discord.NotFound`; any other error kills the task silently.
20|8. `restart()` (os.execv) is invoked from the keyboard hotkey's background thread.
21|9. Substring keyword matching ("RX" matches "Marx"; brands match unrelated hardware).
22|10. Price history is unbounded and all-time; old prices skew the Ø signal.
23|11. Backfill pings `@here` once per listing; `backfill_days` must be reset by hand and
24|    re-runs after every midnight restart.
25|12. `_generation()` would misclassify "RX 580" as 50xx; `_GEN_COLORS` is five copies of
26|    one value.
27|13. `/clear` and `/archive` have no permission gate.
28|14. Archiver retries embed-less messages forever (`send(embeds=[])` raises).
29|15. Two per-channel spinners fight over one terminal line.
30|
31|## Design
32|
33|### Deployability
34|- **README.md**: features, requirements, setup (venv, pip, .env, config), config key
35|  reference, slash commands and reactions, operational notes.
36|- **`.env.example`** with `DISCORD_BOT_TOKEN=`.
37|- **`cfg/config.example.json`** with placeholder channel IDs mirroring the real shape.
38|- **`.gitignore`**: stop ignoring `tests/` and `docs/`; keep ignoring `.env`,
39|  `cfg/config.json`, `cfg/seen.json`, `cfg/prices.json`, `cfg/stats_state.json`,
40|  caches, `temp/`.
41|- Commit the pending local fixes (optional `keyboard` import, `discord.py` in
42|  requirements).
43|
44|### Correctness
45|- **`storage.py`** (new): `load_seen(path)` / `save_seen(seen, path)` with atomic
46|  tmp-file + `os.replace` writes (same pattern as `price_tracker._save`). Unit-testable.
47|- **`scan_once`** no longer mutates state: it receives a *snapshot* of seen IDs and
48|  returns new listings. The event loop (single-threaded) does `seen_ids.update(...)` and
49|  `save_seen`. No cross-thread mutation → no lock needed.
50|- **KeyboardInterrupt handler**: drop the no-op save (per-cycle saves already persist).
51|- **`stats_loop`**: wrap each cycle in broad try/except; keep the NotFound repost path.
52|- **Restart**: hotkey callback marshals onto the event loop via
53|  `loop.call_soon_threadsafe(restart)` so `os.execv` runs on the main thread.
54|- **`_generation`**: extract the model number with a digit-boundary regex
55|  (`(?<!\d)([1-5])0\d0(?!\d)`); anything else → "other". Single `_EMBED_COLOR` constant.
56|- **Archiver/commands**: messages without embeds are deleted without forwarding
57|  (forwarding an empty embed list raises and the message is retried forever).
58|
59|### Behavior
60|- **Keyword matching**: per-keyword compiled regex with character-class boundaries —
61|  a keyword edge that is a letter must not be adjacent to another letter, a digit edge
62|  must not be adjacent to another digit. "RX" no longer matches "Marx"; "3060" still
63|  matches "RTX3060" but not "13060". Unicode-aware (umlauts).
64|- **Price history cap**: keep the most recent 100 entries per model (rolling window).
65|- **Backfill**: notifications sent with `mention=False` (no `@here`);
66|  `backfill_days` is reset to 0 in `cfg/config.json` automatically (atomic write).
67|- **Notifier**: `send_notification(channel, listing, mention=True)`; explicit
68|  `AllowedMentions(everyone=True)` only when mentioning.
69|- **Slash commands**: `@app_commands.default_permissions(manage_messages=True)`.
70|- **Spinner**: one shared spinner object with `pause()`/`resume()`; loops pause around
71|  their prints. Double-start/double-pause safe.
72|
73|### Testing
74|- New `tests/test_storage.py` (roundtrip, atomicity, missing file).
75|- Scanner tests for boundary matching (Marx/RX, RTX3060/3060, umlauts).
76|- Price tracker test for the history cap.
77|- Stats board tests for `_generation` (RX 580 → other, 1080 Ti → 10xx).
78|- Full suite must pass with `python -m pytest tests/`.
79|
80|### Out of scope
81|- LICENSE choice (legal decision left to the repo owner).
82|- The parent home-directory git repo tracking stale copies of these files.
83|- Time-based (rather than count-based) price windows.
84|