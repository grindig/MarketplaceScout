"""Discord notifier for Willhaben listings."""

from datetime import datetime, timezone

import discord

from colors import RESET, BOLD, YELLOW


def build_embed(listing: dict) -> discord.Embed:
    """Build a Discord embed from a listing."""
    price = listing.get("price")
    if price is None:
        price_value = "Kein Preis"
    elif price == int(price):
        price_value = f"{int(price)} €"
    else:
        price_value = f"{price:.2f} €".replace(".", ",")
    location = listing.get("location") or "Unbekannt"

    embed = discord.Embed(
        title=listing["title"],
        url=listing["url"],
        color=0x19AFFF,
        timestamp=listing.get("published") or datetime.now(timezone.utc),
    )
    image_url = listing.get("image_url")
    if image_url:
        embed.set_thumbnail(url=image_url)
    embed.add_field(name="Preis", value=price_value, inline=True)
    embed.add_field(name="Standort", value=location, inline=True)
    embed.add_field(name="PayLivery", value="✅" if listing.get("paylivery") else "❌", inline=True)
    stats = listing.get("price_stats")
    if stats:
        avg = stats["avg"]
        pct = stats["pct"]
        if avg == int(avg):
            avg_str = f"{int(avg)} €"
        else:
            avg_str = f"{avg:.2f} €".replace(".", ",")
        direction = "über" if pct >= 0 else "unter"
        embed.add_field(
            name="Ø-Preis",
            value=f"{avg_str} ({pct:+.0f}% {direction} Ø, {stats['count']} Inserate)",
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
