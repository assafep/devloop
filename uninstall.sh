#!/usr/bin/env bash
set -euo pipefail
name="${1:-jobstein}"
[[ "$name" =~ ^[a-z][a-z0-9-]*$ ]]
systemctl --user disable --now "devloop@$name.service" || true
printf 'Service disabled for %s. Config, checkout and logs retained under ~/.local/state/devloop.\n' "$name"
