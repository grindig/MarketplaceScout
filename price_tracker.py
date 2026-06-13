"""Price tracker: records GPU listing prices and computes historical averages."""

import json
import os
from typing import Optional

PRICES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "json", "prices.json")

# Rolling window: only the most recent entries count toward avg/min/max,
# so months-old market prices don't skew the stats.
MAX_HISTORY = 100


def find_gpu_model(title: str, gpu_models: list[str]) -> Optional[str]:
    """Return the longest GPU model keyword found in title (case-insensitive), or None."""
    title_lower = title.lower()
    matches = [m for m in gpu_models if m.lower() in title_lower]
    return max(matches, key=len) if matches else None


# Write-through cache: the file is read once per path, then kept in memory.
# All callers run on the event loop, so plain dict access is safe.
_cache: dict[str, dict] = {}


def _load(prices_path: str) -> dict:
    if prices_path in _cache:
        return _cache[prices_path]
    prices: dict = {}
    if os.path.exists(prices_path):
        try:
            with open(prices_path, "r", encoding="utf-8") as f:
                prices = json.load(f)
        except (json.JSONDecodeError, OSError):
            print("[WARN] prices.json could not be read, starting fresh.")
    _cache[prices_path] = prices
    return prices


def _save(prices: dict, prices_path: str) -> None:
    tmp = prices_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(prices, f, indent=2)
    os.replace(tmp, prices_path)


def record_price(model: str, price: float, prices_path: str = PRICES_PATH) -> None:
    """Append a price entry for the given GPU model, keeping the last MAX_HISTORY."""
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
