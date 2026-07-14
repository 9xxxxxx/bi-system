# M0 工程基础实现计划

> **执行方式：** 当前阶段按任务顺序在主会话中直接实施，每个任务完成测试、静态检查和独立提交后再继续。涉及数据或目录清理时先验证备份与路径边界；后续功能里程碑只有在明确授权后才启用多 Agent 并行。

**目标：** 在保留并校验现有数据的前提下清理旧原型，建立可在 Windows/Linux 运行、同时验证 SQLite/PostgreSQL 的 FastAPI + React 工程基础，并交付完整的 Git、依赖、测试和开发规范。

**架构：** 采用前后端分离的模块化单体。后端通过 SQLAlchemy 和 Alembic 维护数据库公共模型，SQLite 负责轻量本地运行，PostgreSQL 负责集成与生产验证；前端以 React 单页应用调用版本化 FastAPI 接口。M0 只引入已使用的基础依赖，数据网格、图表和编辑器在对应里程碑通过量化技术验证后加入。

**技术栈：** Python 3.13、uv、FastAPI、Pydantic Settings、SQLAlchemy 2、Alembic、SQLite、PostgreSQL 18、React、TypeScript、Vite、Ant Design、TanStack Query、React Router、npm、Pytest、Ruff、BasedPyright、Vitest、Testing Library、ESLint、Prettier、pre-commit。

---

## 文件结构

### 根目录与工程规范

- 创建 `.python-version`：锁定 Python 3.13。
- 创建 `.node-version`：锁定 Node 24。
- 创建 `pyproject.toml`、`uv.lock`：后端与开发工具依赖的唯一来源。
- 创建 `.gitignore`、`.gitattributes`、`.editorconfig`：忽略生成物并统一 UTF-8、LF 和缩进。
- 创建 `.env.example`：公开可提交的配置契约。
- 创建 `.pre-commit-config.yaml`：提交前质量检查与 Conventional Commits 校验。
- 创建 `README.md`、`AGENTS.md`：开发入口与贡献者指南。
- 创建 `compose.yaml`：服务器或安装 Docker 后使用的 PostgreSQL 18 开发服务。

### 后端

- 创建 `backend/src/bi_system/main.py`：FastAPI 应用工厂与应用实例。
- 创建 `backend/src/bi_system/core/config.py`：类型化环境配置。
- 创建 `backend/src/bi_system/api/router.py`：版本化 API 总路由。
- 创建 `backend/src/bi_system/api/routes/health.py`：存活与就绪检查。
- 创建 `backend/src/bi_system/db/base.py`：SQLAlchemy 声明式基类。
- 创建 `backend/src/bi_system/db/session.py`：SQLite/PostgreSQL 引擎与会话工厂。
- 创建 `backend/alembic.ini`、`backend/migrations/`：统一迁移历史。
- 创建 `backend/tests/unit/`、`backend/tests/integration/`：配置、API、数据库与迁移测试。

### 前端

- 创建 `frontend/src/app/App.tsx`：应用路由与页面壳。
- 创建 `frontend/src/app/providers.tsx`：Ant Design、TanStack Query 与国际化 Provider。
- 创建 `frontend/src/features/system-status/`：验证前后端契约的系统状态功能。
- 创建 `frontend/src/shared/api/client.ts`：统一 API 客户端。
- 创建 `frontend/src/test/setup.ts`：Vitest DOM 测试初始化。
- 创建 `frontend/src/test/TestProviders.tsx`：单元测试使用的 QueryClient 与内存路由包装器。

### 工具与文档

- 创建 `scripts/run_postgres_tests.py`：使用本地 PostgreSQL 二进制启动隔离测试实例。
- 创建 `docs/architecture/adr/0001-platform-stack.md`：核心技术选型与证据。
- 创建 `docs/architecture/adr/0002-database-portability.md`：双数据库约束。
- 创建 `docs/architecture/evaluations/frontend-components.md`：数据网格、图表和编辑器的验证门槛。
- 创建 `.github/workflows/ci.yml`：SQLite、PostgreSQL、后端和前端质量门禁。

