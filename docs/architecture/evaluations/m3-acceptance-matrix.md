# M3 标准数据与验收矩阵

## 1. 状态与范围

- 任务包：`M3-R0-C1`
- fixture：`m3-star-v2`（M3-R0-A1 编译器回归继续固定消费 `m3-star-v1` golden）
- 状态：fixture、golden、权限主体和验收方法已定义；数据库、浏览器和性能实测在 M3-R1 至 M3-R3 执行
- 数据根目录：`spikes/m3/quality/fixture/v2/`
- 生成器：`spikes/m3/quality/fixture_tool.py`
- 自校验：`spikes/m3/quality/tests/test_fixture_tool.py`

本文定义 M3 的共同验收口径，不声称尚未运行的生产实现已经通过。M3-R1/R2 的自动化测试必须直接消费本 fixture；M3-R3 的验收记录必须引用同一 fixture 版本和 `manifest.json` 哈希，禁止复制后静默修改。V2 manifest 固定 `fact_sales.csv=11ffba3a...fffca2`、`golden_results.json=70da7732...715c28`；V1 保留不变，仅用于复现已经完成的 A1 编译/SQLite golden 证据。

## 2. 标准星型数据集

### 2.1 三个来源

| 来源 | 粒度与主键 | 关键类型 | 行数 | 用途 |
|---|---|---|---:|---|
| `fact_sales.csv` | 一行销售事件，`sales_id` | Date、DateTime、Decimal、Boolean、NULL、整数、字符串 | 14 | KPI、聚合、排序、Top N、日期/时间及作用域筛选 |
| `dim_product.csv` | 一行产品，`product_key` | Date、Boolean、字符串 | 4 | 产品、类别；含重复展示名 |
| `dim_region.csv` | 一行区域，`region_key` | Boolean、字符串 | 3 | 区域分组和 RLS |

连接固定为事实表到两个维度的 `LEFT JOIN`。未知键和 NULL 键保留事实行并映射为明确的 `(Unmatched product)` 或 `(Unmatched region)`，不能因内连接而丢失。字段类型、可空性、主键和关系在 `schema.json` 中机器可读地固定。

### 2.2 边界设计

| 边界 | fixture 行/字段 | 预期 |
|---|---|---|
| 精确 Decimal | 所有金额、折扣率 | 使用十进制精确运算，金额只在输出时量化为 2 位 |
| 日期边界 | 2026-01-31 与 2026-02-01 | 区间使用 `[start, end)`，一月筛选不含 2 月 1 日 |
| DateTime 规范化 | `occurred_at` 与 `canonical_utc_serialization` | 带 `+08:00` 的输入规范化为等价 UTC `Z`，响应保持 ISO 8601 |
| 工作区日界 | `Asia/Hong_Kong` 的 2026-01-05 | 本地 `[00:00, next 00:00)` 先解析再转换为 UTC 闭开区间 |
| DST 日界 | `America/New_York` 的 2026-03-08 | spring-forward 工作区日换算为 23 小时 UTC 区间，不按固定 24 小时推算 |
| Boolean | `is_returned`、维度布尔字段 | 同时覆盖 true/false，不按非空字符串转布尔 |
| NULL | 4 行空折扣、1 行空产品键 | NULL 不当作 0 或空白维度成员 |
| 未知产品 | `sales_id=7`，`P999` | 保留并进入 unmatched 产品分组 |
| 未知区域 | `sales_id=11`，`R999` | 保留并进入 unmatched 区域分组 |
| 重复业务事实 | `sales_id=13/14` 共用 `O-DUP` | `count(*)=14`，`count_distinct(order_id)=13` |
| 重复展示名 | `P100/P400` 共用 `Widget Alpha` | 连接和选择以 key/UUID 为准，不能以名称关联 |
| 无事实维度成员 | `P400` | 聚合事实结果不凭空产生一行 |
| RLS 与用户筛选冲突 | 北区查看者伪造南区筛选 | 两者取 AND，返回 0 行而非南区数据 |

### 2.3 人工可核对关键值

完整结果见 `golden_results.json`，以下值是评审时的最小人工核对集：

| 场景 | 行/订单 | 销售额 | 成本 | 毛利 |
|---|---:|---:|---:|---:|
| 全部事实 | 14 / 13 | 2838.74 | 1557.75 | 1280.99 |
| 2026-01 | 7 / 7 | 1532.49 | 811.25 | 721.24 |
| 2026-02 | 7 / 6 | 1306.25 | 746.50 | 559.75 |
| Hardware | 9 / 8 | 2163.50 | 1297.75 | 865.75 |
| Services | 3 / 3 | 519.99 | 210.00 | 309.99 |
| Unmatched product | 2 / 2 | 155.25 | 50.00 | 105.25 |
| 北区受限查看者 | 7 / 6 | 805.74 | 420.25 | 385.49 |

