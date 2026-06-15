"""Slash commands: /clear and /archive over a time window."""

from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands

from archiver import find_or_create_archive_thread
from colors import RESET, BOLD, YELLOW, MAGENTA, CYAN


async def _bot_messages_in_window(
    channel: discord.TextChannel,
    client: discord.Client,
    window: timedelta,
) -> list[discord.Message]:
    """Bot messages within the window, oldest first (history defaults to
    oldest-first when ``after`` is given)."""
    after = datetime.now(timezone.utc) - window
    msgs: list[discord.Message] = []
    async for msg in channel.history(limit=None, after=after):
        if msg.author.id == client.user.id:
            msgs.append(msg)
    return msgs


async def _archive_to_thread(messages: list[discord.Message], archive_thread: discord.Thread) -> int:
    """Forward messages (already oldest-first) to the archive thread and delete the originals.

    Returns the number of successfully archived messages; failures are logged and skipped.
    """
    archived = 0
    for msg in messages:
        try:
            if msg.embeds:  # empty embed list would raise on send
                await archive_thread.send(embeds=msg.embeds)
            await msg.delete()
            archived += 1
        except Exception as exc:
            print(f"{BOLD}{YELLOW}[WARN]{RESET} Archive: msg {msg.id}: {exc}")
    return archived


def _build_window(days: int, hours: int, minutes: int) -> timedelta | None:
    if days == 0 and hours == 0 and minutes == 0:
        return None
    return timedelta(days=days, hours=hours, minutes=minutes)


def _window_label(days: int, hours: int, minutes: int) -> str:
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}min")
    return " ".join(parts)


def register_commands(client: discord.Client, tree: app_commands.CommandTree) -> None:
    @tree.command(name="clear", description="Löscht Bot-Notifications im angegebenen Zeitfenster in diesem Channel.")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(
        days="Tage (rückwärts ab jetzt)",
        hours="Stunden (rückwärts ab jetzt)",
        minutes="Minuten (rückwärts ab jetzt)",
    )
    async def clear_cmd(
        interaction: discord.Interaction,
        days: int = 0,
        hours: int = 0,
        minutes: int = 0,
    ) -> None:
        # Reject negative inputs: a future window silently deletes nothing and
        # gives no feedback, so the user assumes the command worked.
        days, hours, minutes = max(0, days), max(0, hours), max(0, minutes)
        window = _build_window(days, hours, minutes)
        if window is None:
            await interaction.response.send_message("Bitte mindestens einen Wert > 0 angeben.", ephemeral=True)
            return
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Nur in Text-Channels verfügbar.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        after = datetime.now(timezone.utc) - window
        try:
            deleted = await interaction.channel.purge(
                limit=None,
                after=after,
                check=lambda m: m.author.id == client.user.id,
                bulk=True,
            )
        except Exception as exc:
            await interaction.followup.send(f"Fehler: {exc}", ephemeral=True)
            return

        label = _window_label(days, hours, minutes)
        print(f"{CYAN}[CLEAR]{RESET} #{interaction.channel.name}: {len(deleted)} Nachrichten gelöscht ({label}).")
        await interaction.followup.send(f"{len(deleted)} Nachrichten gelöscht.", ephemeral=True)

    @tree.command(name="archive", description="Archiviert Bot-Notifications im angegebenen Zeitfenster in diesem Channel.")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(
        days="Tage (rückwärts ab jetzt)",
        hours="Stunden (rückwärts ab jetzt)",
        minutes="Minuten (rückwärts ab jetzt)",
    )
    async def archive_cmd(
        interaction: discord.Interaction,
        days: int = 0,
        hours: int = 0,
        minutes: int = 0,
    ) -> None:
        days, hours, minutes = max(0, days), max(0, hours), max(0, minutes)
        window = _build_window(days, hours, minutes)
        if window is None:
            await interaction.response.send_message("Bitte mindestens einen Wert > 0 angeben.", ephemeral=True)
            return
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Nur in Text-Channels verfügbar.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            messages = await _bot_messages_in_window(channel, client, window)
        except Exception as exc:
            await interaction.followup.send(f"Fehler beim Laden der Nachrichten: {exc}", ephemeral=True)
            return

        if not messages:
            await interaction.followup.send("Keine Bot-Nachrichten im Zeitfenster gefunden.", ephemeral=True)
            return

        try:
            archive_thread = await find_or_create_archive_thread(channel)
        except Exception as exc:
            await interaction.followup.send(f"Archive-Thread konnte nicht geöffnet werden: {exc}", ephemeral=True)
            return

        archived = await _archive_to_thread(messages, archive_thread)

        label = _window_label(days, hours, minutes)
        print(f"{MAGENTA}[ARCHIVE]{RESET} #{channel.name}: {archived}/{len(messages)} archiviert ({label}).")
        await interaction.followup.send(f"{archived} Nachrichten archiviert.", ephemeral=True)
