# herald

A herald announces things on behalf of the crown. This one announces things on behalf of root.

Secure desktop notifications from root to user sessions on Linux, using filesystem IPC.

## The problem

System daemons, monitoring agents, backup tools, and cron jobs run as root and regularly
detect events that a specific user needs to know about. The natural way to communicate
these is a desktop notification.

But desktop notifications live on the session bus -- a per-user D-Bus instance that root
has no direct access to. The obvious workarounds all have problems:

- `notify-send` as root requires knowing `DBUS_SESSION_BUS_ADDRESS`, `su`/`sudo`
  gymnastics, and breaks across display managers and Wayland sessions.
- D-Bus system bus signals are broadcast -- any user can subscribe. No kernel-level
  enforcement of who receives what.
- Named pipes and Unix sockets require managing lifecycle, framing, and connection state,
  and don't persist messages for offline users.

## How it works

Root writes JSON notification files into per-user directories under `/var/lib/herald/`.
A user-session daemon watches its directory via inotify and displays them as desktop
notifications through the freedesktop D-Bus interface.

Security is enforced by the kernel: each user directory is mode `0700`, owned by that
user. No other non-root user can read, list, or access anything inside. That is the
entire security model.

```
/var/lib/herald/
+-- alice/                               # 0700 alice:alice
|   +-- 1740700800.000000_a3f1.json      # unread
|   +-- 1740700823.456789_b2e4.json      # unread
|   +-- .read/                           # 0700 alice:alice
|       +-- 1740600000.000000_c5d7.json  # read (history)
+-- bob/
    +-- ...
```

Notifications sent while a user is logged out are delivered when they next log in.
Read notifications are moved to `.read/` for history, with automatic rotation.

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

Requires Python 3.11+ and Linux.

The only external dependency is `dbus-fast`. On Debian bookworm:

```
sudo apt install python3-dbus-fast
```

Install herald:

```
git clone <repo-url> herald && cd herald
sudo pip install .
```

Create the base directory:

```
sudo mkdir -p /var/lib/herald
```

Set up the receiver to start on graphical login:

```
cp data/herald-receiver.desktop ~/.config/autostart/
```

Or system-wide for all users:

```
sudo cp data/herald-receiver.desktop /etc/xdg/autostart/
```

Log out and back in, or start it manually for this session:

```
herald receive &
```

TODO: autoinstall script that does all of the above.

## Usage

Sending requires root.

```
# Send to specific users
sudo herald send "Backup complete" --users alice bob

# Send to members of a Unix group
sudo herald send "Patch available" --urgency low --group sudo

# Send to all human users (UID >= 1000)
sudo herald send "Disk warning" "/home is at 92%" --urgency critical --everyone

# Full options
sudo herald send "Title" "Body" \
    --urgency critical \
    --icon drive-harddisk \
    --timeout 0 \
    --users alice
```

## User configuration

Optional. Create `~/.config/herald/config.toml`:

```toml
max_history = 100         # max read notifications to keep (default: 100)
show_body = true          # show notification body text (default: true)
# timeout_override = 0   # force persistent notifications
# urgency_filter = ["critical"]  # only show certain urgency levels
```

## Design notes

**Filesystem as transport.** No sockets, no protocol, no daemon on the sender side. A
syslog-ng action or cron job can call `herald send` directly.

**Atomic delivery.** Notification files are written and `chown`'d to the target user.
The receiver sees complete files or nothing.

**Offline support.** Unread files sit in the user directory until the receiver starts.
On login, existing files are processed before watching for new ones.

**History.** Read notifications are moved to `.read/`, not deleted. Rotation keeps the
directory bounded.

**No compiled dependencies.** `dbus-fast` is pure Python. The inotify wrapper uses
ctypes against libc. Everything else is stdlib.
