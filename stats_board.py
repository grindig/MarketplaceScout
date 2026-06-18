"""Live stats board: posts and hourly-edits one embed per GPU generation."""

import asyncio
import json
import os
import re
from datetime import datetime

import discord

from colors import CYAN, DARK_GRAY, LIGHT_GRAY, RESET
from i18n import t
from price_tracker import _load, PRICES_PATH
from storage import atomic_write_json

STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cfg", "stats_state.json")
_TAG = f"{DARK_GRAY}[{CYAN}STATS{DARK_GRAY}]{RESET}"

_GENERATIONS = ["10xx", "20xx", "30xx", "40xx", "50xx"]
_EMBED_COLOR = 0x76B900  # NVIDIA green
# GeForce model numbers (1050..5090): generation digit, 0, tier 5-9, 0.
# Digit-boundary lookarounds instead of \b so "RTX3060" still matches while
# "Quadro P4000" and "RX 580" stay out.
_MODEL_NUMBER = re.compile(r"(?<!\d)([1-5])0[5-9]0(?!\d)")


def _load_state() -> dict:
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(channel_id: str, message_id: int) -> None:
    atomic_write_json(STATE_PATH, {"channel_id": channel_id, "message_id": message_id})


def _fmt(price: float) -> str:
    if price == int(price):
        return f"{int(price)} €"
    return f"{price:.2f} €".replace(".", ",")


def _generation(model: str) -> str:
    match = _MODEL_NUMBER.search(model)
    return f"{match.group(1)}0xx" if match else "other"


def build_gen_embed(gen: str, prices: dict, show_footer: bool = False) -> discord.Embed:
    """Build a Discord embed for one GPU generation. No title, just fields."""
    embed = discord.Embed(color=_EMBED_COLOR)

    models = sorted(m for m in prices if _generation(m) == gen)
    for model in models:
        history = prices[model]
        if not history:
            continue
        if len(history) == 1:
            value = t("stats_board.field.value_single", price=_fmt(history[0]))
        else:
            avg = sum(history) / len(history)
            value = t(
                "stats_board.field.value_multi",
                avg=_fmt(avg),
                n=len(history),
                min=_fmt(min(history)),
                max=_fmt(max(history)),
            )
        embed.add_field(name=model, value=value, inline=True)

    if not models:
        embed.add_field(
            name=t("stats_board.field.no_data_name"),
            value=t("stats_board.field.no_data_value"),
            inline=True,
        )

    if show_footer:
        now = datetime.now()
        embed.set_footer(
            text=t(
                "stats_board.footer.last_updated",
                datetime=now.strftime("%d.%m.%Y · %H:%M"),
            )
        )

    return embed


async def stats_init(client: discord.Client, channel_id: str | None) -> discord.Message | None:
    """Fetch channel, find or post the stats message. Returns the message or None on failure."""
    if not channel_id:
        return None

    print(f"{_TAG} {LIGHT_GRAY}" + t("stats.initializing") + f"{RESET}")

    try:
        channel = await client.fetch_channel(int(channel_id))
    except (ValueError, discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
        print(f"{_TAG} {LIGHT_GRAY}" + t("stats.channel_unreachable", channel_id=channel_id, e=e) + f"{RESET}")
        return None

    state = _load_state()
    message = None
    if state.get("channel_id") == channel_id and state.get("message_id"):
        try:
            message = await channel.fetch_message(state["message_id"])
            print(f"{_TAG} {LIGHT_GRAY}" + t("stats.existing_message", id=message.id) + f"{RESET}")
        except Exception as e:
            print(f"{_TAG} {LIGHT_GRAY}" + t("stats.message_unfetchable", e=e) + f"{RESET}")

    prices = _load(PRICES_PATH)
    embeds = [
        build_gen_embed(gen, prices, show_footer=(i == len(_GENERATIONS) - 1))
        for i, gen in enumerate(_GENERATIONS)
    ]

    try:
        if message is None:
            message = await channel.send(embeds=embeds)
            _save_state(channel_id, message.id)
            print(f"{_TAG} {LIGHT_GRAY}" + t("stats.new_message", id=message.id) + f"{RESET}")
        else:
            await message.edit(embeds=embeds)
    except Exception as e:
        print(f"{_TAG} {LIGHT_GRAY}" + t("stats.update_failed", e=e) + f"{RESET}")
        return None

    return message


async def stats_loop(client: discord.Client, channel_id: str, message: discord.Message) -> None:
    """Hourly update loop. Edits the existing message, reposts if deleted.

    Transient errors (rate limits, network, 5xx) are logged and retried next
    hour instead of killing the task.
    """
    while True:
        await asyncio.sleep(3600)
        try:
            prices = _load(PRICES_PATH)
            embeds = [
                build_gen_embed(gen, prices, show_footer=(i == len(_GENERATIONS) - 1))
                for i, gen in enumerate(_GENERATIONS)
            ]
            try:
                await message.edit(embeds=embeds)
            except discord.NotFound:
                channel = await client.fetch_channel(int(channel_id))
                message = await channel.send(embeds=embeds)
                _save_state(channel_id, message.id)
        except Exception as e:
            print(f"{_TAG} {LIGHT_GRAY}" + t("stats.update_failed", e=e) + f"{RESET}")
