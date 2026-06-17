"""Price tracker: records GPU listing prices and computes historical averages."""

import json
import os
import re
import threading
from typing import Optional

from i18n import t
from storage import atomic_write_json

PRICES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "json", "prices.json")

_WHITESPACE = re.compile(r"\s+")

# Rolling window: only the most recent entries count toward avg/min/max,
# so months-old market prices don't skew the stats.
MAX_HISTORY = 100


def find_gpu_model(title: str, gpu_models: list[str]) -> Optional[str]:
    """Return the longest GPU model keyword found in title (case-insensitive), or None.

    Whitespace is collapsed on both sides before matching so spaceless titles
    ("RTX3080", "GTX1070Ti") — very common on Willhaben — still match the spaced
    model names in keywords.json. The keyword filter already treats these as hits
    (so they get posted), so without this the price would silently go unrecorded.
    Every model carries a letter prefix (RTX/GTX), so dropping spaces can't make a
    model accidentally match a bare price number.
    """
    title_norm = _WHITESPACE.sub("", title.lower())
    matches = [m for m in gpu_models if _WHITESPACE.sub("", m.lower()) in title_norm]
    return max(matches, key=len) if matches else None


# Write-through cache: the file is read once per path, then kept in memory.
# record_price runs inside asyncio.to_thread (one worker thread per channel
# scan loop), so the read/mutate/write on this cache can race. _lock_for
# serializes that critical section per price file.
_cache: dict[str, dict] = {}

_locks_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}


def _lock_for(path: str) -> threading.Lock:
    """Return a per-absolute-path lock, creating it on first use."""
    path = os.path.abspath(path)
    with _locks_guard:
        lock = _locks.get(path)
        if lock is None:
            lock = threading.Lock()
            _locks[path] = lock
        return lock


def _load(prices_path: str) -> dict:
    if prices_path in _cache:
        return _cache[prices_path]
    prices: dict = {}
    if os.path.exists(prices_path):
        try:
            with open(prices_path, "r", encoding="utf-8") as f:
                prices = json.load(f)
        except (json.JSONDecodeError, OSError):
            print(f"[{t('warn.banner_prefix')}] " + t("price_tracker.prices_corrupt"))
    _cache[prices_path] = prices
    return prices


def _save(prices: dict, prices_path: str) -> None:
    atomic_write_json(prices_path, prices)


def record_price(model: str, price: float, prices_path: str = PRICES_PATH) -> None:
    """Append a price entry for the given GPU model, keeping the last MAX_HISTORY."""
    with _lock_for(prices_path):
        prices = _load(prices_path)
        history = prices.setdefault(model, [])
        history.append(price)
        prices[model] = history[-MAX_HISTORY:]
        _save(prices, prices_path)


def get_stats(model: str, prices_path: str = PRICES_PATH) -> Optional[dict]:
    """Return {avg, count} for the model if at least 2 prices recorded, else None."""
    history = _load(prices_path).get(model, [])
    if len(history) < 2:
        return None
    avg = sum(history) / len(history)
    return {"avg": avg, "count": len(history)}