## 任务 1：保护数据并清理旧原型

**文件：**
- 创建：`.gitignore`
- 创建：`.gitattributes`
- 创建：`.editorconfig`
- 创建：`data/README.md`
- 创建：`data/legacy/README.md`
- 保留：`data/dashboard.db`
- 本地备份但不提交：`data/legacy/dashboard.db`
- 删除：`app.py`、`ARCHITECTURE.md`、`requirements.txt`、旧 `package*.json`、`client/`、`server/`、旧 `scripts/`、`.venv/`、`node_modules/`、`__pycache__/`

- [ ] **步骤 1：生成数据备份和校验值**

运行：

```powershell
$source = (Resolve-Path 'data\dashboard.db').Path
New-Item -ItemType Directory -Force 'data\legacy' | Out-Null
Copy-Item -LiteralPath $source -Destination 'data\legacy\dashboard.db' -Force
$sourceHash = (Get-FileHash -Algorithm SHA256 $source).Hash
$backupHash = (Get-FileHash -Algorithm SHA256 'data\legacy\dashboard.db').Hash
if ($sourceHash -ne $backupHash) { throw 'SQLite backup hash mismatch' }
$sourceHash
```

预期：输出一个 64 位 SHA256，命令退出码为 0。

- [ ] **步骤 2：创建 Git 与编辑器基础配置**

`.gitignore` 必须包含：

```gitignore
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/
.mypy_cache/
.basedpyright/
node_modules/
frontend/dist/
.env
.env.*
!.env.example
.tmp/
coverage.xml
htmlcov/
data/**
!data/README.md
!data/legacy/
data/legacy/**
!data/legacy/README.md
```

`.gitattributes` 必须使用 `* text=auto eol=lf`，并将 `*.db`、`*.xlsx`、`*.png` 标记为 binary。`.editorconfig` 必须设置 UTF-8、LF、末尾换行，Python 使用 4 空格，TypeScript/JSON/YAML/Markdown 使用 2 空格。

- [ ] **步骤 3：验证数据文件会被忽略而说明文件可提交**

运行：

```powershell
git check-ignore data/dashboard.db data/legacy/dashboard.db
git check-ignore -v data/README.md
```

预期：两个数据库文件命中忽略规则；`data/README.md` 不命中，第二条命令返回 1。

- [ ] **步骤 4：安全清理旧原型**

仅在步骤 1 哈希一致后运行以下单一 PowerShell 流程：

```powershell
$root = (Resolve-Path '.').Path
$targets = @(
  'app.py', 'ARCHITECTURE.md', 'requirements.txt', 'package.json',
  'package-lock.json', 'client', 'server', 'scripts', '.venv',
  'node_modules', '__pycache__'
)
foreach ($relative in $targets) {
  $full = [IO.Path]::GetFullPath((Join-Path $root $relative))
  if (-not $full.StartsWith($root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to remove path outside workspace: $full"
  }
  if (Test-Path -LiteralPath $full) { Remove-Item -LiteralPath $full -Recurse -Force }
}
if (-not (Test-Path 'data\dashboard.db')) { throw 'Source data was removed' }
if (-not (Test-Path 'data\legacy\dashboard.db')) { throw 'Backup data was removed' }
```

预期：旧原型和生成目录消失，两个 SQLite 文件仍存在。

- [ ] **步骤 5：提交数据保护与仓库规范**

```powershell
git add .gitignore .gitattributes .editorconfig data/README.md data/legacy/README.md
git diff --cached --check
git commit -m "chore: establish repository baseline"
```

## 任务 2：建立 uv 后端项目与类型化配置

**文件：**
- 创建：`.python-version`
- 创建：`pyproject.toml`
- 创建：`backend/src/bi_system/__init__.py`
- 创建：`backend/src/bi_system/core/__init__.py`
- 创建：`backend/src/bi_system/core/config.py`
- 创建：`backend/tests/unit/test_config.py`

