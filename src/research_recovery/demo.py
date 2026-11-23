import hashlib
import secrets
import struct
import tempfile
from argparse import Namespace
from pathlib import Path

from .auditing import audit
from .models import AuditError, Report
from .paths import local_path
from .restic import Restic, _capture, child_environment
from .restore import check_workspace, execute_restore, plan_restore, require_unprivileged
from .snapshots import parse_snapshots


class DemoFixture:
    def __init__(self, workspace: Path, binary: Path, timeout: float):
        require_unprivileged()
        parent = check_workspace(workspace, {binary})
        self.root = Path(tempfile.mkdtemp(prefix="demo-", dir=parent))
        self.source = self.root / "source"
        self.source.mkdir(mode=0o700)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir(mode=0o700)
        self.engine = Restic(
            binary,
            self.root / "repository",
            child_environment(secrets.token_urlsafe(32), None),
            timeout,
        )
        self.version = self.engine.version()
        files = {
            "parameters.csv": b"step,field\n0,1.0\n1,2.5\n",
            "mesh.bin": struct.pack("<8d", *range(8)),
            "noise.bin": secrets.token_bytes(512 * 1024),
        }
        self.digests = {}
        for name, content in files.items():
            (self.source / name).write_bytes(content)
            self.digests["source/" + name] = hashlib.sha256(content).hexdigest()
        self._fixture_operation("init")

    def _fixture_operation(self, operation: str, *, historical: bool = False) -> None:
        repo = self.root / "repository"
        if self.engine.repo != repo or local_path(self.source).parent != self.root:
            raise AuditError("Invalid synthetic fixture layout.")
        if operation == "init":
            flags = ["init"]
        elif operation == "backup":
            flags = ["backup", "--host", "synthetic-workstation", "--tag"]
            if historical:
                flags.extend(["historical", "--time", "2001-01-01 00:00:00"])
            else:
                flags.append("current")
            flags.append("source")
        else:
            raise AuditError("Unsupported fixture operation.")
        command = [str(self.engine.binary), "--no-cache", "-r", str(repo), *flags]
        _capture(
            command, self.engine.env, self.engine.timeout, 1 << 20, cwd=self.root
        ).require_success()

    def backup(self, *, historical: bool = False) -> None:
        self._fixture_operation("backup", historical=historical)


def run_demo(workspace: Path, binary: Path, timeout: float, report: Report) -> None:
    fixture = DemoFixture(workspace, binary, timeout)
    report.restic_version = fixture.version
    report.warnings.append(
        "The disposable repository and plaintext remain in " + fixture.root.name + "."
    )
    fixture.backup()
    snapshots = parse_snapshots(fixture.engine.snapshots())
    policy = Namespace(
        host="synthetic-workstation",
        path=None,
        tag="current",
        max_age_hours=72,
        check_data="full",
        subset=None,
    )
    report.check_mode = "full"
    audit(fixture.engine, snapshots, policy, report)
    report.completed = False
    report.status = "inconclusive"
    args = Namespace(
        snapshot=report.snapshot["selected_id"],
        max_files=10,
        max_bytes=1 << 20,
        workspace=str(fixture.workspace),
    )
    plan = plan_restore(fixture.engine, snapshots, args, report)
    execute_restore(fixture.engine, plan, report, digests=fixture.digests)
    report.status = "healthy"
    report.completed = True
