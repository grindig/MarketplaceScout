# Design: Archive on ❌ Reaction

**Date:** 2026-04-05  
**Status:** Approved

## Summary

When a user adds a ❌ (`:x:`) reaction to a bot-posted listing message, the bot moves that message into a thread named `"archive"` within the same channel, then deletes the original.

## Architecture

### New module: `archiver.py`

Two functions:

**`find_or_create_archive_thread(channel: discord.TextChannel) -> discord.Thread`**
- Searches `channel.threads` (active threads) for a thread named `"archive"` (case-sensitive)
- If not found: iterates `channel.archived_threads()` to check if it was auto-archived
- If still not found: creates a new public thread (no starter message) named `"archive"`
- Returns the thread (Discord auto-unarchives a thread when a message is posted to it)

**`archive_message(client: discord.Client, payload: discord.RawReactionActionEvent) -> None`**
- Entry point called from `on_raw_reaction_add`
- Early-exit conditions (all silent):
  - Emoji is not ❌ (`\U0000274c`)
  - Reaction was added by the bot itself
  - Message was not sent by the bot
- Fetches the original message via API (`channel.fetch_message`)
- Calls `find_or_create_archive_thread(channel)`
- Re-posts the message content and embed into the archive thread
- Deletes the original message

### Changes to `main.py`

- Explicitly enable `intents.message_content = True` and `intents.reactions = True`
- Register `on_raw_reaction_add` event handler that calls `archive_message(client, payload)`

## Data Flow

```
User adds ❌ reaction
  → on_raw_reaction_add fires
  → archive_message() called
      → validate (emoji, not bot, bot's message)
      → fetch original message
      → find_or_create_archive_thread()
      → post embed + content to archive thread
      → delete original message
```

## Error Handling

| Failure point | Behavior |
|---|---|
| Thread creation fails | Log `[WARN]`, abort — original message is NOT deleted |
| Message fetch fails | Log `[WARN]`, abort |
| Archive post fails | Log `[WARN]`, abort — original message is NOT deleted |
| Delete original fails | Log `[WARN]`, message remains in original channel |

The rule: **never delete the original unless the archive post succeeded.**

## Testing

No new automated tests. The feature is Discord-API-bound and not unit-testable without a mocking framework. Existing tests in `tests/` are unaffected.
