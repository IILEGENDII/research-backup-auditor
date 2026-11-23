import io
import json
import math
import os
import re
import stat
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .models import AuditError
from .paths import local_path

METADATA_LIMIT = 8 << 20
LISTING_LIMIT = 32 << 20
LINE_LIMIT = 128 << 10
SUPPORTED_VERSION = "0.20.0"


def bounded_number(value: float, maximum: float, label: str) -> float:
    if not math.isfinite(value) or not 0 < value <= maximum:
        raise AuditError(f"{label} must be positive, finite and within its limit.")
    return value


def snapshot_id(value: object, *, prefix: bool = False) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        "[0-9a-f]{8,64}" if prefix else "[0-9a-f]{64}", value
    ):
        raise AuditError("Expected a lowercase hexadecimal snapshot ID.")
    return value


def subset_fraction(value: str | None) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,3}/[1-9][0-9]{0,3}", value):
        raise AuditError("Use a subset in n/t form.")
    part, total = map(int, value.split("/"))
    if part > total or total < 2:
        raise AuditError("Choose a valid partial pack group.")
    return value


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def read_json(data: bytes):
    depth = tokens = 0
    quoted = escaped = False
    for byte in data:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (91, 123):
            depth += 1
        elif byte in (93, 125):
            depth -= 1
        elif byte in (44, 58):
            tokens += 1
        if depth > 24 or tokens > 300000:
            raise AuditError("Restic JSON exceeds the structural limits.")

    def number(text):
        value = float(text)
        if not math.isfinite(value):
            raise ValueError
        return value

    try:
        return json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_unique,
            parse_constant=number,
            parse_float=number,
        )
    except (ValueError, RecursionError):
        raise AuditError("Malformed restic JSON.") from None


def records(data: bytes | BinaryIO) -> Iterator[dict]:
    stream = io.BytesIO(data) if isinstance(data, bytes) else data
    while line := stream.readline(LINE_LIMIT + 1):
        if len(line) > LINE_LIMIT:
            raise AuditError("Restic record exceeds the line limit.")
        obj = read_json(line)
        if not isinstance(obj, dict):
            raise AuditError("Expected a restic record.")
        yield obj


@dataclass(frozen=True)
class Result:
    code: int
    stdout: bytes
    seconds: float

    def require_success(self) -> None:
        if self.code:
            reasons = {
                10: "Repository unavailable.",
                11: "Repository locked.",
                12: "Authentication failed.",
            }
            raise AuditError(reasons.get(self.code, "Restic could not complete the operation."))


def _capture(
    command: list[str],
    env: dict[str, str],
    timeout: float,
    limit: int,
    *,
    cwd: Path | None = None,
    sink: BinaryIO | None = None,
) -> Result:
    started = time.monotonic()
    with subprocess.Popen(
        command,
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=env,
    ) as child:
        overflow = threading.Event()
        output = bytearray()

        errors = []

        def drain(pipe, cap, keep):
            size = 0
            try:
                while block := pipe.read(65536):
                    size += len(block)
                    if size > cap:
                        overflow.set()
                        child.kill()
                        return
                    if keep:
                        if sink is None:
                            output.extend(block)
                        else:
                            sink.write(block)
            except OSError as exc:
                errors.append(exc)
                child.kill()

        threads = [
            threading.Thread(target=drain, args=(child.stdout, limit, True)),
            threading.Thread(target=drain, args=(child.stderr, 1 << 20, False)),
        ]
        for thread in threads:
            thread.start()
        try:
            child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            raise AuditError("Restic timed out.") from None
        finally:
            if child.poll() is None:
                child.kill()
            child.wait()
            for thread in threads:
                thread.join()
        if overflow.is_set():
            raise AuditError("Restic output exceeded the capture limit.")
        if errors:
            raise AuditError("Could not capture complete restic output.")
        return Result(child.returncode, bytes(output), round(time.monotonic() - started, 3))