Top 2 按销售额降序、产品键升序作稳定 tie-break：`P100=1110.00`、`P200=1053.50`。作用域筛选的固定行集如下：

| 谓词 | `sales_id` | 销售额 |
|---|---|---:|
| global：2026-01 | 1,2,3,4,5,6,7 | 1532.49 |
| 上述 AND page：R-NORTH | 1,2,6,7 | 530.49 |
| 上述 AND component：Hardware | 1,2 | 350.50 |
| global：2026-01 AND component：日期从 01-05 | 2,3,4,5,6,7 | 1332.49 |

### 2.4 图表数据快照

`chart_cases.json` 将每种 M3 核心数据图表映射到 `golden_results.json` 的 JSON Pointer：KPI、明细表、排行表、柱图、条图、堆叠柱图、折线、面积、饼图和环图。后端测试比较 pointer 指向的精确值；前端测试用同一数据渲染，再按第 7 节保存像素和截图证据。富文本、图片、趋势指标及目标进度不新增聚合口径，分别验证非查询合同或复用 KPI/时间序列 golden。

## 3. 权限主体矩阵

主体定义在 `principals.json`。UUID 是无业务数据的固定测试标识。

| 主体 | 工作区 | 能力 | RLS | 查询预期 | 写入负例 |
|---|---|---|---|---|---|
| administrator | 当前 | dashboard/manage、dataset/manage/query | 无 | 14 行 | 允许授权范围内管理 |
| editor | 当前 | dashboard/manage、dataset/query | 无 | 14 行 | 禁止数据集管理 |
| restricted_viewer | 当前 | dataset/query | `region_key=R-NORTH` | 7 行 | 禁止仪表盘编辑 |
| foreign_administrator | 外部 | 全能力声明 | 无 | 查询执行前拒绝 | 跨工作区资源不可见 |

权限测试必须证明 RLS 在连接和聚合之前生效。客户端筛选只能收紧结果，不能覆盖 RLS；跨工作区主体即使声明相同权限，也必须在查询编译/执行前返回稳定错误且 `query_executed=false`。

## 4. 生成、校验与版本策略

从仓库根目录运行：

```powershell
uv run python spikes/m3/quality/fixture_tool.py check
uv run python spikes/m3/quality/fixture_tool.py summary
uv run pytest spikes/m3/quality/tests -q
```

只有发布新 fixture 版本时才能重建签入文件：

```powershell
uv run python spikes/m3/quality/fixture_tool.py generate
```

版本规则：

1. 修正文档而数据、schema、主体和 golden 不变：不升级 fixture。
2. 增加向后兼容的图表案例但不改变现有结果：升级后缀，例如 `m3-star-v1.1`。
3. 任何源行、字段类型、连接语义、权限语义或既有 golden 变化：升级主版本，例如 `m3-star-v2`。
4. 修改 `FIXTURE_VERSION` 后重建全部生成物；`manifest.json` 的每文件 SHA-256 必须随提交评审。
5. 验收证据记录 fixture 版本和 manifest SHA-256；旧证据不自动适用于新版本。
6. A1 的 V1 chart-case/SQLite golden 结果保持可复现；R2 从 V2 装载 `occurred_at`，在 SQLite/PostgreSQL 比较筛选、时间粒度、规范序列化和 `resolved_filters` 边界证据。

## 5. 数据库与合同验收

