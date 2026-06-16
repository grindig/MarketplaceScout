"""Persistence for seen listing IDs and shared atomic JSON writes."""

import json
import os
import time

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


def load_seen(path: str = SEEN_PATH) -> set[str]:
    """Load the set of seen listing IDs. Returns an empty set if missing or unreadable."""
    if not os.path.exists(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except (json.JSONDecodeError, OSError):
        print(f"[{t('warn.banner_prefix')}] " + t("storage.seen_corrupt"))
        return set()


def save_seen(seen_ids: set[str], path: str = SEEN_PATH) -> None:
    """Write the seen IDs atomically so a crash can't corrupt them."""
    atomic_write_json(path, sorted(seen_ids))