- [ ] **步骤 1：声明 Python 与依赖**

`pyproject.toml` 使用 Hatchling 构建 `backend/src/bi_system`，运行依赖限定为 FastAPI `<1`、Pydantic Settings `<3`、SQLAlchemy `<3`、Alembic `<2`、psycopg `<4` 和 Uvicorn `<1`。开发组包含 Pytest、pytest-cov、HTTPX、Ruff、BasedPyright、pre-commit。运行：

```powershell
uv python pin 3.13
uv lock
uv sync --all-groups
```

预期：创建 `uv.lock` 与全新的 `.venv`，`uv run python --version` 输出 Python 3.13.x。

- [ ] **步骤 2：先编写失败的配置测试**

```python
from bi_system.core.config import Settings


def test_settings_default_to_sqlite(monkeypatch):
    monkeypatch.delenv("BI_DATABASE_URL", raising=False)
    settings = Settings(_env_file=None)
    assert settings.api_prefix == "/api/v1"
    assert settings.database_url.startswith("sqlite+pysqlite:///")
```

运行：`uv run pytest backend/tests/unit/test_config.py -q`

预期：FAIL，提示 `bi_system.core.config` 不存在。

- [ ] **步骤 3：实现最小配置对象**

```python
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "BI System"
    environment: Literal["development", "test", "production"] = "development"
    api_prefix: str = "/api/v1"
    database_url: str = "sqlite+pysqlite:///./data/bi_system.db"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="BI_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **步骤 4：验证测试与静态检查**

运行：

```powershell
uv run pytest backend/tests/unit/test_config.py -q
uv run ruff check backend
uv run basedpyright backend/src backend/tests
```

预期：配置测试通过，Ruff 与 BasedPyright 均返回 0 errors。

- [ ] **步骤 5：提交后端项目基础**

```powershell
git add .python-version pyproject.toml uv.lock backend
git commit -m "build: initialize FastAPI backend project"
```

## 任务 3：以测试驱动建立 FastAPI 健康接口

**文件：**
- 创建：`backend/src/bi_system/api/__init__.py`
- 创建：`backend/src/bi_system/api/routes/__init__.py`
- 创建：`backend/src/bi_system/api/router.py`
- 创建：`backend/src/bi_system/api/routes/health.py`
- 创建：`backend/src/bi_system/main.py`
- 创建：`backend/tests/integration/test_health.py`

- [ ] **步骤 1：编写失败的存活检查测试**

```python
from fastapi.testclient import TestClient

from bi_system.main import create_app


def test_live_endpoint_returns_service_status():
    client = TestClient(create_app())
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "bi-system"}
```

运行：`uv run pytest backend/tests/integration/test_health.py -q`

预期：FAIL，提示 `bi_system.main` 不存在。

- [ ] **步骤 2：实现路由和应用工厂**

`health.py`：

```python
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class LiveResponse(BaseModel):
    status: str
    service: str


@router.get("/live", response_model=LiveResponse)
def live() -> LiveResponse:
    return LiveResponse(status="ok", service="bi-system")
```

`router.py`：

```python
from fastapi import APIRouter

from bi_system.api.routes import health

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
```

`main.py`：

```python
from fastapi import FastAPI

from bi_system.api.router import api_router
from bi_system.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title=settings.app_name)
    application.include_router(api_router, prefix=settings.api_prefix)
    return application


app = create_app()
```

模块导入不得连接数据库。

- [ ] **步骤 3：运行健康接口测试**

运行：`uv run pytest backend/tests/integration/test_health.py -q`

预期：1 passed。

- [ ] **步骤 4：本地启动并执行真实 HTTP 检查**

运行：`uv run uvicorn bi_system.main:app --app-dir backend/src --host 127.0.0.1 --port 8000`

在另一终端运行：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health/live
```

