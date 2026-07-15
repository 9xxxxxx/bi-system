import sys
from pathlib import Path

import yaml


def existing_files(paths: list[str]) -> list[Path]:
    return [Path(path) for path in paths if Path(path).is_file()]


def check_text_hygiene(paths: list[str]) -> int:
    failed = False

    for path in existing_files(paths):
        content = path.read_text(encoding="utf-8")
        if content and not content.endswith("\n"):
            print(f"{path}: missing final newline", file=sys.stderr)
            failed = True

        for line_number, line in enumerate(content.splitlines(), start=1):
            if line.rstrip(" \t") != line:
                print(f"{path}:{line_number}: trailing whitespace", file=sys.stderr)
                failed = True

    return 1 if failed else 0


def check_yaml(paths: list[str]) -> int:
    failed = False

    for path in existing_files(paths):
        try:
            list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
        except yaml.YAMLError as exc:
            print(f"{path}: invalid YAML: {exc}", file=sys.stderr)
            failed = True

    return 1 if failed else 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: check_files.py <text|yaml> [files...]", file=sys.stderr)
        return 2

    command = argv[1]
    paths = argv[2:]

    if command == "text":
        return check_text_hygiene(paths)
    if command == "yaml":
        return check_yaml(paths)

    print(f"Unknown command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
