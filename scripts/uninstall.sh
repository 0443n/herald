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

py_version=$(python3 -c "import sys; v=sys.version_info; print(f'{v.major}.{v.minor}')" 2>/dev/null || true)

echo "Removing /usr/local/bin/herald ..."
rm -f /usr/local/bin/herald

if [ -n "$py_version" ]; then
    pkg_dir="/usr/local/lib/python${py_version}/dist-packages/herald"
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
        read -r answer
        case "$answer" in
            [yY]*) rm -rf /var/lib/herald; echo "Removed." ;;
            *) echo "Kept /var/lib/herald/." ;;
        esac
    fi
fi

echo "Done. Per-user ~/.config/herald/ directories were not touched."
