# Changelog

## v0.1.0

- Added local restic snapshot selection and freshness policy, repository structural checks, pack subset checks and full data checks.
- Added bounded planning and explicit isolated restore tests for snapshots containing supported regular files and directories.
- Added schema 1.0 text and JSON reporting, no-clobber report publication and separate evidence for pack checking and recovery.
- Added a synthetic recovery demo, independent file digest comparisons in the integration suite, and detection of corruption in a copied disposable repository.