预期：返回 `status=ok` 与 `service=bi-system`。完成后停止 Uvicorn。

- [ ] **步骤 5：提交 API 骨架**

```powershell
git add backend
git commit -m "feat(api): add versioned health endpoint"
```

## 任务 4：建立 SQLite/PostgreSQL 公共数据库层

**文件：**
- 创建：`backend/src/bi_system/db/__init__.py`
- 创建：`backend/src/bi_system/db/base.py`
- 创建：`backend/src/bi_system/db/session.py`
- 创建：`backend/alembic.ini`
- 创建：`backend/migrations/env.py`
- 创建：`backend/migrations/versions/0001_baseline.py`
- 创建：`backend/tests/unit/test_database.py`
- 修改：`backend/src/bi_system/api/routes/health.py`
- 修改：`backend/tests/integration/test_health.py`

- [ ] **步骤 1：编写失败的 SQLite 引擎测试**

测试必须验证内存 SQLite 引擎可执行 `SELECT 1`，且连接事件执行 `PRAGMA foreign_keys=ON`。运行：

`uv run pytest backend/tests/unit/test_database.py -q`

预期：FAIL，提示 `create_database_engine` 不存在。

- [ ] **步骤 2：实现公共引擎工厂**

`create_database_engine(url)` 使用 SQLAlchemy 同步引擎：

```python
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker


def create_database_engine(url: str) -> Engine:
    dialect = make_url(url).get_backend_name()
    if dialect == "sqlite":
        engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine
    if dialect == "postgresql":
        return create_engine(url, pool_pre_ping=True)
    raise ValueError(f"Unsupported database dialect: {dialect}")


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
```

`base.py` 定义唯一的 `class Base(DeclarativeBase): pass`。不创建全局连接。

- [ ] **步骤 3：实现 Alembic 基线**

`env.py` 从 `BI_DATABASE_URL` 读取连接串，否则使用 Settings 默认值；SQLite 开启 `render_as_batch`。`0001_baseline.py` 使用固定 revision `0001_baseline`，升级和降级为空操作，用于建立两种数据库共享的迁移起点。

- [ ] **步骤 4：编写并实现就绪检查**

先添加测试，模拟数据库连接成功时 `/api/v1/health/ready` 返回 `{"status":"ready","database":"ok"}`，连接异常时返回 HTTP 503 且不泄露连接串。随后在 `main.py` 的 lifespan 中创建并释放 engine，在同步路由中执行：

```python
@router.get("/ready", response_model=ReadyResponse)
def ready(request: Request) -> ReadyResponse:
    try:
        with request.app.state.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return ReadyResponse(status="ready", database="ok")
```

测试使用 `with TestClient(create_app()) as client:` 触发 lifespan，失败响应只断言固定公开错误，不包含 URL、用户名或密码。

- [ ] **步骤 5：验证 SQLite 迁移和测试**

```powershell
$env:BI_DATABASE_URL='sqlite+pysqlite:///./data/m0-test.db'
uv run alembic -c backend/alembic.ini upgrade head
uv run pytest backend/tests -q
Remove-Item Env:BI_DATABASE_URL
```

预期：迁移成功，全部后端测试通过，`data/m0-test.db` 被 Git 忽略。

- [ ] **步骤 6：提交数据库基础**

```powershell
git add backend
git commit -m "feat(db): add portable database foundation"
```

## 任务 5：建立可重复的 PostgreSQL 18 集成测试

**文件：**
- 创建：`scripts/run_postgres_tests.py`
- 创建：`backend/tests/integration/test_migrations.py`
- 修改：`pyproject.toml`

- [ ] **步骤 1：为 PostgreSQL 测试运行器编写失败测试**

测试 `find_postgres_bin()` 按 `POSTGRES_BIN`、PATH、`C:/Program Files/PostgreSQL/18/bin` 顺序查找，并验证目录必须同时包含 `initdb`、`pg_ctl`、`createdb`。运行后应先因模块不存在而失败。

