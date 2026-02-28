"""Receiver: watches user directory via inotify, shows desktop notifications."""

import asyncio
import json
import logging
import os
import pwd
import signal
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any, TypedDict

from herald import BASE_DIR, Urgency

log = logging.getLogger(__name__)


class Config(TypedDict):
    timeout_override: int | None
    urgency_filter: list[str] | None
    show_body: bool


_CONFIG_DEFAULTS: Config = {
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


class Receiver:
    """Watches a user's herald directory and displays notifications."""

    def __init__(self) -> None:
        self.config = _load_config()
        name = pwd.getpwuid(os.getuid()).pw_name
        self.user_dir = BASE_DIR / name
        self.fd: int | None = None
        self._shutdown = asyncio.Event()

    async def run(self) -> None:
        """Main lifecycle: wait for dir, process existing, watch."""
        from herald.inotify import IN_CLOSE_WRITE, add_watch, inotify_init, read_events

        loop = asyncio.get_running_loop()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._shutdown.set)

        await self._wait_for_dir(loop)

        self.fd = inotify_init()
        add_watch(self.fd, self.user_dir, IN_CLOSE_WRITE)

        # Process existing unread files first.
        for p in sorted(self.user_dir.iterdir(), key=lambda p: p.name):
            if p.name.startswith("."):
                continue
            if p.is_file():
                self._handle_file(p)

        inotify_event = asyncio.Event()
        loop.add_reader(self.fd, inotify_event.set)

        log.info("Watching %s for notifications", self.user_dir)

        try:
            while not self._shutdown.is_set():
                wait_task = asyncio.ensure_future(inotify_event.wait())
                shutdown_task = asyncio.ensure_future(self._shutdown.wait())

                done, pending = await asyncio.wait(
                    {wait_task, shutdown_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()

                if self._shutdown.is_set():
                    break

                inotify_event.clear()
                for ev in read_events(self.fd):
                    p = self.user_dir / ev.name
                    if p.is_file():
                        self._handle_file(p)
        finally:
            self._stop(loop)

    async def _wait_for_dir(self, loop: asyncio.AbstractEventLoop) -> None:
        """Wait for the user directory to appear using inotify on BASE_DIR."""
        if self.user_dir.is_dir():
            return

        from herald.inotify import IN_CREATE, add_watch, inotify_init, read_events

        log.info(
            "Herald directory does not exist yet: %s (waiting for first notification)",
            self.user_dir,
        )

        wait_fd = inotify_init()
        add_watch(wait_fd, BASE_DIR, IN_CREATE)

        # Check again after setting up the watch to avoid a race.
        if self.user_dir.is_dir():
            os.close(wait_fd)
            return

        ready = asyncio.Event()
        loop.add_reader(wait_fd, ready.set)

        try:
            while not self.user_dir.is_dir():
                wait_task = asyncio.ensure_future(ready.wait())
                shutdown_task = asyncio.ensure_future(self._shutdown.wait())

                await asyncio.wait(
                    {wait_task, shutdown_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if self._shutdown.is_set():
                    sys.exit(0)

                ready.clear()
                read_events(wait_fd)  # drain the buffer
        finally:
            loop.remove_reader(wait_fd)
            os.close(wait_fd)

    def _handle_file(self, path: Path) -> None:
        """Parse a notification file, display it, and delete it."""
        data = _parse_notification(path)

        if data is not None:
            urgency_filter = self.config.get("urgency_filter")
            if urgency_filter and data["urgency"].name.lower() not in urgency_filter:
                log.debug(
                    "Filtered notification (urgency %s): %s",
                    data["urgency"].name.lower(),
                    path.name,
                )
            else:
                self._send_notification(
                    title=data["title"],
                    body=data["body"],
                    urgency=data["urgency"],
                    icon=data["icon"],
                    timeout=data["timeout"],
                )

        try:
            path.unlink()
        except OSError:
            log.warning("Could not delete notification: %s", path.name)

    def _send_notification(
        self,
        *,
        title: str,
        body: str,
        urgency: Urgency,
        icon: str,
        timeout: int,
    ) -> None:
        """Send a notification via notify-send."""
        if self.config.get("timeout_override") is not None:
            timeout = self.config["timeout_override"]

        if not self.config.get("show_body", True):
            body = ""

        cmd = [
            "notify-send",
            "--app-name=herald",
            f"--urgency={urgency.name.lower()}",
        ]

        if icon:
            cmd.append(f"--icon={icon}")

        if timeout >= 0:
            cmd.append(f"--expire-time={timeout}")

        cmd.append(title)
        if body:
            cmd.append(body)

        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            log.error(
                "notify-send failed (exit %d): %s",
                result.returncode,
                result.stderr.decode().strip(),
            )

    def _stop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Clean up resources."""
        if self.fd is not None:
            loop.remove_reader(self.fd)
            os.close(self.fd)


async def run() -> None:
    """Entry point for cli.py."""
    receiver = Receiver()
    await receiver.run()
