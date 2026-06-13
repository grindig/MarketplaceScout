"""Archiver: moves bot messages to the 'archive' thread on ❌ reaction or after 24h."""

import asyncio
from datetime import datetime, timedelta, timezone

import discord

from colors import RESET, BOLD, YELLOW, MAGENTA

X_EMOJI = "\U0000274c"  # ❌


async def find_or_create_archive_thread(channel: discord.TextChannel) -> discord.Thread:
    """Return the 'archive' thread in channel, creating it if necessary."""
    for thread in channel.threads:
        if thread.name == "archive":
            return thread

    async for thread in channel.archived_threads():
        if thread.name == "archive":
            await thread.edit(archived=False)  # discord.py rejects sends to archived threads
            return thread

    return await channel.create_thread(
        name="archive",
        type=discord.ChannelType.public_thread,
    )


async def archive_message(client: discord.Client, payload: discord.RawReactionActionEvent) -> None:
    """Handle a raw reaction event: archive the message if ❌ was added."""
    if str(payload.emoji) != X_EMOJI:
        return
    if payload.user_id == client.user.id:
        return

    channel = client.get_channel(payload.channel_id)
    if not isinstance(channel, discord.TextChannel):
        return

    try:
        message = await channel.fetch_message(payload.message_id)
    except Exception as exc:
        print(f"{BOLD}{YELLOW}[WARN]{RESET} Archive: could not fetch message {payload.message_id}: {exc}")
        return

    if message.author.id != client.user.id:
        return

    try:
        archive_thread = await find_or_create_archive_thread(channel)
    except Exception as exc:
        print(f"{BOLD}{YELLOW}[WARN]{RESET} Archive: could not find/create archive thread: {exc}")
        return

    if message.embeds:  # an empty embed list would raise on send
        try:
            await archive_thread.send(embeds=message.embeds)
        except Exception as exc:
            print(f"{BOLD}{YELLOW}[WARN]{RESET} Archive: could not post to archive thread: {exc}")
            return

    try:
        await message.delete()
        print(f"{MAGENTA}[ARCHIVE]{RESET} Message {message.id} archived.")
    except Exception as exc:
        print(f"{BOLD}{YELLOW}[WARN]{RESET} Archive: could not delete original message {message.id}: {exc}")


async def auto_archive_loop(
    client: discord.Client,
    channel_ids: list[int],
    interval_minutes: int = 30,
) -> None:
    """Background task: archive bot messages older than 24h in each channel."""
    await client.wait_until_ready()
    while True:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        for channel_id in channel_ids:
            channel = client.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                continue
            archive_thread = None  # created lazily on the first stale message
            try:
                async for msg in channel.history(limit=None, before=cutoff, oldest_first=True):
                    if msg.author.id != client.user.id:
                        continue
                    if archive_thread is None:
                        try:
                            archive_thread = await find_or_create_archive_thread(channel)
                        except Exception as exc:
                            print(f"{BOLD}{YELLOW}[WARN]{RESET} AutoArchive: archive thread failed for #{channel.name}: {exc}")
                            break
                    # Embed-less messages are deleted without forwarding —
                    # sending an empty embed list raises and would retry forever.
                    if msg.embeds:
                        try:
                            await archive_thread.send(embeds=msg.embeds)
                        except Exception as exc:
                            print(f"{BOLD}{YELLOW}[WARN]{RESET} AutoArchive: could not post msg {msg.id}: {exc}")
                            continue
                    try:
                        await msg.delete()
                        print(f"{MAGENTA}[AUTO-ARCHIVE]{RESET} #{channel.name} msg {msg.id} archived (>24h).")
                    except Exception as exc:
                        print(f"{BOLD}{YELLOW}[WARN]{RESET} AutoArchive: could not delete msg {msg.id}: {exc}")
            except Exception as exc:
                print(f"{BOLD}{YELLOW}[WARN]{RESET} AutoArchive: history fetch failed for #{channel.name}: {exc}")
                continue
        await asyncio.sleep(interval_minutes * 60)