- [ ] **步骤 2：实现隔离实例运行器**

运行器必须：

1. 在 `.tmp/postgres-m0` 创建临时数据目录。
2. 用 `initdb --auth=trust --encoding=UTF8 --username=bi_system` 初始化。
3. 用 `pg_ctl` 在 `127.0.0.1:55432` 启动并写日志到 `.tmp/postgres-m0.log`。
4. 使用 `createdb --host=127.0.0.1 --port=55432 --username=bi_system bi_system_test` 创建数据库。
5. 设置 `BI_DATABASE_URL=postgresql+psycopg://bi_system@127.0.0.1:55432/bi_system_test`。
6. 依次运行 Alembic upgrade、Pytest integration、Alembic downgrade base、再次 upgrade head。
7. 在 `finally` 中停止实例；仅删除已确认位于项目 `.tmp` 下的临时目录。

- [ ] **步骤 3：编写迁移一致性测试**

`test_migrations.py` 使用当前 `BI_DATABASE_URL`，断言 Alembic 当前 revision 为 `0001_baseline`，并通过应用数据库工厂执行 `SELECT 1`。

- [ ] **步骤 4：运行真实 PostgreSQL 验证**

运行：`uv run python scripts/run_postgres_tests.py`

预期：隔离 PostgreSQL 18 启动；升级、降级、再升级与集成测试全部通过；脚本退出后 55432 端口释放。

- [ ] **步骤 5：提交 PostgreSQL 验证工具**

```powershell
git add scripts pyproject.toml uv.lock backend/tests
git commit -m "test(db): verify PostgreSQL migrations locally"
```

## 任务 6：建立 React、Ant Design 与前端测试基础

**文件：**
- 创建：`.node-version`
- 创建：`frontend/` Vite React TypeScript 工程
- 创建：`frontend/src/app/providers.tsx`
- 创建：`frontend/src/features/system-status/SystemStatusPage.tsx`
- 创建：`frontend/src/features/system-status/SystemStatusPage.test.tsx`
- 创建：`frontend/src/shared/api/client.ts`
- 创建：`frontend/src/test/setup.ts`
- 修改：`frontend/src/app/App.tsx`
- 修改：`frontend/package.json`

- [ ] **步骤 1：创建并锁定前端工程**

```powershell
npm create vite@latest frontend -- --template react-ts
npm --prefix frontend install
npm --prefix frontend install antd @ant-design/icons @tanstack/react-query react-router-dom zustand i18next react-i18next
npm --prefix frontend install --save-dev vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event prettier eslint-config-prettier
```

使用 `apply_patch` 创建内容为 `24` 的 `.node-version`。在 `frontend/package.json` 设置 `engines.node` 为 `>=24 <25`、`packageManager` 为 `npm@11.18.0`，增加 `test`、`test:coverage`、`typecheck`、`format:check` 和聚合 `check` 脚本。提交 `package-lock.json`。

- [ ] **步骤 2：先编写失败的状态页测试**

```tsx
it('renders the backend readiness state', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
    status: 'ready', database: 'ok'
  }), { status: 200 })))
  render(<TestProviders><SystemStatusPage /></TestProviders>)
  expect(await screen.findByText('系统运行正常')).toBeInTheDocument()
})
```

在 `afterEach` 中执行 `vi.unstubAllGlobals()`；运行 `npm --prefix frontend test -- --run`，预期因组件不存在而失败。

- [ ] **步骤 3：实现 Provider、API 客户端和状态页**

Provider 统一挂载 Ant Design `ConfigProvider`、中文 locale、QueryClientProvider 与 BrowserRouter。API 客户端只负责 JSON、超时和统一错误类型；状态页通过 TanStack Query 调用就绪接口，明确展示加载、成功和失败状态。

- [ ] **步骤 4：验证前端质量**

```powershell
npm --prefix frontend run check
npm --prefix frontend run build
```

