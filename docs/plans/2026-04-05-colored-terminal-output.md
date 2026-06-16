# Colored Terminal Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add ANSI color codes to all terminal print statements to make the bot's console output easier to read at a glance.

**Architecture:** A new `colors.py` module defines ANSI string constants. `main.py`, `archiver.py`, and `notifier.py` import from it and wrap their print strings. No logic changes, no new dependencies.

**Tech Stack:** Python 3.11+, raw ANSI escape codes

---

### Task 1: Create `colors.py`

**Files:**
- Create: `colors.py`

No tests needed — this is a constants-only file.

- [ ] **Step 1: Create the file**

```python
"""ANSI color constants for terminal output."""

RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
RED     = "\033[31m"
YELLOW  = "\033[33m"
CYAN    = "\033[36m"
MAGENTA = "\033[35m"
GREEN   = "\033[92m"  # bright green
```

- [ ] **Step 2: Commit**

```bash
git add colors.py
git commit -m "feat: add ANSI color constants module"
```

---

### Task 2: Colorize `main.py`

**Files:**
- Modify: `main.py`

Color mapping:
- `[BOOT]` lines and `===` separator → Cyan
- `[SCAN]` neue Treffer → Bold + Bright Green
- `[SCAN]` keine neuen Treffer → Dim
- `  ->` listing detail → Yellow
- `[WARN]` → Bold + Yellow
- `[ERROR]` → Bold + Red
- `[STOP]` → Cyan

No tests needed — pure formatting.

- [ ] **Step 1: Add import to `main.py`**

After the existing local imports (line 10), add:

```python
from colors import RESET, BOLD, DIM, RED, YELLOW, CYAN, GREEN
```

So the local imports block looks like:

```python
from scanner import fetch_html, parse_listings, filter_listings, filter_new
from notifier import send_notification
from archiver import archive_message
from colors import RESET, BOLD, DIM, RED, YELLOW, CYAN, GREEN
```

- [ ] **Step 2: Update all print statements in `main.py`**

Replace the entire `scan_loop` function body's print calls and the `main()` print calls. The full updated file from line 48 onward looks like this:

```python
async def scan_loop(client: discord.Client, config: dict) -> None:
    """Background task: scan Willhaben and notify on new listings."""
    await client.wait_until_ready()

    channel = client.get_channel(int(config["channel_id"]))
    if channel is None:
        print(f"{BOLD}{RED}[ERROR]{RESET} Channel {config['channel_id']} nicht gefunden. Bot wird beendet.")
        await client.close()
        return

    seen_ids = load_seen()
    scan_count = 0
    interval = config.get("scan_interval_seconds", 60)

    print(f"{CYAN}{'=' * 50}{RESET}")
    print(f"{CYAN}[BOOT]{RESET} Willhaben Scanner gestartet")
    print(f"{CYAN}[BOOT]{RESET} Channel: #{channel.name}")
    print(f"{CYAN}[BOOT]{RESET} URLs: {len(config['search_urls'])}")
    print(f"{CYAN}[BOOT]{RESET} Keywords: {len(config['keywords'])}")
    print(f"{CYAN}[BOOT]{RESET} Max Preis: {config['max_price']} EUR")
    print(f"{CYAN}[BOOT]{RESET} Intervall: {interval}s")
    print(f"{CYAN}{'=' * 50}{RESET}")

    while True:
        scan_count += 1
        try:
            new_listings = await asyncio.to_thread(scan_once, config, seen_ids)
            save_seen(seen_ids)

            if new_listings:
                print(f"{BOLD}{GREEN}[SCAN #{scan_count}]{RESET} {len(new_listings)} neue Treffer!")
                for listing in new_listings:
                    price_str = f"{listing['price']:.2f} EUR" if listing["price"] else "N/A"
                    print(f"  {YELLOW}->{RESET} {listing['title']} | {price_str} | {listing['location']}")
                    await send_notification(channel, listing)
            else:
                print(f"{DIM}[SCAN #{scan_count}] Keine neuen Treffer.{RESET}")

        except Exception as e:
            print(f"{BOLD}{YELLOW}[WARN]{RESET} Scan #{scan_count} fehlgeschlagen: {e}")

        await asyncio.sleep(interval)


def main():
    config = load_config()

    intents = discord.Intents.default()
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        print(f"{CYAN}[BOOT]{RESET} Bot eingeloggt als {client.user}")
        client.loop.create_task(scan_loop(client, config))

    @client.event
    async def on_raw_reaction_add(payload: discord.RawReactionActionEvent) -> None:
        await archive_message(client, payload)

    try:
        client.run(config["bot_token"])
    except KeyboardInterrupt:
        print(f"\n{CYAN}[STOP]{RESET} Scanner gestoppt.")
        save_seen(load_seen())
        sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: colorize main.py terminal output"
```

---

### Task 3: Colorize `archiver.py` and `notifier.py`

**Files:**
- Modify: `archiver.py`
- Modify: `notifier.py`

Color mapping:
- `[WARN]` → Bold + Yellow
- `[ARCHIVE]` success → Magenta

No tests needed.

- [ ] **Step 1: Update `archiver.py`**

Add import after `import discord`:

```python
from colors import RESET, BOLD, YELLOW, MAGENTA
```

Replace all print statements in `archiver.py`:

```python
    except Exception as exc:
        print(f"{BOLD}{YELLOW}[WARN]{RESET} Archive: could not fetch message {payload.message_id}: {exc}")
        return
```

```python
    except Exception as exc:
        print(f"{BOLD}{YELLOW}[WARN]{RESET} Archive: could not find/create archive thread: {exc}")
        return
```

```python
    except Exception as exc:
        print(f"{BOLD}{YELLOW}[WARN]{RESET} Archive: could not post to archive thread: {exc}")
        return
```

```python
        print(f"{MAGENTA}[ARCHIVE]{RESET} Message {message.id} archived.")
    except Exception as exc:
        print(f"{BOLD}{YELLOW}[WARN]{RESET} Archive: could not delete original message {message.id}: {exc}")
```

The full updated `archiver.py`:

```python
"""Archiver: moves bot messages to the 'archive' thread on ❌ reaction."""

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

    try:
        await archive_thread.send(
            content=message.content or None,
            embeds=message.embeds,
        )
    except Exception as exc:
        print(f"{BOLD}{YELLOW}[WARN]{RESET} Archive: could not post to archive thread: {exc}")
        return

    try:
        await message.delete()
        print(f"{MAGENTA}[ARCHIVE]{RESET} Message {message.id} archived.")
    except Exception as exc:
        print(f"{BOLD}{YELLOW}[WARN]{RESET} Archive: could not delete original message {message.id}: {exc}")
```

- [ ] **Step 2: Update `notifier.py`**

Add import after existing imports:

```python
from colors import RESET, BOLD, YELLOW
```

Replace the warning print:

```python
        print(f"{BOLD}{YELLOW}Warning:{RESET} Failed to send Discord notification: {exc}")
```

- [ ] **Step 3: Commit**

```bash
git add archiver.py notifier.py
git commit -m "feat: colorize archiver and notifier terminal output"
```
