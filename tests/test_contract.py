import pytest

from research_recovery.cli import main, parser
from research_recovery.models import Report


@pytest.mark.parametrize("verb", ["init", "backup", "prune", "forget", "unlock", "repair"])
def test_no_maintenance_command(verb):
    with pytest.raises(SystemExit) as err:
        parser().parse_args([verb])
    assert err.value.code == 2


def test_default_is_inconclusive():
    assert Report("audit").exit_code == 2
    assert Report("audit", status="healthy", completed=False).exit_code == 2
    assert parser().parse_args(["audit", "--repo", "fixture"]).check_data == "none"
    assert (
        not parser()
        .parse_args(["restore-test", "--repo", "r", "--snapshot", "s", "--workspace", "w"])
        .execute
    )


def test_version(capsys):
    with pytest.raises(SystemExit) as result:
        main(["--version"])
    assert result.value.code == 0
    assert capsys.readouterr().out.strip() == "0.1.0"


def test_explicit_execute_required(capsys):
    with pytest.raises(SystemExit) as error:
        main(["restore-test", "--repo", "r", "--workspace", "w", "--snapshot", "a" * 64, "--exec"])
    assert error.value.code == 2
    with pytest.raises(SystemExit):
        main(["private\x1b-input"])
    assert "private" not in capsys.readouterr().err
