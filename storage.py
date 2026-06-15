"""Persistence for seen listing IDs (atomic JSON writes)."""

import json
import os

from i18n import t

SEEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "json", "seen.json")


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
    """Write the seen IDs atomically (tmp file + os.replace) so a crash can't corrupt them."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sorted(seen_ids), f)
    os.replace(tmp, path)
