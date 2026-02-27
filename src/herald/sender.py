"""Sender: root writes notification files into per-user directories."""

import grp
import json
import logging
import os
import pwd
import stat

from herald import BASE_DIR, VALID_URGENCY, make_filename

log = logging.getLogger(__name__)

# Shells that indicate a non-login/service account.
_NOLOGIN_SHELLS = frozenset({
    "/usr/sbin/nologin",
    "/sbin/nologin",
    "/bin/false",
    "/usr/bin/false",
})


def resolve_recipients(*, users=None, groups=None, everyone=False):
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

    seen = {}

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
                    log.warning("Unknown user in group %s: %s (skipping)",
                                group_name, member_name)
                    continue
                seen.setdefault(pw.pw_name, pw)

    elif everyone:
        # All human users: UID >= 1000 with a login shell.
        for pw in pwd.getpwall():
            if pw.pw_uid >= 1000 and pw.pw_shell not in _NOLOGIN_SHELLS:
                seen.setdefault(pw.pw_name, pw)
        # Union with any existing user dirs in BASE_DIR.
        if os.path.isdir(BASE_DIR):
            for name in os.listdir(BASE_DIR):
                if name.startswith("."):
                    continue
                try:
                    pw = pwd.getpwnam(name)
                except KeyError:
                    continue
                seen.setdefault(pw.pw_name, pw)

    result = list(seen.values())
    if not result:
        raise ValueError("No valid recipients found")
    return result


def _ensure_dir(pw):
    """Create the user's notification directory and .read/ subdirectory."""
    user_dir = os.path.join(BASE_DIR, pw.pw_name)
    read_dir = os.path.join(user_dir, ".read")

    for d in (user_dir, read_dir):
        os.makedirs(d, exist_ok=True)
        os.chown(d, pw.pw_uid, pw.pw_gid)
        os.chmod(d, stat.S_IRWXU)  # 0700

    return user_dir


def send(*, title, body="", urgency="normal", icon="", timeout=-1, recipients):
    """Write a notification file to each recipient's directory.

    Returns the number of successful writes.
    """
    if urgency not in VALID_URGENCY:
        raise ValueError(f"Invalid urgency: {urgency!r} (must be one of {VALID_URGENCY})")

    payload = json.dumps({
        "title": title,
        "body": body,
        "urgency": urgency,
        "icon": icon,
        "timeout": timeout,
    })

    count = 0
    for pw in recipients:
        try:
            user_dir = _ensure_dir(pw)
            path = os.path.join(user_dir, make_filename())
            with open(path, "w") as f:
                f.write(payload)
            os.chown(path, pw.pw_uid, pw.pw_gid)
            count += 1
        except OSError:
            log.exception("Failed to send notification to %s", pw.pw_name)

    return count
