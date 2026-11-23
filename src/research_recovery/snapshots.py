import re
from dataclasses import dataclass
from datetime import UTC, datetime

from .models import AuditError, Finding
from .restic import METADATA_LIMIT, bounded_number, read_json, snapshot_id


@dataclass(frozen=True)
class Snapshot:
    id: str
    time: datetime
    host: str
    paths: tuple[str, ...]
    tags: tuple[str, ...]


def label(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096 or not value.isprintable():
        raise AuditError("Invalid snapshot metadata string.")
    return value


def _labels(values: object) -> tuple[str, ...]:
    if not isinstance(values, list) or len(values) > 1024:
        raise AuditError("Invalid snapshot metadata list.")
    return tuple(sorted(label(value) for value in values))


def parse_snapshots(data: bytes) -> list[Snapshot]:
    if len(data) > METADATA_LIMIT:
        raise AuditError("Snapshot listing exceeds byte limit.")
    rows = read_json(data)
    if not isinstance(rows, list) or len(rows) > 10000:
        raise AuditError("Invalid or excessive snapshot count.")
    seen = set()
    snapshots = []
    for row in rows:
        if not isinstance(row, dict):
            raise AuditError("Invalid snapshot record.")
        identifier = snapshot_id(row.get("id"))
        stamp = row.get("time")
        if (
            identifier in seen
            or not isinstance(stamp, str)
            or not re.fullmatch(
                r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)",
                stamp,
                re.ASCII,
            )
        ):
            raise AuditError("Duplicate ID or invalid snapshot timestamp.")
        try:
            timestamp = datetime.fromisoformat(stamp).astimezone(UTC)
        except (ValueError, OverflowError):
            raise AuditError("Invalid calendar timestamp.") from None
        seen.add(identifier)
        snapshots.append(
            Snapshot(
                identifier,
                timestamp,
                label(row.get("hostname")),
                _labels(row.get("paths")),
                _labels(row.get("tags", [])),
            )
        )
    return snapshots


def select_snapshot(
    snapshots: list[Snapshot], host: str | None, path: str | None, tag: str | None
) -> tuple[Snapshot, int]:
    matches = [
        s
        for s in snapshots
        if (host is None or s.host == host)
        and (path is None or path in s.paths)
        and (tag is None or tag in s.tags)
    ]
    if not matches:
        raise Finding("No snapshot matches the requested scope.")
    if any(not s.paths for s in matches) or len({(s.host, s.paths) for s in matches}) != 1:
        raise AuditError("Ambiguous snapshot scope; narrow the host, path or tag.")
    return max(matches, key=lambda s: (s.time, s.id)), len(matches)


def freshness(snapshot: Snapshot, max_age: float, now: datetime) -> tuple[float, bool]:
    bounded_number(max_age, 87600, "Maximum age")
    age = (now - snapshot.time).total_seconds() / 3600
    if age < 0:
        raise AuditError("Snapshot is in the future; check the clocks.")
    return age, age <= max_age
