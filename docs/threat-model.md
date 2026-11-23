# Threat model

The operator controls the local workstation, restic installation, temporary directory, repository layout and workspace. Assume ordinary user privileges for recovery and a stable local filesystem. Treat metadata and restored content as untrusted. Results depend on the running OS and the restic binary.

| Asset and threat | Control | Residual risk | Test evidence |
| --- | --- | --- | --- |
| Backup freshness, wrong host or source | Exact host/path/tag filters, one host and path set, UTC threshold, full snapshot ID | An authorized writer can supply misleading labels or times | Selection unit tests and historical/current synthetic snapshots |
| Encrypted repository, damaged pack | Structural, subset and full modes with explicit evidence | A structural or partial check can miss damaged content | Full check of a deliberately damaged disposable copy |
| Credentials and local identifiers | No shell, allowlisted child environment, suppressed raw subprocess errors, redacted report fields | OS administrators and processes able to inspect the operator's environment can obtain secrets | Authentication failure and redaction tests |
| Existing files and stored snapshots | Fixed restic commands, independent empty workspace, exclusive restore child and report publication | Restic manages temporary locks. Concurrent filesystem mutation can invalidate checks | Before/after repository hashes, source hashes, rejected overlaps and no-clobber test |
| Plaintext in recovery workspace | Restricted workspace, node/name/mode preflight, post-restore inspection, no execution of restored files | Plaintext persists. The OS, restic and workspace access controls remain trusted | Synthetic hash comparison, unexpected entry and symlink tests |
| Availability, oversized or malformed input | Timeouts, capture caps, node/file/byte limits and free-space check | Logical size does not reserve space or impose an OS quota | Timeout, output limit, malformed JSON and over-budget tests |
| Report consumers, false healthy result | Valid completion evidence, stable statuses and separate check/restore fields | A report records one run and carries no signature | Incomplete summary, wrong password and failed partial restore tests |
