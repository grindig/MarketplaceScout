"""Tests for seen-ID persistence and shared atomic JSON writes."""

import json

from storage import atomic_write_json, load_seen, save_seen


def test_load_seen_missing_file(tmp_path):
    assert load_seen(str(tmp_path / "seen.json")) == set()


def test_roundtrip(tmp_path):
    path = str(tmp_path / "seen.json")
    save_seen({"3", "1", "2"}, path)
    assert load_seen(path) == {"1", "2", "3"}


def test_save_is_sorted_json(tmp_path):
    path = str(tmp_path / "seen.json")
    save_seen({"b", "a"}, path)
    with open(path, encoding="utf-8") as f:
        assert json.load(f) == ["a", "b"]


def test_save_leaves_no_tmp_file(tmp_path):
    path = str(tmp_path / "seen.json")
    save_seen({"1"}, path)
    assert list(tmp_path.iterdir()) == [tmp_path / "seen.json"]


def test_load_seen_corrupt_file(tmp_path):
    path = tmp_path / "seen.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_seen(str(path)) == set()


# ---------------------------------------------------------------------------
# atomic_write_json (shared by storage.save_seen, price_tracker._save,
# stats_board._save_state, main.reset_backfill_days)
# ---------------------------------------------------------------------------

def test_atomic_write_json_roundtrips(tmp_path):
    path = str(tmp_path / "data.json")
    atomic_write_json(path, {"a": 1, "b": [2, 3]})
    with open(path, encoding="utf-8") as f:
        assert json.load(f) == {"a": 1, "b": [2, 3]}


def test_atomic_write_json_replaces_existing(tmp_path):
    path = str(tmp_path / "data.json")
    atomic_write_json(path, {"v": 1})
    atomic_write_json(path, {"v": 2})
    with open(path, encoding="utf-8") as f:
        assert json.load(f) == {"v": 2}


def test_atomic_write_json_leaves_no_tmp_file(tmp_path):
    path = str(tmp_path / "data.json")
    atomic_write_json(path, {"v": 1})
    assert list(tmp_path.iterdir()) == [tmp_path / "data.json"]


def test_atomic_write_json_survives_burst_writes(tmp_path):
    """Regression test for the Windows os.replace race on tight loops.

    On Windows, ``os.replace`` against a destination that was *just* replaced
    fails intermittently with WinError 5 (Access is denied). The helper retries
    on ``PermissionError``; this test fails if the retry is removed.
    """
    path = str(tmp_path / "burst.json")
    # 200 iterations is well over the threshold that the previous
    # implementation failed at on Windows; if the retry logic regresses
    # back to a single os.replace, this test will start raising.
    for i in range(200):
        atomic_write_json(path, {"i": i})
    with open(path, encoding="utf-8") as f:
        assert json.load(f) == {"i": 199}


def test_atomic_write_json_retries_on_permission_error(tmp_path, monkeypatch):
    """Inject a PermissionError on the first two os.replace calls; the helper
    must retry past them and still leave a valid file behind."""
    path = str(tmp_path / "data.json")
    real_replace = __import__("os").replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError(5, "Access is denied (injected)")
        return real_replace(src, dst)

    monkeypatch.setattr("storage.os.replace", flaky_replace)
    atomic_write_json(path, {"ok": True})

    assert calls["n"] == 3  # two failures + one success
    with open(path, encoding="utf-8") as f:
        assert json.load(f) == {"ok": True}
    assert not (tmp_path / "data.json.tmp").exists()
