# Contributing

Keep changes small enough to review against one recovery or reporting behavior. Include the expected assurance level and a synthetic regression test when changing a trust boundary.

Use Python 3.11-compatible code and the supported restic 0.20.0 interface. Use domain names and comment the reason for a bound or platform-specific decision. Keep fixture passwords in memory. Test in temporary directories created by the suite. To simulate corruption, modify only a separate copy of a generated repository.

Install with `python -m pip install -e ".[dev]"`. Run `python -m ruff check .`, `python -m ruff format --check .` and `python -m pytest -m "not integration"`. Set `AUDITOR_TEST_RESTIC` to a verified local binary and run `python -m pytest -m integration` as a non-elevated user. Build with `python -m build`. Record actual versions, failures and skips in reviews. [Security policy](SECURITY.md)
