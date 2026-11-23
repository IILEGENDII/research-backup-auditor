import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .auditing import audit
from .demo import run_demo
from .models import AuditError, Finding, Report
from .paths import local_path
from .reporting import check_output, render, source_paths, write_report
from .restic import (
    Restic,
    bounded_number,
    child_environment,
    executable,
    snapshot_id,
    subset_fraction,
)
from .restore import execute_restore, plan_restore
from .snapshots import Snapshot, parse_snapshots


class ArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, allow_abbrev=False, **kwargs)

    def error(self, message: str):
        self.exit(2, f"{self.prog}: invalid arguments. Use --help for accepted options.\n")


def parser() -> argparse.ArgumentParser:
    cli = ArgumentParser(prog="research-recovery")
    cli.add_argument("--version", action="version", version=__version__)
    commands = cli.add_subparsers(dest="operation", required=True)
    for name in ("audit", "plan-restore", "restore-test", "demo"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--restic")
        cmd.add_argument("--timeout", type=float, default=120)
        cmd.add_argument("--format", choices=("json", "text"), default="text")
        cmd.add_argument("--output")
        if name != "demo":
            cmd.add_argument("--repo", required=True)
            cmd.add_argument("--password-file")
        if name != "audit":
            cmd.add_argument("--workspace", required=True)
        if name in {"plan-restore", "restore-test"}:
            cmd.add_argument("--snapshot", required=True)
            cmd.add_argument("--max-files", type=int, default=10000)
            cmd.add_argument("--max-bytes", type=int, default=1 << 30)
        if name == "restore-test":
            cmd.add_argument("--execute", action="store_true")
        if name == "audit":
            for selector in ("host", "path", "tag"):
                cmd.add_argument("--" + selector)
            cmd.add_argument("--max-age-hours", type=float, default=72)
            cmd.add_argument("--check-data", choices=("none", "subset", "full"), default="none")
            cmd.add_argument("--subset")
    return cli


def open_repository(
    args: argparse.Namespace, binary: Path, report: Report
) -> tuple[Restic, list[Snapshot]]:
    repo = local_path(args.repo)
    if not repo.is_dir():
        raise AuditError("Expected a local repository directory.")
    for name in ("config", "data", "index", "keys", "locks", "snapshots"):
        local_path(repo / name, existing=False)
    password_file = args.password_file or os.environ.get("RESTIC_PASSWORD_FILE")
    env = child_environment(os.environ.get("RESTIC_PASSWORD"), password_file)
    engine = Restic(binary, repo, env, args.timeout)
    report.restic_version = engine.version()
    return engine, parse_snapshots(engine.snapshots())


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    report = Report(args.operation, check_mode=getattr(args, "check_data", None))
    output = None
    try:
        bounded_number(args.timeout, 86400, "Timeout")
        if args.operation == "audit":
            bounded_number(args.max_age_hours, 87600, "Maximum age")
            if args.check_data == "subset":
                args.subset = subset_fraction("1/5" if args.subset is None else args.subset)
            elif args.subset is not None:
                raise AuditError("--subset requires --check-data subset.")
        elif args.operation != "demo":
            snapshot_id(args.snapshot, prefix=True)
        binary = executable(args.restic)
        if args.operation == "demo":
            workspace = local_path(args.workspace)
            if args.output:
                output = check_output(args.output, args.format, {binary, workspace})
            run_demo(workspace, binary, args.timeout, report)
        else:
            engine, snapshots = open_repository(args, binary, report)
            if args.output:
                protected = source_paths(snapshots) | {engine.repo, binary}
                if getattr(args, "workspace", None):
                    protected.add(local_path(args.workspace))
                output = check_output(args.output, args.format, protected)
            if args.operation == "audit":
                audit(engine, snapshots, args, report)
            else:
                plan = plan_restore(engine, snapshots, args, report)
                if getattr(args, "execute", False):
                    execute_restore(engine, plan, report)
                report.status = "healthy"
                report.completed = True
    except Finding as exc:
        report.status = "failed"
        report.errors.append(str(exc))
    except AuditError as exc:
        report.status = "inconclusive"
        report.completed = False
        report.errors.append(str(exc))
    except (OSError, UnicodeError):
        report.status = "inconclusive"
        report.completed = False
        report.errors.append("Local filesystem or encoding error.")
    if output is not None:
        try:
            write_report(output, render(report, args.format))
            return report.exit_code
        except (OSError, AuditError):
            report.status = "inconclusive"
            report.completed = False
            report.errors.append("Cannot publish report at the selected destination.")
    sys.stdout.write(render(report, args.format))
    return report.exit_code
