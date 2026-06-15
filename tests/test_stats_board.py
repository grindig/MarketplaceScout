"""Tests for the stats board embed builder."""

import discord
from stats_board import build_gen_embed


def test_empty_prices_shows_no_data():
    embed = build_gen_embed("30xx", {})
    assert len(embed.fields) == 1
    assert "No data available yet" in embed.fields[0].value
    assert embed.fields[0].name == "No data"


def test_single_price_no_average():
    embed = build_gen_embed("30xx", {"RTX 3060 Ti": [240.0]})
    field = embed.fields[0]
    assert field.name == "RTX 3060 Ti"
    assert "240 €" in field.value
    assert "1 listing" in field.value
    assert "Ø" not in field.value


def test_multi_price_shows_avg_min_max():
    embed = build_gen_embed("30xx", {"RTX 3070": [249.0, 300.0, 550.0, 335.0, 330.0]})
    field = embed.fields[0]
    assert field.name == "RTX 3070"
    assert "Ø" in field.value
    assert "5 listings" in field.value
    assert "Min 249 €" in field.value
    assert "Max 550 €" in field.value


def test_models_sorted_alphabetically():
    prices = {"RTX 3080": [370.0, 350.0], "RTX 3060": [90.0, 80.0]}
    embed = build_gen_embed("30xx", prices)
    names = [f.name for f in embed.fields]
    assert names == sorted(names)


def test_only_shows_models_for_generation():
    prices = {"RTX 3080": [370.0], "RTX 4090": [1200.0], "GTX 1080": [80.0]}
    embed = build_gen_embed("30xx", prices)
    names = [f.name for f in embed.fields]
    assert "RTX 3080" in names
    assert "RTX 4090" not in names
    assert "GTX 1080" not in names


def test_no_title():
    embed = build_gen_embed("30xx", {"RTX 3060": [200.0]})
    assert embed.title is None


def test_all_embeds_are_green():
    for gen in ["10xx", "20xx", "30xx", "40xx", "50xx"]:
        assert build_gen_embed(gen, {}).color.value == 0x76b900


def test_footer_shown_when_requested():
    embed = build_gen_embed("50xx", {}, show_footer=True)
    assert embed.footer.text.startswith("Last updated:")
    assert "Uhr" not in embed.footer.text


def test_no_footer_by_default():
    embed = build_gen_embed("30xx", {})
    assert embed.footer.text is None


def test_fields_are_inline():
    embed = build_gen_embed("30xx", {"RTX 3080": [370.0, 350.0]})
    assert embed.fields[0].inline is True


def test_stats_init_returns_none_when_initial_send_fails(tmp_path, monkeypatch):
    """Stats-board send errors must not abort the bot startup sequence."""
    import asyncio
    import price_tracker
    import stats_board

    class BadChannel:
        async def send(self, embeds=None):
            raise RuntimeError("missing Embed Links")

    class FakeClient:
        async def fetch_channel(self, channel_id):
            return BadChannel()

    price_tracker._cache.clear()
    monkeypatch.setattr(stats_board, "STATE_PATH", str(tmp_path / "stats_state.json"))
    monkeypatch.setattr(stats_board, "PRICES_PATH", str(tmp_path / "prices.json"))

    result = asyncio.run(stats_board.stats_init(FakeClient(), "123"))

    assert result is None


def test_price_with_cents():
    embed = build_gen_embed("10xx", {"GTX 1060": [49.5, 51.0]})
    assert "50,25 €" in embed.fields[0].value


def test_empty_history_list_skipped():
    prices = {"RTX 3080": [], "RTX 3060": [90.0, 80.0]}
    embed = build_gen_embed("30xx", prices)
    names = [f.name for f in embed.fields]
    assert "RTX 3080" not in names
    assert "RTX 3060" in names


def test_generation_from_model_number():
    from stats_board import _generation
    assert _generation("GTX 1080 Ti") == "10xx"
    assert _generation("RTX 3060 Ti") == "30xx"
    assert _generation("RTX 5090") == "50xx"


def test_generation_unknown_models_are_other():
    from stats_board import _generation
    assert _generation("RX 580") == "other"  # must not land in 50xx
    assert _generation("RX 7900") == "other"
    assert _generation("Quadro P4000") == "other"


class TestStatsBoardGerman:
    """Drive build_gen_embed through German to catch any un-translated string."""

    def setup_method(self):
        from i18n import set_language
        set_language("de")

    def teardown_method(self):
        from i18n import set_language
        set_language("en")

    def test_empty_prices_german(self):
        embed = build_gen_embed("30xx", {})
        assert embed.fields[0].name == "Keine Daten"
        assert "Noch keine Daten vorhanden" in embed.fields[0].value

    def test_single_listing_german(self):
        embed = build_gen_embed("30xx", {"RTX 3060 Ti": [240.0]})
        assert "240 €" in embed.fields[0].value
        assert "1 Inserat" in embed.fields[0].value

    def test_multi_listing_german(self):
        embed = build_gen_embed("30xx", {"RTX 3070": [249.0, 300.0, 550.0, 335.0, 330.0]})
        assert "5 Inserate" in embed.fields[0].value
        assert "Min 249 €" in embed.fields[0].value
        assert "Max 550 €" in embed.fields[0].value

    def test_footer_german(self):
        embed = build_gen_embed("50xx", {}, show_footer=True)
        assert embed.footer.text.startswith("Zuletzt aktualisiert:")
        assert embed.footer.text.endswith("Uhr")
