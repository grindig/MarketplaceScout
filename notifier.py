"""Discord notifier for Willhaben listings."""

from datetime import datetime, timezone

import discord

from colors import RESET, BOLD, YELLOW
from i18n import t


def build_embed(listing: dict) -> discord.Embed:
    """Build a Discord embed from a listing."""
    price = listing.get("price")
    if price is None:
        price_value = t("embed.no_price")
    elif price == int(price):
        price_value = f"{int(price)} €"
    else:
        price_value = f"{price:.2f} €".replace(".", ",")
    location = listing.get("location") or t("embed.location_unknown")

    embed = discord.Embed(
        title=listing["title"],
        url=listing["url"],
        color=0x19AFFF,
        timestamp=listing.get("published") or datetime.now(timezone.utc),
    )
    image_url = listing.get("image_url")
    if image_url:
        embed.set_thumbnail(url=image_url)
    embed.add_field(name=t("embed.field.price"), value=price_value, inline=True)
    embed.add_field(name=t("embed.field.location"), value=location, inline=True)
    embed.add_field(name=t("embed.field.paylivery"), value="✅" if listing.get("paylivery") else "❌", inline=True)
    stats = listing.get("price_stats")
    if stats:
        avg = stats["avg"]
        pct = stats["pct"]
        if avg == int(avg):
            avg_str = f"{int(avg)} €"
        else:
            avg_str = f"{avg:.2f} €".replace(".", ",")
        direction = t("embed.field.avg_price.below" if pct < 0 else "embed.field.avg_price.above")
        embed.add_field(
            name=t("embed.field.avg_price"),
            value=t(
                "embed.field.avg_price.value",
                avg=avg_str,
                pct=pct,
                direction=direction,
                count=stats["count"],
            ),
            inline=False,
        )
    return embed


async def send_notification(channel: discord.TextChannel, listing: dict, mention: bool = True) -> bool:
    """Send a listing embed to a Discord channel and add reactions.

    Returns whether the embed was delivered — the caller only marks the
    listing as seen on success, so a transient Discord failure is retried
    on the next scan instead of dropping the listing forever. Failed
    reactions don't count as failed delivery.

    ``mention=False`` suppresses the @here ping (used during backfill so a
    multi-day catch-up doesn't ping once per listing).
    """
    try:
        embed = build_embed(listing)
        msg = await channel.send(
            content="@here" if mention else None,
            embed=embed,
            allowed_mentions=discord.AllowedMentions(everyone=mention),
        )
    except Exception as exc:
        print(f"{BOLD}{YELLOW}[WARN]{RESET} Failed to send Discord notification: {exc}")
        return False

    try:
        await msg.add_reaction("✅")
        await msg.add_reaction("❌")
    except Exception as exc:
        print(f"{BOLD}{YELLOW}[WARN]{RESET} Failed to add reactions: {exc}")

    return True