| ID | 阶段 | 验收项 | 方法 | 通过标准 | 证据 |
|---|---|---|---|---|---|
| M3-C01 | R0 | fixture 可复现 | 运行 `check` 和 fixture pytest | 生成内容逐字节一致，测试全绿 | `fixture-check.log` |
| M3-C02 | R0/A1 | 安全查询边界 | 图表配置编译 spike 注入物理表名、SQL、函数和未知 UUID | 全部在执行前拒绝；无 SQL/内部标识泄露 | `contract-negative.json` |
| M3-C03 | R0/A1 | 图表配置到 M2 AST | 对 `chart_cases.json` 每项编译并查询 | 与对应 golden pointer 一致 | `compiler-golden.json` |
| M3-C04 | R2 | 筛选顺序 | 运行四个 `filter_cases` | `mandatory AND RLS AND global AND page AND component`；行 ID 和金额一致 | `filter-golden.json` |
| M3-C05 | R2 | NULL/Decimal/Boolean/Date/DateTime | 双库运行 V2 边界查询 | 类型和值一致，无 float 漂移、NULL 改写、时区/DST 或日期越界 | `type-parity.json` |
| M3-C06 | R2 | 排序与 Top N | Top 2 查询重复运行 10 次 | 始终 P100、P200；稳定 tie-break；服务端截断前排序 | `top-n.json` |
| M3-DB01 | R1/R2 | SQLite golden | 新建空库、upgrade head、装载 fixture、运行全部图表/筛选查询 | 与 `golden_results.json` 完全一致 | `db-sqlite-golden.json` |
| M3-DB02 | R1/R2 | PostgreSQL golden | 隔离 PostgreSQL 库执行同组测试 | 与 golden 完全一致 | `db-postgresql-golden.json` |
| M3-DB03 | R2 | 双库一致性 | 对 DB01/DB02 规范化排序后比较 | columns、rows、类型、截断和来源证据一致 | `db-parity.json` |
| M3-DB04 | R1/R3 | 迁移可逆性 | SQLite/PostgreSQL 均执行 upgrade head、downgrade 前一 revision、re-upgrade head | schema 和数据约束恢复；无业务代码分叉 | `migration-{dialect}.log` |
| M3-P01 | R1/R2 | 三类当前工作区主体 | 分别运行相同 KPI 与分类聚合 | admin/editor 全量；viewer 仅固定北区 golden | `permission-principals.json` |
| M3-P02 | R2 | RLS 聚合前生效 | viewer 查询全部、分类、Top N | 未授权区域不进入聚合、中间缓存或 tooltip | `permission-rls-preaggregate.json` |
| M3-P03 | R2 | 伪造筛选不能放宽 RLS | viewer 提交南区或删除 RLS 的配置 | 南区交集 0 行；客户端不能表达/覆盖 RLS | `permission-forged-filter.json` |
| M3-P04 | R1/R2 | 跨工作区 | foreign administrator 读取 dashboard/dataset/field/query | 资源不可见或稳定拒绝；查询未执行 | `permission-cross-workspace.json` |
| M3-P05 | R1 | 能力边界 | editor 管数据集、viewer 编辑 dashboard | 403 稳定错误；无部分写入 | `permission-capabilities.json` |

## 6. 性能基准方法

### 6.1 输入和环境

正确性使用签入的 14 行 fixture；负载使用同一工具的确定性放大版本：

```powershell
uv run python spikes/m3/quality/fixture_tool.py benchmark --rows 100000 --output .tmp/m3-star-benchmark-100000
```

放大算法按原 14 行循环，重新编号事实主键和循环前缀订单号，每轮仍保留一对重复业务订单。两个维度不放大。`benchmark_manifest.json` 固定行数、字节数和 SHA-256。性能报告必须记录 Windows、CPU、内存、Python、Node、npm、SQLite、PostgreSQL、Chrome、Edge 版本；关闭开发热更新，使用 production build，服务与数据库不得与并行测试争用资源。

每个场景先预热 5 次，再记录至少 30 次；20 并发场景至少 3 轮，每轮每个 worker 执行相同的代表查询组合。使用 `perf_counter` 测端到端墙钟时间，服务端同时保留 `elapsed_ms`。报告原始样本、P50、P95、最大值、吞吐、错误、超时、截断、冷/热缓存状态，不删除离群值。P95 使用 nearest-rank：排序后取 `ceil(0.95*n)` 项。

代表查询组合固定为：全量 KPI、类别柱图、类别/区域堆叠、月趋势、Top 2、全局+页面+组件筛选、受限查看者同组查询。并发主体至少包含 administrator、editor 和 restricted viewer，缓存键不得跨 RLS 主体复用。

### 6.2 性能门禁

| ID | 场景 | 样本与负载 | 通过标准 | 证据 |
|---|---|---|---|---|
| M3-PERF01 | 普通页面可交互 | production build，清空 HTTP 缓存后导航，30 次 | P95 <= 2.0 s；可操作入口已稳定 | `perf-page-{browser}.json` |
| M3-PERF02 | 缓存仪表盘主要组件 | 已预热服务端查询缓存，打开标准 dashboard，30 次 | 主要组件最终态 P95 <= 3.0 s | `perf-dashboard-cached-{browser}.json` |
| M3-PERF03 | 常规单查询 | 100k 行，固定查询组合，单 worker 各 30 次 | 端到端 P95 <= 5.0 s，0 错误 | `perf-query-{dialect}-100000-c1.json` |
| M3-PERF04 | 20 用户并发 | PostgreSQL，20 worker，至少 3 轮 | 0 错误/越权/交叉缓存；P95、吞吐和超时完整记录；常规查询仍以 5 s 目标判定 | `perf-query-postgresql-100000-c20.json` |
| M3-PERF05 | 复杂/超时恢复 | 构造超过 10 s 或命中配置超时的查询 | 10 s 前显示进度；受服务端超时约束；可取消/重试 | `perf-timeout-recovery.json` |

