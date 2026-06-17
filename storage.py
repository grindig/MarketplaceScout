"""Persistence for seen listing IDs and shared atomic JSON writes."""

import asyncio
import json
import os
import tempfile
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

    Writes to a unique temp file (via ``tempfile.mkstemp``) in the same
    directory first, then ``os.replace``s onto the target. Same directory
    matters because ``os.replace`` is only atomic within one filesystem.

    Using a *unique* temp file per call avoids collisions when several
    writers target the same path concurrently — the previous fixed
    ``path + ".tmp"`` name let two concurrent writes clobber each other's
    temp file. The ``os.replace`` is retried on ``PermissionError``
    (Windows race after a recent replace of the same target) with
    exponential backoff.
    """
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(
        prefix=os.path.basename(path) + ".",
        suffix=".tmp",
        dir=directory,
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        delay = _ATOMIC_RETRY_INITIAL_SLEEP_S
        for attempt in range(_ATOMIC_RETRY_ATTEMPTS):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == _ATOMIC_RETRY_ATTEMPTS - 1:
                    raise
                time.sleep(delay)
                delay *= 2
    finally:
        # On success os.replace moved tmp away; on a fatal error it's still
        # there. Tolerate both.
        if os.path.exists(tmp):
            os.unlink(tmp)


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


# Default debounce window for the in-memory seen-ID writer. Long enough that
# back-to-back scans within the same minute coalesce into one disk write,
# short enough that an unclean shutdown loses at most a few listings (which
# re-notify on next start, with no @here ping because they re-hit the in-memory
# filter_new check on the very next cycle anyway).
DEFAULT_SEEN_FLUSH_SECONDS = 300


class SeenWriter:
    """In-memory seen-ID store with debounced background flush.

    Why this exists: ``save_seen`` does a read-merge-write of the whole
    ``seen.json`` file, and the previous code called it after *every* scan
    cycle that found anything. With multiple channels and a 60 s interval,
    that's a few rewrites/minute of a file that grows to thousands of IDs —
    each rewrite does a full JSON parse + serialize + ``os.replace`` (which
    on Windows can hit the PermissionError-retry tail of ``atomic_write_json``,
    with a worst-case backoff of ~2.5 s on the event loop). The merge work
    is O(N) in the seen-set size every cycle even when nothing changed.

    The SeenWriter keeps the seen set purely in memory and flushes to disk
    on a debounce timer, on graceful shutdown, or on demand. The in-memory
    set is the dedup source of truth at runtime; the on-disk file is a
    cold-start cache. A crash loses at most ``DEFAULT_SEEN_FLUSH_SECONDS``
    worth of new IDs, and the next scan's ``filter_new`` re-checks the
    in-memory set before sending, so a re-notification is impossible within
    a single process lifetime — only across a restart.

    Thread/coroutine model: ``add`` may be called from the event loop or from
    worker threads (the scan loop runs ``scan_once`` inside ``asyncio.to_thread``).
    The set mutations are tiny and Python's GIL makes single ``set.add`` calls
    effectively atomic; the flush loop lives on the event loop, so it never
    races with itself.
    """

    def __init__(
        self,
        path: str = SEEN_PATH,
        ttl_days: int = DEFAULT_SEEN_TTL_DAYS,
        flush_seconds: float = DEFAULT_SEEN_FLUSH_SECONDS,
    ) -> None:
        self._path = path
        self._ttl_days = ttl_days
        self._flush_seconds = flush_seconds
        # Loaded from disk at construction so the in-memory set is the
        # dedup source of truth from the very first filter_new call.
        self._seen: set[str] = load_seen(path, ttl_days=ttl_days)
        self._dirty = False
        self._task: asyncio.Task | None = None
        self._stop: asyncio.Event | None = None

    @property
    def seen(self) -> set[str]:
        """The live in-memory seen set. Callers must not mutate it directly;
        use :meth:`add` so the dirty flag is set and the flush is scheduled."""
        return self._seen

    def add(self, item_id: str) -> None:
        """Record an item as seen. O(1); safe to call from any thread."""
        if item_id in self._seen:
            return
        self._seen.add(item_id)
        self._dirty = True

    def extend(self, item_ids) -> None:
        """Record a batch of IDs in one shot."""
        for item_id in item_ids:
            if item_id not in self._seen:
                self._seen.add(item_id)
                self._dirty = True

    def start(self) -> None:
        """Start the background flush loop. Idempotent."""
        if self._task is not None and not self._task.done():
            return
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._run(self._stop))

    async def stop(self) -> None:
        """Stop the flush loop and write any pending changes to disk.

        Always safe to call, even if ``start`` was never called — the
        post-stop flush is a no-op when nothing is dirty.
        """
        if self._task is not None:
            self._stop.set()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self.flush_now()

    async def flush_now(self) -> None:
        """Force a write if anything is dirty. Cheap no-op otherwise.

        The disk write (read-merge-write of the whole file, plus the
        PermissionError-retry tail of ``atomic_write_json`` that can sleep
        up to ~2.5 s on Windows) runs in a worker thread so it never blocks
        the event loop — the very stall this class exists to avoid. The set
        is snapshotted under the GIL first so the worker thread iterates a
        private copy and can never race a concurrent ``add``.
        """
        if not self._dirty:
            return
        snapshot = set(self._seen)  # atomic copy; decouples the slow write from add()
        self._dirty = False
        try:
            await asyncio.to_thread(save_seen, snapshot, self._path, self._ttl_days)
        except Exception:
            # Write failed — keep the dirty flag set so the next tick retries
            # instead of dropping the IDs on the floor.
            self._dirty = True
            raise

    async def _run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            # Sleep in short slices so ``stop`` is responsive even when
            # flush_seconds is large.
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._flush_seconds)
                return  # stop was set
            except asyncio.TimeoutError:
                pass
            try:
                await self.flush_now()
            except Exception as exc:
                # Don't let one bad write kill the flush loop — the next
                # tick will retry. Surface it as a warning.
                print(f"[{t('warn.banner_prefix')}] " + t("storage.seen_flush_failed", exc=exc))
