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

In review-only mode, DevLoop passes the verified base commit, CI result and run ID to Codex. Codex checks its local `HEAD` against that commit and uses the runner's result for the base CI gate.

## Safety and limitations
Agent and configured build/test subprocesses receive only PATH, HOME, USER, LOGNAME, LANG, LC_ALL, LC_CTYPE, TMPDIR and TERM from the runner, plus GIT_TERMINAL_PROMPT=0. Agents also receive CODEX_HOME for user-controlled Codex setup. Unknown environment variables, publication tokens, SSH agent sockets, Git configuration overrides and runtime injection variables are excluded. Build commands needing additional configuration must use a reviewed, user-controlled setup; environment inheritance is deliberately restricted. Runner-side Git/GitHub operations retain their environment for publication.

This filtering covers inherited environment variables only. HOME, CODEX_HOME, PATH executables, temporary directories and repository files can still expose credentials or execute code; Git credential helpers and configuration on disk remain accessible. It does not isolate processes from the runner's user account, filesystem or network. Use a separate account/container with restricted mounts and credentials before running untrusted code.

This is an initial prototype, not a complete security boundary. Environment variable filtering and path allowlists do not prevent all credential exposure or malicious generated code; the local build command executes code. Keep auto_push disabled. Use isolated credentials and filesystem, never real applicant data. No live Codex or WSL service test has been completed. The installer does not start the service. The uninstall script only disables the named service and preserves state.

Run offline tests: `python3 -m unittest discover -s tests -v`. See AGENTS.md and BACKLOG.md for continuation.
The integration test requires Git and runs a complete review-only iteration with temporary repositories, local clone/fetch transport and synthetic Codex/gh executables. It checks environment filtering and staged-change preservation without live credentials or service calls. It does not validate real Codex sandbox enforcement or filesystem credential isolation.
