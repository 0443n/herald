# herald

A herald announces things on behalf of the crown. This one announces things on behalf of root.

Secure desktop notifications from root to user sessions on Linux, using filesystem IPC.

Root writes notification files to per-user directories (`/var/lib/herald/<username>/`, mode `0700`). A user-session daemon watches via inotify and displays them as desktop notifications. Security is enforced by the kernel -- no user can read another user's notifications.

See [DESIGN.md](DESIGN.md) for the full architecture.
