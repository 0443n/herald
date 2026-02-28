"""Receiver: watches user directory via inotify, shows desktop notifications."""

import asyncio
import json
import logging
import os
import pwd
import shutil
import sys
import tomllib
from pathlib import Path
from typing import Any, TypedDict

from dbus_fast import Message as DBusMessage
from dbus_fast import Variant
from dbus_fast.aio import MessageBus
from dbus_fast.constants import MessageType

from herald import BASE_DIR, Urgency

log = logging.getLogger(__name__)


class Config(TypedDict):
    max_history: int
    timeout_override: int | None
    urgency_filter: list[str] | None
    show_body: bool


_CONFIG_DEFAULTS: Config = {
    "max_history": 100,
    "timeout_override": None,
    "urgency_filter": None,
    "show_body": True,
}


def _load_config() -> Config:
    """Read ~/.config/herald/config.toml if it exists, merge over defaults."""
    config = dict(_CONFIG_DEFAULTS)
    config_path = Path.home() / ".config" / "herald" / "config.toml"

    if not config_path.is_file():
        return config  # type: ignore[return-value]

    try:
        with open(config_path, "rb") as f:
            user_config = tomllib.load(f)

        for key in _CONFIG_DEFAULTS:
            if key in user_config:
                config[key] = user_config[key]
    except Exception:
        log.exception("Failed to read config from %s, using defaults", config_path)

    return config  # type: ignore[return-value]


def _user_dir() -> Path:
    """Return the current user's herald directory, or exit if missing."""
    name = pwd.getpwuid(os.getuid()).pw_name
    d = BASE_DIR / name
    if not d.is_dir():
        log.error("Herald directory does not exist: %s", d)
        log.error("No notifications have been sent to this user yet.")
        sys.exit(1)
    return d


def _parse_notification(path: Path) -> dict[str, Any] | None:
    """Read and validate a notification JSON file. Returns dict or None."""
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        log.warning("Could not parse notification: %s", path)
        return None

    if not isinstance(data, dict) or "title" not in data:
        log.warning("Invalid notification (missing title): %s", path)
        return None

    data.setdefault("body", "")
    data.setdefault("icon", "")
    data.setdefault("timeout", -1)
    try:
        data["urgency"] = Urgency.from_string(data.get("urgency", "normal"))
    except ValueError:
        data["urgency"] = Urgency.NORMAL

    return data


async def _send_notification(
    bus: MessageBus,
    *,
    title: str,
    body: str,
    urgency: Urgency,
    icon: str,
    timeout: int,
    config: Config,
) -> Any:
    """Send a notification via the D-Bus session bus."""
    if config.get("timeout_override") is not None:
        timeout = config["timeout_override"]

    if not config.get("show_body", True):
        body = ""

    hints = {
        "urgency": Variant("y", urgency.value),
        "desktop-entry": Variant("s", "herald"),
    }

    msg = DBusMessage(
        destination="org.freedesktop.Notifications",
        path="/org/freedesktop/Notifications",
        interface="org.freedesktop.Notifications",
        member="Notify",
        signature="susssasa{sv}i",
        body=[
            "herald",       # app_name
            0,              # replaces_id
            icon,           # app_icon
            title,          # summary
            body,           # body
            [],             # actions
            hints,          # hints
            timeout,        # expire_timeout
        ],
    )

    reply = await bus.call(msg)
    if reply.message_type == MessageType.ERROR:
        log.error("D-Bus notification failed: %s", reply.body)
    return reply


def _rotate_history(read_dir: Path, max_history: int) -> None:
    """Delete the oldest files in .read/ when over the limit."""
    try:
        entries = sorted(read_dir.iterdir(), key=lambda p: p.name)
    except OSError:
        return

    excess = len(entries) - max_history
    if excess <= 0:
        return

    for p in entries[:excess]:
        try:
            p.unlink()
        except OSError:
            log.warning("Could not remove old notification: %s", p.name)


async def _handle_file(
    path: Path, bus: MessageBus, read_dir: Path, config: Config
) -> None:
    """Parse a notification file, display it, and move to .read/."""
    data = _parse_notification(path)
    dest = read_dir / path.name

    if data is not None:
        urgency_filter = config.get("urgency_filter")
        if urgency_filter and data["urgency"].name.lower() not in urgency_filter:
            log.debug(
                "Filtered notification (urgency %s): %s",
                data["urgency"].name.lower(),
                path.name,
            )
        else:
            await _send_notification(
                bus,
                title=data["title"],
                body=data["body"],
                urgency=data["urgency"],
                icon=data["icon"],
                timeout=data["timeout"],
                config=config,
            )

    # Always move to .read/, even if malformed or filtered.
    try:
        shutil.move(path, dest)
    except OSError:
        log.warning("Could not move notification to .read/: %s", path.name)

    _rotate_history(read_dir, config["max_history"])


async def run() -> None:
    """Main receiver loop."""
    from herald.inotify import IN_CLOSE_WRITE, add_watch, inotify_init, read_events

    config = _load_config()
    user_d = _user_dir()
    read_dir = user_d / ".read"

    bus = await MessageBus().connect()

    fd = inotify_init()
    add_watch(fd, user_d, IN_CLOSE_WRITE)

    # Process existing unread files first.
    for p in sorted(user_d.iterdir(), key=lambda p: p.name):
        if p.name.startswith("."):
            continue
        if p.is_file():
            await _handle_file(p, bus, read_dir, config)

    # Set up the event loop to watch for new files.
    loop = asyncio.get_running_loop()
    event = asyncio.Event()

    loop.add_reader(fd, event.set)

    log.info("Watching %s for notifications", user_d)

    try:
        while True:
            await event.wait()
            event.clear()

            for ev in read_events(fd):
                p = user_d / ev.name
                if p.is_file():
                    await _handle_file(p, bus, read_dir, config)
    finally:
        loop.remove_reader(fd)
        os.close(fd)
        bus.disconnect()
