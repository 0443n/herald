#!/usr/bin/env bash
# Herald CLI usage examples
# All send commands require root.

# Send a simple notification to specific users
sudo herald send "Backup complete" --users alice bob

# Send to members of a Unix group
sudo herald send "Patch available" --urgency low --group sudo

# Send to all human users (UID >= 1000)
sudo herald send "Disk warning" "/home is at 92%" --urgency critical --everyone

# Full options: title, body, urgency, icon, timeout, and target user
sudo herald send "Title" "Body" \
    --urgency critical \
    --icon drive-harddisk \
    --timeout 0 \
    --users alice

# Start the receiver (normally handled by autostart on login)
herald receive &