若 PERF04 未达到 5 秒，M3-R3 不能把性能项记为通过；必须登记缺陷、对比 M2 同机基线并给出 M4 优化前是否允许里程碑验收的明确产品决定，不能只报告平均值。

## 7. 浏览器、视觉与前端状态矩阵

浏览器为验收日当前稳定版 Chrome 和 Edge。桌面固定 1440 x 900、DPR 1；移动固定 390 x 844，并额外用 DPR 2 验证 PNG 清晰度。每个 Canvas 检查像素缓冲区宽高大于 0，且采样区不全透明、不全为同一背景色；不能只断言 DOM 中存在 `<canvas>`。

| ID | 阶段 | 验收项 | 通过标准 | 证据 |
|---|---|---|---|---|
| M3-UI01 | R0/B1 | Chrome/Edge 核心图表 spike | 所有 chart case 非空、标签可读、无控制台错误 | 浏览器截图、console JSON、pixel JSON |
| M3-UI02 | R0/B1 | 1440 桌面布局 | 1/20/50 组件无重叠漂移；编辑控件可用 | `browser-*-desktop-layout-*.png` |
| M3-UI03 | R0/B1 | 390 移动只读布局 | 无横向溢出和文本遮挡；筛选可用；无编辑入口 | `browser-*-mobile-readonly-*.png` |
| M3-UI04 | R2 | 核心图表 golden | KPI、表格、排行、柱/条/堆叠、线/面积、饼/环数值与 golden 一致 | 每 case 数据断言及截图 |
| M3-UI05 | R2 | 图表固定尺寸 | loading/empty/error/hover/长标签不改变网格外尺寸 | 布局 bounding-box JSON |
| M3-UI06 | R2 | Canvas 与可访问替代 | Canvas 非空；标题、摘要和表格/文本替代可访问 | pixel JSON、accessibility snapshot |
| M3-UI07 | R0/R2 | 2x PNG | 像素尺寸为 CSS 尺寸 2 倍，文字/线条清晰且非空 | `export-2x-*.png`、尺寸 JSON |
| M3-UI08 | R1/R2 | loading/success/empty | 状态明确，空数据不伪装为 0 | 三态截图和组件测试 |
| M3-UI09 | R1/R2 | error/forbidden/timeout/truncated | 分别显示 code 对应信息、恢复动作和截断提示 | 状态截图、网络/console JSON |
| M3-UI10 | R1/R3 | 错误恢复 | 网络失败重试、取消旧请求、刷新/重开 | 旧响应不覆盖新状态；保存内容不丢失 | trace、恢复前后截图 |
| M3-UI11 | R3 | Chrome/Edge 完整流程 | 创建、配置、筛选、保存、重开、模板实例化、移动查看 | 每浏览器 trace 和关键截图 |

## 8. 依赖、包体积、许可证和回归

| ID | 阶段 | 验收项 | 通过标准 | 证据 |
|---|---|---|---|---|
| M3-D01 | R0/B1 | 图表/布局候选许可证 | 版本、直接/传递许可证、版权文件、商用兼容均记录，无未知/禁止项 | `licenses-m3.csv`、评估文档 |
| M3-D02 | R0/B1 | 候选 bundle | 同一 Vite production build 比较 baseline、gzip/brotli 和 route chunk | 原始 stats 可复现；超过预算有明确拒绝/拆包决定 | `bundle-m3.json`、build log |
| M3-D03 | R1 | lockfile 准入 | 仅 winner 在独立依赖提交进入生产 lockfile | 版本与 R0 证据一致，无 spike 依赖泄漏 | lockfile diff、许可证复核 |
| M3-R01 | 每轮 | M0 工程基线 | 后端健康/认证、前端 app shell、迁移及静态门禁 | 受影响测试全绿 | `regression-m0.log` |
| M3-R02 | 每轮 | M1 数据接入 | CSV/XLSX、预览、批次、质量规则、错误报告 | 受影响测试全绿，`data/` 样本保留 | `regression-m1.log` |
| M3-R03 | 每轮 | M2 数据建模 | 模型、数据集、指标、计算字段、RLS、超时、结果上限 | 全部查询治理行为保持 | `regression-m2.log` |
| M3-R04 | R3 | 完整后端门禁 | pytest+coverage、Ruff、BasedPyright | 命令成功，覆盖率不低于项目门槛 | `quality-backend.log` |
| M3-R05 | R3 | 完整前端门禁 | `npm check` 和 production build | lint/format/type/test/build 全绿 | `quality-frontend.log` |
| M3-R06 | R3 | PostgreSQL 与迁移 | `scripts/run_postgres_tests.py` | 集成测试和升降级全绿 | `quality-postgresql.log` |

