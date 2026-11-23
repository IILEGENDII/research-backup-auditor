# Synthetic evaluation

Local release-candidate run on November 23, 2026. Windows 11 build 10.0.26300, CPython 3.14.7, restic 0.20.0 (windows/amd64), pytest 9.2.0, Ruff 0.17.6 and build 1.6.1. The Windows restic archive matched SHA-256 `bba9061c3dce081701ab353ec8cb73a78be73b71a538aad560f2d1067602b7fe` in the upstream release manifest.

## Reproduce

From the repository, install the development dependencies in a virtual environment. Set `AUDITOR_TEST_RESTIC` to the absolute path of a verified 0.20.0 binary. Use a normal user account. The tests generate credentials in memory and use temporary directories. No repository path or research dataset is required.

```sh
python -m pip install -e ".[dev]"
python -m ruff check .
python -m ruff format --check .
python -m pytest -q -rs -m "not integration"
python -m pytest -q -rs -m integration
python -m pytest -q -rs
python -m build
research-recovery --help
python -m research_recovery --version
```

On Windows the combined run used:

```powershell
$env:AUDITOR_TEST_RESTIC = (Resolve-Path .local/bin/restic_0.20.0_windows_amd64.exe).Path
.venv/Scripts/python.exe -m pytest -q -rs
```

The combined suite passed 78 tests in 39.97 seconds. One file-symlink test skipped because the local Windows account could not create a symlink. All eight real-engine cases ran. Ruff lint and format checks passed. Phase gate totals before final review were 8, 37, 50, 66 and 69 unit passes, followed by 7 real-engine passes in 39.85 seconds. The final review added explicit-option and interrupted-full-check coverage. Wall times describe this run only.

## Observations

The first Linux integration run passed seven cases and stopped before injecting corruption: the copied pack retained restic's read-only POSIX permissions. The fixture now grants its owner write access to that one disposable copy before flipping a byte. The original pack is never opened for writing.

The fixture inputs comprised a 23-byte CSV, 64 bytes of little-endian doubles and 524,288 random bytes. Snapshot IDs, times, credentials, random bytes and generated directory names vary across runs. The two example reports were written by CLI invocations against the same fresh fixture.

| Scenario | Observed evidence |
| --- | --- |
| Fresh backup | Structural mode returned 0, an unambiguous current ID and scope `structure`. |
| Historical backup | Selecting the 2001 snapshot returned 1 with `freshness_status: stale`, although a current snapshot also existed. |
| Empty repository or wrong host | Each produced exit 1. |
| Partial data read | Restic ran `--read-data-subset=1/5`. The successful report identified `subset`. |
| One damaged pack | The test copied the entire disposable repository and flipped one byte in a copied pack. Full checking returned 1 with a failed repository check. |
| Planning, including restore without execution | The dedicated workspace remained empty. An over-budget request returned 1. |
| Unsafe destination | Pointing recovery at the synthetic source returned 2. |
| Successful recovery | The independent test harness hashed source and restored files and compared their digests. All three matched. Repository files outside the transient lock directory retained their hashes. |
| Explicit full check interrupted | A very short execution timeout after real snapshot selection left the full check incomplete. |
| Wrong password, missing repo or absent executable | The CLI returned 2. Reports omitted secrets and private paths. |
| Demo | The CLI independently checked all three restored digests. In the separate ordinary recovery example, `independent_sha256` is false. |

The samples record 524,375 restored bytes. The evaluation is a project test suite using synthetic files. It measures neither multi-terabyte throughput nor the integrity of any third-party repository. [Sample audit](../examples/sample-audit.json) · [Sample recovery](../examples/sample-restore-report.json) · [Hosted CI runs](https://github.com/IILEGENDII/research-backup-auditor/actions/workflows/ci.yml)
