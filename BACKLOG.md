# Development backlog

- Independently verify which filesystem reads and writes the installed Codex sandbox permits using synthetic files in a controlled environment. The integration suite checks the requested sandbox options, and the Linux review-only self-test exercised the real CLI. Broader filesystem enforcement is still unverified.

Linux is the validated platform for foreground and user-service operation. WSL validation was intentionally skipped. A live automatic publication trial is deferred while review-only operation is the chosen workflow. See the [operations guide](docs/operations.md) for the current operating limits.