当前 bundle 基线引用 M0 记录：初始 Ant Design bundle 679.02 kB、gzip 220.47 kB。M3-R0-B1 必须在相同 Node/npm、构建模式和入口条件下报告增量，不能拿不同构建设置的总量直接比较。最终预算由图表/布局 spike 决定并写入候选评估；本矩阵不预先伪造未测数值。

M3-R0 实测使用同一 Vite 配置的 React/Lucide/CSS baseline，候选初始增量为 84,199 raw / 24,291 gzip / 21,239 brotli bytes。ECharts 已通过动态 import 从初始 manifest 闭包移除，生产集成必须保持该边界。结构化结果见 `docs/verification/bundle-m3.json`、`licenses-m3.csv`、`m3-r0-browser-evidence.json`、`m3-r0-canvas-pixels.json` 和 `m3-r0-console.json`。

## 9. 证据目录与命名

M3-R3 将证据保存到 `docs/verification/m3/<run-id>/`，`run-id` 格式为 `YYYYMMDD-HHMM-<git-short-sha>`。文件名只用小写 ASCII、数字和连字符。每次运行至少包含：

- `environment.json`：操作系统、硬件、运行时、数据库和浏览器版本。
- `fixture-manifest.json`：签入 manifest 原样副本及其 SHA-256。
- `commands.log`：按执行顺序记录命令、退出码、开始/结束时间。
- `db-<dialect>-golden.json`、`permission-*.json`、`perf-*.json`。
- `browser-<browser>-<desktop|mobile>-<case>.png`。
- `canvas-pixels-<browser>-<viewport>-<case>.json`。
- `console-<browser>-<viewport>.json` 与 trace 文件。
- `bundle-m3.json`、`licenses-m3.csv` 和 production build log。

截图不得包含 Cookie、token、生产凭据或真实业务数据。JSON 证据使用稳定 key 顺序并包含 git SHA、fixture version、case ID、browser/dialect、viewport、started_at、duration、status。失败证据也保留，修复后用新 run-id 重跑，不覆盖原始证据。

## 10. 复现命令清单

当前已存在且应立即可运行：

```powershell
uv run python spikes/m3/quality/fixture_tool.py check
uv run pytest spikes/m3/quality/tests -q
uv run ruff check backend scripts spikes/m3/quality
uv run ruff format --check backend scripts spikes/m3/quality
```

M3-R1/R2 集成测试落地后纳入：

```powershell
uv run pytest backend/tests -q --cov=bi_system
uv run basedpyright backend/src backend/tests scripts
uv run python scripts/run_postgres_tests.py
npm --prefix frontend run check
npm --prefix frontend run build
```

浏览器和 M3 专用性能命令由 M3-R0-B1/M3-R2 实现后固定到 `commands.log`；在工具尚不存在时不写虚构命令。所有 Python 入口保持通过 `uv run` 调用。

## 11. M3-R0 退出清单

- [x] 三源星型 fixture 可确定性生成和逐字节校验。
- [x] Date、DateTime、Decimal、Boolean、NULL、时区/DST、重复业务键和无匹配维度均有固定用例。
- [x] KPI、表格、核心图表、排序、Top N 和四层筛选有 golden 数据指针。
- [x] administrator、editor、restricted viewer 和跨工作区负例已定义。
- [x] SQLite/PostgreSQL、迁移、20 并发、P95 和证据命名方法已定义。
- [x] Chrome/Edge、桌面/390 px、Canvas、截图、错误恢复、bundle 和许可证矩阵已定义。
- [x] M0-M2 持续回归门禁已列入矩阵。
- [x] M3-R0-A1 已证明 8 个 M2 可表达 chart case 编译执行并匹配 golden，2 个 time-grain case 稳定 fail closed。
- [x] M3-R0-B1 已交付 Chrome/Edge、桌面/390 px、1/20/50、Canvas、截图、bundle 和许可证实测证据。
- [x] 主 Agent 已将 A1/B1/C1 结论并入 M3 架构文档，所有阻塞合同已冻结。
- [x] ADR 0004 状态已由 Proposed 变为 Accepted。

最后四项是 M3-R0 的共同退出条件，不属于 C1 单独可以宣称完成的证据。任一项未完成，不进入仪表盘迁移、生产 API、生产路由或依赖提交。
