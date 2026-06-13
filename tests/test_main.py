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


def test_load_config_missing_keywords_exits(tmp_path, monkeypatch, capsys):
    """A missing keywords.json must exit with a friendly error, not a traceback."""
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"channels": []}), encoding="utf-8")
    monkeypatch.setattr(main, "CONFIG_PATH", str(cfg))
    monkeypatch.setattr(main, "KEYWORDS_PATH", str(tmp_path / "keywords.json"))

    with pytest.raises(SystemExit):
        main.load_config()

    assert "keywords.json" in capsys.readouterr().out


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
