import os
import shutil
import subprocess
from pathlib import Path

REQUIRED_POSTGRES_TOOLS = ("initdb", "pg_ctl", "createdb")
DEFAULT_POSTGRES_BIN = Path("C:/Program Files/PostgreSQL/18/bin")
ROOT = Path(__file__).resolve().parents[1]
TMP_ROOT = ROOT / ".tmp"
DATA_DIR = TMP_ROOT / "postgres-m0"
LOG_FILE = TMP_ROOT / "postgres-m0.log"
TEST_PORT = "55432"
TEST_USER = "bi_system"
TEST_DATABASE = "bi_system_test"


def tool_names(tool: str) -> tuple[str, ...]:
    if os.name == "nt":
        return (f"{tool}.exe", tool)
    return (tool, f"{tool}.exe")


def tool_path(bin_dir: Path, tool: str) -> Path:
    for name in tool_names(tool):
        candidate = bin_dir / name
        if candidate.is_file():
            return candidate

    msg = f"Missing PostgreSQL tool {tool!r} in {bin_dir}"
    raise RuntimeError(msg)


def directory_has_required_tools(bin_dir: Path) -> bool:
    if not bin_dir.is_dir():
        return False
    return all(
        any((bin_dir / name).is_file() for name in tool_names(tool))
        for tool in REQUIRED_POSTGRES_TOOLS
    )


def path_candidate() -> Path | None:
    initdb = shutil.which("initdb")
    if initdb is None:
        return None
    return Path(initdb).resolve().parent


def find_postgres_bin() -> Path:
    candidates: list[Path] = []

    postgres_bin = os.environ.get("POSTGRES_BIN")
    if postgres_bin:
        candidates.append(Path(postgres_bin))

    path_bin = path_candidate()
    if path_bin is not None:
        candidates.append(path_bin)

    candidates.append(DEFAULT_POSTGRES_BIN)

    checked: list[str] = []
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        checked.append(str(resolved))
        if directory_has_required_tools(resolved):
            return resolved

    msg = "PostgreSQL binaries not found. Checked: " + ", ".join(checked)
    raise RuntimeError(msg)


def run_command(args: list[str], env: dict[str, str] | None = None) -> None:
    print("+ " + " ".join(args), flush=True)
    subprocess.run(args, cwd=ROOT, env=env, check=True)


def ensure_within_tmp(path: Path) -> None:
    resolved_tmp = TMP_ROOT.resolve()
    resolved_path = path.resolve()
    try:
        resolved_path.relative_to(resolved_tmp)
    except ValueError as exc:
        msg = f"Refusing to remove path outside .tmp: {resolved_path}"
        raise RuntimeError(msg) from exc


def prepare_data_dir() -> None:
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    ensure_within_tmp(DATA_DIR)
    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)
    if LOG_FILE.exists():
        LOG_FILE.unlink()


def cleanup_data_dir() -> None:
    ensure_within_tmp(DATA_DIR)
    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)


def main() -> int:
    bin_dir = find_postgres_bin()
    prepare_data_dir()

    database_url = f"postgresql+psycopg://{TEST_USER}@127.0.0.1:{TEST_PORT}/{TEST_DATABASE}"
    env = os.environ.copy()
    env["BI_DATABASE_URL"] = database_url
    started = False

    try:
        run_command(
            [
                str(tool_path(bin_dir, "initdb")),
                "--auth=trust",
                "--encoding=UTF8",
                f"--username={TEST_USER}",
                "-D",
                str(DATA_DIR),
            ],
        )
        run_command(
            [
                str(tool_path(bin_dir, "pg_ctl")),
                "-D",
                str(DATA_DIR),
                "-l",
                str(LOG_FILE),
                "-o",
                f"-h 127.0.0.1 -p {TEST_PORT}",
                "-w",
                "start",
            ],
        )
        started = True
        run_command(
            [
                str(tool_path(bin_dir, "createdb")),
                "--host=127.0.0.1",
                f"--port={TEST_PORT}",
                f"--username={TEST_USER}",
                TEST_DATABASE,
            ],
        )
        run_command(
            ["uv", "run", "alembic", "-c", "backend/alembic.ini", "upgrade", "head"],
            env=env,
        )
        run_command(["uv", "run", "pytest", "backend/tests/integration", "-q"], env=env)
        run_command(
            ["uv", "run", "alembic", "-c", "backend/alembic.ini", "downgrade", "base"],
            env=env,
        )
        run_command(
            ["uv", "run", "alembic", "-c", "backend/alembic.ini", "upgrade", "head"],
            env=env,
        )
    finally:
        if started:
            subprocess.run(
                [
                    str(tool_path(bin_dir, "pg_ctl")),
                    "-D",
                    str(DATA_DIR),
                    "-m",
                    "fast",
                    "-w",
                    "stop",
                ],
                cwd=ROOT,
                check=False,
            )
        cleanup_data_dir()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
