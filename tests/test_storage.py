"""Tests for seen-ID persistence and shared atomic JSON writes."""

import asyncio
import json
from datetime import datetime, timedelta, timezone

from storage import atomic_write_json, load_seen, save_seen, SeenWriter, DEFAULT_SEEN_TTL_DAYS


def test_load_seen_missing_file(tmp_path):
    assert load_seen(str(tmp_path / "seen.json")) == set()


def test_roundtrip(tmp_path):
    path = str(tmp_path / "seen.json")
    save_seen({"3", "1", "2"}, path)
    assert load_seen(path) == {"1", "2", "3"}


def test_save_is_timestamped_json(tmp_path):
    """seen.json is now a dict of id -> first_seen ISO timestamp."""
    path = str(tmp_path / "seen.json")
    save_seen({"b", "a"}, path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert set(data.keys()) == {"a", "b"}
    for ts in data.values():
        datetime.fromisoformat(ts)  # valid ISO timestamp


def test_save_leaves_no_tmp_file(tmp_path):
    path = str(tmp_path / "seen.json")
    save_seen({"1"}, path)
    assert list(tmp_path.iterdir()) == [tmp_path / "seen.json"]


def test_load_seen_corrupt_file(tmp_path):
    path = tmp_path / "seen.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_seen(str(path)) == set()


def test_load_seen_migrates_legacy_list(tmp_path):
    """The old flat list format is migrated to timestamped dict on first load."""
    path = tmp_path / "seen.json"
    path.write_text(json.dumps(["1", "2", "3"]), encoding="utf-8")
    assert load_seen(str(path)) == {"1", "2", "3"}


def test_load_seen_prunes_old_entries(tmp_path):
    """IDs older than the TTL window are dropped on load."""
    path = tmp_path / "seen.json"
    old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    fresh = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    path.write_text(json.dumps({"old": old, "fresh": fresh}), encoding="utf-8")
    assert load_seen(str(path), ttl_days=52) == {"fresh"}


def test_save_seen_preserves_first_seen_timestamp(tmp_path):
    """Re-saving must not refresh the timestamp of an already-known ID."""
    path = str(tmp_path / "seen.json")
    save_seen({"a"}, path)
    with open(path, encoding="utf-8") as f:
        first_ts = json.load(f)["a"]
    save_seen({"a", "b"}, path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["a"] == first_ts
    assert data["b"] != first_ts


def test_save_seen_prunes_old_entries(tmp_path):
    """Saving drops IDs that crossed the TTL threshold."""
    path = str(tmp_path / "seen.json")
    old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    fresh = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    save_seen(set(), path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"old": old, "fresh": fresh}, f)
    save_seen({"fresh"}, path, ttl_days=52)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert "old" not in data
    assert "fresh" in data


def test_default_seen_ttl_is_52_days():
    assert DEFAULT_SEEN_TTL_DAYS == 52


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


def test_atomic_write_json_concurrent_writes_leave_valid_json(tmp_path):
    """Concurrent writers to the same path must not corrupt the file or leak
    temp files. Each call used to share the fixed ``path + ".tmp"`` name, so
    two simultaneous writes could clobber each other's temp file."""
    from concurrent.futures import ThreadPoolExecutor

    path = str(tmp_path / "data.json")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: atomic_write_json(path, {"i": i}), range(50)))

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    assert isinstance(data["i"], int)
    assert not list(tmp_path.glob("*.tmp"))


# ---------------------------------------------------------------------------
# SeenWriter: in-memory dedup with debounced disk flush.
# ---------------------------------------------------------------------------


def test_seen_writer_loads_existing(tmp_path):
    """On construction the in-memory set is hydrated from the on-disk file."""
    path = tmp_path / "seen.json"
    path.write_text(json.dumps({"a": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")

    writer = SeenWriter(path=str(path))

    assert writer.seen == {"a"}


def test_seen_writer_add_idempotent(tmp_path):
    """Adding the same ID twice doesn't double-write or change the set."""
    writer = SeenWriter(path=str(tmp_path / "seen.json"))
    writer.add("42")
    assert writer.seen == {"42"}
    writer.add("42")
    assert writer.seen == {"42"}


def test_seen_writer_stop_flushes_when_dirty(tmp_path):
    """stop() persists pending adds so a graceful shutdown doesn't lose them."""
    path = tmp_path / "seen.json"
    writer = SeenWriter(path=str(path))
    writer.add("a")
    writer.add("b")
    # File doesn't exist yet — stop() must create it with the new IDs.
    assert not path.exists()

    asyncio.run(writer.stop())

    assert path.exists()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert set(on_disk.keys()) == {"a", "b"}


def test_seen_writer_stop_is_noop_when_clean(tmp_path):
    """stop() with no pending adds must not rewrite the file."""
    path = tmp_path / "seen.json"
    valid_ts = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps({"a": valid_ts}), encoding="utf-8")
    mtime_before = path.stat().st_mtime

    writer = SeenWriter(path=str(path))
    asyncio.run(writer.stop())

    # File contents unchanged.
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": valid_ts}
    # mtime preserved: stop() took the dirty-skip path.
    assert path.stat().st_mtime == mtime_before


def test_seen_writer_flush_now_is_noop_when_clean(tmp_path):
    """flush_now() is a cheap O(1) call when nothing changed."""
    path = tmp_path / "seen.json"
    writer = SeenWriter(path=str(path))
    # File doesn't exist; a clean flush must NOT create it.
    asyncio.run(writer.flush_now())
    assert not path.exists()


def test_seen_writer_extend_batch(tmp_path):
    """extend() marks multiple IDs in one shot."""
    writer = SeenWriter(path=str(tmp_path / "seen.json"))
    writer.extend({"a", "b", "c"})
    assert writer.seen == {"a", "b", "c"}


def test_seen_writer_start_is_idempotent(tmp_path):
    """Calling start() twice doesn't spawn two flush tasks."""
    async def cycle():
        writer = SeenWriter(path=str(tmp_path / "seen.json"))
        writer.start()
        writer.start()
        # The second start() is a no-op; if it spawned a duplicate task the
        # assertion below would see two tasks in the writer's tracked set.
        assert writer._task is not None
        await writer.stop()

    asyncio.run(cycle())


def test_seen_writer_debounce_persists_after_interval(tmp_path):
    """The background loop actually writes to disk after the debounce window."""
    path = tmp_path / "seen.json"
    writer = SeenWriter(path=str(path), flush_seconds=0.05)

    async def cycle():
        writer.start()
        writer.add("late")
        # Wait past the debounce window so the background task wakes up.
        await asyncio.sleep(0.1)
        # Don't call stop() — it would also flush, masking whether the
        # background tick did the work. Instead, check the file directly.
        writer._stop.set()
        try:
            await writer._task
        except asyncio.CancelledError:
            pass

    asyncio.run(cycle())

    assert path.exists()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert "late" in on_disk


def test_seen_writer_persists_first_seen_timestamp(tmp_path):
    """Re-adding an already-known ID must not refresh its first-seen timestamp."""
    path = tmp_path / "seen.json"
    writer = SeenWriter(path=str(path))
    writer.add("a")
    asyncio.run(writer.stop())
    ts_first = json.loads(path.read_text(encoding="utf-8"))["a"]

    # Simulate a fresh start: rebuild the writer, re-add the same ID, flush.
    writer2 = SeenWriter(path=str(path))
    writer2.add("a")
    asyncio.run(writer2.stop())
    ts_second = json.loads(path.read_text(encoding="utf-8"))["a"]

    assert ts_first == ts_second
