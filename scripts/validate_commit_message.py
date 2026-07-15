import re
import sys
from pathlib import Path

CONVENTIONAL_COMMIT_RE = re.compile(
    r"^(build|chore|ci|docs|feat|fix|perf|refactor|style|test)"
    r"(\([a-z0-9-]+\))?!?: .+"
)


def is_valid_commit_message(message: str) -> bool:
    first_line = message.strip().splitlines()[0] if message.strip() else ""
    if first_line.startswith(("Merge ", "Revert ")):
        return True
    return CONVENTIONAL_COMMIT_RE.fullmatch(first_line) is not None


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: validate_commit_message.py <commit-msg-file>", file=sys.stderr)
        return 2

    message = Path(argv[1]).read_text(encoding="utf-8")
    if is_valid_commit_message(message):
        return 0

    print(
        "Commit message must use Conventional Commits, for example "
        "'feat(api): add dataset preview'.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
