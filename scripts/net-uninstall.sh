#!/bin/bash
set -eu

REPO="https://github.com/0443n/herald.git"

if [ "$(id -u)" -ne 0 ]; then
    echo "Error: must be run as root (try: curl ... | sudo bash)." >&2
    exit 1
fi

if ! command -v git >/dev/null 2>&1; then
    echo "Error: git not found." >&2
    exit 1
fi

tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

echo "Cloning herald..."
git clone --quiet --depth 1 "$REPO" "$tmpdir/herald"

"$tmpdir/herald/scripts/uninstall.sh" "$@"
