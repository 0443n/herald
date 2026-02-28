#!/bin/bash
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Error: must be run as root." >&2
    exit 1
fi

purge=0
for arg in "$@"; do
    case "$arg" in
        --purge) purge=1 ;;
        *) echo "Unknown option: $arg" >&2; exit 1 ;;
    esac
done

echo "Removing /usr/local/bin/herald ..."
rm -f /usr/local/bin/herald

if command -v python3 >/dev/null 2>&1; then
    pkg_dir=$(python3 -c "import sysconfig; print(sysconfig.get_path('purelib'))")/herald
    echo "Removing ${pkg_dir}/ ..."
    rm -rf "$pkg_dir"
else
    echo "Warning: python3 not found, skipping package removal."
fi

echo "Removing /etc/xdg/autostart/herald-receiver.desktop ..."
rm -f /etc/xdg/autostart/herald-receiver.desktop

if [ "$purge" -eq 1 ]; then
    echo "Removing /var/lib/herald/ ..."
    rm -rf /var/lib/herald
else
    if [ -d /var/lib/herald ]; then
        printf "Remove /var/lib/herald/? [y/N] "
        read -r answer < /dev/tty
        case "$answer" in
            [yY]*) rm -rf /var/lib/herald; echo "Removed." ;;
            *) echo "Kept /var/lib/herald/." ;;
        esac
    fi
fi

echo "Done. Per-user ~/.config/herald/ directories were not touched."
