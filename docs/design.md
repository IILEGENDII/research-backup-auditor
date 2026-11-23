# Implementation notes

The CLI resolves a local executable, checks its version and obtains snapshot metadata before it accepts a report destination. The restic adapter builds argument lists, disables the cache, discards stderr after enforcing a byte limit, and supplies an allowlisted environment. Authentication uses a local password file or an environment variable. Restic can acquire its normal repository locks.

Snapshot timestamps are converted to UTC. ID prefixes resolve against all snapshots. Planning pins the full ID before requesting a long JSON inventory. The inventory capture spills above 1 MiB to a temporary file and the parser consumes one bounded record at a time. Only validated names, directory membership, inode information and file sizes are needed to construct the plan. The private operating-system temporary directory must have space for metadata.

Execution rechecks the empty workspace and creates a private child with a random name. Restic receives the full snapshot ID, a fixed target, overwrite policy `never`, an extended-attribute exclusion and `--verify`. On success the auditor walks the actual tree and compares it with the plan. POSIX inspection uses directory descriptors and no-follow opens. On Windows it checks reparse points and file identities. Only the synthetic demo has a separate content baseline.

The report writer flushes a private temporary file in the destination directory. On POSIX, a hard link installs the finished report only if the name is free. On Windows a same-directory rename has the same no-clobber property. A filesystem that cannot publish this way returns an error. An unconditional replacement would overwrite another writer's report.

The demo's repository initialization and backup calls live in the fixture module. Both use a newly created directory, fixed local names and a random process-local password. The production adapter exposes listing, checking and an isolated restore. The corruption test alters one pack in a second, test-owned copy.
