import asyncio
import json
import os
import sys
from datetime import datetime, timedelta

from dotenv import load_dotenv
load_dotenv()

import discord

from scanner import fetch_html, parse_listings, filter_listings, filter_new, fetch_listings_since
from notifier import send_notification
from archiver import archive_message, auto_archive_loop
from commands import register_commands
from marker import mark_message
from colors import RESET, BOLD, DIM, RED, YELLOW, CYAN, GREEN, DARK_GRAY, LIGHT_GRAY
from price_tracker import find_gpu_model, record_price, get_stats
from stats_board import stats_init, stats_loop
from storage import load_seen, save_seen

BOT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BOT_DIR, "json", "config.json")
KEYWORDS_PATH = os.path.join(BOT_DIR, "json", "keywords.json")


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        print(
            f"{BOLD}{RED}[ERROR]{RESET} {CONFIG_PATH} fehlt.\n"
            f"Kopiere json/config.example.json nach json/config.json und trage deine Channel-IDs ein."
        )
        sys.exit(1)
    if not os.path.exists(KEYWORDS_PATH):
        print(f"{BOLD}{RED}[ERROR]{RESET} {KEYWORDS_PATH} fehlt (keywords.json mit 'general' und 'gpu_models' Listen).")
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
    with open(KEYWORDS_PATH, "r", encoding="utf-8") as f:
        kw = json.load(f)
    config["keywords"] = kw["general"] + kw["gpu_models"]
    config["gpu_models"] = kw["gpu_models"]
    return config


