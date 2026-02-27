"""Receiver: watches user directory via inotify, shows desktop notifications."""

import asyncio
import json
import logging
import os
import pwd
import shutil
import sys

from inotify_simple import INotify, flags as iflags

from dbus_fast import Message as DBusMessage, Variant
from dbus_fast.aio import MessageBus
from dbus_fast.constants import MessageType

from herald import BASE_DIR, VALID_URGENCY

log = logging.getLogger(__name__)

_CONFIG_DEFAULTS = {
    "max_history": 100,
    "timeout_override": None,
    "urgency_filter": None,
    "show_body": True,
}

_URGENCY_BYTE = {"low": 0, "normal": 1, "critical": 2}


def _load_config():
    """Read ~/.config/herald/config.toml if it exists, merge over defaults."""
    config = dict(_CONFIG_DEFAULTS)
    config_path = os.path.expanduser("~/.config/herald/config.toml")

    if not os.path.isfile(config_path):
        return config

    try:
        # tomllib is stdlib in 3.11+, tomli is the backport.
        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib

        with open(config_path, "rb") as f:
            user_config = tomllib.load(f)

        for key in _CONFIG_DEFAULTS:
            if key in user_config:
                config[key] = user_config[key]
    except Exception:
        log.exception("Failed to read config from %s, using defaults", config_path)

    return config


def _user_dir():
    """Return the current user's herald directory, or exit if missing."""
    name = pwd.getpwuid(os.getuid()).pw_name
    d = os.path.join(BASE_DIR, name)
    if not os.path.isdir(d):
        log.error("Herald directory does not exist: %s", d)
        log.error("No notifications have been sent to this user yet.")
        sys.exit(1)
    return d


def _parse_notification(path):
    """Read and validate a notification JSON file. Returns dict or None."""
    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        log.warning("Could not parse notification: %s", path)
        return None

    if not isinstance(data, dict) or "title" not in data:
        log.warning("Invalid notification (missing title): %s", path)
        return None

    data.setdefault("body", "")
    data.setdefault("icon", "")
    data.setdefault("timeout", -1)
    if data.get("urgency") not in VALID_URGENCY:
        data["urgency"] = "normal"

    return data


async def _send_notification(bus, *, title, body, urgency, icon, timeout, config):
    """Send a notification via the D-Bus session bus."""
    if config.get("timeout_override") is not None:
        timeout = config["timeout_override"]

    if not config.get("show_body", True):
        body = ""

    hints = {
        "urgency": Variant("y", _URGENCY_BYTE.get(urgency, 1)),
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


def _rotate_history(read_dir, max_history):
    """Delete the oldest files in .read/ when over the limit."""
    try:
        entries = sorted(os.listdir(read_dir))
    except OSError:
        return

    excess = len(entries) - max_history
    if excess <= 0:
        return

    for name in entries[:excess]:
        try:
            os.remove(os.path.join(read_dir, name))
        except OSError:
            log.warning("Could not remove old notification: %s", name)


async def _handle_file(path, bus, read_dir, config):
    """Parse a notification file, display it, and move to .read/."""
    data = _parse_notification(path)
    filename = os.path.basename(path)
    dest = os.path.join(read_dir, filename)

    if data is not None:
        # Apply urgency filter.
        urgency_filter = config.get("urgency_filter")
        if urgency_filter and data["urgency"] not in urgency_filter:
            log.debug("Filtered notification (urgency %s): %s",
                      data["urgency"], filename)
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
        log.warning("Could not move notification to .read/: %s", filename)

    _rotate_history(read_dir, config["max_history"])


async def run():
    """Main receiver loop."""
    config = _load_config()
    user_d = _user_dir()
    read_dir = os.path.join(user_d, ".read")

    bus = await MessageBus().connect()

    inotify = INotify()
    inotify.add_watch(user_d, iflags.CLOSE_WRITE)

    # Process existing unread files first.
    for name in sorted(os.listdir(user_d)):
        if name.startswith("."):
            continue
        path = os.path.join(user_d, name)
        if os.path.isfile(path):
            await _handle_file(path, bus, read_dir, config)

    # Set up the event loop to watch for new files.
    loop = asyncio.get_running_loop()
    event = asyncio.Event()

    loop.add_reader(inotify.fd, event.set)

    log.info("Watching %s for notifications", user_d)

    try:
        while True:
            await event.wait()
            event.clear()

            for inotify_event in inotify.read():
                path = os.path.join(user_d, inotify_event.name)
                if os.path.isfile(path):
                    await _handle_file(path, bus, read_dir, config)
    finally:
        loop.remove_reader(inotify.fd)
        inotify.close()
        bus.disconnect()
