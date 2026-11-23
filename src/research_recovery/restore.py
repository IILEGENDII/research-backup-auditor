import hashlib
import os
import shutil
import stat
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .models import AuditError, Finding, Report
from .paths import is_link, local_path, overlaps, portable_component
from .reporting import source_paths
from .restic import Restic, records, snapshot_id
from .snapshots import Snapshot

MAX_NODES = 50000
MAX_BYTES = 16 << 30


@dataclass(frozen=True)
class Inventory:
    files: dict[str, int]
    directories: set[str]
    total_bytes: int


def read_inventory(
    data: bytes | BinaryIO, identifier: str, max_files: int, max_bytes: int
) -> Inventory:
    lines = records(data)
    header = next(lines, None)
    if not header or header.get("message_type") != "snapshot" or header.get("id") != identifier:
        raise AuditError("Inventory does not identify the pinned snapshot.")
    files = {}
    directories = set()
    spellings = set()
    inodes = set()
    total = 0
    for node in lines:
        path = node.get("path")
        if (
            node.get("message_type") != "node"
            or not isinstance(path, str)
            or not path.startswith("/")
            or not path.isprintable()
            or len(path.encode("utf-8")) > 4096
            or unicodedata.normalize("NFC", path) != path
        ):
            raise AuditError("Invalid inventory node or path.")
        name = path[1:]
        parts = name.split("/")
        if len(parts) > 64 or len(spellings) >= MAX_NODES:
            raise AuditError("Inventory exceeds the node or depth limit.")
        for part in parts:
            portable_component(part)
        folded = name.casefold()
        if node.get("name") != parts[-1] or folded in spellings:
            raise AuditError("Duplicate or ambiguous archive name.")
        spellings.add(folded)
        kind = node.get("type")
        mode = node.get("mode")
        if (
            kind not in ("dir", "file")
            or type(mode) is not int
            or mode < 0
            or mode & ~(0o777 | (1 << 31 if kind == "dir" else 0))
        ):
            raise AuditError("Unsupported node type or mode in snapshot.")
        if kind == "dir":
            directories.add(name)
            continue
        size = node.get("size")
        # The JSON listing omits link counts; repeated inode numbers can indicate hard links.
        inode = node.get("inode", 0)
        links = node.get("links", 1)
        if (
            type(inode) is not int
            or inode < 0
            or type(links) is not int
            or links != 1
            or (inode and inode in inodes)
        ):
            raise AuditError("Possible hard link or invalid inode metadata.")
        if inode:
            inodes.add(inode)
        if type(size) is not int or size < 0:
            raise AuditError("Invalid regular file size.")
        total += size
        files[name] = size
        if len(files) > max_files or total > max_bytes:
            raise Finding("Snapshot exceeds the configured restore budget.")
    if not files:
        raise AuditError("No regular files available for a recovery test.")
    for name in (*files, *directories):
        parent, _, _ = name.rpartition("/")
        if parent and parent not in directories:
            raise AuditError("Missing or inconsistent parent directory.")
    return Inventory(files, directories, total)


def check_workspace(value: str | Path, protected: set[Path]) -> Path:
    workspace = local_path(value)
    if (
        not workspace.is_dir()
        or Path.home().is_relative_to(workspace)
        or Path.cwd().is_relative_to(workspace)
        or any(overlaps(workspace, p) for p in protected)
    ):
        raise AuditError("Workspace overlaps a protected location or is not a directory.")
    info = workspace.stat()
    if os.name == "posix" and (info.st_uid != os.geteuid() or info.st_mode & 0o022):
        raise AuditError("Use a workspace owned by this user without shared write access.")
    with os.scandir(workspace) as entries:
        if next(entries, None) is not None:
            raise AuditError("Choose an empty dedicated workspace.")
    return workspace


@dataclass(frozen=True)
class Plan:
    snapshot: Snapshot
    inventory: Inventory
    workspace: Path
    protected: set[Path]


def plan_restore(engine: Restic, snapshots: list[Snapshot], args, report: Report) -> Plan:
    prefix = snapshot_id(args.snapshot, prefix=True)
    matches = [s for s in snapshots if s.id.startswith(prefix)]
    if len(matches) != 1:
        raise AuditError("Snapshot ID is absent or ambiguous.")
    if not 1 <= args.max_files <= MAX_NODES or not 1 <= args.max_bytes <= MAX_BYTES:
        raise AuditError("Restore budgets exceed supported bounds.")
    protected = source_paths(snapshots) | {engine.repo, engine.binary}
    if "RESTIC_PASSWORD_FILE" in engine.env:
        protected.add(Path(engine.env["RESTIC_PASSWORD_FILE"]))
    workspace = check_workspace(args.workspace, protected)
    selected = matches[0]
    report.snapshot = {"selected_id": selected.id, "selection_status": "pinned"}
    report.restore = {
        "executed": False,
        "allowed": False,
        "max_files": args.max_files,
        "max_bytes": args.max_bytes,
        "target_policy": "new private child of empty workspace",
    }
    with engine.listing(selected.id) as listing:
        inventory = read_inventory(listing, selected.id, args.max_files, args.max_bytes)
    if shutil.disk_usage(workspace).free < inventory.total_bytes:
        raise Finding("Insufficient available workspace storage.")
    report.restore.update(
        allowed=True,
        files=len(inventory.files),
        directories=len(inventory.directories),
        logical_bytes=inventory.total_bytes,
    )
    report.warnings.append("Estimates use snapshot metadata. Available disk space can change.")
    return Plan(selected, inventory, workspace, protected)


