#!/usr/bin/env bash
set -euo pipefail
umask 077
install_service=true
case $#:$* in
    0:) ;;
    1:--no-service) install_service=false ;;
    *) printf 'Usage: %s [--no-service]\n' "$0" >&2; exit 2 ;;
esac
cd "$(dirname "$0")"
python3 -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ required"'

install_file() (
    target="$2"
    temporary=$(mktemp -- "$target.tmp.XXXXXXXX")
    trap 'rm -f -- "$temporary"' EXIT
    install -m "$3" -- "$1" "$temporary"
    mv -fT -- "$temporary" "$target"
)

bin_dir="$HOME/.local/bin"
mkdir -p -- "$bin_dir"
install_file devloop.py "$bin_dir/devloop" 700
if "$install_service"; then
    config_home="$HOME/.config"
    if [[ ${XDG_CONFIG_HOME:-} == /* ]]; then
        config_home="$XDG_CONFIG_HOME"
    fi
    unit_dir="$config_home/systemd/user"
    mkdir -p -- "$unit_dir"
    install_file systemd/devloop@.service "$unit_dir/devloop@.service" 600
    if command -v systemctl >/dev/null && systemctl --user daemon-reload; then
        printf 'User service template installed at %s. Start it explicitly when ready.\n' "$unit_dir"
    else
        printf 'User service template copied to %s, but daemon-reload did not complete. Use devloop run in a terminal.\n' "$unit_dir" >&2
    fi
fi
printf 'Run %q add jobstein %q\n' "$bin_dir/devloop" "$PWD/examples/jobstein.json"
