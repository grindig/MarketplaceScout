"""Marker: moves bot messages to the 'marked' thread on ✅ reaction."""

import discord

from colors import RESET, BOLD, YELLOW, GREEN

CHECK_EMOJI = "\U00002705"  # ✅


async def find_or_create_marked_thread(channel: discord.TextChannel) -> discord.Thread:
    """Return the 'marked' thread in channel, creating it if necessary."""
    for thread in channel.threads:
        if thread.name == "marked":
            return thread

    async for thread in channel.archived_threads():
        if thread.name == "marked":
            await thread.edit(archived=False)
            return thread

    return await channel.create_thread(
        name="marked",
        type=discord.ChannelType.public_thread,
    )


async def mark_message(client: discord.Client, payload: discord.RawReactionActionEvent) -> None:
    """Handle a raw reaction event: move the message to 'marked' if ✅ was added."""
    if str(payload.emoji) != CHECK_EMOJI:
        return
    if payload.user_id == client.user.id:
        return

    channel = client.get_channel(payload.channel_id)
    if not isinstance(channel, discord.TextChannel):
        return

    try:
        message = await channel.fetch_message(payload.message_id)
    except Exception as exc:
        print(f"{BOLD}{YELLOW}[WARN]{RESET} Marker: could not fetch message {payload.message_id}: {exc}")
        return

    if message.author.id != client.user.id:
        return

    try:
        marked_thread = await find_or_create_marked_thread(channel)
    except Exception as exc:
        print(f"{BOLD}{YELLOW}[WARN]{RESET} Marker: could not find/create marked thread: {exc}")
        return

    try:
        clean = message.content.replace("@here", "").strip()
        await marked_thread.send(
            content=clean or None,
            embeds=message.embeds,
        )
    except Exception as exc:
        print(f"{BOLD}{YELLOW}[WARN]{RESET} Marker: could not post to marked thread: {exc}")
        return

    try:
        await message.delete()
        print(f"{GREEN}[MARKED]{RESET} Message {message.id} marked.")
    except Exception as exc:
        print(f"{BOLD}{YELLOW}[WARN]{RESET} Marker: could not delete original message {message.id}: {exc}")
