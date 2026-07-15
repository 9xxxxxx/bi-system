from pathlib import Path

from scripts.validate_commit_message import is_valid_commit_message, main


def test_commit_message_accepts_conventional_format() -> None:
    assert is_valid_commit_message("feat(api): add dataset preview")
    assert is_valid_commit_message("fix!: remove deprecated setting")
    assert is_valid_commit_message("docs: update readme")


def test_commit_message_rejects_plain_text() -> None:
    assert not is_valid_commit_message("updated stuff")


def test_commit_message_cli_returns_nonzero_for_invalid_message(tmp_path: Path) -> None:
    message_file = tmp_path / "COMMIT_EDITMSG"
    message_file.write_text("bad message\n", encoding="utf-8")

    assert main(["validate_commit_message.py", str(message_file)]) == 1
