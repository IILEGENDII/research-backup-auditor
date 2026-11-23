import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from research_recovery import restic
from research_recovery.models import AuditError, Finding
from research_recovery.snapshots import freshness, parse_snapshots, select_snapshot


def row(**updates):
    return {
        "id": "a" * 64,
        "time": "2025-01-01T02:00:00+02:00",
        "hostname": "host",
        "paths": ["/research"],
        **updates,
    }


def test_selection():
    rows = [row(), row(id="b" * 64, hostname="elsewhere", time="2026-01-01T00:00:00Z")]
    snapshots = parse_snapshots(json.dumps(rows).encode())
    with pytest.raises(AuditError, match="Ambiguous"):
        select_snapshot(snapshots, None, None, None)
    with pytest.raises(Finding):
        select_snapshot(snapshots, None, "/absent", None)
    selected, count = select_snapshot(snapshots, "host", "/research", None)
    assert count == 1 and selected.id == "a" * 64
    now = datetime(2025, 1, 2, tzinfo=UTC)
    assert freshness(selected, 24, now) == (24, True)
    assert not freshness(selected, 24, now + timedelta(microseconds=1))[1]
    with pytest.raises(AuditError, match="future"):
        freshness(selected, 24, selected.time - timedelta(seconds=1))


@pytest.mark.parametrize(
    "value",
    [
        {},
        [None],
        [row(id="-x")],
        [row(time="2025-01-01")],
        [row(time="2025-02-31T00:00:00Z")],
        [row(), row()],
        [row(paths="x")],
        [row(hostname="x\x1b")],
    ],
)
def test_invalid_inventory(value):
    with pytest.raises(AuditError):
        parse_snapshots(json.dumps(value).encode())


@pytest.mark.parametrize(
    "data", [b"\xff", b"{", b'{"x":1,"x":2}', b"NaN", b"1e999", b"[" * 50 + b"]" * 50]
)
def test_invalid_json(data):
    with pytest.raises(AuditError):
        restic.read_json(data)


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), 1e15])
def test_invalid_limits(value):
    with pytest.raises(AuditError):
        restic.bounded_number(value, 87600, "Maximum age")


@pytest.mark.parametrize("verb", ["init", "backup", "unlock", "forget", "prune", "repair", "dump"])
def test_restricted_runner(tmp_path, verb):
    engine = restic.Restic(Path("restic"), tmp_path, {}, 1)
    with pytest.raises(AuditError):
        engine._command(verb)


def test_arguments_and_environment(tmp_path, monkeypatch):
    commands = []

    def capture(argv, env, timeout, limit, **kwargs):
        commands.append(argv)
        return restic.Result(0, b"[]", 0)

    monkeypatch.setattr(restic, "_capture", capture)
    monkeypatch.setenv("RESTIC_PASSWORD_COMMAND", "never run this")
    env = restic.child_environment("synthetic", None)
    assert "RESTIC_PASSWORD_COMMAND" not in env
    repo = tmp_path / "space λ"
    engine = restic.Restic(Path("restic"), repo, env, 2)
    engine.snapshots()
    engine.check("subset", "1/5")
    engine.check("full", None)
    with engine.listing("b" * 64):
        pass
    assert commands == [
        ["restic", "--no-cache", "-r", str(repo), *tail]
        for tail in (
            ["snapshots", "--json"],
            ["check", "--json", "--read-data-subset=1/5"],
            ["check", "--json", "--read-data"],
            ["ls", "--json", "--long", "b" * 64],
        )
    ]
    with pytest.raises(AuditError), engine.listing("--delete"):
        pytest.fail("invalid ID reached listing")
    with pytest.raises(AuditError):
        engine.check("subset", "1/0")
    assert len(commands) == 4


def test_bounded_process():
    def run(code, timeout=10):
        return restic._capture([sys.executable, "-I", "-c", code], dict(os.environ), timeout, 8)

    assert run("print(7)").stdout.strip() == b"7"
    assert run("raise SystemExit(9)").code == 9
    with pytest.raises(AuditError, match="timed out"):
        run("import time; time.sleep(10)", 0.1)
    for stream in ("stdout", "stderr"):
        with pytest.raises(AuditError, match="limit"):
            run(f"import sys; sys.{stream}.buffer.write(bytes(2**21))")
