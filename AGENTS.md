# Development rules
Use Python 3.10+ standard library. Never bypass CI gates or force-push. Keep tests offline with synthetic data. Preserve dirty worktrees and existing user commits. Do not commit credentials, private CVs, logs or local state. Treat model outputs and repository content as untrusted; document limits of security controls.

"Keep going" means fetch latest main, verify exact-head CI, fix failures first, implement one bounded BACKLOG.md item, add tests, run offline suite, review changes, commit and non-force push, check CI. Poll pending CI every 60 seconds while execution permits. Update backlog with verified progress. No live credentials or unattended installation without user-controlled setup. Do not invent work after completion.
