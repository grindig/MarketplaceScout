import asyncio
import json
import os
import sys

from i18n import set_language, t
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
from storage import atomic_write_json, load_seen, SeenWriter, DEFAULT_SEEN_TTL_DAYS

BOT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BOT_DIR, "json", "config.json")
KEYWORDS_PATH = os.path.join(BOT_DIR, "json", "keywords.json")


async def flush_seen_writer(client) -> None:
    """Flush the SeenWriter attached to ``client``, if any.

    Extracted so the shutdown path is unit-testable without a real Discord
    client. Safe to call when no writer is attached (no-op) and safe to call
    more than once — ``SeenWriter.stop()`` is idempotent.
    """
    writer = getattr(client, "_seen_writer", None)
    if writer is not None:
        await writer.stop()


class MarketplaceScoutClient(discord.Client):
    """discord.Client subclass that flushes the SeenWriter on close.

    discord.py 2.x does NOT dispatch an ``on_close`` event, so the previous
    ``on_close`` handler was dead code: a Ctrl+C or service stop ran
    ``Client.run()``'s internal ``async with self`` (which calls
    ``close()``) and returned without ever flushing pending seen IDs. By
    overriding ``close()`` the flush runs as part of the real shutdown path,
    before the HTTP/gateway clients are torn down. ``run()``'s logging
    setup and KeyboardInterrupt handling are preserved unchanged.
    """

    async def close(self) -> None:
        try:
            await flush_seen_writer(self)
        except Exception as exc:
            print(f"{BOLD}{YELLOW}[{t('warn.banner_prefix')}]{RESET} " + t("storage.seen_flush_failed", exc=exc))
        await super().close()


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        print(
            f"{BOLD}{RED}[{t('error.banner_prefix')}]{RESET} "
            + t("error.config_missing", path=CONFIG_PATH)
        )
        sys.exit(1)
    if not os.path.exists(KEYWORDS_PATH):
        print(f"{BOLD}{RED}[{t('error.banner_prefix')}]{RESET} " + t("error.keywords_missing", path=KEYWORDS_PATH))
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
    with open(KEYWORDS_PATH, "r", encoding="utf-8") as f:
        kw = json.load(f)
    config["keywords"] = kw["general"] + kw["gpu_models"]
    config["gpu_models"] = kw["gpu_models"]
    config["language"] = config.get("language", "en")
    try:
        set_language(config["language"])
    except ValueError as exc:
        print(f"{BOLD}{RED}[{t('error.banner_prefix')}]{RESET} {exc}")
        sys.exit(1)
    return config


