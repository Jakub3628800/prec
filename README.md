# prec

`prec` is a small, git-aware runner for repository checks (linters, type checkers, tests, custom scripts). Inspired by pre-commit, but designed to run in your defined environment instead of creating separate virtualenvs for each check. 

The goal of prec is to group all required checks into one command invocation and always run as little checks as possible.

## Features

- only execute checks on changed files

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
| `run` | yes | — | Non-empty argv array. The first entry is resolved through `PATH`. |
| `files` | no | all candidates | Git-wildmatch include patterns. |
| `exclude` | no | `[]` | Git-wildmatch exclusion patterns. |
| `pass_filenames` | no | `true` | Append matching paths as separate argv entries. |
| `always_run` | no | `false` | Run even when no paths match. |
| `timeout_seconds` | no | no timeout | Positive finite command timeout. |

Unknown fields and invalid types are errors. Commands are argv arrays; shell strings are not accepted. To use shell features, invoke a shell explicitly:

```toml
run = ["sh", "-c", "your command"]
```

The executable in `run[0]` cannot contain `/`. Repository scripts can still be passed to an interpreter:

```toml
run = ["python3", "scripts/check.py"]
```

## Usage

```sh
prec                         # current changes and untracked files
prec run                     # same as bare prec
prec run --staged            # exact contents of the Git index
prec run --all               # all tracked and non-ignored files
prec run ruff mypy           # selected checks, in configuration order
prec list                    # list check IDs
prec install                 # install the pre-commit hook
prec uninstall               # uninstall the pre-commit hook
```

### Git hooks

`install` and `uninstall` manage the pre-commit hook. It checks the exact staged contents.
Re-running `install` updates a hook managed by `prec`. To avoid losing custom hooks, `prec`
refuses to replace or remove a hook it did not install.

### File sources

With no source option, `prec` selects tracked files differing from `HEAD` plus untracked, non-ignored files. Deleted files and directories are excluded.

`--all` selects existing tracked files plus untracked, non-ignored files.

`--staged` reads both configuration and file contents from a disposable copy of the Git index. A partially staged file is therefore checked exactly as it will be committed. Child Git commands receive the disposable index and cannot mutate the real index.

Candidate paths are repository-relative, deduplicated, UTF-8 validated, and sorted by their UTF-8 byte representation.

## Output

Each check produces one result line:

```text
ruff..............................................success (exit code: 0)
tests...............................................error (exit code: 1)
docs........................................................skipped
missing...........................................other (exit code: N/A)
```

- `success`: the child exited with code `0`;
- `error`: the child exited with code `1`;
- `skipped`: no files matched and `always_run` is false;
- `other`: another exit code, spawn failure, timeout, or runner problem.

On interactive terminals, `success` is green and `error` is red. Set `NO_COLOR` to disable color. Captured stdout and stderr are suppressed on success and displayed in labeled sections for `error` and `other`.

### `prec` exit codes

| Code | Meaning |
|---:|---|
| `0` | All executed checks passed; skipped checks are allowed. |
| `1` | At least one command exited nonzero and no runner error occurred. |
| `2` | Usage, configuration, Git, spawn, timeout, or runner error. |
| `130` | Interrupted by SIGINT. |

Checks continue after failures and errors. Runner errors take precedence over command failures when calculating the final status.

## Deliberate v1 limits

Version 1 has no caching, parallel execution, watcher, environment management, machine-readable output, configuration includes, plugin API, or special `.prec/hooks/` behavior.

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
