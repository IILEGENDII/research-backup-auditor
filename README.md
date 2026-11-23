# Research Backup & Recovery Auditor

A recent snapshot can still live in a damaged repository. `research-recovery` checks the selected workstation's backup age, asks restic to check the repository, and can test recovery of one pinned snapshot into an empty workspace. Each report records which checks actually finished.

Restic supplies encrypted storage, snapshot enumeration and data verification. This CLI adds selection policy, recovery budgets, a protected restore destination and machine-readable evidence. It uses Python 3.11 or later and a separately installed, verified restic **0.20.0** binary.

## Install

Download the wheel and checksum file from the [v0.1.0 GitHub Release](https://github.com/IILEGENDII/research-backup-auditor/releases/tag/v0.1.0). Compare the wheel's SHA-256 with the checksum file. On Linux use `sha256sum`, on macOS `shasum -a 256`, and on Windows `Get-FileHash -Algorithm SHA256`.

On Linux or macOS, from the directory containing the wheel:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install ./research_backup_auditor-0.1.0-py3-none-any.whl
research-recovery --version
```

In Windows PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install .\research_backup_auditor-0.1.0-py3-none-any.whl
.venv\Scripts\research-recovery --version
```

`python -m research_recovery` supports the same arguments as the console script. For development, install from the checkout with `python -m pip install -e ".[dev]"`.

## Try a disposable recovery

Run as an ordinary user. The demo generates a private synthetic source, a new encrypted repository and a recovery workspace. It performs a full pack check and compares the three restored files with independent SHA-256 digests. It leaves plaintext in the generated directory for inspection. In an activated POSIX environment:

```sh
workspace=$(mktemp -d)
research-recovery demo --workspace "$(cd "$workspace" && pwd -P)" --format json
```

For an existing owner-controlled **test** repository, use a protected restic password file. The following commands assume its location has already been set in `RESTIC_PASSWORD_FILE`. Replace the capitalized values with absolute local paths and the ID printed by the audit.

```sh
research-recovery audit --repo ABSOLUTE_TEST_REPO --check-data none --format json
research-recovery audit --repo ABSOLUTE_TEST_REPO --host synthetic-workstation --check-data subset --subset 1/5
research-recovery audit --repo ABSOLUTE_TEST_REPO --check-data full
research-recovery plan-restore --repo ABSOLUTE_TEST_REPO --snapshot SNAPSHOT_ID --workspace EMPTY_WORKSPACE
research-recovery restore-test --repo ABSOLUTE_TEST_REPO --snapshot SNAPSHOT_ID --workspace EMPTY_WORKSPACE --execute
```

See the [operator guide](docs/operator-guide.md) for Windows examples, trusted executable selection and sandbox handling.

## Use a report

JSON schema `1.0` has stable top-level fields `tool`, `schema_version`, `operation`, `status`, `completed`, `restic_version`, `check_mode`, `snapshot`, `repository_check`, `restore`, `warnings` and `errors`. An empty evidence object means the operation did not supply that evidence. Inspect `repository_check.data_scope` and `restore.executed` before relying on a result. The selected snapshot ID, UTC time, counts and durations can themselves be sensitive. [Audit example](examples/sample-audit.json) · [Restore example](examples/sample-restore-report.json)

| Exit | Meaning |
| --- | --- |
| 0 | Requested operation completed successfully. A successful plan is still a dry run. |
| 1 | Confirmed finding, including stale or missing selection, failed check, restore mismatch or exceeded policy budget. |
| 2 | Inconclusive or invalid request, including authentication, timeout, unavailable engine, unsafe location or unsupported data. |

The report format reserves `warning` for a nonzero policy result. This version treats stale backups as `failed`. Informational caveats appear in `warnings` even on a healthy result. Argument syntax errors print usage guidance to stderr. Operational errors produce a report. `--output` requires a new file with the matching extension.

A full pack check and a successful sandbox restore answer different questions. Neither establishes that every intended research file was captured. [Assurance levels](docs/assurance-levels.md) · [Threat model](docs/threat-model.md) · [Limits](docs/limitations.md)

## Development and evidence

The unit suite runs without restic. The integration suite creates its own synthetic backups and exercises the installed CLI. CI separates cross-platform unit and packaging checks from Linux integration with a checksum-pinned restic download. [Test commands and recorded evaluation](docs/evaluation.md) · [Implementation notes](docs/design.md) · [Contributing](CONTRIBUTING.md) · [Security policy](SECURITY.md) · [MIT license](LICENSE)
