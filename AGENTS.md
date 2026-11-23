# Development rules

- Work only in this repository and owner-controlled synthetic directories. Never access Hyak, university systems, private datasets or production backup repositories during development.
- Preserve the fixed restic operations, local paths, timeout and output limits. Keep all initialization and backup commands inside the disposable fixture helper. Never add repair, pruning, unlock or deletion to the production adapter.
- Require the full --execute option for an operator's restore. Pin the snapshot ID, validate the inventory and create a new child of an empty private workspace. Never execute restored files.
- Keep credentials, real paths and raw restic errors out of reports, commits and CI output. Build sample reports with the application.
- Run Ruff lint and format checks, the unit suite, real synthetic integration tests and a package build. Record genuine failures or skips. Preserve assertions and fix the cause of failures. See CONTRIBUTING.md for commands.
