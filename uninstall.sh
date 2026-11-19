#!/usr/bin/env bash
set -euo pipefail
name="${1:-jobstein}"
if [[ $# -gt 1 || ! "$name" =~ ^[a-z][a-z0-9-]{0,50}$ ]]; then
    printf 'Usage: %s [PROJECT_NAME]\n' "$0" >&2
    exit 2
fi
systemctl --user disable --now "devloop@$name.service"
printf 'Service disabled for %s. Project files and state were preserved.\n' "$name"
