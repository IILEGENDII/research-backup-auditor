import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path, PureWindowsPath

from .models import AuditError, Report
from .paths import local_path, overlaps
from .snapshots import Snapshot


def source_paths(snapshots: list[Snapshot]) -> set[Path]:
    paths = set()
    for snapshot in snapshots:
        if not snapshot.paths:
            raise AuditError("Missing source path metadata.")
        for value in snapshot.paths:
            path = Path(value)
            if (
                not path.is_absolute()
                or ".." in path.parts
                or value.startswith(("//", "\\\\"))
                or (os.name == "nt" and (len(path.drive) != 2 or ":" in value[2:]))
                or (os.name != "nt" and (PureWindowsPath(value).drive or "\\" in value))
            ):
                raise AuditError("Cannot establish the local source boundary.")
            if path != Path(path.anchor):
                local_path(path, missing_tail=True)
            paths.add(path)
    return paths


def check_output(value: str, fmt: str, protected: set[Path]) -> Path:
    path = local_path(Path(value).absolute(), existing=False)
    if path.suffix.lower() != (".json" if fmt == "json" else ".txt"):
        raise AuditError("Choose a new report file with the matching .json or .txt extension.")
    if any(overlaps(path, p) for p in protected) or path.exists():
        raise AuditError("Report destination exists or overlaps protected data.")
    if any(part.startswith("recovery-") for part in path.parts):
        raise AuditError("Reports cannot be written inside a restore sandbox.")
    return path


def render(report: Report, fmt: str) -> str:
    data = {"schema_version": "1.0", "tool": "research-recovery", **asdict(report)}
    if fmt == "json":
        return json.dumps(data, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    lines = [f"{report.operation}: {report.status}"]
    for key in (
        "completed",
        "restic_version",
        "check_mode",
        "snapshot",
        "repository_check",
        "restore",
    ):
        if data[key] is not None and data[key] != {}:
            lines.append(f"{key}: {json.dumps(data[key], ensure_ascii=True)}")
    lines.extend(report.warnings + report.errors)
    return "\n".join(lines) + "\n"


def write_report(path: Path, content: str) -> None:
    local_path(path, existing=False)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".audit-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        # os.replace could clobber a file created between validation and publication.
        if os.name == "nt":
            os.rename(name, path)
        else:
            os.link(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
