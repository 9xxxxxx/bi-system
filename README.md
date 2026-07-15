# BI 报表与通报编辑系统

面向团组内部的数据分析、仪表盘制作和经营通报发布平台。项目采用 FastAPI 模块化单体后端与 React 单页前端，默认使用 SQLite 轻量开发，并持续验证 PostgreSQL 18 生产兼容性。当前 M0 只提供工程基础和系统状态页，业务能力按 `M1` 至 `M6` 里程碑逐步交付。

## 技术栈与目录

- `backend/src/bi_system/`：FastAPI API、配置和数据库基础设施。
- `backend/tests/`：后端单元与集成测试；`backend/migrations/`：Alembic 迁移。
- `frontend/`：React 19、TypeScript、Vite、Ant Design 应用。
- `docs/architecture/`：技术决策和组件准入评估。
- `data/`：本地数据与已保留样本；数据库文件由 Git 忽略。

Python 依赖只能通过 `uv` 管理。前端使用 npm，并提交 `frontend/package-lock.json`。

## 环境要求

- Git
- Python 3.13 与 [uv](https://docs.astral.sh/uv/)
- Node.js 24 与 npm 11
- PostgreSQL 18（仅共享环境或兼容性测试需要）

## SQLite 快速启动

在仓库根目录执行：

```powershell
uv sync --locked --all-groups
npm --prefix frontend ci
Copy-Item .env.example .env
Copy-Item frontend/.env.example frontend/.env.local
uv run alembic -c backend/alembic.ini upgrade head
```

分别启动后端和前端：

```powershell
uv run uvicorn bi_system.main:app --app-dir backend/src --reload
npm --prefix frontend run dev
```

前端默认地址为 `http://localhost:5173`，API 文档为 `http://127.0.0.1:8000/docs`。就绪探针位于 `/api/v1/health/ready`。

## PostgreSQL 兼容性

本机安装 PostgreSQL 18 后，可执行隔离测试；脚本使用临时数据目录和端口 `55432`，完成迁移升降级后自动停止并清理：

```powershell
uv run python scripts/run_postgres_tests.py
```

也可用 `docker compose up -d postgres` 启动开发数据库，并将 `.env` 中的 `BI_DATABASE_URL` 改为 `.env.example` 提供的 PostgreSQL URL，再运行 Alembic。Compose 默认凭据仅用于本地开发，部署时必须替换。

## 配置

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `BI_ENVIRONMENT` | `development` | `development`、`test` 或 `production` |
| `BI_DATABASE_URL` | `sqlite+pysqlite:///./data/bi_system.db` | SQLAlchemy 数据库连接 |
| `BI_CORS_ORIGINS` | 本地 Vite 地址 | 逗号分隔的允许来源 |
| `BI_WORKSPACE_ID` | `00000000-0000-0000-0000-000000000001` | 当前默认工作区 UUID |
| `BI_STORAGE_ROOT` | `data/uploads` | 内容寻址上传文件根目录 |
| `BI_UPLOAD_MAX_BYTES` | `104857600` | 单文件字节上限 |
| `BI_XLSX_MAX_UNCOMPRESSED_BYTES` | `1073741824` | XLSX 解压后字节上限 |
| `BI_XLSX_MAX_COMPRESSION_RATIO` | `200` | XLSX 最大安全压缩比 |
| `BI_IMPORT_MAX_ROWS` | `1000000` | 单批数据行上限 |
| `BI_IMPORT_CHUNK_ROWS` | `2000` | 后台处理提交块行数 |
| `BI_PREVIEW_MAX_ROWS` | `100` | 文件预览最大样例行数 |
| `VITE_API_BASE_URL` | `http://127.0.0.1:8000/api/v1` | 前端 API 根地址 |

生产环境必须显式设置 CORS 来源。不要提交 `.env`、Cookie、令牌、下载数据或生产凭据；发送到外部模型的数据必须先脱敏。

## 文件上传与预览

M1 已提供流式源文件上传和有界预览基础接口：

- `POST /api/v1/source-files`：上传 CSV/XLSX，计算 SHA256 并复用重复内容。
- `GET /api/v1/source-files/{id}`：读取当前工作区文件元数据。
- `POST /api/v1/source-files/{id}/preview`：选择 CSV 编码或 XLSX 工作表并获取最多 100 行预览。
- `POST /api/v1/import-templates`：保存字段映射和强类型质量规则的新版本。
- `GET /api/v1/import-templates`：读取当前有效模板；可显式包含历史版本。
- `POST /api/v1/import-batches`：冻结导入定义并创建可恢复的待处理批次。
- `GET /api/v1/import-batches`：读取最近批次及进度；单批次支持查询、取消和失败重试。

支持 UTF-8、UTF-8 BOM 和显式 GB18030 CSV。旧版 `.xls`、宏工作簿、加密或损坏 XLSX 会返回可执行的转换建议。上传内容保存在 `BI_STORAGE_ROOT`，不得手工改名或移动哈希对象。

## 迁移与质量检查

创建迁移后必须在 SQLite 和 PostgreSQL 上验证 upgrade/downgrade：

```powershell
uv run alembic -c backend/alembic.ini revision --autogenerate -m "describe change"
uv run alembic -c backend/alembic.ini upgrade head
uv run python scripts/run_postgres_tests.py
```

提交前执行：

```powershell
uv run ruff check backend scripts
uv run ruff format --check backend scripts
uv run basedpyright backend/src backend/tests scripts
uv run pytest backend/tests -q --cov=bi_system
npm --prefix frontend run check
npm --prefix frontend run build
uv run pre-commit run --all-files
```

安装 Git hooks：`uv run pre-commit install --hook-type pre-commit --hook-type commit-msg`。提交信息遵循 Conventional Commits，例如 `feat(api): add dataset preview`。

## 数据保护

不要删除或提交 `data/dashboard.db` 与 `data/legacy/dashboard.db`。本地数据库、上传文件、导出文件和备份默认都应保持在 Git 之外。危险迁移前先备份；备份应压缩、限速并按需求规格控制保留数量，避免持续占用磁盘和运行资源。

需求范围见 [需求规格](docs/superpowers/specs/2026-07-14-bi-reporting-system-requirements.md)，技术选择见 [架构决策](docs/architecture/adr/0001-platform-stack.md)。
