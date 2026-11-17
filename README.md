# DevLoop

A local, reusable Codex development loop for Linux/WSL. Initial prototype; use review-only mode until the security and live integration checks are complete.

## Quick start

Requires Python 3.10+, Git, GitHub CLI, authenticated Codex CLI and the target project's build tools. Use a dedicated isolated Linux environment and repository-scoped credentials.

```sh
bash install.sh
export PATH="$HOME/.local/bin:$PATH"
devloop add jobstein examples/jobstein.json
devloop doctor jobstein
devloop run-once jobstein
devloop status jobstein
```

By default the prototype preserves staged changes for manual review and pauses. It does not automatically publish. Review the dedicated checkout under ~/.local/state/devloop/jobstein/checkout. Do not enable auto_push before a successful controlled trial and security review. Pause the competing ChatGPT Jobstein automation before enabling local publication.

## Commands
add NAME CONFIG; configure NAME (prints config path); doctor NAME; run-once NAME; run NAME; start/stop/restart NAME (systemd user service); pause/resume NAME; status NAME; logs NAME [--follow]; history NAME.

The Jobstein example uses 120 seconds between iterations and polls exact-commit CI every 60 seconds. CI wait is bounded. Local tests must pass before publication. Dirty, divergent or unpublished work is preserved for review. Only non-force pushes are supported.

## Safety and limitations
This is an initial prototype, not a complete security boundary. Environment variable filtering and path allowlists do not prevent all credential exposure or malicious generated code; the local build command executes code. Keep auto_push disabled. Use isolated credentials and filesystem, never real applicant data. No live Codex or WSL service test has been completed. The installer does not start the service. The uninstall script only disables the named service and preserves state.

Run offline tests: `python3 -m unittest discover -s tests -v`. See AGENTS.md and BACKLOG.md for continuation.
