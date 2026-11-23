import hashlib
from datetime import UTC, datetime

import pytest

from research_recovery import restore
from research_recovery.cli import main
from research_recovery.models import AuditError, Finding, Report
from research_recovery.restic import Restic, Result
from research_recovery.snapshots import Snapshot


def test_inspection(tmp_path):
    root = tmp_path.resolve()
    (root / "dir").mkdir()
    (root / "dir" / "sample").write_bytes(b"abc")
    inv = restore.Inventory({"dir/sample": 3}, {"dir"}, 3)
    restore.inspect_restore(root, inv, digests={"dir/sample": hashlib.sha256(b"abc").hexdigest()})
    with pytest.raises(Finding):
        restore.inspect_restore(root, inv, digests={"dir/sample": "0" * 64})
    (root / "extra").touch()
    with pytest.raises(Finding):
        restore.inspect_restore(root, inv)
    (root / "extra").unlink()
    (root / "dir" / "sample").unlink()
    with pytest.raises(Finding):
        restore.inspect_restore(root, inv)


def test_link_not_followed(tmp_path):
    root = tmp_path.resolve()
    sandbox = root / "restore"
    sandbox.mkdir()
    target = root / "private"
    target.write_bytes(b"no")
    try:
        (sandbox / "alias").symlink_to(target)
    except OSError:
        pytest.skip("file symlink unavailable")
    with pytest.raises(Finding):
        restore.inspect_restore(sandbox, restore.Inventory({"alias": 2}, set(), 2))


def test_fixed_target_and_partial_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(restore, "require_unprivileged", lambda: None)
    root = tmp_path.resolve()
    workspace = root / "restore"
    workspace.mkdir()
    keep = root / "existing"
    keep.write_bytes(b"prior")
    s = Snapshot("d" * 64, datetime.now(UTC), "synthetic", (str(keep),), ())
    plan = restore.Plan(s, restore.Inventory({"test": 3}, set(), 3), workspace, {keep})

    class Engine:
        def _restore(self, identifier, target):
            assert target.parent == workspace and not list(target.iterdir()) and identifier == s.id
            (target / "test").write_bytes(b"abc")
            return Result(1, b"private failure", 0.1)

    report = Report("restore-test")
    with pytest.raises(AuditError):
        restore.execute_restore(Engine(), plan, report)
    assert report.restore["executed"] and not report.restore["verified"]
    assert (workspace / report.restore["sandbox"] / "test").read_bytes() == b"abc"
    assert keep.read_bytes() == b"prior"


def test_dry_run_and_invalid_id(tmp_path, monkeypatch, capsys):
    from research_recovery import cli

    root = tmp_path.resolve()
    repo = root / "repo"
    work = root / "work"
    repo.mkdir()
    work.mkdir()
    calls = []
    monkeypatch.setattr(cli, "executable", lambda binary: root / "restic")
    monkeypatch.setenv("RESTIC_PASSWORD", "disposable")
    monkeypatch.delenv("RESTIC_PASSWORD_FILE", raising=False)
    monkeypatch.setattr(Restic, "version", lambda self: "0.20.0")
    monkeypatch.setattr(Restic, "snapshots", lambda self: b"[]")
    monkeypatch.setattr(cli, "plan_restore", lambda *args: calls.append("plan"))
    monkeypatch.setattr(cli, "execute_restore", lambda *args: pytest.fail("unexpected restore"))
    args = ["restore-test", "--repo", str(repo), "--workspace", str(work), "--snapshot"]
    assert main([*args, "d" * 64]) == 0 and calls == ["plan"] and not list(work.iterdir())
    monkeypatch.setattr(cli, "executable", lambda binary: pytest.fail("ran before ID validation"))
    assert main([*args, "latest"]) == 2
