# Development backlog

Baseline: Python runner prototype, installer, Jobstein example, offline CI and a verified live review-only iteration.

1. Harden subprocess isolation, cancellation, sensitive environment handling and sandbox boundaries; build/test code must not inherit publication credentials. Keep auto_push disabled until reviewed.
   - Verified offline: environment allowlists exclude synthetic publication secrets, SSH sockets, Git overrides and runtime injection variables from agent and build/test subprocesses. Pause, stop signals and subprocess timeouts cancel the active process group and preserve the checkout. Filesystem credential isolation and sandbox hardening remain open. The example keeps `auto_push=false`.
2. Strict configuration schema; atomic private state, symlink protection, repository-level locking across aliases and concurrent commands.
3. Durable publication/recovery journal, ambiguous push outcome recovery, stale-head and exact CI checks; failure logs passed safely to agent.
4. Review workflow and explicit acknowledgement; staged changes, forbidden paths and binary/secret scanning; tests for git hooks/config/remote changes.
5. Offline integration tests using temporary Git repositories and fake Codex/gh executables, cancellation, CI timeout, restart and publication scenarios.
   - Verified offline: a complete review-only iteration uses temporary Git repositories and fake Codex/gh tools. Cancellation tests use real local subprocesses to cover pause, SIGTERM, timeout with an exited group leader, and input/output across polling. CI timeout, restart and publication scenarios remain open.
6. Improve installer, service management, packaging, status reporting and multi-project isolation; verify on Linux.
7. Document local WSL/Codex authentication and controlled first live run, pause competing Jobstein writer before enabling local auto-push. Real authentication requires user machine.
   - Verified live on 2026-11-19 with DevLoop `0bd926e`. The built-in exact-commit CI handoff supplied Jobstein run `44478426833` to Codex, Gradle `test installDist` passed, and the runner paused in `review` with only the synthetic fixture staged and `auto_push=false`. WSL service validation and publication cutover remain open. See the [README](README.md#live-review-only-verification) for the trial record.
