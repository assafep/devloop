#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ required"'
install -d -m 700 "$HOME/.local/bin" "$HOME/.config/systemd/user"
install -m 700 devloop.py "$HOME/.local/bin/devloop"
install -m 600 systemd/devloop@.service "$HOME/.config/systemd/user/devloop@.service"
if systemctl --user daemon-reload; then echo 'User service installed; not started.'; else echo 'systemd user manager unavailable; use devloop run jobstein in a terminal.'; fi
printf 'Run %s add jobstein %s/examples/jobstein.json\n' "$HOME/.local/bin/devloop" "$PWD"
