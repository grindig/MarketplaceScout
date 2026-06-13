# Design: Colored Terminal Output

**Date:** 2026-04-05  
**Status:** Approved

## Summary

Add ANSI color codes to all terminal print statements across `main.py`, `archiver.py`, and `notifier.py`. No new dependencies — raw ANSI escape codes only. Colors are defined once in a new `colors.py` module and imported where needed.

## Architecture

### New module: `colors.py`

Defines ANSI string constants only. No logic, no functions.

```python
RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
RED     = "\033[31m"
YELLOW  = "\033[33m"
CYAN    = "\033[36m"
MAGENTA = "\033[35m"
GREEN   = "\033[92m"   # bright green
```

### Color scheme

| Tag / Context | Color |
|---|---|
| `[BOOT]` messages, `===` separator lines | Cyan |
| `[SCAN]` — neue Treffer (success) | Bright Green |
| `[SCAN]` — keine neuen Treffer | Dim |
| `  ->` listing detail line | Yellow |
| `[ARCHIVE]` success | Magenta |
| `[WARN]` | Bold + Yellow |
| `[ERROR]` | Bold + Red |
| `[STOP]` | Cyan |

### Files modified

- **`main.py`** — boot block, scan loop prints, error/stop prints
- **`archiver.py`** — `[WARN]` and `[ARCHIVE]` prints
- **`notifier.py`** — warning print

## Error Handling & Testing

No error handling changes. No tests needed — this is pure string formatting with no logic.

## Notes

- Raw ANSI codes work on Windows Terminal, PowerShell, VS Code terminal, and all modern terminals on Windows 11.
- Each print wraps the colored section and appends `RESET` to avoid color bleed.
