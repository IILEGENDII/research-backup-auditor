import json
from argparse import Namespace
from datetime import UTC, datetime, timedelta

import pytest

from research_recovery.auditing import audit, check_evidence
from research_recovery.cli import main
from research_recovery.models import AuditError, Finding, Report
from research_recovery.reporting import check_output, render, write_report
from research_recovery.restic import Result
from research_recovery.snapshots import Snapshot


@pytest.mark.parametrize(
    ("mode", "scope"), [("none", "structure"), ("subset", "subset"), ("full", "full")]
)
def test_scopes(mode, scope):
    class Engine:
        def check(self, actual, subset):
            assert actual == mode
            assert subset == ("1/5" if mode == "subset" else None)
            return Result(0, b'{"message_type":"summary","num_errors":0}', 0.5)

    args = Namespace(
        host=None,
        path=None,
        tag=None,
        max_age_hours=72,
        check_data=mode,
        subset="1/5" if mode == "subset" else None,
    )
    private = "origin-private"
    s = Snapshot("b" * 64, datetime.now(UTC), private, ("/private-source",), ())
    report = Report("audit", check_mode=mode)
    audit(Engine(), [s], args, report)
    assert report.exit_code == 0 and report.repository_check["data_scope"] == scope
    assert report.completed and report.repository_check["seconds"] == 0.5
    for fmt in ("json", "text"):
        assert private not in render(report, fmt)
    old = Snapshot(s.id, s.time - timedelta(days=90), s.host, s.paths, ())
    with pytest.raises(Finding, match="freshness"):
        audit(Engine(), [old], args, Report("audit"))


@pytest.mark.parametrize(
    ("code", "output"),
    [
        (0, b""),
        (0, b"{}"),
        (1, b"fatal error"),
        (12, b"private"),
        (0, b'{"message_type":"summary","num_errors":true}'),
        (1, b'{"message_type":"summary","num_errors":0}'),
        (0, b'{"message_type":"summary","num_errors":0}\n{}'),
    ],
)
def test_incomplete_evidence(code, output):
    with pytest.raises(AuditError):
        check_evidence(Result(code, output, 0))


def test_confirmed_error():
    assert not check_evidence(Result(1, b'{"message_type":"summary","num_errors":1}', 0))


def test_no_clobber(tmp_path):
    tmp_path = tmp_path.resolve()
    repo = tmp_path / "repo"
    repo.mkdir()
    for forbidden in [repo / "check.json", tmp_path / "analysis.py"]:
        with pytest.raises(AuditError):
            check_output(str(forbidden), "json", {repo})
    path = check_output(str(tmp_path / "check.json"), "json", {repo})
    path.write_text("previous")
    with pytest.raises((AuditError, OSError)):
        write_report(path, "updated")
    assert path.read_text() == "previous"
    path.unlink()
    write_report(path, "complete")
    assert path.read_text() == "complete"


def test_missing_binary_and_redaction(tmp_path, capsys):
    secret = "private-host"
    code = main(
        [
            "audit",
            "--repo",
            str(tmp_path),
            "--restic",
            str(tmp_path / secret),
            "--format",
            "json",
            "--host",
            secret,
        ]
    )
    out = capsys.readouterr().out
    assert code == 2 and secret not in out and str(tmp_path) not in out
    assert json.loads(out)["status"] == "inconclusive"
