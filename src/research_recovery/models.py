from dataclasses import dataclass, field


class AuditError(Exception):
    """A sanitized reason the requested operation could not finish."""


class Finding(AuditError):
    """An observed integrity or policy failure."""


@dataclass
class Report:
    operation: str
    status: str = "inconclusive"
    completed: bool = False
    restic_version: str | None = None
    check_mode: str | None = None
    snapshot: dict = field(default_factory=dict)
    repository_check: dict = field(default_factory=dict)
    restore: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        if self.status == "healthy" and not self.completed:
            return 2
        return {"healthy": 0, "warning": 1, "failed": 1, "inconclusive": 2}[self.status]