def reset_backfill_days() -> None:
    """Set backfill_days to 0 in config.json (atomic write) after a completed backfill."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    raw["backfill_days"] = 0
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONFIG_PATH)


def scan_once(config: dict) -> list[dict]:
    """Run one scan cycle across all URLs. Returns matching listings, deduped per cycle.

    Runs in a worker thread, so it must not touch shared state like ``seen_ids`` —
    dedup against seen IDs happens in the event loop where the per-channel tasks
    are serialized.
    """
    all_matches: list[dict] = []
    cycle_ids: set[str] = set()  # the same listing may appear in several search URLs
    for url in config["search_urls"]:
        html = fetch_html(url)
        all_listings = parse_listings(html)
        for item in filter_listings(all_listings, config["keywords"], config["max_price"]):
            if item["id"] not in cycle_ids:
                cycle_ids.add(item["id"])
                all_matches.append(item)
    return all_matches


_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class _Spinner:
    """One shared terminal spinner; loops pause it around their prints.

    No-op when stdout is not a TTY (systemd/nohup/redirected to a log file).
    A backgrounded bot would otherwise wake ~12x/second around the clock just
    to animate a spinner nobody sees, and write a `\\r` frame into the logfile
    every 0.08s. When disabled, resume()/pause() do nothing.
    """

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop: asyncio.Event | None = None
        self._enabled = sys.stdout.isatty()

    async def _run(self, stop: asyncio.Event) -> None:
        i = 0
        while not stop.is_set():
            print(f"  {DARK_GRAY}{_SPINNER_FRAMES[i % len(_SPINNER_FRAMES)]}{RESET}", end="\r", flush=True)
            i += 1
            await asyncio.sleep(0.08)

    def resume(self) -> None:
        if not self._enabled:
            return
        if self._task is None or self._task.done():
            self._stop = asyncio.Event()
            self._task = asyncio.create_task(self._run(self._stop))

    async def pause(self) -> None:
        if not self._enabled:
            return
        task, self._task = self._task, None
        if task is None:
            return
        self._stop.set()
        await task
        print(" " * 60, end="\r", flush=True)


SPINNER = _Spinner()


async def _send_and_mark(channel, listing: dict, seen_ids: set[str], mention: bool = True) -> bool:
    """Send one listing and mark it seen only on success, so failed sends are retried."""
    if await send_notification(channel, listing, mention=mention):
        seen_ids.add(listing["id"])
        return True
    return False


async def backfill_channel(
    client: discord.Client,
    config: dict,
    channel_cfg: dict,
    seen_ids: set[str],
    days_back: int,
) -> None:
    """Fetch listings from the last ``days_back`` days and send them as Discord notifications."""
    channel = client.get_channel(int(channel_cfg["channel_id"]))
    if channel is None:
        return

    print(f"{DARK_GRAY}[{YELLOW}BACKFILL{DARK_GRAY}]{RESET} #{channel.name}: hole letzte {days_back} Tage...")

    all_backfill: list[dict] = []
    pending_ids: set[str] = set()  # the same listing may appear in several search URLs
    for url in channel_cfg["search_urls"]:
        listings = await asyncio.to_thread(fetch_listings_since, url, days_back)
        filtered = filter_listings(listings, config["keywords"], channel_cfg["max_price"])
        for listing in filter_new(filtered, seen_ids):
            if listing["id"] not in pending_ids:
                pending_ids.add(listing["id"])
                all_backfill.append(listing)

    if not all_backfill:
        print(f"{DARK_GRAY}[{YELLOW}BACKFILL{DARK_GRAY}]{RESET} #{channel.name}: keine neuen Inserate gefunden.")
        return

    print(f"{DARK_GRAY}[{YELLOW}BACKFILL{DARK_GRAY}]{RESET} #{channel.name}: {GREEN}{len(all_backfill)}{RESET} Inserate werden gesendet...")
    for listing in all_backfill:
        # mention=False: a multi-day catch-up must not @here-ping per listing
        await _send_and_mark(channel, listing, seen_ids, mention=False)
        await asyncio.sleep(0.5)  # Discord rate limit

    save_seen(seen_ids)
    print(f"{DARK_GRAY}[{YELLOW}BACKFILL{DARK_GRAY}]{RESET} #{channel.name}: fertig.")


async def scan_loop(client: discord.Client, config: dict, channel_cfg: dict, seen_ids: set[str]) -> None:
    """Background task: scan Willhaben for one channel and notify on new listings."""
    await client.wait_until_ready()

    channel = client.get_channel(int(channel_cfg["channel_id"]))
    if channel is None:
        print(f"{BOLD}{RED}[ERROR]{RESET} Channel {channel_cfg['channel_id']} nicht gefunden.")
        return

    scan_count = 0
    interval = config.get("scan_interval_seconds", 60)

    print(f"{DARK_GRAY}{'=' * 50}{RESET}")
    print(f"{DARK_GRAY}[{CYAN}BOOT{DARK_GRAY}]{RESET} Scanner gestartet: {DARK_GRAY}#{GREEN}{channel.name}{RESET}")
    print(f"{DARK_GRAY}[{CYAN}BOOT{DARK_GRAY}]{RESET} URLs: {len(channel_cfg['search_urls'])}")
    print(f"{DARK_GRAY}[{CYAN}BOOT{DARK_GRAY}]{RESET} Keywords: {len(config['keywords'])}")
    max_price_display = f"{channel_cfg['max_price']} EUR" if channel_cfg['max_price'] is not None else "unbegrenzt"
    print(f"{DARK_GRAY}[{CYAN}BOOT{DARK_GRAY}]{RESET} Max Preis: {max_price_display}")
    print(f"{DARK_GRAY}[{CYAN}BOOT{DARK_GRAY}]{RESET} Intervall: {interval}s")
    print(f"{DARK_GRAY}{'=' * 50}{RESET}")

    # Build a per-channel config slice for scan_once
    channel_scan_config = {
        "keywords": config["keywords"],
        "max_price": channel_cfg["max_price"],
        "search_urls": channel_cfg["search_urls"],
    }

    while True:
        scan_count += 1
        try:
            matches = await asyncio.to_thread(scan_once, channel_scan_config)
            new_listings = filter_new(matches, seen_ids)

            if new_listings:
                await SPINNER.pause()
                print(f"{BOLD}{GREEN}[#{channel.name} SCAN #{scan_count}]{RESET} {len(new_listings)} neue Treffer!")
                sent_any = False
                for listing in new_listings:
                    price_str = f"{listing['price']:.2f} EUR" if listing["price"] is not None else "N/A"
                    print(f"  {YELLOW}->{RESET} {listing['title']} | {price_str} | {listing['location']}")

                    model = None
                    if channel_cfg.get("track_prices") and listing.get("price") is not None:
                        model = find_gpu_model(listing["title"], config["gpu_models"])
                        if model and channel_cfg.get("show_price_stats"):
                            stats = get_stats(model)  # historical avg only; this price is recorded after the send
                            if stats:
                                pct = ((listing["price"] - stats["avg"]) / stats["avg"]) * 100
                                listing["price_stats"] = {
                                    "avg": stats["avg"],
                                    "count": stats["count"],
                                    "pct": pct,
                                }

                    # mark seen + record price only after a successful send, so a
                    # transient Discord failure retries on the next scan without
                    # double-recording the price
                    if await _send_and_mark(channel, listing, seen_ids):
                        sent_any = True
                        if model:
                            record_price(model, listing["price"])

                if sent_any:
                    save_seen(seen_ids)

        except Exception as e:
            await SPINNER.pause()
            print(f"{BOLD}{YELLOW}[WARN]{RESET} #{channel.name} Scan #{scan_count} fehlgeschlagen: {e}")

        SPINNER.resume()
        await asyncio.sleep(interval)


def restart():
    print(f"\n{CYAN}[RESTART]{RESET} Neustart...")
    os.execv(sys.executable, [sys.executable] + sys.argv)


async def midnight_restart():
    """Restart the bot at midnight every day."""
    while True:
        now = datetime.now()
        next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        seconds_until_midnight = (next_midnight - now).total_seconds()
        print(f"{DARK_GRAY}[{YELLOW}SCHEDULER{DARK_GRAY}]{RESET} {LIGHT_GRAY}Nächster Neustart: {next_midnight.strftime('%d.%m.%Y %H:%M')}{RESET}")
        await asyncio.sleep(seconds_until_midnight)
        restart()


def main():
    os.system("cls" if os.name == "nt" else "clear")
    sys.stdout.write("\033]0;@grindig\007")
    sys.stdout.flush()
    config = load_config()

    intents = discord.Intents.default()
    # max_messages=None disables discord.py's default 1000-message RAM cache:
    # the bot drives everything from raw reaction events + channel.fetch_message,
    # so the cache is never read — only memory.
    client = discord.Client(intents=intents, max_messages=None)
    tree = discord.app_commands.CommandTree(client)
    register_commands(client, tree)

    # Ctrl+R restart hotkey — interactive runs only. `keyboard` installs a
    # global system-wide hook (and needs root/accessibility on some systems), so
    # skip it on a headless 24/7 deploy: midnight_restart + Ctrl+C already cover
    # restart there, and a global hook would let Ctrl+R in any app (e.g. a browser
    # refresh) restart the bot.
    if sys.stdout.isatty():
        try:
            # imported lazily; the hotkey fires on a background thread, but
            # os.execv must run on the main thread, so marshal the restart
            # onto the event loop.
            import keyboard
            keyboard.add_hotkey("ctrl + r", lambda: client.loop.call_soon_threadsafe(restart))
        except Exception:
            pass

    started = False

    @client.event
    async def on_ready():
        nonlocal started
        print(f"{DARK_GRAY}[{CYAN}BOOT{DARK_GRAY}]{RESET} Bot eingeloggt als {client.user}")
        if started:
            # on_ready re-fires after gateway reconnects; the background
            # tasks are already running and must not be duplicated.
            return
        started = True

        try:
            synced = await tree.sync()
            print(f"{DARK_GRAY}[{CYAN}BOOT{DARK_GRAY}]{RESET} {len(synced)} Slash-Commands synchronisiert.")
        except Exception as exc:
            print(f"{BOLD}{YELLOW}[WARN]{RESET} Command-Sync fehlgeschlagen: {exc}")

        seen_ids = load_seen()
        stats_channel_id = config.get("stats_channel_id")
        stats_msg = await stats_init(client, stats_channel_id)
        asyncio.create_task(midnight_restart())

        backfill_days = config.get("backfill_days", 0)
        if backfill_days > 0:
            for channel_cfg in config["channels"]:
                await backfill_channel(client, config, channel_cfg, seen_ids, backfill_days)
            try:
                reset_backfill_days()
                print(f"{DARK_GRAY}[{YELLOW}BACKFILL{DARK_GRAY}]{RESET} {GREEN}Backfill abgeschlossen.{RESET} backfill_days wurde auf 0 zurückgesetzt.")
            except Exception as exc:
                print(f"{BOLD}{YELLOW}[WARN]{RESET} backfill_days konnte nicht zurückgesetzt werden: {exc}")

        for channel_cfg in config["channels"]:
            asyncio.create_task(scan_loop(client, config, channel_cfg, seen_ids))
        if stats_msg:
            asyncio.create_task(stats_loop(client, stats_channel_id, stats_msg))

        archive_channel_ids = [int(ch["channel_id"]) for ch in config["channels"]]
        archive_interval = config.get("auto_archive_interval_minutes", 30)
        asyncio.create_task(auto_archive_loop(client, archive_channel_ids, archive_interval))

    @client.event
    async def on_raw_reaction_add(payload: discord.RawReactionActionEvent) -> None:
        if str(payload.channel_id) == config.get("stats_channel_id", ""):
            return
        await archive_message(client, payload)
        await mark_message(client, payload)

    bot_token = os.environ.get("WILLHABEN_BOT_TOKEN")
    if not bot_token:
        print(f"{BOLD}{RED}[ERROR]{RESET} WILLHABEN_BOT_TOKEN Umgebungsvariable nicht gesetzt (siehe .env.example).")
        sys.exit(1)

    try:
        client.run(bot_token)
    except KeyboardInterrupt:
        # seen.json is already saved after every scan that finds something new
        print(f"\n{CYAN}[STOP]{RESET} Scanner gestoppt.")
        sys.exit(0)


if __name__ == "__main__":
    main()
