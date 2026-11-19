# DevLoop

DevLoop runs a bounded Codex development iteration in a dedicated local checkout of a GitHub repository. It checks GitHub Actions for the starting commit, screens the proposed changes, runs your test command, and pauses with the tested changes staged for your review. Start with `"auto_push": false`.

## Run your first iteration on Linux

You need Python 3.10+, Git with an author identity, authenticated GitHub and Codex CLIs, and your project's test tools. Pick a repository and branch with a GitHub Actions workflow that runs on pushes. Use a dedicated account or isolated environment with limited credentials.

### 1. Install

From the DevLoop source directory, install the foreground runner. Sign in to both CLIs as the Linux user who will run DevLoop.

```sh
bash install.sh --no-service
export PATH="$HOME/.local/bin:$PATH"
codex login
gh auth login --hostname github.com
```

### 2. Configure your project

Save the following as `project.json`. Replace the repository, branch, workflow, test command, allowed paths, and task instructions with values for your project. This example uses a Python project and allows changes to `docs/` and `README.md`. A trailing slash allows a directory prefix. The test command is an argument array run from the checkout.

```json
{
  "repository": "your-org/your-repo",
  "branch": "main",
  "workflow": "CI",
  "interval_seconds": 120,
  "ci_poll_seconds": 60,
  "ci_timeout_seconds": 1800,
  "agent_timeout_seconds": 1200,
  "test_timeout_seconds": 300,
  "auto_push": false,
  "test_command": ["python3", "-B", "-m", "unittest", "discover", "-s", "tests"],
  "allowed_paths": ["docs/", "README.md"],
  "instructions": "Make one bounded documentation improvement from the project backlog."
}
```

See the [operations guide](docs/operations.md#build-and-test-isolation) to select Bubblewrap isolation. With the configuration above, tests run with the runner user's filesystem access.

### 3. Register and run

```sh
devloop add my-project project.json
devloop doctor my-project
devloop run-once my-project
devloop status my-project
```

`add` copies the configuration into DevLoop's local state. To edit the registered copy later, get its path with `devloop configure my-project`. Check `status` after each run for the result, checkout path, and any pending review.

### 4. Review and continue

When the status is `review`, inspect the staged diff in the checkout shown in `status`. With the default state location:

```sh
git -C "$HOME/.local/state/devloop/my-project/checkout" diff --cached
```

Resolve the changes manually. Keep them through your project's normal review process or discard them after inspection. Once the dedicated checkout is clean, substitute the review ID from `status` below.

```sh
devloop acknowledge my-project REVIEW_ID
devloop resume my-project
devloop run-once my-project
```

A local commit must be reconciled with the configured branch before the next iteration can proceed. If the result is `blocked`, inspect `devloop logs my-project` and the checkout before resuming.

## Where to go next

- [How DevLoop works](docs/workflow.md) shows who does what, which checks run, and how an iteration ends.
- [Operations guide](docs/operations.md) covers the command reference, user services, state, isolation, and publication recovery.
- [Backlog](BACKLOG.md) tracks remaining development work. To test changes to DevLoop itself, run `python3 -m unittest discover -s tests -v`.
