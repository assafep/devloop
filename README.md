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
add NAME CONFIG; configure NAME (prints config path); doctor NAME; run-once NAME; run NAME; start/stop/restart NAME (systemd user service); pause/resume NAME; acknowledge NAME REVIEW_ID; status NAME; logs NAME [--follow]; history NAME.

The Jobstein example uses 120 seconds between iterations and polls exact-commit CI every 60 seconds. CI wait is bounded. Local tests must pass before publication. Dirty, divergent or unpublished work is preserved for review. Only non-force pushes are supported.

In review-only mode, DevLoop passes the verified base commit, CI result and run ID to Codex. Codex checks its local `HEAD` against that commit and uses the runner's result for the base CI gate.

When the exact base CI result is `failure`, DevLoop retrieves the failed-step log and gives Codex at most 200 lines and 12,000 characters after removing common bearer tokens, API keys, passwords and GitHub/AWS token forms. The log is delimited as untrusted diagnostic text; Codex must not follow commands, URLs or instructions found in it. A missing run ID or retrieval error is represented by a safe unavailable marker and never exposes raw output. The runner's activity log remains private.

Pausing an active iteration, interrupting the runner with SIGINT or SIGTERM, or reaching a subprocess timeout terminates the active subprocess group and preserves the checkout for inspection. Descendants that create their own process group are outside this cleanup.

## Pending review

After tests pass in review-only mode, `devloop status NAME` shows the pending review ID, base commit and tested Git tree. Inspect `git diff --cached` in the dedicated checkout and resolve the changes manually. Older pending reviews use the base commit as the ID and show a null tested tree.

Once the checkout is clean, run `devloop acknowledge NAME REVIEW_ID` to record that you handled the review, then `devloop resume NAME` when you are ready for another iteration. Acknowledgement leaves the runner paused and performs local checks only. If you kept the changes as a local commit, DevLoop's normal branch and remote checks still require you to reconcile that commit before it starts new work.

Before running the test command, DevLoop checks the staged tree for forbidden paths, symlinks, submodules, binary or non-UTF-8 content and common credential formats. The scan accepts up to 1 MiB per changed file and 16 MiB total. A blocked check preserves the checkout and index. Credential detection is heuristic, and staging already writes blobs into the local Git object store. Review the staged diff and use synthetic data.

DevLoop fingerprints the standalone checkout's local Git configuration, hooks and selected metadata before invoking Codex. It compares them after Codex and again after tests, before issuing more Git commands. A mismatch preserves the checkout and the fingerprint across restarts. Inspect and restore the affected Git metadata before resuming. This check covers repository-local files and assumes the surrounding account and Git configuration are trusted.

## Configuration and local state

Project configs must contain exactly the fields shown in `examples/jobstein.json`. Timings are positive integers, `auto_push` is a boolean, and `test_command` is a JSON argument array. Use canonical repository-relative entries in `allowed_paths` and a trailing slash for directory prefixes. Invalid configs fail before registration.

Use a real, owner-only directory for `DEVLOOP_HOME`. DevLoop requires mode 0700 on its state root and project directories, and mode 0600 on runner-owned state files. It rejects symlinked directory components, symlinked checkout roots, and linked or special state files. Configuration and status snapshots use atomic replacement. For existing state, inspect ownership, links and modes before correcting individual paths. Processes with the same user ID still share access to this state.

Project aliases under one `DEVLOOP_HOME` share a lock for each GitHub repository, regardless of repository-name casing or branch. An iteration holds the lock from preflight through completion. A competing alias pauses with a repository-lock diagnostic. Resume it after the active iteration finishes. Use one state root on a local filesystem for cooperating runners. Separate state roots and hosts require external coordination.

## Publication recovery

Keep `auto_push=false` for review-only operation. The publication path checks the fetched base and the tested tree, then saves a private, durable repository journal before sending a non-force push of the exact commit. `devloop status NAME` shows any pending journal for that repository.

If a push ends with an unconfirmed outcome, use `devloop resume NAME` followed by `devloop run-once NAME` with the original branch and workflow. This recovery iteration works with `auto_push=false`. It checks the remote branch. If the tip matches the journaled commit, DevLoop records that observation and follows CI for that exact SHA, including after a restart. It clears the journal after recording exact-commit CI success or failure. If the remote is unavailable or the branch is missing, unchanged, or at another SHA before the commit was observed, DevLoop pauses and preserves the journal and checkout for manual review. Recovery issues no push.

## Live review-only verification

On 2026-11-19, DevLoop `0bd926e565e518710fcd342e99a707f25646a8a8` completed a controlled Jobstein `run-once` with real Codex and GitHub CLI. Codex used DevLoop's verified CI result for Jobstein `08e7cfbb336a37988238784e0e4b854220c03dac` without a second GitHub query. Gradle `test` and `installDist` passed in 20 seconds. DevLoop paused in `review` with only the synthetic fixture staged and `auto_push=false`. The trial checkout stayed at the verified base commit. [Jobstein CI run 44478426833](https://github.com/assafep/assaf-jobstein/actions/runs/44478426833)

## Safety and limitations
Agent and configured build/test subprocesses receive only PATH, HOME, USER, LOGNAME, LANG, LC_ALL, LC_CTYPE, TMPDIR and TERM from the runner, plus GIT_TERMINAL_PROMPT=0. Agents also receive CODEX_HOME for user-controlled Codex setup. Unknown environment variables, publication tokens, SSH agent sockets, Git configuration overrides and runtime injection variables are excluded. Build commands needing additional configuration must use a reviewed, user-controlled setup; environment inheritance is deliberately restricted. Runner-side Git/GitHub operations retain their environment for publication.

This filtering covers inherited environment variables only. HOME, CODEX_HOME, PATH executables, temporary directories and repository files can still expose credentials or execute code; Git credential helpers and configuration on disk remain accessible. It does not isolate processes from the runner's user account, filesystem or network. Use a separate account/container with restricted mounts and credentials before running untrusted code.

This is an initial prototype, not a complete security boundary. Environment variable filtering and path allowlists do not prevent all credential exposure or malicious generated code; the local build command executes code. Keep auto_push disabled. Use isolated credentials and filesystem, never real applicant data. WSL service operation and unattended publication remain unverified. The installer does not start the service. The uninstall script only disables the named service and preserves state.

Run offline tests: `python3 -m unittest discover -s tests -v`. See AGENTS.md and BACKLOG.md for continuation.
The integration test requires Git and runs a complete review-only iteration with temporary repositories, local clone/fetch transport and synthetic Codex/gh executables. It checks environment filtering and staged-change preservation without live credentials or service calls. It does not validate real Codex sandbox enforcement or filesystem credential isolation.