def executable(value: str | None) -> Path:
    if value is None:
        # Relative PATH entries would make the selected binary depend on the working directory.
        for directory in os.get_exec_path():
            candidate = Path(directory) / ("restic.exe" if os.name == "nt" else "restic")
            if not candidate.is_absolute() or candidate.parent == Path.cwd():
                continue
            try:
                local_path(candidate)
            except (AuditError, OSError):
                continue
            if candidate.is_file() and os.access(candidate, os.X_OK):
                value = str(candidate)
                break
    if not value:
        raise AuditError(
            "Install restic 0.20.0 or supply --restic with an absolute executable path."
        )
    path = local_path(value, existing=False)
    if not path.exists():
        raise AuditError("Install restic 0.20.0 or select an existing executable with --restic.")
    if (
        not path.is_file()
        or not os.access(path, os.X_OK)
        or (os.name == "nt" and path.suffix.lower() != ".exe")
    ):
        raise AuditError("Expected a trusted local restic executable.")
    return path


def child_environment(password: str | None, password_file: str | None) -> dict[str, str]:
    env = {
        k: os.environ[k]
        for k in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR")
        if k in os.environ
    }
    env.update(LC_ALL="C", TZ="UTC")
    if password_file:
        path = local_path(password_file)
        if not stat.S_ISREG(path.lstat().st_mode):
            raise AuditError("Expected a regular password file.")
        env["RESTIC_PASSWORD_FILE"] = str(path)
    elif password:
        env["RESTIC_PASSWORD"] = password
    else:
        raise AuditError("Set RESTIC_PASSWORD or select a protected password file.")
    return env


class Restic:
    def __init__(self, binary: Path, repo: Path, env: dict[str, str], timeout: float):
        self.binary = binary
        self.repo = repo
        self.env = env
        self.timeout = bounded_number(timeout, 86400, "Timeout")

    def version(self) -> str:
        result = _capture([str(self.binary), "version"], self.env, self.timeout, 4096)
        result.require_success()
        if not re.fullmatch(
            rb"restic 0\.20\.0 compiled with go[^\s]+ on [a-z0-9]+/[a-z0-9]+\s*", result.stdout
        ):
            raise AuditError("Unsupported restic version or version response; use 0.20.0.")
        return SUPPORTED_VERSION

    def _command(self, verb: str) -> list[str]:
        if verb not in {"snapshots", "check", "ls", "restore"}:
            raise AuditError("Unsupported restic operation.")
        return [str(self.binary), "--no-cache", "-r", str(self.repo), verb, "--json"]

    def snapshots(self) -> bytes:
        result = _capture(self._command("snapshots"), self.env, self.timeout, METADATA_LIMIT)
        result.require_success()
        return result.stdout

    def check(self, mode: str, subset: str | None) -> Result:
        if mode == "subset":
            flags = ["--read-data-subset=" + subset_fraction(subset)]
        elif mode in ("none", "full") and subset is None:
            flags = ["--read-data"] if mode == "full" else []
        else:
            raise AuditError("Invalid check mode or unexpected subset.")
        return _capture(self._command("check") + flags, self.env, self.timeout, METADATA_LIMIT)

    @contextmanager
    def listing(self, identifier: str) -> Iterator[BinaryIO]:
        command = self._command("ls") + ["--long", snapshot_id(identifier)]
        with tempfile.SpooledTemporaryFile(max_size=1 << 20) as stream:
            result = _capture(command, self.env, self.timeout, LISTING_LIMIT, sink=stream)
            result.require_success()
            stream.seek(0)
            yield stream

    def _restore(self, identifier: str, target: Path) -> Result:
        command = self._command("restore") + [
            snapshot_id(identifier),
            "--target",
            str(target),
            "--overwrite",
            "never",
            "--exclude-xattr",
            "*",
            "--verify",
        ]
        return _capture(command, self.env, self.timeout, METADATA_LIMIT)
