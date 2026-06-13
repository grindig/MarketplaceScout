"""Tests for main module helpers."""

import asyncio
import json

import pytest

import main


def test_reset_backfill_days(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps({"backfill_days": 3, "scan_interval_seconds": 60, "channels": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(cfg))

    main.reset_backfill_days()

    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["backfill_days"] == 0
    assert data["scan_interval_seconds"] == 60  # other keys untouched
    assert list(tmp_path.iterdir()) == [cfg]  # no leftover tmp file


def test_scan_once_dedupes_within_cycle(monkeypatch):
    """The same listing appearing in several search URLs is returned only once."""
    monkeypatch.setattr(main, "fetch_html", lambda url: "")
    monkeypatch.setattr(
        main, "parse_listings",
        lambda html: [{"id": "42", "title": "RTX 3080 defekt", "price": 100.0, "url": "", "location": ""}],
    )
    config = {"search_urls": ["u1", "u2"], "keywords": ["RTX"], "max_price": None}

    new = main.scan_once(config)

    assert [l["id"] for l in new] == ["42"]


def test_scan_once_isolates_failing_url(monkeypatch):
    """One failing search URL must not drop the listings from the others."""
    def fake_fetch(url):
        if url == "bad":
            raise RuntimeError("boom")
        return url

    monkeypatch.setattr(main, "fetch_html", fake_fetch)
    monkeypatch.setattr(
        main, "parse_listings",
        lambda html: [{"id": "7", "title": "RTX 3080 defekt", "price": 100.0, "url": "", "location": ""}],
    )
    config = {"search_urls": ["bad", "good"], "keywords": ["RTX"], "max_price": None}

    new = main.scan_once(config)

    assert [l["id"] for l in new] == ["7"]


def test_load_config_missing_keywords_exits(tmp_path, monkeypatch, capsys):
    """A missing keywords.json must exit with a friendly error, not a traceback."""
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"channels": []}), encoding="utf-8")
    monkeypatch.setattr(main, "CONFIG_PATH", str(cfg))
    monkeypatch.setattr(main, "KEYWORDS_PATH", str(tmp_path / "keywords.json"))

    with pytest.raises(SystemExit):
        main.load_config()

    assert "keywords.json" in capsys.readouterr().out


class _FakeChannel:
    name = "test"


class _FakeClient:
    """Minimal discord.Client stand-in for driving scan_loop one iteration."""

    def __init__(self, channel):
        self._channel = channel

    async def wait_until_ready(self):
        return

    def get_channel(self, _id):
        return self._channel


def test_scan_loop_skips_listing_already_seen(monkeypatch):
    """A listing another channel already marked seen mid-cycle is not re-sent."""
    listing = {"id": "99", "title": "RTX 3080", "price": 100.0, "url": "", "location": ""}

    # scan_once still surfaces the listing (new_listings is computed before the
    # send awaits), but seen_ids already contains it — the guard must skip it.
    monkeypatch.setattr(main, "scan_once", lambda cfg: [listing])
    # Model the race: filter_new ran while seen_ids was still empty (so the
    # listing passed), but another channel marked it seen before the send.
    monkeypatch.setattr(main, "filter_new", lambda listings, seen: listings)

    sends: list = []

    async def fake_send(channel, lst, mention=True):
        sends.append(lst["id"])
        return True

    monkeypatch.setattr(main, "send_notification", fake_send)

    seen = {"99"}
    config = {"keywords": ["RTX"], "scan_interval_seconds": 3600}
    channel_cfg = {"channel_id": "1", "max_price": None, "search_urls": ["u1"]}

    async def drive():
        task = asyncio.create_task(
            main.scan_loop(_FakeClient(_FakeChannel()), config, channel_cfg, seen)
        )
        # let it run one scan, then it parks on the interval sleep; cancel it
        for _ in range(20):
            await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(drive())

    assert sends == []  # already-seen listing was skipped, never sent


def _make_send_stub(result: bool, calls: list):
    async def stub(channel, listing, mention=True):
        calls.append((listing["id"], mention))
        return result
    return stub


def test_send_and_mark_adds_seen_on_success(monkeypatch):
    calls: list = []
    monkeypatch.setattr(main, "send_notification", _make_send_stub(True, calls))
    seen: set[str] = set()

    ok = asyncio.run(main._send_and_mark("channel", {"id": "42"}, seen))

    assert ok is True
    assert seen == {"42"}
    assert calls == [("42", True)]


def test_send_and_mark_keeps_unseen_on_failure(monkeypatch):
    """A failed send must leave the listing unseen so the next scan retries it."""
    calls: list = []
    monkeypatch.setattr(main, "send_notification", _make_send_stub(False, calls))
    seen: set[str] = set()

    ok = asyncio.run(main._send_and_mark("channel", {"id": "42"}, seen, mention=False))

    assert ok is False
    assert seen == set()
    assert calls == [("42", False)]
