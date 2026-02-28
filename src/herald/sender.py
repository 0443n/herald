"""Sender: root writes notification files into per-user directories."""

import grp
import json
import logging
import pwd
import shutil
import stat
from pathlib import Path

from herald import BASE_DIR, Urgency, make_filename

log = logging.getLogger(__name__)


def resolve_recipients(
    *,
    users: list[str] | None = None,
    groups: list[str] | None = None,
    everyone: bool = False,
) -> list[pwd.struct_passwd]:
    """Resolve targeting arguments to a list of pwd.struct_passwd entries.

    Exactly one of users, groups, or everyone must be specified.
    Returns a deduplicated list. Raises ValueError if the result is empty
    or if conflicting modes are given.
    """
    modes = sum([bool(users), bool(groups), everyone])
    if modes == 0:
        raise ValueError("No targeting mode specified")
    if modes > 1:
        raise ValueError("Only one targeting mode may be used at a time")

    seen: dict[str, pwd.struct_passwd] = {}

    if users:
        for name in users:
            try:
                pw = pwd.getpwnam(name)
            except KeyError:
                log.warning("Unknown user: %s (skipping)", name)
                continue
            seen.setdefault(pw.pw_name, pw)

    elif groups:
        for group_name in groups:
            try:
                gr = grp.getgrnam(group_name)
            except KeyError:
                log.warning("Unknown group: %s (skipping)", group_name)
                continue
            for member_name in gr.gr_mem:
                try:
                    pw = pwd.getpwnam(member_name)
                except KeyError:
                    log.warning(
                        "Unknown user in group %s: %s (skipping)",
                        group_name,
                        member_name,
                    )
                    continue
                seen.setdefault(pw.pw_name, pw)

    elif everyone:
        for pw in pwd.getpwall():
            if pw.pw_uid >= 1000:
                seen.setdefault(pw.pw_name, pw)
        if BASE_DIR.is_dir():
            for entry in BASE_DIR.iterdir():
                if entry.name.startswith("."):
                    continue
                try:
                    pw = pwd.getpwnam(entry.name)
                except KeyError:
                    continue
                seen.setdefault(pw.pw_name, pw)

    result = list(seen.values())
    if not result:
        raise ValueError("No valid recipients found")
    return result


def _ensure_dir(pw: pwd.struct_passwd) -> Path:
    """Create the user's notification directory and .read/ subdirectory."""
    user_dir = BASE_DIR / pw.pw_name
    read_dir = user_dir / ".read"

    for d in (user_dir, read_dir):
        d.mkdir(parents=True, exist_ok=True)
        shutil.chown(d, pw.pw_uid, pw.pw_gid)
        d.chmod(stat.S_IRWXU)  # 0700

    return user_dir


def send(
    *,
    title: str,
    body: str = "",
    urgency: Urgency = Urgency.NORMAL,
    icon: str = "",
    timeout: int = -1,
    recipients: list[pwd.struct_passwd],
) -> int:
    """Write a notification file to each recipient's directory.

    Returns the number of successful writes.
    """
    payload = json.dumps({
        "title": title,
        "body": body,
        "urgency": urgency.name.lower(),
        "icon": icon,
        "timeout": timeout,
    })

    count = 0
    for pw in recipients:
        try:
            user_dir = _ensure_dir(pw)
            path = user_dir / make_filename()
            path.write_text(payload)
            shutil.chown(path, pw.pw_uid, pw.pw_gid)
            count += 1
        except OSError:
            log.exception("Failed to send notification to %s", pw.pw_name)

    return count
