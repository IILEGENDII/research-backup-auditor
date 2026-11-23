from datetime import UTC, datetime

from .models import AuditError, Finding, Report
from .restic import Restic, Result, records
from .snapshots import Snapshot, freshness, select_snapshot


def check_evidence(result: Result) -> bool:
    if result.code not in (0, 1):
        result.require_success()
    summary = None
    for record in records(result.stdout):
        kind = record.get("message_type")
        if summary is not None or kind not in ("status", "summary", "error"):
            raise AuditError("Unexpected repository check output.")
        if kind == "error" and result.code == 0:
            raise AuditError("Conflicting repository check evidence.")
        if kind == "summary":
            summary = record
    if summary is None or type(summary.get("num_errors")) is not int or summary["num_errors"] < 0:
        raise AuditError("Missing or malformed repository check summary.")
    if summary["num_errors"] > 0:
        return False
    result.require_success()
    if (
        summary.get("broken_packs")
        or summary.get("suggest_repair_index")
        or summary.get("suggest_prune")
    ):
        raise AuditError("Repository check summary contains unresolved warnings.")
    return True


def audit(engine: Restic, snapshots: list[Snapshot], args, report: Report) -> None:
    selected, count = select_snapshot(snapshots, args.host, args.path, args.tag)
    age, fresh = freshness(selected, args.max_age_hours, datetime.now(UTC))
    report.snapshot = {
        "selected_id": selected.id,
        "latest_time_utc": selected.time.isoformat(),
        "matched_count": count,
        "selection_status": "unambiguous",
        "age_hours": round(age, 6),
        "max_age_hours": args.max_age_hours,
        "freshness_status": "fresh" if fresh else "stale",
    }
    scope = {"none": "structure", "subset": "subset", "full": "full"}[args.check_data]
    check = report.repository_check = {
        "completed": False,
        "passed": None,
        "data_scope": "unverified",
    }
    result = engine.check(args.check_data, args.subset)
    check.update(return_code=result.code, seconds=result.seconds)
    passed = check_evidence(result)
    check.update(completed=True, passed=passed, data_scope=scope, subset=args.subset)
    report.completed = True
    report.warnings.append(
        {
            "structure": "Repository structure checked. Data packs were not exhaustively read.",
            "subset": "Only the selected group of packs was checked.",
            "full": "All packs were checked. Source completeness remains unverified.",
        }[scope]
    )
    if not passed:
        raise Finding("Restic reported a repository consistency error.")
    if not fresh:
        raise Finding("Selected backup exceeds the freshness limit.")
    report.status = "healthy"