预期：ESLint、Prettier、TypeScript、Vitest 全部通过，Vite 生成 `frontend/dist/` 且目录被 Git 忽略。

- [ ] **步骤 5：提交前端基础**

```powershell
git add .node-version frontend
git commit -m "feat(web): initialize React application shell"
```

## 任务 7：配置环境、跨域与可移植运行

**文件：**
- 创建：`.env.example`
- 创建：`compose.yaml`
- 修改：`backend/src/bi_system/core/config.py`
- 修改：`backend/src/bi_system/main.py`
- 创建：`backend/tests/unit/test_cors.py`
- 创建：`frontend/.env.example`

- [ ] **步骤 1：先编写 CORS 配置测试**

测试 development 默认仅允许 `http://localhost:5173` 和 `http://127.0.0.1:5173`，production 环境若未显式提供允许来源则 Settings 校验失败。先运行并确认失败。

- [ ] **步骤 2：实现环境契约**

根 `.env.example` 包含 `BI_ENVIRONMENT`、`BI_DATABASE_URL`、`BI_CORS_ORIGINS`；前端示例包含 `VITE_API_BASE_URL`。CORS 来源解析为明确 URL 列表，禁止生产环境通配符。

- [ ] **步骤 3：提供 PostgreSQL 18 Compose 服务**

`compose.yaml` 使用 `postgres:18`、命名卷、健康检查和仅用于开发的默认账号 `bi_system/bi_system`，端口通过 `${POSTGRES_PORT:-5432}` 配置。不得在文件中放置生产密钥。

- [ ] **步骤 4：验证两种本地启动方式**

SQLite：`uv run uvicorn bi_system.main:app --app-dir backend/src --reload`

PostgreSQL：先执行 `docker compose config`；Docker 可用时执行 `docker compose up -d postgres` 和 Alembic upgrade。当前机器没有 Docker，因此 M0 的强制 PostgreSQL验收使用任务 5 的隔离实例，Compose 只做静态配置审查。

- [ ] **步骤 5：提交环境配置**

```powershell
git add .env.example compose.yaml frontend/.env.example backend
git commit -m "chore: add portable environment configuration"
```

## 任务 8：建立质量门禁与持续集成

**文件：**
- 创建：`.pre-commit-config.yaml`
- 创建：`.github/workflows/ci.yml`
- 修改：`pyproject.toml`
- 修改：`frontend/package.json`

- [ ] **步骤 1：配置本地提交门禁**

pre-commit 必须运行 trailing whitespace、end-of-file、YAML 检查、Ruff lint/format，并用 `conventional-pre-commit` 校验 commit message。前端完整检查由 CI 执行，避免每次提交重复启动 Node 全量测试。

- [ ] **步骤 2：安装并验证 hooks**

```powershell
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg
uv run pre-commit run --all-files
```

预期：所有 hooks 通过；故意创建的非法测试提交信息 `bad message` 被 commit-msg hook 拒绝，随后删除测试提交操作，不改写已有提交。

- [ ] **步骤 3：创建 CI 工作流**

CI 在 Ubuntu 上固定 Python 3.13、Node 24 和 PostgreSQL 18 service，执行：

```text
uv sync --locked --all-groups
uv run ruff check .
uv run ruff format --check .
uv run basedpyright backend/src backend/tests scripts
uv run pytest backend/tests -q --cov=bi_system --cov-report=xml
uv run alembic -c backend/alembic.ini upgrade head   # PostgreSQL URL
npm --prefix frontend ci
npm --prefix frontend run check
npm --prefix frontend run build
```

工作流只读取仓库变量，不保存生产凭据。

- [ ] **步骤 4：本地执行与 CI 相同的命令**

逐条运行上述命令；PostgreSQL部分通过 `uv run python scripts/run_postgres_tests.py` 执行。预期全部退出码为 0。

- [ ] **步骤 5：提交质量门禁**

