import os
import re
import stat
import unicodedata
from pathlib import Path

from .models import AuditError


def is_link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def local_path(value: str | Path, *, existing: bool = True, missing_tail: bool = False) -> Path:
    raw = str(value)
    path = Path(value)
    if (
        not path.is_absolute()
        or ".." in path.parts
        or not raw.isprintable()
        or raw.startswith(("//", "\\\\"))
        or path == Path(path.anchor)
    ):
        raise AuditError("Choose an absolute local path below the filesystem root.")
    if os.name == "nt":
        import ctypes

        if not re.fullmatch(r"[A-Za-z]:", path.drive):
            raise AuditError("A local drive is required.")
        if ctypes.windll.kernel32.GetDriveTypeW(path.anchor) not in (2, 3, 6):
            raise AuditError("Use a mounted local disk.")
        for part in path.parts[1:]:
            portable_component(part)
    elif "\\" in raw:
        raise AuditError("Backslashes are not accepted in local paths.")
    for item in (*reversed(path.parents), path):
        try:
            info = item.lstat()
        except FileNotFoundError:
            if missing_tail or (not existing and item == path):
                break
            raise AuditError("Local path does not exist.") from None
        if is_link(info):
            raise AuditError("A local path crosses a link or reparse point.")
    return path


def portable_component(name: str) -> None:
    if (
        not name
        or not name.isprintable()
        or name in (".", "..")
        or name.endswith((".", " "))
        or any(c in '<>:"/\\|?*' for c in name)
        or re.fullmatch(
            r"CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|CLOCK\$|(?:COM|LPT)[0-9¹²³]",
            name.split(".")[0].rstrip().upper(),
        )
        or re.search(r"~[0-9]", name)
        or len(name.encode("utf-8")) > 255
    ):
        raise AuditError("Unsafe path component.")


def overlaps(first: Path, second: Path) -> bool:
    # macOS and Windows can resolve distinct spellings to the same directory.
    a = tuple(unicodedata.normalize("NFC", p).casefold() for p in first.parts)
    b = tuple(unicodedata.normalize("NFC", p).casefold() for p in second.parts)
    n = min(len(a), len(b))
    return a[:n] == b[:n]
