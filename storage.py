"""Persistence for seen listing IDs and shared atomic JSON writes."""

import json
import os
import time
from datetime import datetime, timedelta, timezone

from i18n import t

SEEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "json", "seen.json")

# On Windows, os.replace against a destination that was *just* replaced can
# fail with WinError 5 (Access is denied) because the destination still has
# lingering metadata for a few milliseconds. A handful of retries with a short
# backoff absorbs the race for any caller that writes in a tight loop
# (backfill, scan_loop, stats_loop, etc.). The exception is re-raised after
# _ATOMIC_RETRY_ATTEMPTS so genuine "destination locked forever" failures
# still surface instead of hanging.
_ATOMIC_RETRY_ATTEMPTS = 10
_ATOMIC_RETRY_INITIAL_SLEEP_S = 0.005  # 5 ms

# How many days to remember seen listing IDs. Willhaben listings expire and
# are not reposted with the same ID, so a bounded window keeps the state file
# from growing forever without losing meaningful dedup coverage.
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


def atomic_write_json(path: str, data) -> None:
    """Write ``data`` (as JSON) to ``path`` atomically.

    Writes to ``path + ".tmp"`` first, then ``os.replace``s onto the target.
    The ``os.replace`` is retried on ``PermissionError`` (Windows race after
    a recent replace of the same target) with exponential backoff.
    """
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    delay = _ATOMIC_RETRY_INITIAL_SLEEP_S
    for attempt in range(_ATOMIC_RETRY_ATTEMPTS):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == _ATOMIC_RETRY_ATTEMPTS - 1:
                # Final attempt: clean up the tmp so we don't leak it, then
                # re-raise so the caller knows the write failed.
                if os.path.exists(tmp):
                    os.unlink(tmp)
                raise
            time.sleep(delay)
            delay *= 2


def load_seen(path: str = SEEN_PATH, ttl_days: int = DEFAULT_SEEN_TTL_DAYS) -> set[str]:
    """Load the set of seen listing IDs, pruning entries older than ``ttl_days``.

    Returns an empty set if the file is missing or unreadable. Automatically
    migrates the legacy list format by treating every existing ID as seen at
    load time; the next save will rewrite it as a timestamped dict.
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
        # Legacy format: migrate in-memory; next save writes as a dict.
        return set(data)

    if not isinstance(data, dict):
        print(f"[{t('warn.banner_prefix')}] " + t("storage.seen_corrupt"))
        return set()

    cutoff = _cutoff(ttl_days)
    return {
        item_id for item_id, ts in data.items()
        if _parse_iso(ts) >= cutoff
    }


def save_seen(
    seen_ids: set[str],
    path: str = SEEN_PATH,
    ttl_days: int = DEFAULT_SEEN_TTL_DAYS,
) -> None:
    """Write the seen IDs atomically with first-seen timestamps, pruning old entries.

    Preserves timestamps for IDs already on disk so the TTL window reflects
    when the ID was first encountered, not last saved.
    """
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

    # Keep existing timestamps for IDs still within the TTL window.
    data = {item_id: ts for item_id, ts in existing.items() if _parse_iso(ts) >= cutoff}

    # Add any brand-new IDs.
    for item_id in seen_ids:
        if item_id not in data:
            data[item_id] = now

    atomic_write_json(path, data)
