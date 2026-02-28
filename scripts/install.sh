#!/bin/bash
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Error: must be run as root." >&2
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 not found." >&2
    exit 1
fi

py_version=$(python3 -c "import sys; v=sys.version_info; print(f'{v.major}.{v.minor}')")
py_major=$(echo "$py_version" | cut -d. -f1)
py_minor=$(echo "$py_version" | cut -d. -f2)

if [ "$py_major" -lt 3 ] || { [ "$py_major" -eq 3 ] && [ "$py_minor" -lt 11 ]; }; then
    echo "Error: Python 3.11+ required, found $py_version." >&2
    exit 1
fi

if ! command -v notify-send >/dev/null 2>&1; then
    echo "Error: notify-send not found. Install libnotify." >&2
    exit 1
fi

script_dir=$(cd "$(dirname "$0")" && pwd)
repo_dir=$(cd "$script_dir/.." && pwd)

site_packages=$(python3 -c "import sysconfig; print(sysconfig.get_path('purelib'))")

echo "Installing herald package to ${site_packages}/herald/ ..."
mkdir -p "$site_packages"
cp -r "${repo_dir}/src/herald" "${site_packages}/herald"

echo "Installing entry point to /usr/local/bin/herald ..."
cat > /usr/local/bin/herald <<'WRAPPER'
#!/usr/bin/env python3
from herald.cli import main
main()
WRAPPER
chmod 0755 /usr/local/bin/herald

echo "Creating /var/lib/herald/ ..."
mkdir -p /var/lib/herald

echo "Installing autostart entry to /etc/xdg/autostart/ ..."
mkdir -p /etc/xdg/autostart
cp "${repo_dir}/data/herald-receiver.desktop" /etc/xdg/autostart/

if [ -n "${SUDO_USER:-}" ]; then
    echo "Sending welcome notification to ${SUDO_USER}..."
    herald send "Herald is up and running" \
        "If you see this, notifications are working." \
        --users "$SUDO_USER"
fi

echo "Done. Log out and back in to start the receiver, or run: herald receive &"
