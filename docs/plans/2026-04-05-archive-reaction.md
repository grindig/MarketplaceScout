# Archive-on-Reaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a user adds ❌ to a bot-posted listing message, the bot reposts it into a thread named "archive" (within the same channel) and deletes the original.

**Architecture:** A new `archiver.py` module handles the full archive flow. `main.py` only registers the `on_raw_reaction_add` event and delegates to `archiver.archive_message()`. No automated tests — the feature is Discord-API-bound and cannot be unit-tested without a mocking framework.

**Tech Stack:** Python 3.11+, discord.py 2.x

---

### Task 1: Create `archiver.py`

**Files:**
- Create: `archiver.py`

- [ ] **Step 1: Create the file with both functions**

```python
"""Archiver: moves bot messages to the 'archive' thread on ❌ reaction."""

import discord

X_EMOJI = "\U0000274c"  # ❌


async def find_or_create_archive_thread(channel: discord.TextChannel) -> discord.Thread:
    """Return the 'archive' thread in channel, creating it if necessary."""
    for thread in channel.threads:
        if thread.name == "archive":
            return thread

    async for thread in channel.archived_threads():
        if thread.name == "archive":
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
        print(f"[WARN] Archive: could not fetch message {payload.message_id}: {exc}")
        return

    if message.author.id != client.user.id:
        return

    try:
        archive_thread = await find_or_create_archive_thread(channel)
    except Exception as exc:
        print(f"[WARN] Archive: could not find/create archive thread: {exc}")
        return

    try:
        await archive_thread.send(
            content=message.content or None,
            embeds=message.embeds,
        )
    except Exception as exc:
        print(f"[WARN] Archive: could not post to archive thread: {exc}")
        return

    try:
        await message.delete()
        print(f"[ARCHIVE] Message {message.id} archived.")
    except Exception as exc:
        print(f"[WARN] Archive: could not delete original message {message.id}: {exc}")
```

- [ ] **Step 2: Commit**

```bash
git add archiver.py
git commit -m "feat: add archiver module for reaction-based message archiving"
```

---

### Task 2: Wire up `on_raw_reaction_add` in `main.py`

**Files:**
- Modify: `main.py`

Current `main.py` imports: `from notifier import send_notification`

- [ ] **Step 1: Add the import at the top of `main.py`**

After the existing imports block, add:

```python
from archiver import archive_message
```

So the imports section looks like:

```python
from scanner import fetch_html, parse_listings, filter_listings, filter_new
from notifier import send_notification
from archiver import archive_message
```

- [ ] **Step 2: Register the event handler inside `main()`**

In `main()`, inside the `client` setup block — after the existing `on_ready` function and before `client.run(...)` — add:

```python
    @client.event
    async def on_raw_reaction_add(payload: discord.RawReactionActionEvent) -> None:
        await archive_message(client, payload)
```

The full updated `main()` function should look like this:

```python
def main():
    config = load_config()

    intents = discord.Intents.default()
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        print(f"[BOOT] Bot eingeloggt als {client.user}")
        client.loop.create_task(scan_loop(client, config))

    @client.event
    async def on_raw_reaction_add(payload: discord.RawReactionActionEvent) -> None:
        await archive_message(client, payload)

    try:
        client.run(config["bot_token"])
    except KeyboardInterrupt:
        print("\n[STOP] Scanner gestoppt.")
        save_seen(load_seen())
        sys.exit(0)
```

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: wire on_raw_reaction_add to archive bot messages on ❌"
```

---

### Task 3: Manual Smoke Test

- [ ] **Step 1: Start the bot**

```bash
python main.py
```

Expected boot output:
```
[BOOT] Bot eingeloggt als <BotName>#XXXX
[BOOT] Willhaben Scanner gestartet
...
```

- [ ] **Step 2: Add ❌ reaction to a bot-posted listing message**

In Discord, click the ❌ reaction on any message the bot sent.

Expected:
- The message disappears from the original channel
- A thread named "archive" appears (or already exists)
- The message reappears inside the archive thread
- Console logs: `[ARCHIVE] Message <id> archived.`

- [ ] **Step 3: Verify thread reuse**

React ❌ on a second bot message.

Expected:
- Same "archive" thread is reused (no new thread created)
- Both messages are in the archive thread

- [ ] **Step 4: Verify non-bot messages are ignored**

Post a message yourself and react ❌ to it.

Expected: nothing happens (bot only archives its own messages)
