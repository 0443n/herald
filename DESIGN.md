# Secure root-to-user desktop notifications via filesystem IPC

## Context

System daemons (log processors, monitoring agents, backup tools) run as root and regularly detect events that a specific user needs to know about — disk warnings, failed services, security alerts, completed jobs. The natural way to communicate these is a desktop notification.

But on Linux, desktop notifications live on the **session bus** — a per-user D-Bus instance that root has no direct access to. There is no built-in, secure mechanism for a root process to send a targeted desktop notification to a specific user's session.

## Problem

The obvious approaches all fall short:

**`notify-send` as root.** Requires knowing the user's `DBUS_SESSION_BUS_ADDRESS` and running under their UID. Fragile, requires `su`/`sudo` gymnastics, breaks across display managers and Wayland sessions.

**D-Bus system bus signals.** Signals on the system bus are broadcast — any user can subscribe to any signal path. A notification intended for `alice` can be read by `bob` simply by adding a match rule. There is no kernel-level enforcement of who receives a signal. This is fundamentally insecure for targeted or sensitive notifications.

**D-Bus system bus directed messages.** Requires the receiver to register a well-known name, a D-Bus policy file to control access, and a mechanism to route messages to the correct user's bus instance. Complex, still doesn't provide per-user confidentiality without significant infrastructure.

**Named pipes / Unix sockets.** Workable, but require managing socket lifecycle, connection state, message framing, and don't provide persistence (offline users miss notifications).

### Requirements

1. **Security** — a user must only be able to read their own notifications. Enforced by the kernel, not by application logic.
2. **Atomic delivery** — no partial reads, no corruption from concurrent writes.
3. **Offline support** — notifications sent while a user is logged out must be delivered when they log in.
4. **History** — read notifications should be preserved for later review.
5. **Simplicity** — minimal dependencies, easy to debug, no registration or handshake protocol.

## Solution

Use the **filesystem as a message transport**. Root writes notification files into per-user directories. A user-session daemon watches its directory via inotify and displays notifications on the session bus.

### Directory layout

```
/var/lib/<project>/
└── <username>/                             # 0700 <username>:<username>
    ├── 1740700800.000000_a3f1.json         # unread notification
    ├── 1740700823.456789_b2e4.json         # unread notification
    └── .read/                              # 0700 <username>:<username>
        └── 1740600000.000000_c5d7.json     # read notification (history)
```

**Permissions.** Each user directory is owned by that user with mode `0700`. The kernel enforces that no other non-root user can read, list, or access anything inside. This is the entire security model — no application-level access control needed.

**File ownership.** Notification files are also `chown`'d to the target user after writing, so the receiver (running as that user) can move them to `.read/`.

**Directory creation.** Root creates user directories on first send. If a user doesn't exist in the system, their directory is never created.

### Notification file format

Each notification is a single JSON file:

```json
{
    "title": "Disk usage warning",
    "body": "/home is at 92%",
    "urgency": "critical",
    "icon": "drive-harddisk",
    "timeout": 0
}
```

Fields map directly to the [Desktop Notifications Specification](https://specifications.freedesktop.org/notification-spec/latest/):

| Field     | Type   | Description                                                     |
|-----------|--------|-----------------------------------------------------------------|
| `title`   | string | Notification summary                                            |
| `body`    | string | Notification body (can be empty)                                |
| `urgency` | string | `low`, `normal`, or `critical` — maps to the urgency hint byte  |
| `icon`    | string | FreeDesktop icon name (e.g. `dialog-warning`, `security-high`)  |
| `timeout` | int    | Display timeout in ms (`0` = persistent until dismissed)         |

### Filename convention

```
<unix_timestamp_with_microseconds>_<4_hex_random>.json
```

Example: `1740700800.123456_a3f1.json`

The timestamp prefix provides chronological ordering. The random suffix prevents collisions when multiple notifications are sent in the same microsecond. Together they produce a unique, sortable filename without requiring any state or coordination.

### Sender flow

The sender runs as root and is synchronous (just file I/O):

1. **Resolve recipients.** Accept target users by username list, group membership, admin group membership, or broadcast to all human users. Resolution uses the system user/group databases (`/etc/passwd`, `/etc/group`).
2. **Ensure directory.** Create `/var/lib/<project>/<username>/` and `.read/` if they don't exist, set ownership and `0700` permissions.
3. **Atomic write.** For each target user:
   - Write to a temporary file in the user's directory (`.tmp` suffix)
   - `fsync` the file descriptor
   - `fchown` to the target user
   - `rename()` the temp file to the final filename

The `rename()` is atomic on all Linux filesystems — the receiver either sees the complete file or nothing. There is no window where a partial file is visible under the final name.

### Receiver flow

The receiver runs as a regular user in their session and is asynchronous (event loop):

1. **Startup.** Process any existing unread files (notifications sent while the receiver wasn't running).
2. **Watch.** Register an inotify watch on the user's directory for `IN_MOVED_TO` events — this fires exactly when `rename()` completes, ensuring the file is always complete.
3. **Handle.** On each event:
   - Read and parse the JSON file
   - Send a desktop notification via the D-Bus session bus (`org.freedesktop.Notifications.Notify`)
   - Move the file to `.read/`
4. **History rotation.** Enforce a maximum number of files in `.read/`, deleting the oldest when exceeded.

### Recipient targeting

The sender supports four targeting modes:

| Mode        | Behavior                                                              |
|-------------|-----------------------------------------------------------------------|
| **Everyone**    | All human users (UID >= 1000 with a login shell) + any existing user dirs |
| **Admins only** | Members of admin groups (e.g. `sudo`, `wheel`)                        |
| **Users**       | Explicit list of usernames                                            |
| **Groups**      | All members of specified Unix groups                                  |

Targeting is resolved entirely on the sender side. The receiver has no filtering logic — if a file appears in your directory, it's for you.

## Notes

**Why inotify `IN_MOVED_TO` and not `IN_CREATE`.** `IN_CREATE` fires when the file is created, but the content may not be fully written yet. `IN_MOVED_TO` fires on `rename()`, which is atomic — the file is guaranteed complete.

**Why not a database.** SQLite or similar would require locking, schema management, and shared file access. Individual JSON files are simpler, debuggable with `cat`, and the filesystem provides the concurrency model for free.

**Why `/var/lib/`.** FHS-compliant location for variable application state data. Survives reboots, appropriate for persistent per-user data managed by a system service.

**History.** Moving read files to `.read/` rather than deleting them gives users notification history at zero cost. The rotation limit prevents unbounded growth.

**No daemon on the sender side.** The sender is a simple function call or CLI invocation — no long-running process, no socket to manage, no protocol negotiation. A syslog-ng action or cron job can call it directly.

## Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Sender file I/O | Python stdlib (`os`, `json`, `tempfile`, `pwd`, `grp`) | No dependencies needed for atomic file writes and user/group resolution |
| Receiver inotify | `inotify_simple` | Minimal Python wrapper around Linux `inotify(7)`, exposes the raw fd for integration with any event loop |
| Receiver desktop notifications | `dbus_fast` | Pure-Python async D-Bus client, no compiled dependencies (`dbus-python` requires `libdbus` and GLib) |
| Receiver event loop | `asyncio` | stdlib, integrates with `inotify_simple` fd via `add_reader()` and with `dbus_fast` natively |
