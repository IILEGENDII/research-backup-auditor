import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from argparse import Namespace
from pathlib import Path

import pytest

from research_recovery.auditing import audit
from research_recovery.demo import DemoFixture
from research_recovery.models import AuditError, Report
from research_recovery.restic import executable
from research_recovery.snapshots import parse_snapshots

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def binary():
    value = os.environ.get("AUDITOR_TEST_RESTIC") or shutil.which("restic")
    if not value:
        pytest.skip("requires a verified local restic 0.20.0 executable")
    return executable(value)


def command(binary, operation, *args, password=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("RESTIC_")}
    if password:
        env["RESTIC_PASSWORD"] = password
    p = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "research_recovery",
            operation,
            "--format",
            "json",
            "--restic",
            str(binary),
            *map(str, args),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
        check=False,
    )
    report = json.loads(p.stdout)
    assert not p.stderr and report["schema_version"] == "1.0"
    if password:
        assert password not in p.stdout
    return p.returncode, report


@pytest.fixture(scope="module")
def backup(binary):
    with tempfile.TemporaryDirectory(prefix="auditor-test-") as directory:
        root = Path(directory).resolve()
        fixture = DemoFixture(root, binary, 90)
        password = fixture.engine.env["RESTIC_PASSWORD"]
        code, empty = command(binary, "audit", "--repo", fixture.engine.repo, password=password)
        assert code == 1 and empty["status"] == "failed"
        expected = {
            p.name: hashlib.sha256(p.read_bytes()).digest() for p in fixture.source.iterdir()
        }
        fixture.backup(historical=True)
        fixture.backup()
        yield fixture, expected


@pytest.mark.parametrize(
    ("mode", "label"), [("none", "structure"), ("subset", "subset"), ("full", "full")]
)
def test_audit_real(backup, binary, mode, label):
    fixture, _ = backup
    code, report = command(
        binary,
        "audit",
        "--repo",
        fixture.engine.repo,
        "--check-data",
        mode,
        "--host",
        "synthetic-workstation",
        "--tag",
        "current",
        password=fixture.engine.env["RESTIC_PASSWORD"],
    )
    assert code == 0 and report["completed"] and report["restic_version"] == "0.20.0"
    assert (
        report["repository_check"]["data_scope"] == label and report["repository_check"]["passed"]
    )
    assert report["snapshot"]["matched_count"] == 1
    assert "synthetic-workstation" not in json.dumps(report)


def test_history_and_credentials(backup, binary):
    fixture, _ = backup
    args = ("--repo", fixture.engine.repo)
    password = fixture.engine.env["RESTIC_PASSWORD"]
    code, old = command(binary, "audit", *args, "--tag", "historical", password=password)
    assert code == 1 and old["snapshot"]["freshness_status"] == "stale"
    code, missing = command(binary, "audit", *args, "--host", "absent", password=password)
    assert code == 1 and missing["status"] == "failed"
    code, wrong = command(binary, "audit", *args, password=secrets.token_urlsafe(24))
    assert code == 2 and wrong["status"] == "inconclusive"
    code, missing = command(binary, "audit", "--repo", fixture.root / "absent", password=password)
    assert code == 2


def test_isolated_restore(backup, binary):
    fixture, expected = backup
    password = fixture.engine.env["RESTIC_PASSWORD"]
    repo = fixture.engine.repo

    def repository_files():
        return {
            p.relative_to(repo): hashlib.sha256(p.read_bytes()).digest()
            for p in repo.rglob("*")
            if p.is_file() and "locks" not in p.relative_to(repo).parts
        }

    before = repository_files()
    _, audit = command(binary, "audit", "--repo", repo, "--tag", "current", password=password)
    identifier = audit["snapshot"]["selected_id"]
    args = ("--repo", repo, "--snapshot", identifier[:16], "--workspace", fixture.workspace)
    for op in ("plan-restore", "restore-test"):
        code, plan = command(binary, op, *args, password=password)
        assert (
            code == 0 and not plan["restore"]["executed"] and not list(fixture.workspace.iterdir())
        )
    code, refused = command(
        binary, "restore-test", *args, "--max-bytes", 1, "--execute", password=password
    )
    assert code == 1 and not refused["restore"]["allowed"] and not list(fixture.workspace.iterdir())
    code, bad = command(
        binary,
        "restore-test",
        "--repo",
        repo,
        "--snapshot",
        identifier,
        "--workspace",
        fixture.source,
        "--execute",
        password=password,
    )
    assert code == 2 and bad["status"] == "inconclusive"
    code, result = command(binary, "restore-test", *args, "--execute", password=password)
    assert (
        code == 0 and result["restore"]["verified"] and not result["restore"]["independent_sha256"]
    )
    assert result["snapshot"]["selected_id"] == identifier
    restored = fixture.workspace / result["restore"]["sandbox"] / "source"
    for path in (fixture.source, restored):
        assert {p.name: hashlib.sha256(p.read_bytes()).digest() for p in path.iterdir()} == expected
    assert repository_files() == before


def test_pack_corruption(backup, binary):
    fixture, _ = backup
    copy = fixture.root / "damaged-copy"
    shutil.copytree(fixture.engine.repo, copy)
    pack = max(
        (p for p in (copy / "data").rglob("*") if p.is_file()), key=lambda p: p.stat().st_size
    )
    with pack.open("r+b") as handle:
        first = handle.read(1)
        handle.seek(0)
        handle.write(bytes([first[0] ^ 1]))
    code, report = command(
        binary,
        "audit",
        "--repo",
        copy,
        "--check-data",
        "full",
        password=fixture.engine.env["RESTIC_PASSWORD"],
    )
    assert (
        code == 1 and report["status"] == "failed" and report["repository_check"]["passed"] is False
    )


def test_demo_real(binary):
    with tempfile.TemporaryDirectory() as workspace:
        code, report = command(binary, "demo", "--workspace", Path(workspace).resolve())
        assert code == 0 and report["restore"]["independent_sha256"]
        assert report["restore"]["observed_files"] == 3


def test_interrupted_full_check(backup, monkeypatch):
    fixture, _ = backup
    engine = fixture.engine
    snapshots = parse_snapshots(engine.snapshots())
    monkeypatch.setattr(engine, "timeout", 0.001)
    report = Report("audit", check_mode="full")
    options = Namespace(
        host=None, path=None, tag="current", max_age_hours=72, check_data="full", subset=None
    )
    with pytest.raises(AuditError, match="timed out"):
        audit(engine, snapshots, options, report)
    assert report.exit_code == 2 and not report.repository_check["completed"]
