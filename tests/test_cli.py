from pathlib import Path

from typer.testing import CliRunner

from scraper.cli import app
from scraper.version import __version__


runner = CliRunner()


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_init_config_command(tmp_path) -> None:
    target = tmp_path / "scraper.yml"
    result = runner.invoke(app, ["init-config", str(target)])
    assert result.exit_code == 0
    assert target.exists()
    assert "user_agent:" in target.read_text(encoding="utf-8")
