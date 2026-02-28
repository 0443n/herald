# herald

**Root-to-desktop notifications for Linux.**

System daemons, cron jobs, and scripts running as root can send desktop notifications
to specific users -- no D-Bus gymnastics, no sockets, no dependencies beyond Python
and `notify-send`.

**At a glance:**

- Root writes JSON files; a per-user receiver displays them via `notify-send`
- Targets users by name, Unix group, or broadcast to all human accounts
- Messages queue on disk and deliver when the user next logs in
- Security enforced by the kernel: per-user directories, mode `0700`
- No external Python dependencies; inotify via ctypes, everything else is stdlib

```
sudo herald send "Backup complete" --users alice
```

## The problem

System daemons, monitoring agents, backup tools, and cron jobs run as root and regularly
detect events that a specific user needs to know about. The natural way to communicate
these is a desktop notification.

But desktop notifications live on the session bus -- a per-user D-Bus instance that root
has no direct access to. The obvious workarounds all have problems:

- Running `notify-send` as root requires knowing `DBUS_SESSION_BUS_ADDRESS`, `su`/`sudo`
  gymnastics, and breaks across display managers and Wayland sessions.
- D-Bus system bus signals are broadcast -- any user can subscribe. No kernel-level
  enforcement of who receives what.
- Named pipes and Unix sockets require managing lifecycle, framing, and connection state,
  and don't persist messages for offline users.

## How it works

Root writes JSON notification files into per-user directories under `/var/lib/herald/`.
A user-session daemon watches its directory via inotify and displays them via
`notify-send`, which runs as the user and has normal access to the session bus.

Security is enforced by the kernel: each user directory is mode `0700`, owned by that
user. No other non-root user can read, list, or access anything inside. That is the
entire security model.

```
/var/lib/herald/
+-- alice/                               # 0700 alice:alice
|   +-- 1740700800.000000_a3f1.json      # pending
|   +-- 1740700823.456789_b2e4.json      # pending
+-- bob/
    +-- ...
```

Notifications sent while a user is logged out are delivered when they next log in.
Files are deleted after display.

### Notification format

Each file maps directly to the
[Desktop Notifications Specification](https://specifications.freedesktop.org/notification-spec/latest/):

```json
{
    "title": "Disk usage warning",
    "body": "/home is at 92%",
    "urgency": "critical",
    "icon": "drive-harddisk",
    "timeout": 0
}
```

| Field     | Type   | Description                                                    |
|-----------|--------|----------------------------------------------------------------|
| `title`   | string | Notification summary (required)                                |
| `body`    | string | Notification body (default: empty)                             |
| `urgency` | string | `low`, `normal`, or `critical` (default: `normal`)             |
| `icon`    | string | FreeDesktop icon name (default: empty)                         |
| `timeout` | int    | Display timeout in ms; `0` = persistent, `-1` = server default |

## Installation

Requires Python 3.11+ and Linux. No external Python dependencies.

### Runtime dependencies

`notify-send` from `libnotify` is the only runtime dependency outside of Python stdlib.
It is present by default on all major desktop Linux distributions:

| Distro        | Package          |
|---------------|------------------|
| Debian/Ubuntu | `libnotify-bin`  |
| Arch          | `libnotify`      |
| Fedora        | `libnotify`      |
| openSUSE      | `libnotify-tools`|

Any system running a desktop environment (GNOME, KDE, XFCE, etc.) will already have it
installed as a dependency.

### Setup

```
curl -fsSL https://raw.githubusercontent.com/0443n/herald/main/scripts/net-install.sh | sudo bash
```

Or from a clone:

```
git clone https://github.com/0443n/herald.git && cd herald
sudo ./scripts/install.sh
```

Log out and back in, or start the receiver manually for this session:

```
herald receive &
```

### Manual setup

If you prefer not to use the install script:

1. Copy `src/herald/` to your Python dist-packages directory.
2. Create an entry point at `/usr/local/bin/herald` that calls `herald.cli:main`.
3. Create `/var/lib/herald/`.
4. Copy `data/herald-receiver.desktop` to `/etc/xdg/autostart/` (system-wide) or
   `~/.config/autostart/` (single user).

## Uninstall

```
curl -fsSL https://raw.githubusercontent.com/0443n/herald/main/scripts/net-uninstall.sh | sudo bash
```

Or from a clone:

```
sudo ./scripts/uninstall.sh
```

To skip the prompt and also remove `/var/lib/herald/`, pass `--purge`:

```
sudo ./scripts/uninstall.sh --purge
```

Per-user `~/.config/herald/` directories are not touched.

## Usage

Sending requires root.

```
sudo herald send "Backup complete" --users alice bob
sudo herald send "Disk warning" "/home is at 92%" --urgency critical --everyone
```

See [examples/cli.sh](examples/cli.sh) for the full set of CLI examples.

### Python API

Herald can be used as a library from Python scripts running as root:

```python
from herald.sender import resolve_recipients, send
from herald import Urgency

recipients = resolve_recipients(users=["alice", "bob"])
send(title="Backup complete", urgency=Urgency.NORMAL, recipients=recipients)
```

See [examples/python_api.py](examples/python_api.py) for a complete example with all
options. `resolve_recipients()` accepts `users`, `groups`, or `everyone` (one at a
time). `send()` returns the number of successful deliveries.

## User configuration

Optional. Create `~/.config/herald/config.toml`:

```toml
show_body = true          # show notification body text (default: true)
# timeout_override = 0   # force persistent notifications
# urgency_filter = ["critical"]  # only show certain urgency levels
```

## TODO

- Bash autocompletion (subcommands, flags, urgency values, user/group completion)

## Design notes

**Filesystem as transport.** No sockets, no protocol, no daemon on the sender side. A
syslog-ng action or cron job can call `herald send` directly.

**Atomic delivery.** Notification files are written and `chown`'d to the target user.
The receiver sees complete files or nothing.

**Offline support.** Unread files sit in the user directory until the receiver starts.
On login, existing files are processed before watching for new ones. If the user
directory does not exist yet (root has never sent to this user), the receiver watches
the base directory via inotify and proceeds as soon as it appears.

**No history.** Notification files are deleted after display. Herald is a delivery
mechanism, not a log viewer.

**No Python dependencies.** The inotify wrapper uses ctypes against libc. Notifications
are sent via `notify-send`. Everything else is stdlib.
