"""Tests for the /archive command helpers."""

import asyncio
from datetime import timedelta, timezone
from unittest.mock import AsyncMock

from commands import _archive_window_to_thread


class FakeChannel:
    """Yields fake messages from a mocked history() async iterator."""

    def __init__(self, messages):
        self.messages = messages

    def history(self, limit=None, after=None):
        # history() returns an async iterator; mimic it with an async generator wrapper.
        return _HistoryIter(self.messages)


class _HistoryIter:
    def __init__(self, messages):
        self.messages = messages

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.messages:
            raise StopAsyncIteration
        return self.messages.pop(0)


class FakeThread:
    """Records sent embeds; raises when asked to send the marker 'boom'."""

    def __init__(self):
        self.sent: list[list] = []

    async def send(self, embeds):
        if embeds == ["boom"]:
            raise RuntimeError("boom")
        self.sent.append(embeds)


class FakeMessage:
    def __init__(self, msg_id, author_id=1, embeds=None):
        self.id = msg_id
        self.author = type("Author", (), {"id": author_id})()
        self.embeds = [f"embed{msg_id}"] if embeds is None else embeds
        self.deleted = False

    async def delete(self):
        self.deleted = True


def _run(coro):
    return asyncio.run(coro)


def test_archive_window_to_thread_preserves_oldest_first_order():
    """Messages arrive oldest-first (history with after=) and must be posted in that order."""
    client = AsyncMock()
    client.user.id = 1
    channel = FakeChannel([FakeMessage(1), FakeMessage(2), FakeMessage(3)])
    thread = FakeThread()

    archived = _run(
        _archive_window_to_thread(channel, thread, client, timedelta(hours=1))
    )

    assert archived == 3
    assert thread.sent == [["embed1"], ["embed2"], ["embed3"]]
    assert all(m.deleted for m in channel.messages)  # messages were consumed


def test_archive_window_to_thread_skips_non_bot_messages():
    """Only messages authored by the bot are archived."""
    client = AsyncMock()
    client.user.id = 1
    channel = FakeChannel([FakeMessage(1, author_id=1), FakeMessage(2, author_id=99)])
    thread = FakeThread()

    archived = _run(
        _archive_window_to_thread(channel, thread, client, timedelta(hours=1))
    )

    assert archived == 1
    assert thread.sent == [["embed1"]]


def test_archive_window_to_thread_continues_after_failure():
    """One failing message must not stop the rest from being archived."""
    client = AsyncMock()
    client.user.id = 1
    channel = FakeChannel([FakeMessage(1), FakeMessage(2, embeds=["boom"]), FakeMessage(3)])
    thread = FakeThread()

    archived = _run(
        _archive_window_to_thread(channel, thread, client, timedelta(hours=1))
    )

    assert archived == 2
    assert thread.sent == [["embed1"], ["embed3"]]


def test_archive_window_to_thread_deletes_embedless_without_posting():
    """Messages without embeds are deleted but not forwarded (empty embed list raises on send)."""
    client = AsyncMock()
    client.user.id = 1
    channel = FakeChannel([FakeMessage(1, embeds=[])])
    thread = FakeThread()

    archived = _run(
        _archive_window_to_thread(channel, thread, client, timedelta(hours=1))
    )

    assert archived == 1
    assert thread.sent == []


class TestCommandsGerman:
    """Drive all /clear and /archive user-facing strings through German.

    Existing tests call the helper functions directly and only assert runtime
    behavior, not what Discord sees at sync time. So we have to build a real
    command tree and read the registered description/parameter strings off it
    - that is the only way to catch a missing t() wrap on the @tree.command
    decorator itself.
    """

    def setup_method(self):
        from i18n import set_language
        set_language("de")

    def teardown_method(self):
        from i18n import set_language
        set_language("en")

    @staticmethod
    def _build_tree():
        """Register the commands against a fresh mock client and return the tree."""
        from unittest.mock import MagicMock, PropertyMock
        import discord
        from commands import register_commands

        client = MagicMock()
        client.user.id = 1
        client.http = MagicMock()
        # CommandTree.__init__ checks self._state._command_tree is None.
        type(client)._connection = PropertyMock(return_value=MagicMock())
        type(client)._connection._command_tree = None

        tree = discord.app_commands.CommandTree(client)
        register_commands(client, tree)
        return tree

    def test_clear_description_german(self):
        tree = self._build_tree()
        cmd = tree.get_command("clear")
        assert "Löscht" in cmd.description

    def test_clear_param_descriptions_german(self):
        tree = self._build_tree()
        cmd = tree.get_command("clear")
        param_descs = {p.name: p.description for p in cmd.parameters}
        assert param_descs["days"] == "Tage (rückwärts ab jetzt)"
        assert param_descs["hours"] == "Stunden (rückwärts ab jetzt)"
        assert param_descs["minutes"] == "Minuten (rückwärts ab jetzt)"

    def test_clear_reply_need_value_german(self):
        from i18n import t
        assert t("command.clear.reply.need_value") == "Bitte mindestens einen Wert > 0 angeben."

    def test_archive_description_german(self):
        tree = self._build_tree()
        cmd = tree.get_command("archive")
        assert "Archiviert" in cmd.description

    def test_archive_reply_no_messages_german(self):
        from i18n import t
        assert t("command.archive.reply.no_messages") == "Keine Bot-Nachrichten im Zeitfenster gefunden."
