# TTL for seen listing IDs

> **For Hermes:** Implement this plan task-by-task.

**Goal:** Stop `json/seen.json` from growing forever by keeping only IDs seen within the last 52 days.

**Architecture:** Replace the flat sorted-list format with a dict mapping `id -> first_seen_iso_timestamp`. On load, drop entries older than `seen_ttl_days`. On save, preserve existing timestamps, add new IDs with the current timestamp, prune old entries, and atomically rewrite the file. The old list format is detected and migrated automatically on first boot.

**Tech Stack:** Python stdlib (`datetime`, `json`), existing `storage.atomic_write_json`.

---

## Task 1: Add `seen_ttl_days` to the example config

**Objective:** Expose the TTL setting so users can tune it.

**Files:**
- Modify: `json/config.example.json`

**Step 1: Add the key**

Add `"seen_ttl_days": 52` at the top level, next to `scan_interval_seconds`.

**Step 2: Verify**

Run: `python -c "import json; print(json.load(open('json/config.example.json'))['seen_ttl_days'])"`
Expected: `52`

---

## Task 2: Rewrite `storage.py` for TTL-aware seen IDs

**Objective:** Support loading/saving a timestamped dict, prune old entries, and migrate the legacy list format.

**Files:**
- Modify: `storage.py`

**Step 1: Add constants and helpers**

```python
from datetime import datetime, timedelta, timezone

DEFAULT_SEEN_TTL_DAYS = 52


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _cutoff(ttl_days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=ttl_days)
```

**Step 2: Update `load_seen`**

```python
def load_seen(path: str = SEEN_PATH, ttl_days: int = DEFAULT_SEEN_TTL_DAYS) -> set[str]:
    """Load seen IDs, pruning entries older than ``ttl_days``.

    Automatically migrates the legacy list format (plain IDs) by assigning
    the current timestamp to every existing ID on first load.
    """
    if not os.path.exists(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        print(f"[{t('warn.banner_prefix')}] " + t("storage.seen_corrupt"))
        return set()

    if isinstance(data, list):
        # Legacy format: migrate in-memory; the next save will rewrite as dict.
        return set(data)

    if not isinstance(data, dict):
        print(f"[{t('warn.banner_prefix')}] " + t("storage.seen_corrupt"))
        return set()

    cutoff = _cutoff(ttl_days)
    return {
        item_id for item_id, ts in data.items()
        if _parse_iso(ts) >= cutoff
    }
```

**Step 3: Update `save_seen`**

```python
def save_seen(
    seen_ids: set[str],
    path: str = SEEN_PATH,
    ttl_days: int = DEFAULT_SEEN_TTL_DAYS,
) -> None:
    """Write seen IDs atomically with first-seen timestamps, pruning old entries."""
    now = _now_iso()
    cutoff = _cutoff(ttl_days)

    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            existing = {}
    else:
        existing = {}

    if isinstance(existing, list):
        existing = {item_id: now for item_id in existing}
    elif not isinstance(existing, dict):
        existing = {}

    # Preserve first-seen timestamps for IDs we already know about.
    data = {item_id: ts for item_id, ts in existing.items() if _parse_iso(ts) >= cutoff}

    # Add any brand-new IDs.
    for item_id in seen_ids:
        if item_id not in data:
            data[item_id] = now

    atomic_write_json(path, data)
```

**Step 4: Verify syntax**

Run: `python -m py_compile storage.py`
Expected: no output / exit 0

---

## Task 3: Wire the TTL from `main.py` config

**Objective:** Pass the configured TTL into `load_seen` and `save_seen`.

**Files:**
- Modify: `main.py`

**Step 1: Load TTL in `on_ready`**

After `config = load_config()` is irrelevant; `on_ready` already has `config`. Update:

```python
seen_ids = load_seen(ttl_days=config.get("seen_ttl_days", DEFAULT_SEEN_TTL_DAYS))
```

**Step 2: Pass TTL to saves**

Find both `save_seen(seen_ids)` calls inside `backfill_channel` and `scan_loop` and change them to:

```python
save_seen(seen_ids, ttl_days=config.get("seen_ttl_days", DEFAULT_SEEN_TTL_DAYS))
```

**Step 3: Import the default**

Add to the existing `storage` import:

```python
from storage import atomic_write_json, load_seen, save_seen, DEFAULT_SEEN_TTL_DAYS
```

**Step 4: Verify**

Run: `python -m py_compile main.py`
Expected: no output / exit 0

---

## Task 4: Update tests for TTL behavior

**Objective:** Prove migration, pruning, and timestamp preservation work.

**Files:**
- Modify: `tests/test_storage.py`

**Step 1: Update the roundtrip test**

The file is no longer a sorted list. Assert the dict shape instead:

```python
def test_roundtrip(tmp_path):
    path = str(tmp_path / "seen.json")
    save_seen({"3", "1", "2"}, path)
    assert load_seen(path) == {"1", "2", "3"}
```

**Step 2: Update the JSON-shape test**

```python
def test_save_is_timestamped_json(tmp_path):
    path = str(tmp_path / "seen.json")
    save_seen({"a", "b"}, path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert set(data.keys()) == {"a", "b"}
    for ts in data.values():
        datetime.fromisoformat(ts)  # valid ISO timestamp
```

**Step 3: Add migration test**

```python
def test_load_seen_migrates_legacy_list(tmp_path):
    path = tmp_path / "seen.json"
    path.write_text(json.dumps(["1", "2", "3"]), encoding="utf-8")
    assert load_seen(str(path)) == {"1", "2", "3"}
```

**Step 4: Add pruning test**

```python
def test_load_seen_prunes_old_entries(tmp_path):
    path = tmp_path / "seen.json"
    old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    fresh = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    path.write_text(json.dumps({"old": old, "fresh": fresh}), encoding="utf-8")
    assert load_seen(str(path), ttl_days=52) == {"fresh"}
```

**Step 5: Add timestamp preservation test**

```python
def test_save_seen_preserves_first_seen_timestamp(tmp_path):
    path = str(tmp_path / "seen.json")
    old_ts = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    save_seen({"a"}, path)
    with open(path, encoding="utf-8") as f:
        first_ts = json.load(f)["a"]
    save_seen({"a", "b"}, path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["a"] == first_ts
    assert data["b"] != first_ts  # b was added later
```

**Step 6: Add default TTL test**

```python
def test_default_seen_ttl_is_52_days():
    from storage import DEFAULT_SEEN_TTL_DAYS
    assert DEFAULT_SEEN_TTL_DAYS == 52
```

**Step 7: Run tests**

Run: `python -m pytest tests/test_storage.py -q`
Expected: all pass

---

## Task 5: Document the setting in the README

**Objective:** Users should know the new config key exists.

**Files:**
- Modify: `README.md`

**Step 1: Add a row in the config table**

Add:

```markdown
| `seen_ttl_days` | Days to remember seen listing IDs (default `52`). Older IDs are pruned on load/save. |
```

**Step 2: Verify**

Run: `grep "seen_ttl_days" README.md`
Expected: one match

---

## Task 6: Full test run and review

**Objective:** Make sure nothing else broke.

Run: `python -m pytest tests/ -q`
Expected: all pass

Review `git diff --stat` and confirm only the intended files changed.

---

## Migration behavior summary

- First boot after deploy loads the legacy list, treats every ID as seen "now", and rewrites `seen.json` as a timestamped dict.
- From then on, IDs older than 52 days are dropped on startup and whenever the file is saved.
- If the bot is down for a while, pruning still happens at startup based on the timestamps already on disk.
