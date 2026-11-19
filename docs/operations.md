# Operating DevLoop

## Commands

| Task | Command |
| --- | --- |
| Register a project from JSON | `devloop add NAME CONFIG` |
| Find the registered config | `devloop configure NAME` |
| Check prerequisites and selected test isolation | `devloop doctor NAME` |
| Run once or loop in the foreground | `devloop run-once NAME` or `devloop run NAME` |
| Check the checkout path, last result, and pending review or publication | `devloop status NAME` |
| Inspect recent activity or iteration history | `devloop logs NAME [--follow]` or `devloop history NAME` |
| Pause or resume iterations | `devloop pause NAME` or `devloop resume NAME` |
| Resolve a pending review after cleaning the checkout | `devloop acknowledge NAME REVIEW_ID` |
| Manage the user service | `devloop start NAME`, `devloop stop NAME`, or `devloop restart NAME` |

Pausing, stopping the runner with SIGINT or SIGTERM, or timing out a subprocess terminates the active subprocess group. Descendants in separate process groups are outside that cleanup. The CI timeout covers both poll delays and GitHub CLI queries. If the budget expires, check `status` and try again once CI has finished.

## Run under user systemd

Run `bash install.sh` from the source directory to install the executable and the user service template and request a daemon reload. The installer preserves registered projects. Start the service explicitly. The service uses a fixed PATH that includes `~/.local/bin`. Configure the service environment explicitly if tools depend on paths set by your shell. If using a custom `DEVLOOP_HOME`, give the service the same value.

To verify the service with a registered project while keeping iterations paused:

```sh
devloop pause my-project
devloop start my-project
systemctl --user is-active devloop@my-project.service
devloop status my-project
devloop stop my-project
```

`start` starts the process without clearing the pause. To use the service for iterations, resume after resolving any pending review. Run `bash uninstall.sh my-project` to stop and disable that instance while retaining the executable, template, and project state.

Foreground review-only operation and the user-systemd lifecycle have been exercised on Linux. WSL was outside the live validation scope.

## Local state and concurrency

The default state root is `~/.local/state/devloop`. Each project has a directory containing its config, checkout, logs, and review state. When overriding `DEVLOOP_HOME`, use a real directory on a local filesystem. The state root and project directories require mode `0700`, and DevLoop-owned files require mode `0600`. DevLoop rejects symlinked directory components and checkout roots, as well as linked or special state files. Keep state and logs private.

Within one state root, aliases for the same GitHub repository share an iteration lock regardless of branch or repository-name casing. A competing alias can be resumed after the active iteration finishes. A duplicate run of the same project leaves the active runner's state alone. Coordinate separately across different state roots or hosts.

## Build and test isolation

Set `"test_isolation": "bubblewrap"` in the registered configuration and run `devloop doctor NAME`. The default is `"host"`, which gives the build and test command the runner user's filesystem access. Bubblewrap requires a system installation with working unprivileged user namespaces and support for `--disable-userns`. DevLoop blocks if sandbox startup fails.

In Bubblewrap, the checkout is writable at `/workspace`, its `.git` directory is hidden, and the test command has a temporary home, selected read-only runtime paths, and a private network namespace. The runner home and state are outside the mounts. To supply offline dependencies, place a credential-free seed in an owner-only `test-dependencies` directory beside `config.json`. The sandbox mounts it read-only at `/dependencies`. Copy files that need writes into the sandbox's temporary home.

DevLoop filters the environment for Codex and tests, excluding inherited publication tokens, SSH agent sockets, Git overrides, and unknown variables. Codex has its own authentication and receives a workspace-write request with network access disabled for its commands. Bubblewrap covers only the configured test command. Environment filtering and staged-path rules cannot prevent access to files already visible to a process. Use limited credentials, a dedicated account or isolated environment, and keep secrets out of the checkout and mounted dependencies.

## Recover an existing publication

Keep `auto_push=false` for review-only operation. The automatic push path has offline coverage. A live automatic publication trial remains deferred.

If an earlier publication attempt left a journal in `status`, use the original branch and workflow. Resume the project and run one iteration. Recovery works with `auto_push=false` and issues no push. It checks whether the remote tip matches the journaled commit, then follows CI for that commit. If the remote is unavailable or the tip is missing, unchanged, or unexpected before the journaled commit is observed, DevLoop preserves the journal and checkout for manual inspection.
