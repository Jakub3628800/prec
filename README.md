# prec

`prec` is a small, git-aware runner for repository checks (linters, type checkers, tests, custom scripts). Inspired by pre-commit, but designed to run in your defined environment instead of creating separate virtualenvs for each check. 

The goal of prec is to group all required checks into one command invocation and always run as little checks as possible.

## Features

- only execute checks on changed files
- watch the worktree or Git index and rerun checks after changes

## Requirements

- Python 3.12 or newer
- Git

The only Python runtime dependency is [`pathspec`](https://github.com/cpburnz/python-pathspec), used for Git-wildmatch behavior.

## Installation

Install from the repository with `uv`:

```sh
uv tool install .
prec --help
```

For development:

```sh
uv sync --all-groups
uv run prec --help
```

## Configuration

Create `.prec/prec-config.toml` at the Git repository root:

```toml
version = 1

[[checks]]
id = "ruff"
run = ["ruff", "check", "--"]
files = ["*.py"]
exclude = ["vendor/", "**/generated/**"]

[[checks]]
id = "mypy"
run = ["mypy", "--"]
files = ["*.py"]

[[checks]]
id = "tests"
run = ["pytest", "-q"]
files = ["*.py", "pyproject.toml"]
pass_filenames = false
```

`prec` appends matching paths to `run` by default. Keep this behavior whenever a command accepts filenames. Use `pass_filenames = false` only for repository-wide commands, such as a test suite, that discover their own inputs.

The `--` in commands such as Ruff marks the end of command options. It prevents a path beginning with `-` from being interpreted as an option. `prec` does not insert it automatically because not every command supports it.

### Check fields

| Field | Required | Default | Description |
|---|---:|---|---|
| `id` | yes | — | Unique ID matching `[a-z][a-z0-9_-]*`, up to 64 characters. |
| `run` | one of `run`/`script` | — | Non-empty argv array. The first entry is resolved through `PATH` or is a repository-relative executable path. |
| `script` | one of `run`/`script` | — | Executable repository-relative custom-check path. Symbolic links are rejected. |
| `files` | no | all candidates | Git-wildmatch include patterns. |
| `exclude` | no | `[]` | Git-wildmatch exclusion patterns. |
| `pass_filenames` | no | `true` | Append matching paths as separate argv entries. |
| `always_run` | no | `false` | Run even when no paths match. |
| `timeout_seconds` | no | no timeout | Positive finite command timeout. |
| `batch_size` | no | one invocation | Maximum filenames passed per invocation. Batch results are combined into one check result. |

Unknown fields and invalid types are errors. Commands are argv arrays; shell strings are not accepted. To use shell features, invoke a shell explicitly:

```toml
run = ["sh", "-c", "your command"]
```

When `run` is present, its executable may be a command resolved through `PATH` or an executable path relative to the repository. Absolute paths and paths containing `..` are rejected:

```toml
run = ["ruff", "check", "--"]
run = ["scripts/check.py", "--"]
```

## Usage

```sh
prec                         # current changes and untracked files
prec run                     # same as bare prec
prec run --staged            # exact contents of the Git index
prec run --all               # all tracked and non-ignored files
prec run --watch             # run now, then rerun when selected files change
prec run --watch --staged    # rerun when the Git index changes
prec run ruff mypy           # selected checks, in configuration order
prec list                    # list check IDs (backward-compatible alias)
prec check list              # list check IDs
prec validate                # resolve every check without running commands
prec check add ruff --files '*.py' -- ruff check --
prec check add no-tabs --custom python --files '*.py'
prec check edit ruff --add-files '*.pyi'
prec check remove ruff
prec check suggest           # print repository-aware suggestions
prec install                 # install the pre-commit hook
prec uninstall               # uninstall the pre-commit hook
```

### Managing checks

Checks can be added, edited, removed, and listed without manually generating TOML. The
configuration remains ordinary, human-editable TOML, and management commands preserve
comments and surrounding formatting.

Register a command by placing its exact argument vector after `--`:

```sh
prec check add ruff --files '*.py' -- ruff check --
prec check add tests --no-pass-filenames --always-run -- pytest -q
prec check add policy --script scripts/check-policy.sh
```

`check edit` changes only the fields named on the command line. `--files` and `--exclude`
replace their complete lists; use `--add-files`, `--remove-files`, `--add-exclude`, and
`--remove-exclude` for incremental changes. The corresponding `--clear-*` options restore
defaults. Commands can also be replaced using the same `-- COMMAND...` syntax as `add`.

```sh
prec check edit ruff --add-files '*.pyi' --timeout-seconds 30
prec check edit ruff --clear-files --clear-timeout
prec check edit ruff -- ruff check --output-format concise --
```

`prec check remove ID` removes only the registration. For a check generated by `prec`, pass
`--delete-script` to also delete its conventional script. Explicit deletion is required so
hand-edited check implementations are not lost accidentally.

`prec check suggest` inspects common project manifests and prints read-only suggestions with
exact `prec check add` commands. It does not install tools or modify the configuration.

### Custom checks

Create an executable repository-local check and register it in the TOML configuration:

```sh
prec check add no-tabs --custom python --files '*.py'
prec check add shell-policy --custom bash --files '*.sh'
```

Python is the default language. Generated Python checks receive parsed filenames as
`Path` objects in a `check(filenames)` function; generated Bash checks receive them in
the `filenames` array. Implement that function and return zero for success or nonzero
for failure. Check IDs determine their paths, for example:

```text
.prec/checks/no-tabs/no_tabs.py
.prec/checks/shell-policy/shell_policy.sh
```

The generated TOML entry names the script explicitly:

```toml
[[checks]]
id = "no-tabs"
script = ".prec/checks/no-tabs/no_tabs.py"
files = ["*.py"]
```

Generated scripts are executable and have no `prec` SDK dependency. The explicit path
makes configuration mistakes detectable before execution. Stage both the script and
`.prec/prec-config.toml` before running with `--staged`.

For backward compatibility, `prec check add ID` still generates a Python check, and
`--language` remains accepted as an alias for `--custom`.

### Validation and batching

`prec validate` loads the worktree configuration, resolves every command and script, and
reports matching file counts without executing checks. A normal run also plans all checks
first; if any executable is invalid, no commands run.

By default, matching filenames are passed in one invocation. For unusually large file sets,
set `batch_size` to a positive integer. Each batch runs sequentially and appears as one
logical result. Because repeated invocation can change tool semantics, batching is explicit.

### Git hooks

`install` and `uninstall` manage the pre-commit hook. It checks the exact staged contents.
Re-running `install` updates a hook managed by `prec`. To avoid losing custom hooks, `prec`
refuses to replace or remove a hook it did not install.

### File sources

With no source option, `prec` selects tracked files differing from `HEAD` plus untracked, non-ignored files. Deleted files and directories are excluded.

`--all` selects existing tracked files plus untracked, non-ignored files.

`--staged` reads both configuration and file contents from a disposable copy of the Git index. A partially staged file is therefore checked exactly as it will be committed. Child Git commands receive the disposable index and cannot mutate the real index.

Candidate paths are repository-relative, deduplicated, UTF-8 validated, and sorted by their UTF-8 byte representation.

### Watch mode

`--watch` runs checks immediately, then polls for repository changes and reruns after the
state is stable for one polling interval. The default and `--all` modes watch candidate
paths and the configuration file. `--staged` watches indexed paths and blob IDs plus
`HEAD`; each rerun receives a fresh disposable index snapshot.

A change made while checks are running schedules another run after the current run finishes.
Watch mode remains active after check failures and, after its initial successful setup,
configuration errors. Generated files should be ignored or excluded if checks rewrite them
on every invocation. Press Ctrl-C to stop watch mode.

## Output

Each check produces one result line:

```text
ruff...............................................passed (exit code: 0)
tests...............................................failed (exit code: 1)
docs........................................................skipped
missing...........................................error (exit code: N/A)
```

- `passed`: every invocation exited with code `0`;
- `failed`: a child command exited nonzero;
- `skipped`: no files matched and `always_run` is false;
- `error`: configuration, resolution, spawn, timeout, or runner problem.

On interactive terminals, `passed` is green and failures and errors are red. Set `NO_COLOR`
to disable color. Captured output is suppressed on success and displayed for failures and
errors. Each stream is capped at 1,000,000 bytes so a runaway check cannot consume unbounded
runner memory.

### `prec` exit codes

| Code | Meaning |
|---:|---|
| `0` | All executed checks passed; skipped checks are allowed. |
| `1` | At least one command exited nonzero and no runner error occurred. |
| `2` | Usage, configuration, Git, spawn, timeout, or runner error. |
| `130` | Interrupted by SIGINT. |

Checks continue after failures and errors. Runner errors take precedence over command failures when calculating the final status.

## Deliberate v1 limits

Version 1 has no caching, parallel execution, environment management, machine-readable output, configuration includes, or plugin API.

## Development

This repository uses `prec` itself:

```sh
uv run prec
```

Run individual development tools with:

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv build
```