```powershell
git add .pre-commit-config.yaml .github pyproject.toml uv.lock frontend/package.json frontend/package-lock.json
git commit -m "ci: enforce backend and frontend quality gates"
```

## 任务 9：记录技术决策与组件验证门槛

**文件：**
- 创建：`docs/architecture/adr/0001-platform-stack.md`
- 创建：`docs/architecture/adr/0002-database-portability.md`
- 创建：`docs/architecture/evaluations/frontend-components.md`

- [ ] **步骤 1：记录核心栈证据**

ADR 0001 记录已验证命令、版本、选择理由和替代方案：React/Vite 对比 Vue/Next.js，FastAPI 模块化单体对比微服务，uv/npm 的锁文件策略。状态写为 `Accepted`，并链接需求规格和 M0 验证结果。

- [ ] **步骤 2：记录双数据库限制**

ADR 0002 明确：公共模型优先使用 UUID、String、Integer、Numeric、Date、DateTime 和通用 JSON；禁止未封装的 JSONB、数组、全文检索及方言 SQL；SQLite 启用外键；每次迁移必须在 SQLite 与 PostgreSQL 完成 upgrade/downgrade 验证。状态写为 `Accepted`。

- [ ] **步骤 3：建立前端组件量化评估表**

评估文档固定以下决策时间和门槛：

- M1 开始前比较 React Data Grid 与 Glide Data Grid：复制粘贴 20%、10 万行滚动 20%、编辑校验 15%、Ant Design 主题 10%、键盘操作 10%、许可证 10%、维护活跃度 10%、可访问性 5%；总分至少 80 且无阻断项。
- M3 开始前验证 ECharts：需求图表覆盖、移动适配、导出清晰度、下钻事件、包体与无障碍替代内容。
- M5 开始前验证 TipTap：结构化块、锁定块、分页导出、版本序列化、中文输入和粘贴清洗。

每项必须保存可运行 spike、测试数据、测试命令、浏览器截图和结论 ADR；失败候选不得进入生产依赖。

- [ ] **步骤 4：核对依赖元数据**

运行 `npm view <package> version license` 和 `uv tree`，将实际版本、许可证和查询日期写入评估文档。预期所有已安装直接依赖具有可接受许可证，且无未解释的重复核心库。

- [ ] **步骤 5：提交技术决策**

```powershell
git add docs/architecture
git commit -m "docs: record platform technology decisions"
```

## 任务 10：编写开发文档与英文贡献者指南

**文件：**
- 创建：`README.md`
- 创建：`AGENTS.md`

- [ ] **步骤 1：编写 README**

README 使用中文，包含架构简介、前置版本、SQLite 快速启动、PostgreSQL测试、前后端命令、环境变量、迁移流程、数据目录保护和质量检查。所有命令必须从干净检出验证。

- [ ] **步骤 2：编写 200–400 词英文 AGENTS.md**

标题必须为 `# Repository Guidelines`，包含以下项目专用内容：

