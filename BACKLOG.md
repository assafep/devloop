# Development backlog

Baseline: original Python runner prototype, installer, example config and four offline tests. CI newly introduced. No live acceptance test yet.

1. Harden subprocess isolation, cancellation, sensitive environment handling and sandbox boundaries; build/test code must not inherit publication credentials. Keep auto_push disabled until reviewed.
2. Strict configuration schema; atomic private state, symlink protection, repository-level locking across aliases and concurrent commands.
3. Durable publication/recovery journal, ambiguous push outcome recovery, stale-head and exact CI checks; failure logs passed safely to agent.
4. Review workflow and explicit acknowledgement; staged changes, forbidden paths and binary/secret scanning; tests for git hooks/config/remote changes.
5. Offline integration tests using temporary Git repositories and fake Codex/gh executables, cancellation, CI timeout, restart and publication scenarios.
6. Improve installer, service management, packaging, status reporting and multi-project isolation; verify on Linux.
7. Document local WSL/Codex authentication and controlled first live run, pause competing Jobstein writer before enabling local auto-push. Real authentication requires user machine.