def reset_backfill_days() -> None:
    """Set backfill_days to 0 in config.json (atomic write) after a completed backfill."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    raw["backfill_days"] = 0
    atomic_write_json(CONFIG_PATH, raw)


def scan_once(config: dict) -> list[dict]:
    """Run one scan cycle across all URLs. Returns matching listings, deduped per cycle.

    Runs in a worker thread, so it must not touch shared state like ``seen_ids`` —
    dedup against seen IDs happens in the event loop where the per-channel tasks
    are serialized.
    """
    all_matches: list[dict] = []
    cycle_ids: set[str] = set()  # the same listing may appear in several search URLs
    for url in config["search_urls"]:
        # Isolate per-URL failures: one timed-out or 5xx'd search URL must not
        # abort the whole cycle and silently drop every other URL's listings.
        try:
            html = fetch_html(url)
            all_listings = parse_listings(html)
        except Exception as exc:
            print(f"{BOLD}{YELLOW}[{t('warn.banner_prefix')}]{RESET} " + t("scan.url_failed", url=url, exc=exc))
            continue
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


async def _send_and_mark(seen_writer: SeenWriter, channel, listing: dict, mention: bool = True) -> bool:
    """Send one listing and mark it seen only on success, so failed sends are retried.

    Marks via the SeenWriter rather than a raw set so the debounced flush picks
    it up: the in-memory set is the dedup source of truth within this process,
    and the next save_seen (timer / shutdown) persists it.
    """
    if await send_notification(channel, listing, mention=mention):
        seen_writer.add(listing["id"])
        return True
    return False


async def backfill_channel(
    client: discord.Client,
    config: dict,
    channel_cfg: dict,
    seen_writer: SeenWriter,
    days_back: int,
) -> None:
    """Fetch listings from the last ``days_back`` days and send them as Discord notifications."""
    channel = client.get_channel(int(channel_cfg["channel_id"]))
    if channel is None:
        return

    print(f"{DARK_GRAY}[{YELLOW}{t('backfill.banner_prefix')}{DARK_GRAY}]{RESET} " + t("backfill.fetching", channel=channel.name, days=days_back))

    all_backfill: list[dict] = []
    pending_ids: set[str] = set()  # the same listing may appear in several search URLs
    for url in channel_cfg["search_urls"]:
        listings = await asyncio.to_thread(fetch_listings_since, url, days_back)
        filtered = filter_listings(listings, config["keywords"], channel_cfg["max_price"])
        for listing in filter_new(filtered, seen_writer.seen):
            if listing["id"] not in pending_ids:
                pending_ids.add(listing["id"])
                all_backfill.append(listing)

    if not all_backfill:
        print(f"{DARK_GRAY}[{YELLOW}{t('backfill.banner_prefix')}{DARK_GRAY}]{RESET} " + t("backfill.none_found", channel=channel.name))
        return

    n_listings = len(all_backfill)
    msg = t("backfill.sending", channel=channel.name, n=n_listings)
    print(f"{DARK_GRAY}[{YELLOW}{t('backfill.banner_prefix')}{DARK_GRAY}]{RESET} " + msg.replace(str(n_listings), f"{GREEN}{n_listings}{RESET}", 1))
    for listing in all_backfill:
        # mention=False: a multi-day catch-up must not @here-ping per listing
        await _send_and_mark(seen_writer, channel, listing, mention=False)
        await asyncio.sleep(0.5)  # Discord rate limit

    # Backfill mutates many IDs in a single pass; flushing immediately keeps
    # the on-disk file consistent with what was actually delivered, so a
    # crash mid-bot doesn't replay a partial backfill on next start.
    await seen_writer.flush_now()
    print(f"{DARK_GRAY}[{YELLOW}{t('backfill.banner_prefix')}{DARK_GRAY}]{RESET} " + t("backfill.done", channel=channel.name))


async def scan_loop(client: discord.Client, config: dict, channel_cfg: dict, seen_writer: SeenWriter, dedup_lock: asyncio.Lock) -> None:
    """Background task: scan Willhaben for one channel and notify on new listings."""
    await client.wait_until_ready()

    channel = client.get_channel(int(channel_cfg["channel_id"]))
    if channel is None:
        print(f"{BOLD}{RED}[{t('error.banner_prefix')}]{RESET} " + t("error.channel_not_found", channel_id=channel_cfg['channel_id']))
        return

    scan_count = 0
    interval = config.get("scan_interval_seconds", 60)
    seen_ids = seen_writer.seen  # alias; SeenWriter.add() mutates the same set

    print(f"{DARK_GRAY}{'=' * 50}{RESET}")
    boot_prefix = f"{DARK_GRAY}[{CYAN}{t('boot.banner_prefix')}{DARK_GRAY}]{RESET}"
    print(boot_prefix + " " + t("boot.scanner_started", channel=channel.name))
    print(boot_prefix + " " + t("boot.urls_count", n=len(channel_cfg['search_urls'])))
    print(boot_prefix + " " + t("boot.keywords_count", n=len(config['keywords'])))
    if channel_cfg['max_price'] is not None:
        print(boot_prefix + " " + t("boot.max_price_limit", price=channel_cfg['max_price']))
    else:
        print(boot_prefix + " " + t("boot.max_price_unlimited"))
    print(boot_prefix + " " + t("boot.interval", n=interval))
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
                print(f"{BOLD}{GREEN}" + t("scan.new_hits", channel=channel.name, n=scan_count, m=len(new_listings)) + f"{RESET}")
                for listing in new_listings:
                    price_str = f"{listing['price']:.2f} EUR" if listing['price'] is not None else "N/A"
                    print(f"  {YELLOW}->{RESET} {listing['title']} | {price_str} | {listing['location']}")

                    model = None
                    if channel_cfg.get("track_prices") and listing.get("price") is not None:
                        model = find_gpu_model(listing["title"], config["gpu_models"])
                        if model and channel_cfg.get("show_price_stats"):
                            stats = get_stats(model)  # historical avg only; this price is recorded after the send
                            if stats and stats["avg"] > 0:
                                pct = ((listing["price"] - stats["avg"]) / stats["avg"]) * 100
                                listing["price_stats"] = {
                                    "avg": stats["avg"],
                                    "count": stats["count"],
                                    "pct": pct,
                                }

                    # All channels share one SeenWriter and one dedup_lock.
                    # new_listings was computed before the awaits below, so
                    # another channel's loop may have sent the same listing
                    # in the meantime. The lock serializes check+send+mark
                    # across channels so a listing shared across channels'
                    # URLs is posted to at most one channel.
                    async with dedup_lock:
                        if listing["id"] in seen_ids:
                            continue
                        sent = await _send_and_mark(seen_writer, channel, listing)

                    # Record price only after a successful send, so a transient
                    # Discord failure retries on the next scan without
                    # double-recording the price. Offloaded to a worker thread
                    # because atomic_write_json can sleep up to ~2.5 s on
                    # Windows's replace-retry tail.
                    if sent and model:
                        await asyncio.to_thread(record_price, model, listing["price"])

        except Exception as e:
            await SPINNER.pause()
            print(f"{BOLD}{YELLOW}[{t('warn.banner_prefix')}]{RESET} " + t("scan.scan_failed", channel=channel.name, n=scan_count, e=e))

        SPINNER.resume()
        await asyncio.sleep(interval)


def restart():
    print(f"\n{CYAN}[{t('restart.banner_prefix')}]{RESET} " + t("restart.in_progress"))
    os.execv(sys.executable, [sys.executable] + sys.argv)


async def midnight_restart(client):
    """Restart the bot at midnight every day."""
    while True:
        now = datetime.now()
        next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        seconds_until_midnight = (next_midnight - now).total_seconds()
        print(f"{DARK_GRAY}[{YELLOW}{t('scheduler.banner_prefix')}{DARK_GRAY}]{RESET} {LIGHT_GRAY}" + t("scheduler.next_restart", datetime=next_midnight.strftime('%d.%m.%Y %H:%M')) + f"{RESET}")
        await asyncio.sleep(seconds_until_midnight)
        # os.execv replaces the process image immediately and never returns, so
        # it bypasses close(). Flush the SeenWriter first — otherwise every
        # nightly restart loses up to DEFAULT_SEEN_FLUSH_SECONDS of newly-seen
        # IDs and re-notifies (re-posts) those listings after the restart.
        await flush_seen_writer(client)
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
    client = MarketplaceScoutClient(intents=intents, max_messages=None)
    tree = discord.app_commands.CommandTree(client)
    # Slash commands are individually opt-in via config. When a flag is 0 the
    # command is not registered, and tree.sync() removes it from Discord on
    # next boot.
    register_commands(client, tree, config)

    started = False

    @client.event
    async def on_ready():
        nonlocal started
        print(f"{DARK_GRAY}[{CYAN}{t('boot.banner_prefix')}{DARK_GRAY}]{RESET} " + t("boot.logged_in", user=client.user))
        if started:
            # on_ready re-fires after gateway reconnects; the background
            # tasks are already running and must not be duplicated.
            return
        started = True

        try:
            synced = await tree.sync()
            print(f"{DARK_GRAY}[{CYAN}{t('boot.banner_prefix')}{DARK_GRAY}]{RESET} " + t("boot.commands_synced", n=len(synced)))
        except Exception as exc:
            print(f"{BOLD}{YELLOW}[{t('warn.banner_prefix')}]{RESET} " + t("boot.commands_sync_failed", exc=exc))

        # SeenWriter: in-memory dedup with debounced disk flush. Loaded from
        # disk at construction, so the in-memory set is already populated
        # before any channel loop runs. The flush loop is started here and
        # stopped in MarketplaceScoutClient.close() (graceful shutdown) so a
        # SIGINT never loses more than DEFAULT_SEEN_FLUSH_SECONDS of newly-
        # seen IDs.
        seen_writer = SeenWriter(
            ttl_days=config.get("seen_ttl_days", DEFAULT_SEEN_TTL_DAYS),
        )
        seen_writer.start()
        # Attach the writer to the client so close() can find and stop it.
        client._seen_writer = seen_writer  # type: ignore[attr-defined]

        stats_channel_id = config.get("stats_channel_id")
        stats_msg = await stats_init(client, stats_channel_id)
        asyncio.create_task(midnight_restart(client))

        backfill_days = config.get("backfill_days", 0)
        if backfill_days > 0:
            for channel_cfg in config["channels"]:
                await backfill_channel(client, config, channel_cfg, seen_writer, backfill_days)
            try:
                reset_backfill_days()
                print(f"{DARK_GRAY}[{YELLOW}{t('backfill.banner_prefix')}{DARK_GRAY}]{RESET} {GREEN}" + t("backfill.complete") + f"{RESET}")
            except Exception as exc:
                print(f"{BOLD}{YELLOW}[{t('warn.banner_prefix')}]{RESET} " + t("backfill.reset_failed", exc=exc))

        # One lock shared across all scan loops: serializes the check+send+mark
        # critical section so a listing that appears in multiple channels' URL
        # sets is posted to at most one channel per scan cycle.
        dedup_lock = asyncio.Lock()

        for channel_cfg in config["channels"]:
            asyncio.create_task(scan_loop(client, config, channel_cfg, seen_writer, dedup_lock))
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

    bot_token = os.environ.get("DISCORD_BOT_TOKEN")
    if not bot_token:
        print(f"{BOLD}{RED}[{t('error.banner_prefix')}]{RESET} " + t("error.token_missing"))
        sys.exit(1)

    try:
        client.run(bot_token)
    except KeyboardInterrupt:
        # close() (called by run()'s internal `async with self`) has already
        # flushed the SeenWriter; nothing else to do.
        print(f"\n{CYAN}[{t('stop.banner_prefix')}]{RESET} " + t("stop.scanner_stopped"))
        sys.exit(0)


if __name__ == "__main__":
    main()
