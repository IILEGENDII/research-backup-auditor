import io
import json
from argparse import Namespace
from datetime import UTC, datetime

import pytest

from research_recovery.models import AuditError, Finding, Report
from research_recovery.restore import check_workspace, plan_restore, read_inventory
from research_recovery.snapshots import Snapshot

ID = "d" * 64


def listing(*nodes):
    return b"\n".join(
        json.dumps(row).encode() for row in ({"message_type": "snapshot", "id": ID}, *nodes)
    )


def file(name="result.bin", **options):
    return {
        "message_type": "node",
        "name": name.split("/")[-1],
        "path": "/" + name,
        "type": "file",
        "size": 3,
        "mode": 0o600,
        **options,
    }


@pytest.mark.parametrize(
    "node",
    [
        file("../outside"),
        file("sub/file"),
        file("sub\\file"),
        file("NUL"),
        file("a:b"),
        file("a\x1b"),
        file("x."),
        file("a", size=-1),
        file("a", size=True),
        file("a", type="fifo"),
        file("a", type="symlink"),
        file("a", links=2),
        file("a", mode=1 << 23),
    ],
)
def test_unsafe_node(node):
    with pytest.raises(AuditError):
        read_inventory(listing(node), ID, 10, 100)


def test_inventory_bounds():
    with pytest.raises(Finding):
        read_inventory(listing(file()), ID, 1, 2)
    with pytest.raises(Finding):
        read_inventory(listing(file(), file("other")), ID, 1, 100)
    for nodes in [(file("A"), file("a")), (file("a", inode=8), file("b", inode=8))]:
        with pytest.raises(AuditError):
            read_inventory(listing(*nodes), ID, 5, 100)
    with pytest.raises(AuditError):
        read_inventory(listing(file()), "b" * 64, 10, 100)


def test_workspace(tmp_path):
    root = tmp_path.resolve()
    w = root / "work"
    w.mkdir()
    assert check_workspace(w, {root / "repo"}) == w
    for protected in ({root}, {w / "source"}, {w}):
        with pytest.raises(AuditError):
            check_workspace(w, protected)
    (w / "keep").touch()
    with pytest.raises(AuditError):
        check_workspace(w, set())
    assert (w / "keep").exists()


def test_plan_pins_before_listing(tmp_path):
    root = tmp_path.resolve()
    workspace = root / "work"
    workspace.mkdir()

    class Engine:
        repo = root / "repo"
        binary = root / "restic"
        env = ()

        def listing(self, identifier):
            assert identifier == ID
            return io.BytesIO(listing(file()))

    snapshot = Snapshot(ID, datetime.now(UTC), "synthetic", (str(root / "src"),), ())
    args = Namespace(snapshot=ID[:8], max_files=1, max_bytes=3, workspace=str(workspace))
    report = Report("plan-restore")
    plan = plan_restore(Engine(), [snapshot], args, report)
    assert not list(workspace.iterdir()) and plan.inventory.total_bytes == 3
    assert report.restore["allowed"] and not report.restore["executed"]
    with pytest.raises(AuditError):
        plan_restore(Engine(), [snapshot, snapshot], args, report)
    args.snapshot = "latest"
    with pytest.raises(AuditError):
        plan_restore(Engine(), [snapshot], args, report)
