from pathlib import Path

import pytest

from scripts import run_postgres_tests as runner


def create_fake_postgres_bin(path: Path) -> None:
    path.mkdir(parents=True)
    for tool in runner.REQUIRED_POSTGRES_TOOLS:
        for name in runner.tool_names(tool):
            executable = path / name
            executable.write_text("", encoding="utf-8")
            executable.chmod(0o755)


def test_find_postgres_bin_prefers_postgres_bin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_bin = tmp_path / "env-bin"
    path_bin = tmp_path / "path-bin"
    create_fake_postgres_bin(env_bin)
    create_fake_postgres_bin(path_bin)
    monkeypatch.setenv("POSTGRES_BIN", str(env_bin))
    monkeypatch.setenv("PATH", str(path_bin))

    assert runner.find_postgres_bin() == env_bin.resolve()


def test_find_postgres_bin_uses_path_before_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path_bin = tmp_path / "path-bin"
    default_bin = tmp_path / "default-bin"
    create_fake_postgres_bin(path_bin)
    create_fake_postgres_bin(default_bin)
    monkeypatch.delenv("POSTGRES_BIN", raising=False)
    monkeypatch.setenv("PATH", str(path_bin))
    monkeypatch.setattr(runner, "DEFAULT_POSTGRES_BIN", default_bin)

    assert runner.find_postgres_bin() == path_bin.resolve()


def test_find_postgres_bin_falls_back_to_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    default_bin = tmp_path / "default-bin"
    create_fake_postgres_bin(default_bin)
    monkeypatch.delenv("POSTGRES_BIN", raising=False)
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(runner, "DEFAULT_POSTGRES_BIN", default_bin)

    assert runner.find_postgres_bin() == default_bin.resolve()


def test_find_postgres_bin_requires_all_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incomplete_bin = tmp_path / "incomplete-bin"
    incomplete_bin.mkdir()
    (incomplete_bin / runner.tool_names("initdb")[0]).write_text("", encoding="utf-8")
    monkeypatch.setenv("POSTGRES_BIN", str(incomplete_bin))
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(runner, "DEFAULT_POSTGRES_BIN", tmp_path / "missing")

    with pytest.raises(RuntimeError, match="PostgreSQL binaries not found"):
        runner.find_postgres_bin()
