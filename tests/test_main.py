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


def test_scan_loop_sends_listing_when_historical_average_is_zero(monkeypatch):
    """A zero price-history average must not abort delivery of the listing."""
    listing = {"id": "42", "title": "RTX 3060", "price": 100.0, "url": "", "location": ""}

    monkeypatch.setattr(main, "scan_once", lambda cfg: [listing])
    monkeypatch.setattr(main, "find_gpu_model", lambda title, models: "RTX 3060")
    monkeypatch.setattr(main, "get_stats", lambda model: {"avg": 0.0, "count": 2})
    monkeypatch.setattr(main, "save_seen", lambda seen: None)

    recorded: list[tuple[str, float]] = []
    monkeypatch.setattr(main, "record_price", lambda model, price: recorded.append((model, price)))

    sends: list[dict] = []

    async def fake_send(channel, lst, mention=True):
        sends.append(dict(lst))
        return True

    monkeypatch.setattr(main, "send_notification", fake_send)

    seen: set[str] = set()
    config = {"keywords": ["RTX"], "scan_interval_seconds": 3600, "gpu_models": ["RTX 3060"]}
    channel_cfg = {
        "channel_id": "1",
        "max_price": None,
        "search_urls": ["u1"],
        "track_prices": True,
        "show_price_stats": True,
    }

    async def drive():
        task = asyncio.create_task(
            main.scan_loop(_FakeClient(_FakeChannel()), config, channel_cfg, seen)
        )
        for _ in range(20):
            await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(drive())

    assert [s["id"] for s in sends] == ["42"]
    assert "price_stats" not in sends[0]
    assert recorded == [("RTX 3060", 100.0)]
    assert seen == {"42"}


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

def test_load_config_defaults_to_english(tmp_path, monkeypatch):
    """No 'language' key in config -> English is the active language."""
    from i18n import get_language
    (tmp_path / "config.json").write_text(json.dumps({"channels": []}), encoding="utf-8")
    (tmp_path / "keywords.json").write_text(
        json.dumps({"general": [], "gpu_models": []}), encoding="utf-8"
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(main, "KEYWORDS_PATH", str(tmp_path / "keywords.json"))

    main.load_config()
    assert get_language() == "en"


def test_load_config_applies_language(tmp_path, monkeypatch):
    """'language: de' in config -> set_language('de') is called."""
    from i18n import get_language
    (tmp_path / "config.json").write_text(
        json.dumps({"language": "de", "channels": []}), encoding="utf-8"
    )
    (tmp_path / "keywords.json").write_text(
        json.dumps({"general": [], "gpu_models": []}), encoding="utf-8"
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(main, "KEYWORDS_PATH", str(tmp_path / "keywords.json"))

    main.load_config()
    assert get_language() == "de"
    # Reset to en so other tests aren't polluted
    from i18n import set_language
    set_language("en")


def test_load_config_rejects_unknown_language(tmp_path, monkeypatch, capsys):
    """Unknown 'language' value exits with a friendly error."""
    (tmp_path / "config.json").write_text(
        json.dumps({"language": "klingon", "channels": []}), encoding="utf-8"
    )
    (tmp_path / "keywords.json").write_text(
        json.dumps({"general": [], "gpu_models": []}), encoding="utf-8"
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(main, "KEYWORDS_PATH", str(tmp_path / "keywords.json"))

    with pytest.raises(SystemExit):
        main.load_config()
    assert "klingon" in capsys.readouterr().out