def require_unprivileged() -> None:
    if os.name == "nt":
        import ctypes

        elevated = ctypes.windll.shell32.IsUserAnAdmin()
    else:
        elevated = os.geteuid() == 0
    if elevated:
        raise AuditError("Restore tests require a non-elevated user account.")


def inspect_restore(
    root: Path, inventory: Inventory, *, digests: dict[str, str] | None = None
) -> None:
    seen_files = set()
    seen_dirs = set()
    root_stat = local_path(root).lstat()

    def visit(path, prefix, expected, parent_fd=None):
        fd = None
        try:
            if os.name == "posix":
                fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
            opened = os.fstat(fd) if fd is not None else local_path(path).lstat()
            if not os.path.samestat(opened, expected) or is_link(opened):
                raise Finding("Restored directory identity changed.")
            with os.scandir(fd if fd is not None else path) as children:
                for entry in children:
                    name = prefix + entry.name
                    child = entry.name if fd is not None else Path(path) / entry.name
                    info = os.stat(child, dir_fd=fd, follow_symlinks=False)
                    if is_link(info) or info.st_dev != root_stat.st_dev:
                        raise Finding("Unexpected link or filesystem in restored data.")
                    if name in inventory.directories and stat.S_ISDIR(info.st_mode):
                        seen_dirs.add(name)
                        visit(child, name + "/", info, fd)
                    elif (
                        name in inventory.files
                        and stat.S_ISREG(info.st_mode)
                        and info.st_nlink == 1
                        and info.st_size == inventory.files[name]
                    ):
                        seen_files.add(name)
                        if digests is not None:
                            flags = (
                                os.O_RDONLY
                                | getattr(os, "O_NOFOLLOW", 0)
                                | getattr(os, "O_NONBLOCK", 0)
                                | getattr(os, "O_BINARY", 0)
                            )
                            with os.fdopen(os.open(child, flags, dir_fd=fd), "rb") as stream:
                                if not os.path.samestat(info, os.fstat(stream.fileno())):
                                    raise Finding("Restored file identity changed.")
                                digest = hashlib.sha256()
                                remaining = info.st_size
                                while remaining:
                                    block = stream.read(min(1 << 20, remaining))
                                    if not block:
                                        raise Finding("Restored file ended early.")
                                    digest.update(block)
                                    remaining -= len(block)
                                if stream.read(1) or digest.hexdigest() != digests.get(name):
                                    raise Finding(
                                        "Restored content differs from the synthetic baseline."
                                    )
                    else:
                        raise Finding("Restored entries differ in name, size, type or link count.")
            after = os.stat(path, dir_fd=parent_fd, follow_symlinks=False)
            if not os.path.samestat(after, opened) or after.st_mtime_ns != opened.st_mtime_ns:
                raise Finding("Restored directory changed during inspection.")
        finally:
            if fd is not None:
                os.close(fd)

    visit(root, "", root_stat)
    if (
        seen_files != inventory.files.keys()
        or seen_dirs != inventory.directories
        or (digests is not None and seen_files != digests.keys())
    ):
        raise Finding("Restored inventory is incomplete.")


def execute_restore(
    engine: Restic, plan: Plan, report: Report, *, digests: dict[str, str] | None = None
) -> None:
    require_unprivileged()
    workspace = check_workspace(plan.workspace, plan.protected)
    target = Path(tempfile.mkdtemp(dir=workspace, prefix="recovery-"))
    identity = target.lstat()
    report.restore.update(executed=True, sandbox=target.name, verified=False)
    report.warnings.append("Plaintext may remain in the named sandbox, including after failure.")
    if local_path(target).parent != workspace or not os.path.samestat(identity, target.lstat()):
        raise AuditError("New restore directory changed.")
    result = engine._restore(plan.snapshot.id, target)
    report.restore.update(return_code=result.code, seconds=result.seconds)
    result.require_success()
    summary = None
    for record in records(result.stdout):
        kind = record.get("message_type")
        if kind not in ("status", "summary") or summary is not None:
            raise AuditError("Unexpected restore output.")
        if kind == "summary":
            summary = record
    if (
        not summary
        or type(summary.get("total_files")) is not int
        or summary["total_files"] < len(plan.inventory.files)
    ):
        raise AuditError("Missing or incomplete restore summary.")
    for key in ("total_bytes", "bytes_restored"):
        count = summary.get(key, 0)
        if type(count) is not int or count != plan.inventory.total_bytes:
            raise Finding("Restored byte count differs from the plan.")
    if any(summary.get(k, 0) != 0 for k in ("files_skipped", "files_deleted", "bytes_skipped")):
        raise Finding("Restore skipped or removed entries.")
    if not os.path.samestat(identity, local_path(target).lstat()):
        raise Finding("Restore sandbox identity changed.")
    inspect_restore(target, plan.inventory, digests=digests)
    report.restore.update(
        verified=True,
        observed_files=len(plan.inventory.files),
        observed_bytes=plan.inventory.total_bytes,
        independent_sha256=digests is not None,
    )
    if digests is None:
        report.warnings.append("Original-source equivalence has no independent digest baseline.")
