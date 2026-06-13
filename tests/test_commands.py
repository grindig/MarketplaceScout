"""Tests for the /archive command helpers."""

import asyncio

from commands import _archive_to_thread


class FakeThread:
    """Records sent embeds; raises when asked to send the marker 'boom'."""

    def __init__(self):
        self.sent: list[list] = []

    async def send(self, embeds):
        if embeds == ["boom"]:
            raise RuntimeError("boom")
        self.sent.append(embeds)


class FakeMessage:
    def __init__(self, msg_id, embeds=None):
        self.id = msg_id
        self.embeds = [f"embed{msg_id}"] if embeds is None else embeds
        self.deleted = False

    async def delete(self):
        self.deleted = True


def test_archive_to_thread_preserves_oldest_first_order():
    """Messages arrive oldest-first (history with after=) and must be posted in that order."""
    msgs = [FakeMessage(1), FakeMessage(2), FakeMessage(3)]
    thread = FakeThread()

    archived = asyncio.run(_archive_to_thread(msgs, thread))

    assert archived == 3
    assert thread.sent == [["embed1"], ["embed2"], ["embed3"]]
    assert all(m.deleted for m in msgs)


def test_archive_to_thread_continues_after_failure():
    """One failing message must not stop the rest from being archived."""
    msgs = [FakeMessage(1), FakeMessage(2, embeds=["boom"]), FakeMessage(3)]
    thread = FakeThread()

    archived = asyncio.run(_archive_to_thread(msgs, thread))

    assert archived == 2
    assert thread.sent == [["embed1"], ["embed3"]]
    assert msgs[0].deleted and msgs[2].deleted
    assert not msgs[1].deleted


def test_archive_to_thread_deletes_embedless_without_posting():
    """Messages without embeds are deleted but not forwarded (empty embed list raises on send)."""
    msgs = [FakeMessage(1, embeds=[])]
    thread = FakeThread()

    archived = asyncio.run(_archive_to_thread(msgs, thread))

    assert archived == 1
    assert thread.sent == []
    assert msgs[0].deleted
