# Reading an audit result

| Evidence | How to obtain it | What a successful result establishes | Remaining question |
| --- | --- | --- | --- |
| No completed check | Authentication, selection, parsing or the engine failed | The report records the reason the operation stopped | Repository condition is unknown |
| Structure | `audit --check-data none` (default) | Restic completed its consistency check against repository metadata | Most stored data may never have been read |
| Partial data | `audit --check-data subset --subset 1/5` | Restic also checked the selected group of packs | Other groups may contain damage. Pack groups can have different sizes |
| Full data | `audit --check-data full` | Restic also read and checked all repository packs available in this run | The source may already have been incomplete or corrupt |
| Restore plan | `plan-restore` or `restore-test` without execution | One snapshot ID and its supported inventory fit the requested workspace and budgets | The data has yet to be restored |
| Recovery test | `restore-test --execute` | Restic completed a verified restore. The sandbox matched the planned names, types, regular-file sizes and counts | Source-to-backup equivalence requires independent evidence |
| Synthetic content comparison | `demo` | SHA-256 digests of three restored files matched digests captured when the fixture was generated | This comparison applies to that disposable fixture |

Freshness uses the newest snapshot in the selected host and source-path set. Repository checks cover the repository. A recent snapshot and a successful check are separate observations. A recovery test refers only to its pinned snapshot.
