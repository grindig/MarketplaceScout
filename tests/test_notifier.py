"""Tests for the Discord notifier."""

import asyncio

import pytest
import discord

from notifier import build_embed, send_notification


class FakeMessage:
    def __init__(self, react_fails=False):
        self.react_fails = react_fails
        self.reactions: list[str] = []

    async def add_reaction(self, emoji):
        if self.react_fails:
            raise RuntimeError("no reaction permission")
        self.reactions.append(emoji)


class FakeChannel:
    def __init__(self, send_fails=False, react_fails=False):
        self.send_fails = send_fails
        self.react_fails = react_fails

    async def send(self, content=None, embed=None, allowed_mentions=None):
        if self.send_fails:
            raise RuntimeError("discord down")
        return FakeMessage(react_fails=self.react_fails)


def make_listing(**kwargs):
    base = {
        "id": "123",
        "title": "RTX 3080 defekt",
        "url": "https://willhaben.at/iad/test",
        "price": 150.0,
        "location": "Wien",
        "paylivery": True,
    }
    base.update(kwargs)
    return base


def test_build_embed_title_and_url():
    listing = make_listing()
    embed = build_embed(listing)
    assert embed.title == "RTX 3080 defekt"
    assert embed.url == "https://willhaben.at/iad/test"


def test_build_embed_price_whole_number():
    listing = make_listing(price=150.0)
    embed = build_embed(listing)
    price_field = next(f for f in embed.fields if f.name == "Preis")
    assert price_field.value == "150 €"


def test_build_embed_price_with_cents():
    listing = make_listing(price=49.99)
    embed = build_embed(listing)
    price_field = next(f for f in embed.fields if f.name == "Preis")
    assert price_field.value == "49,99 €"


def test_build_embed_no_price():
    listing = make_listing(price=None)
    embed = build_embed(listing)
    price_field = next(f for f in embed.fields if f.name == "Preis")
    assert price_field.value == "Kein Preis"


def test_build_embed_paylivery_yes():
    listing = make_listing(paylivery=True)
    embed = build_embed(listing)
    field = next(f for f in embed.fields if f.name == "PayLivery")
    assert field.value == "✅"


def test_build_embed_paylivery_no():
    listing = make_listing(paylivery=False)
    embed = build_embed(listing)
    field = next(f for f in embed.fields if f.name == "PayLivery")
    assert field.value == "❌"


def test_build_embed_price_stats_shown():
    listing = make_listing(price_stats={"avg": 160.0, "count": 5, "pct": -6.25})
    embed = build_embed(listing)
    field = next(f for f in embed.fields if f.name == "Ø-Preis")
    assert "160 €" in field.value
    assert "-6%" in field.value
    assert "5 Inserate" in field.value


def test_build_embed_no_price_stats():
    listing = make_listing()  # no price_stats key
    embed = build_embed(listing)
    names = [f.name for f in embed.fields]
    assert "Ø-Preis" not in names


def test_send_notification_returns_true_on_success():
    result = asyncio.run(send_notification(FakeChannel(), make_listing()))
    assert result is True


def test_send_notification_returns_false_when_send_fails():
    result = asyncio.run(send_notification(FakeChannel(send_fails=True), make_listing()))
    assert result is False


def test_send_notification_returns_true_when_only_reactions_fail():
    """The listing was delivered — a failed reaction must not count as a lost notification."""
    result = asyncio.run(send_notification(FakeChannel(react_fails=True), make_listing()))
    assert result is True
