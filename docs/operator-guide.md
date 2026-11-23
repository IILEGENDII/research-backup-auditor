# Operator guide

**Review command effects before using any research data. Use only disposable synthetic inputs for the following exercises.** Run as an ordinary user on a personally controlled workstation.

## Prepare the engine

Download restic 0.20.0 for your operating system and CPU, verify the published checksum manifest using restic's release verification instructions, then compare the downloaded archive's SHA-256 with its entry. Unpack the executable in a trusted, non-shared local directory. Use `--restic` with its absolute path if it is outside PATH. Run `restic version` to confirm the version. [Official release and checksums](https://github.com/restic/restic/releases/tag/v0.20.0) · [Installation instructions](https://restic.readthedocs.io/en/stable/020_installation.html)

The CLI searches absolute PATH entries for the native executable. It rejects relative paths, executable links and Windows command scripts. Do not add the current directory or an untrusted directory to PATH.

## Create a test repository

The simplest way to create a private test repository and exercise all three stages is the built-in demo. It creates the password in memory and generates synthetic CSV, numeric binary and random binary files. Start with an empty local directory owned by your account. On POSIX, use the demo command in the README. On Windows PowerShell, from the checkout with the wheel installed into its virtual environment:

```powershell
$workspace = Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $workspace -ErrorAction Stop | Out-Null
.venv\Scripts\research-recovery demo --workspace $workspace --format json
```

Confirm `restore.executed`, `restore.verified` and `restore.independent_sha256` are true. The demo prints the generated child name and keeps its files there, including plaintext. Its random credentials are discarded at process exit. For repeatable separate invocations against fresh fixtures, run the integration suite, which holds credentials only for each test session. [Evaluation](evaluation.md)

## Audit a local test repository

For a separately prepared test repository, store its password in a file readable only by your user. Use an owner-only directory with mode 0700 and file mode 0600 on POSIX. Check the owner and ACL on Windows. Keep the file outside the source, repository and recovery workspace. The CLI accepts `--password-file ABSOLUTE_FILE` or the path in `RESTIC_PASSWORD_FILE`. An explicit file takes precedence. If no file is selected, the CLI accepts `RESTIC_PASSWORD` from the caller's environment. Avoid supplying secret values in commands or shell history.

Start with `research-recovery audit --repo ABSOLUTE_TEST_REPO --format json`. Narrow multiple sources with exact `--host`, `--path` or `--tag` selectors. Check the selected full ID, UTC timestamp and `freshness_status`. Use `--max-age-hours 24` to apply a one-day policy. Ambiguous scopes require further selection. An empty match fails.

The default structural check reads repository metadata. `--check-data subset --subset 1/5` also reads one restic pack group. `--check-data full` reads every pack and may occupy the disk for a long time. Schedule full checks when the disk has capacity. Set `--timeout` in seconds per process if the default of 120 is insufficient. Full checks impose their own I/O cost regardless of the restore budget.

## Plan and execute

Choose a new empty workspace outside the source and repository, with sufficient disk space and access restricted to your account. Use the full ID printed by the audit. An unambiguous hexadecimal prefix of at least eight characters also works. Both commands resolve it to a full ID before invoking restic.

```sh
research-recovery plan-restore --repo ABSOLUTE_TEST_REPO --snapshot SNAPSHOT_ID --workspace EMPTY_WORKSPACE --max-files 20 --max-bytes 1048576
research-recovery restore-test --repo ABSOLUTE_TEST_REPO --snapshot SNAPSHOT_ID --workspace EMPTY_WORKSPACE --max-files 20 --max-bytes 1048576 --execute --format json
```

The plan checks node types, paths, file count, logical bytes and free space. Execution repeats planning, rechecks the workspace, creates a new child and inspects the resulting tree. Keep the same budgets and full ID when moving from planning to execution. For `--output`, choose a new .json or .txt file outside the source, repository and workspace.

Inspect the reported child even after an interrupted recovery. Treat its contents as untrusted. Never execute restored programs. For cleanup, inspect the absolute workspace and generated child in the file manager, verify ownership and purpose, and remove only the disposable content you created. The tool leaves all cleanup decisions to the operator.
