#!/usr/bin/env python3
"""Herald Python API usage examples. Must be run as root."""

from herald import Urgency
from herald.sender import resolve_recipients, send

# Resolve target users by name
recipients = resolve_recipients(users=["alice", "bob"])

# resolve_recipients() also accepts groups=["sudo"] or everyone=True.
# Only one targeting mode may be specified at a time.

# Send a notification to the resolved recipients
count = send(
    title="Backup complete",
    body="/home backed up successfully",
    urgency=Urgency.NORMAL,
    recipients=recipients,
)

# send() returns the number of successful deliveries.
# Optional parameters: body, urgency, icon, timeout.
print(f"Delivered to {count} user(s)")
