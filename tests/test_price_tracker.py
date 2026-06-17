"""Tests for price_tracker module."""

import json

from price_tracker import find_gpu_model, record_price, get_stats

GPU_MODELS = [
    "GTX 1060", "GTX 1070", "GTX 1080",
    "RTX 2060", "RTX 2070", "RTX 2080",
    "RTX 3060", "RTX 3070", "RTX 3080", "RTX 3090",
]


def test_find_gpu_model_match():
    assert find_gpu_model("RTX 3080 defekt", GPU_MODELS) == "RTX 3080"


def test_find_gpu_model_case_insensitive():
    assert find_gpu_model("rtx 3080 Grafikkarte", GPU_MODELS) == "RTX 3080"


def test_find_gpu_model_longest_match():
    # "RTX 3080" and a hypothetical "RTX 3080 Ti" — longest wins
    models = GPU_MODELS + ["RTX 3080 Ti"]
    assert find_gpu_model("RTX 3080 Ti kaputt", models) == "RTX 3080 Ti"


def test_find_gpu_model_spaceless_title():
    # Willhaben titles routinely drop the space ("RTX3080"); these still pass the
    # keyword filter, so the price must be recorded too.
    assert find_gpu_model("RTX3080 defekt", GPU_MODELS) == "RTX 3080"
    assert find_gpu_model("GTX1080 kein Bild", GPU_MODELS) == "GTX 1080"


def test_find_gpu_model_spaceless_longest_match():
    models = GPU_MODELS + ["RTX 3080 Ti"]
    assert find_gpu_model("Verkaufe RTX3080Ti, Bastler", models) == "RTX 3080 Ti"


def test_find_gpu_model_no_false_match_on_price_number():
    # A bare number in the title (e.g. a price) must not match a model.
    assert find_gpu_model("Grafikkarte um 3080 Euro", ["RTX 3080"]) is None


def test_find_gpu_model_no_match():
    assert find_gpu_model("Mainboard defekt", GPU_MODELS) is None


def test_record_and_get_stats(tmp_path):
    p = str(tmp_path / "prices.json")
    record_price("RTX 3080", 150.0, p)
    record_price("RTX 3080", 170.0, p)
    stats = get_stats("RTX 3080", p)
    assert stats["avg"] == 160.0
    assert stats["count"] == 2


def test_get_stats_insufficient_data(tmp_path):
    p = str(tmp_path / "prices.json")
    record_price("RTX 3080", 150.0, p)
    assert get_stats("RTX 3080", p) is None  # need at least 2 entries


def test_get_stats_unknown_model(tmp_path):
    p = str(tmp_path / "prices.json")
    assert get_stats("RTX 9999", p) is None


def test_record_price_persists(tmp_path):
    p = str(tmp_path / "prices.json")
    record_price("GTX 1080", 80.0, p)
    with open(p) as f:
        data = json.load(f)
    assert data["GTX 1080"] == [80.0]


def test_record_price_caps_history(tmp_path):
    from price_tracker import MAX_HISTORY
    p = str(tmp_path / "prices.json")
    for i in range(MAX_HISTORY + 5):
        record_price("RTX 3080", float(i), p)
    with open(p) as f:
        history = json.load(f)["RTX 3080"]
    assert len(history) == MAX_HISTORY
    assert history[-1] == float(MAX_HISTORY + 4)  # newest kept
    assert history[0] == 5.0  # oldest trimmed


def test_record_price_concurrent_writes_preserve_entries(tmp_path):
    """Concurrent record_price calls (one per channel scan thread) must not
    lose entries to the read/mutate/write race on the shared _cache."""
    from concurrent.futures import ThreadPoolExecutor
    import price_tracker

    path = str(tmp_path / "prices.json")
    price_tracker._cache.clear()

    values = [float(i) for i in range(50)]

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda p: record_price("RTX 3080", p, path), values))

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    assert sorted(data["RTX 3080"]) == values