```markdown
# Repository Guidelines

## Project Structure & Module Organization

The FastAPI application lives in `backend/src/bi_system/`; keep API routes, core configuration, and database infrastructure in their existing focused packages. Backend tests live under `backend/tests/unit/` and `backend/tests/integration/`. The React application is in `frontend/src/`, grouped by `app/`, feature folders, and shared infrastructure. Alembic migrations are stored in `backend/migrations/`. Keep architecture decisions in `docs/architecture/` and local runtime data in the ignored `data/` directory.

## Build, Test, and Development Commands

Use `uv sync --all-groups` to create the Python 3.13 environment. Start the API with `uv run uvicorn bi_system.main:app --app-dir backend/src --reload`. Apply migrations with `uv run alembic -c backend/alembic.ini upgrade head`. Run backend checks with `uv run pytest backend/tests -q`, `uv run ruff check .`, and `uv run basedpyright backend/src backend/tests scripts`. Install and run the frontend with `npm --prefix frontend ci` and `npm --prefix frontend run dev`; use `npm --prefix frontend run check` before committing.

## Coding Style & Naming Conventions

Python uses four spaces, type annotations, Ruff formatting, and `snake_case`; classes use `PascalCase`. TypeScript uses two spaces, Prettier, `PascalCase` components, and `camelCase` hooks and functions. Keep modules small and feature-focused. Do not add database-specific SQL outside an explicit adapter.

## Testing Guidelines

Follow test-first development. Name Python tests `test_*.py` and frontend tests `*.test.tsx`. Every migration and database behavior must pass against SQLite and PostgreSQL. Add integration tests for API contracts and component tests for loading, success, empty, and error states.

## Commit & Pull Request Guidelines

Use Conventional Commits, for example `feat(api): add dataset preview` or `fix(web): preserve dashboard filters`. Keep commits focused. Pull requests must explain scope, database impact, verification commands, linked issues, and screenshots for visible UI changes.

## Security & Configuration

Never commit `.env`, database files, uploaded data, cookies, tokens, or production credentials. Update `.env.example` whenever configuration changes. Preserve `data/dashboard.db` and its verified local backup during repository cleanup.
```

正文必须说明 `uv` 是唯一 Python 环境入口、npm lockfile 必须同步、迁移需双数据库验证、PR 需描述验证命令与 UI 截图。英文单词数必须在 200–400。

- [ ] **步骤 3：验证文档命令和字数**

运行 README 中每条非破坏性命令；再运行：

```powershell
$text = Get-Content -Raw AGENTS.md
$words = ([regex]::Matches($text, "\b[\w'-]+\b")).Count
if ($words -lt 200 -or $words -gt 400) { throw "AGENTS.md word count: $words" }
$words
```

预期：命令通过，字数在 200–400。

- [ ] **步骤 4：提交开发文档**

```powershell
git add README.md AGENTS.md
git commit -m "docs: add contributor and development guides"
```

## 任务 11：执行 M0 完整验收

**文件：**
- 验证：所有已创建文件
- 验证但不提交：`data/dashboard.db`、`data/legacy/dashboard.db`

- [ ] **步骤 1：重新验证数据完整性**

比较源数据库与备份 SHA256；使用 SQLite 查询并断言 `dim_city=9`、`dz_data=50`、`metric_def=21`、`rk_data=140`。任一不一致即停止验收。

- [ ] **步骤 2：执行后端全量检查**

```powershell
uv sync --locked --all-groups
uv run ruff check .
uv run ruff format --check .
uv run basedpyright backend/src backend/tests scripts
uv run pytest backend/tests -q --cov=bi_system
uv run python scripts/run_postgres_tests.py
```

预期：所有命令退出码为 0；SQLite 与 PostgreSQL迁移和测试通过。

- [ ] **步骤 3：执行前端全量检查**

```powershell
npm --prefix frontend ci
npm --prefix frontend run check
npm --prefix frontend run build
```

预期：lint、格式、类型、单元测试与生产构建全部通过。

- [ ] **步骤 4：执行跨进程冒烟测试**

启动 FastAPI 与 Vite，使用浏览器打开前端状态页，确认成功状态；停止后端并刷新，确认失败状态可理解且布局不跳动。保存桌面与移动视口截图作为 M0 验收证据。

- [ ] **步骤 5：检查 Git 边界**

```powershell
git status --short
git diff --check
git ls-files data
git log --oneline --decorate -12
```

预期：工作区干净；Git 只跟踪 `data/README.md` 与 `data/legacy/README.md`，不跟踪数据库；提交均符合 Conventional Commits。

- [ ] **步骤 6：提交验收记录**

将实际版本、命令结果、SQLite/PostgreSQL测试数和截图路径写入 `docs/verification/m0-verification.md`，然后提交：

```powershell
git add docs/verification/m0-verification.md
git commit -m "docs: record M0 verification evidence"
```

预期：M0 的每项完成声明均能追溯到新鲜命令输出或截图。
