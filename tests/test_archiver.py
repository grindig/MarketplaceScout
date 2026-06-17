"""Tests for reaction and scheduled archiving helpers."""

import asyncio

import archiver


class _StopAfterOneCycle(Exception):
    """Raised by the patched sleep() to stop auto_archive_loop after one pass."""


class FakeAuthor:
    def __init__(self, author_id):
        self.id = author_id


class FakeMessage:
    def __init__(self, msg_id, author_id=1):
        self.id = msg_id
        self.author = FakeAuthor(author_id)
        self.embeds = [f"embed{msg_id}"]
        self.deleted = False

    async def delete(self):
        self.deleted = True


class FakeThread:
    def __init__(self):
        self.sent = []

    async def send(self, embeds):
        self.sent.append(embeds)


class FakeHistory:
    def __init__(self, messages):
        self._messages = list(messages)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)


class FakeTextChannel:
    name = "deals"

    def __init__(self, messages):
        self.messages = messages
        self.history_calls = []
        self.archive_thread = FakeThread()

    def history(self, **kwargs):
        self.history_calls.append(kwargs)
        return FakeHistory(self.messages)


class FakeClient:
    def __init__(self, channel):
        self._channel = channel
        self.user = FakeAuthor(1)

    async def wait_until_ready(self):
        return

    def get_channel(self, channel_id):
        return self._channel


def test_auto_archive_loop_bounds_history_and_preserves_archive_order(monkeypatch):
    """The scheduled archiver should scan only a bounded newest-stale batch.

    Discord returns newest-first when ``oldest_first=False``. The archiver
    buffers only that bounded batch and processes it oldest-first so the archive
    thread stays readable without walking the entire stale channel history.
    """
    # Simulate Discord returning the newest stale messages first.
    newest_to_oldest = [FakeMessage(3), FakeMessage(2), FakeMessage(1)]
    channel = FakeTextChannel(newest_to_oldest)
    client = FakeClient(channel)

    monkeypatch.setattr(archiver.discord, "TextChannel", FakeTextChannel)
    monkeypatch.setattr(archiver, "find_or_create_archive_thread", lambda _channel: _return(channel.archive_thread))

    async def stop_after_cycle(_seconds):
        raise _StopAfterOneCycle

    monkeypatch.setattr(archiver.asyncio, "sleep", stop_after_cycle)

    try:
        asyncio.run(archiver.auto_archive_loop(client, [123], interval_minutes=30))
    except _StopAfterOneCycle:
        pass

    assert channel.history_calls
    call = channel.history_calls[0]
    assert call["limit"] == archiver.AUTO_ARCHIVE_HISTORY_LIMIT
    assert call["oldest_first"] is False
    assert call["before"] is not None
    assert channel.archive_thread.sent == [["embed1"], ["embed2"], ["embed3"]]
    assert all(msg.deleted for msg in newest_to_oldest)


async def _return(value):
    return value
