# M3-M6 全功能并行开发详细计划

## 0. 文档定位

本文是 `2026-07-17-m3-m6-multi-agent-development.md` 的可派发执行层，不替代需求规格、ADR、阶段验收记录或现有总纲。它将 M3-M6 拆成有依赖、有文件边界、有局部验证、有集成顺序的任务包，供最多 4 个并发 Agent 执行。

基线固定为 2026-07-17 已验收的 M2：M0 工程基础、M1 数据接入和 M2 数据建模不重复实现，只进入持续回归保护。当前唯一允许启动的生产阶段是 M3-R0；M3-R0 未通过前，不创建仪表盘迁移、生产 API、前端业务路由或生产依赖。

权威输入：

- `AGENTS.md`
- `docs/superpowers/specs/2026-07-14-bi-reporting-system-requirements.md`
- `docs/plans/2026-07-17-development-handoff.md`
- `docs/plans/2026-07-17-m3-m6-multi-agent-development.md`
- `docs/architecture/evaluations/frontend-components.md`
- `docs/verification/m2-verification.md`

## 1. 并行开发边界

### 1.1 允许的并行

- 里程碑按 M3、M4、M5、M6 串行过闸，单个里程碑内部按 R0、R1、R2、R3 串行。
- 每轮内部最多派发 3 个互不重叠的子任务，主 Agent 同时处理共享合同、集成和审查。
- 后续里程碑可以提前进行无生产依赖的资料评估、测试数据设计和 spike，但不得写迁移、注册路由、修改共享合同或添加生产依赖。
- 同一轮的后端、前端、质量任务只能依赖轮次开始时已冻结的合同，不得通过未提交的临时接口互相追赶。

### 1.2 禁止的并行

- 不同时实施两个里程碑的生产领域模型。
- 不允许两个 Agent 同时修改迁移链、`backend/src/bi_system/api/router.py`、`frontend/src/app/App.tsx`、依赖清单或共享配置。
- 不允许前端根据未冻结的响应样例先写生产适配，再要求后端追认合同。
- 不允许以 SQLite 单库通过代替共享数据库行为验收。
- 不允许以组件能显示代替权限、空状态、错误状态、移动端和浏览器验收。

### 1.3 总依赖链

```text
M2 accepted
  -> M3-R0 contracts and spikes
  -> M3-R1 domain foundation
  -> M3-R2 charts, queries and filters
  -> M3-R3 layouts, templates and M3 acceptance
  -> M4-R0 interaction context
  -> M4-R1 interaction queries
  -> M4-R2 parameters, bookmarks and advanced charts
  -> M4-R3 alerts and performance
  -> M5-R0 editor and export spikes
  -> M5-R1 bulletin editing foundation
  -> M5-R2 references and immutable publication snapshots
  -> M5-R3 export and notification
  -> M6-R0 AI security and evaluation baseline
  -> M6-R1 desensitized natural-language queries
  -> M6-R2 forecasting, anomaly and contribution analysis
  -> M6-R3 audit, recovery, security and cross-platform acceptance
  -> V1 acceptance
```

## 2. Agent 角色与所有权

| 角色 | 职责 | 默认允许修改 | 默认禁止修改 |
|---|---|---|---|
| 主 Agent / P | 合同冻结、计划、共享文件、依赖、迁移顺序、集成、提交、阶段验收 | 计划、ADR、共享合同、迁移、路由汇总、应用壳、配置、依赖清单、验收记录 | 未审查即批量接收子任务改动 |
| Agent A / 后端 | 领域模型、服务、独立 API 路由文件、后台任务、后端单元测试 | `backend/src/bi_system/<feature>/`、新路由文件、对应单元测试 | 路由汇总、迁移头、依赖清单、前端 |
| Agent B / 前端 | 页面、编辑器、交互、前端 API、组件测试、响应式状态 | `frontend/src/features/<feature>/`、对应测试和局部样式 | `App.tsx`、依赖清单、后端、共享配置 |
| Agent C / 质量专项 | spike、夹具、双数据库、权限负测、性能、浏览器、导出或 AI 专项 | 独立集成测试、基准脚本、测试夹具、截图和专项适配器 | 生产路由汇总、迁移头、应用壳、最终验收结论 |

共享文件由主 Agent 串行修改：

- `backend/src/bi_system/api/router.py`
- `frontend/src/app/App.tsx`
- `backend/migrations/versions/` 中的新 revision 及迁移链
- `pyproject.toml`、`uv.lock`、`frontend/package.json`、`frontend/package-lock.json`
- `.env.example`、`frontend/.env.example`、`compose.yaml`
- `docs/verification/mx-verification.md`
- 跨功能共享类型、配置和最终 ADR

建议的新功能边界需由各 R0 最终确认，初始候选为：

| 里程碑 | 后端候选目录 | 前端候选目录 |
|---|---|---|
| M3 | `bi_system.dashboards` | `features/dashboards` |
| M4 | `bi_system.analytics`、`bi_system.alerts` | `features/analytics`、`features/alerts` |
| M5 | `bi_system.bulletins`、`bi_system.exports`、`bi_system.notifications` | `features/bulletins`、`features/exports`、`features/notifications` |
| M6 | `bi_system.intelligence`、`bi_system.audit`、`bi_system.operations` | `features/intelligence`、`features/administration` |

## 3. planning-with-files v3.7 运行方式

### 3.1 计划隔离

- 正式实施时为 M3、M4、M5、M6 分别建立独立活动计划，不使用一个跨四个里程碑的长期运行计划。
- 正式项目计划和验收证据提交到 `docs/plans/`、`docs/architecture/`、`docs/verification/`。
- `.planning/`、活动指针、attestation、停止计数和 Agent JSONL ledger 属于本地运行态，不进入功能提交；开始 M3-R0 前先冻结其 Git 忽略策略。
- 主 Agent 独占里程碑 `task_plan.md`；子 Agent 不直接修改它。

### 3.2 Agent ledger

每个并行 Agent 只追加自己的 ledger 或提交结构化交接，至少包含：

```text
task_id
status: started | test_failed | blocked | ready_for_review
owned_files
changed_contracts
commands_run
test_result
remaining_risks
handoff_commit_candidate
```

主 Agent 仅依据文件差异、命令输出和 ledger 状态更新共享计划。计划内容冻结后进行 attestation；计划发生批准过的变更时由主 Agent 重新确认，不接受子 Agent 静默改写。

### 3.3 任务包合同

每个任务包派发时必须写明：

1. `task_id`、业务目标和进入条件。
2. 输入合同版本及允许修改的绝对文件边界。
3. 禁止修改列表和共享文件所有者。
4. 必须覆盖的成功、空、错误、越权或恢复状态。
5. 局部验证命令和期望结果。
6. 交付文件、合同变化、已知风险和建议提交信息。

任务包目标大小为一个可独立审查的集成提交。任务超过一个领域、一个迁移或一组明确 UI 状态时继续拆分，不通过延长并行占用来隐藏过大范围。

## 4. 每轮标准工作流

### 4.1 轮次开始

1. 主 Agent 检查 `git status --short`，识别用户或其他 Agent 的已有改动。
2. 确认上一轮完整门禁绿色，读取当前里程碑计划、ADR 和验证矩阵。
3. 冻结本轮合同、文件所有权和禁止修改清单。
4. 创建最多三个子任务；不能形成互斥文件边界时改为串行。
5. 记录基准提交、数据库 revision、依赖锁版本和标准夹具版本。

### 4.2 并行执行

- Agent A、B、C 先写失败测试或可执行验证，再实现任务范围。
- 子 Agent 只运行局部检查，不执行 `git add`、`git commit` 或共享迁移调整。
- 发现合同不足时停止相关任务并上报，不在子任务内扩展共享合同。
- 主 Agent 同步处理共享合同或审查准备，不与子 Agent 争用文件。

### 4.3 串行集成

1. 主 Agent 逐个审查任务包，先查越权、权限继承、可移植性和错误状态。
2. 按“合同/迁移 -> 后端 -> 前端 -> 质量证据”顺序集成。
3. 每个集成提交先运行受影响测试和 `git diff --check`。
4. 完成本轮后运行后端静态检查、前端检查和必要的 PostgreSQL 测试。
5. 更新计划和 ledger；未满足退出条件则继续当前轮，不进入下一轮。

## 5. M0-M2 基线保护通道

M0-M2 已完成，不重新派发功能开发。每个后续轮次保留以下回归责任：

| 基线 | 必保行为 | 触发扩展验证的改动 |
|---|---|---|
| M0 | 认证、会话、配置、CORS、迁移链、Windows/SQLite 启动、应用壳 | 身份、配置、路由、迁移、部署或安全改动 |
| M1 | 上传、预览、模板、质量规则、批次状态、重试、取消、错误报告、worker 恢复 | 后台任务、文件存储、通知、审计或备份改动 |
| M2 | 语义模型、数据集、指标、计算字段、RLS、受控查询、超时和双数据库语义 | 图表查询、交互查询、导出、AI、缓存或索引改动 |

主 Agent 每轮至少运行受影响的 M0-M2 测试；里程碑末运行完整后端、前端和 PostgreSQL 门禁。任何后续功能不得绕过 M2 的工作区、资源权限、行级权限、版本、批次、超时和结果规模限制。

## 6. M3 BI 核心

### 6.1 M3-R0 架构与技术验证

进入条件：M2 验收记录存在；工作区来源明确；不添加生产依赖。

| 任务包 | 所有者 | 范围 | 交付物 | 局部验证 |
|---|---|---|---|---|
| M3-R0-P1 | P | 冻结 dashboard、version、page、component、template、layout、filter、permission、recycle-bin 状态模型 | M3 详细架构计划、领域词汇、状态机、版本与并发规则 | 合同评审清单，无未决必填字段 |
| M3-R0-P2 | P | 冻结图表配置、字段槽、查询请求/响应、错误码、截断、来源批次和指标版本合同 | 强类型合同草案及前后端示例 | 非法配置、未知字段、越权和超时矩阵完整 |
| M3-R0-A1 | A | spike：图表配置编译为 M2 查询 AST，不接受物理表名、SQL 或任意函数 | 可运行服务端 spike、映射矩阵、结构化错误、性能结论 | 代表图表与人工/M2 结果一致，注入负测通过 |
| M3-R0-B1 | B | spike：ECharts 与候选布局库；桌面编辑、390 px 只读移动、2x PNG、事件上下文、可访问替代 | 可运行前端 spike、桌面/移动截图、bundle、浏览器和许可证报告 | Canvas 非空、图表可读、无重叠、无控制台错误 |
| M3-R0-C1 | C | 标准星型数据集、金色查询结果、图表快照、权限用户矩阵、基准与浏览器矩阵 | M3 fixture 设计与验收矩阵 | SQLite/PostgreSQL 期望值、20 并发和 P95 方法可复现 |

主 Agent 集成顺序：P1 -> P2 -> A1/B1/C1 结论 -> ADR/评估。只有通过准入的图表和布局库才能由主 Agent 在后续独立依赖提交中加入 lockfile。

退出条件：合同无阻塞项；库的版本、许可证、bundle、浏览器、截图和选择理由有记录；错误矩阵和 M3 验收矩阵可执行。建议提交：`docs: define M3 dashboard architecture`。

### 6.2 M3-R1 领域基础与工作台骨架

进入条件：M3-R0 文档提交且工作区绿色。

| 任务包 | 所有者 | 范围 | 交付物 | 局部验证 |
|---|---|---|---|---|
| M3-R1-P1 | P | 建立共享合同模块、新迁移、路由注册和懒加载入口；独立处理生产依赖 | 迁移 revision、共享配置、依赖锁、集成骨架 | SQLite 升降级；依赖许可证和 bundle 基线 |
| M3-R1-A1 | A | dashboard、version、page、component、layout、template、permission、trash 领域服务 | 后端领域包、新 API 路由文件、单元测试 | 生命周期、工作区隔离、乐观并发、引用保护测试 |
| M3-R1-B1 | B | 仪表盘列表、空白/模板创建入口、编辑器壳、组件面板、画布、属性面板 | `features/dashboards` 页面与组件测试 | 加载、成功、空、错误、无权限、桌面/移动状态 |
| M3-R1-C1 | C | 图表配置 schema、非法组合、迁移可移植性、标准夹具装载 | 合同测试和双数据库集成测试 | 未知版本、重复布局、悬空引用、跨工作区负测 |

主 Agent 集成顺序：依赖提交 -> 迁移与合同 -> 后端领域/API -> 前端骨架 -> 集成测试。迁移、后端、前端和依赖不得混为一个提交。

退出条件：可以创建、列出、读取和保存空仪表盘草稿；前端所有基础状态可见；SQLite/PostgreSQL 迁移一致；尚不要求真实图表查询。

### 6.3 M3-R2 核心图表、字段配置与筛选

进入条件：M3-R1 生命周期和工作台骨架稳定。

| 任务包 | 所有者 | 范围 | 交付物 | 局部验证 |
|---|---|---|---|---|
| M3-R2-A1 | A | 图表查询服务与 API，复用 M2 权限/版本/批次/超时/规模限制 | 查询编译、执行、序列化、截断和错误响应 | 人工核算、RLS 聚合前生效、越权、超时、NULL/Decimal/日期测试 |
| M3-R2-B1 | B | KPI、趋势指标、目标进度、明细表、排行表、柱状/条形/堆叠、折线/面积、饼/环图、富文本和图片 | 图表渲染器、字段槽、聚合、排序、Top N、单位、图例、标签、提示和主题 | 各图加载/成功/空/错误；长标签；390 px；非空 Canvas |
| M3-R2-C1 | C | 全局、页面、组件筛选；相对/绝对日期；筛选类型和合并优先级 | 筛选合同、服务端合并测试、权限回归夹具 | `RLS AND global AND page AND component` 顺序确定，跨库结果一致 |
| M3-R2-P1 | P | 集成共享类型、前端 API、路由及缓存键；审查查询边界 | 端到端核心图表闭环 | 网络错误、取消、截断提示和来源证据可见 |

退出条件：核心图表与 M2/人工结果一致；筛选优先级固定；所有查询继承权限；移动端可查看和筛选；常规查询 P95 有基线。

### 6.4 M3-R3 布局、模板、生命周期与验收

进入条件：M3-R2 核心图表和筛选稳定。

| 任务包 | 所有者 | 范围 | 交付物 | 局部验证 |
|---|---|---|---|---|
| M3-R3-A1 | A | 模板发布/实例化、版本保存、并发冲突、回收站 30 天、恢复、引用影响和删除保护 | 生命周期 API 与审计上下文 | 模板升级不影响实例；冲突不丢数据；悬空引用被阻止 |
| M3-R3-B1 | B | 拖拽缩放、组件复制粘贴、多页面导航、桌面/移动独立布局、模板流程 | 完整桌面编辑器与移动只读视图 | 布局不覆盖、不漂移；键盘基本操作；390 px 无横向溢出 |
| M3-R3-C1 | C | M3 性能、双数据库、权限、Chrome/Edge、桌面/移动浏览器验收 | P95 报告、截图、浏览器日志、缺陷清单 | 页面 2 秒、缓存首屏 3 秒、常规查询 5 秒目标有证据或明确缺陷 |
| M3-R3-P1 | P | 收口缺陷、完整门禁、验收记录和可运行版本 | `docs/verification/m3-verification.md` | 全门禁、截图引用、标准数据集和版本信息完整 |

退出条件：空白和模板均可创建、保存、重开；桌面可编辑；移动可查看与筛选；布局独立；核心图表正确；完整 M3 门禁通过。建议验收提交：`docs: record M3 verification evidence`。

## 7. M4 高级分析

### 7.1 M4-R0 交互上下文合同

进入条件：M3 已验收。M3-R3 后半段可以预写无生产改动的评估材料，但正式合同以 M3 验收基线为输入。

| 任务包 | 所有者 | 范围 | 交付物 | 局部验证 |
|---|---|---|---|---|
| M4-R0-P1 | P | 冻结 interaction context：工作区、权限、批次、指标版本、筛选、参数、层级路径、来源组件、事件 ID | M4 计划、状态机、事件合同和 ADR | 重放、循环检测、版本固定和权限传播规则无歧义 |
| M4-R0-A1 | A | spike：联动、下钻、上钻、明细穿透服务端查询边界 | 查询原型、成本限制、错误矩阵 | 不接受任意明细字段；RLS 和资源权限始终生效 |
| M4-R0-B1 | B | spike：跨组件事件、面包屑、撤销交互、异步竞态和 URL/内存状态边界 | 前端状态机和交互原型 | 快速点击无旧请求覆盖；循环联动可阻止 |
| M4-R0-C1 | C | 权限泄漏、循环联动、高基数、深层级、批次/版本漂移测试设计 | M4 标准场景和验收矩阵 | 正向、负向、性能和恢复场景齐全 |

退出条件：所有交互都能携带并验证完整上下文；事件可追踪、可取消、可防循环；提交 `docs: define M4 interaction architecture`。

### 7.2 M4-R1 联动、下钻、上钻与穿透

| 任务包 | 所有者 | 范围 | 交付物 | 局部验证 |
|---|---|---|---|---|
| M4-R1-A1 | A | 交互查询编排、层级解析、受控明细查询、审计上下文 | 服务与 API 路由文件 | 权限、字段白名单、结果上限、超时、批次和版本测试 |
| M4-R1-B1 | B | 点击联动、级联筛选、下钻/上钻、面包屑、明细抽屉/页面、加载与取消 | 交互 UI 和组件测试 | 快速切换、空明细、错误恢复、移动查看和筛选上下文 |
| M4-R1-C1 | C | 跨组件权限、循环图、竞态、高基数和跨数据库语义 | 集成与压力测试 | 不泄漏未授权维度/行；旧请求不覆盖新状态 |
| M4-R1-P1 | P | 共享事件类型和端到端集成 | 可重放交互闭环 | 浏览器证据包含筛选链、面包屑和网络上下文 |

退出条件：联动、下钻、上钻和穿透可恢复且不可绕过权限；审计可定位来源组件与查询上下文。

### 7.3 M4-R2 参数、个人视图、书签与高级图表

| 任务包 | 所有者 | 范围 | 交付物 | 局部验证 |
|---|---|---|---|---|
| M4-R2-A1 | A | 参数定义/校验、个人视图、书签持久化与权限 | 领域服务和 API | 默认值、类型、共享边界、版本兼容和恢复测试 |
| M4-R2-B1 | B | 参数控件、书签管理、双轴、组合图、条件格式、阈值、目标线、参考区间 | 高级配置 UI | 序列化重放、错误配置提示、键盘和移动查看 |
| M4-R2-B2 | B | 瀑布、矩形树、旭日、散点、气泡、箱线、直方、热力、漏斗、桑基、仪表盘、交叉表 | 标准图表适配器 | 每类图金色结果、空/错误、长标签、非空渲染和导出清晰度 |
| M4-R2-C1 | C | 地图候选、地理数据许可、图表兼容矩阵与视觉回归 | 地图评估/适配器结论、快照矩阵 | 无许可风险；地理缺失值和移动端降级明确 |

Agent B 的两个任务包不得同时派给同一 Agent；应按“高级配置”和“扩展图表”拆成两个集成波次，或将图表兼容专项临时交给 Agent C，在文件边界不重叠时执行。

退出条件：参数、个人视图和书签可恢复；高级配置只使用强类型 schema；全部 V1 图表家族有生产适配或明确的准入阻塞记录。

### 7.4 M4-R3 规则告警与性能优化

| 任务包 | 所有者 | 范围 | 交付物 | 局部验证 |
|---|---|---|---|---|
| M4-R3-A1 | A | 告警规则版本、调度状态、触发记录、通知事件 | 告警领域、任务和 API | 重复触发、版本固定、权限、失败重试和审计测试 |
| M4-R3-A2 | A | 查询缓存、失效键、索引建议和 PostgreSQL 适配器 | 缓存/优化服务及 portable fallback | 不跨用户/RLS 复用；批次/版本变更正确失效 |
| M4-R3-B1 | B | 告警配置与状态、复杂查询进度、取消、性能感知反馈 | UI 和状态测试 | 进度不阻塞页面；失败可恢复；移动端可查看告警 |
| M4-R3-C1 | C | 20 并发、常规联动 P95、复杂查询、缓存冷/热、权限回归 | 基准报告和浏览器证据 | 常规联动 P95 < 2 秒；复杂查询受超时限制 |
| M4-R3-P1 | P | 收口、完整门禁和 M4 验收 | `docs/verification/m4-verification.md` | 双数据库、权限、性能、桌面/移动和回归全部记录 |

Agent A 的两个任务包按独立目录/提交串行集成；如缓存与告警共享任务基础设施，则由主 Agent 先冻结后台任务合同。

退出条件：高级分析可恢复且安全；告警可追溯；常规联动达到 P95 目标；提交 `docs: record M4 verification evidence`。

## 8. M5 通报系统

### 8.1 M5-R0 编辑器、快照与导出验证

进入条件：M4 已验收。可在 M4-R3 中提前开展不依赖生产合同的编辑器和导出 spike，但发布快照合同必须以已验收的 M3/M4 资源版本为准。

| 任务包 | 所有者 | 范围 | 交付物 | 局部验证 |
|---|---|---|---|---|
| M5-R0-P1 | P | 冻结 bulletin、template、block、draft version、publication snapshot、revision、withdrawal、lock、export job 状态机 | M5 计划、领域合同、引用与不可变性 ADR | 发布后禁止覆盖；模板升级不改变既有通报；引用版本固定 |
| M5-R0-A1 | A | spike：单人锁、租约、自动保存、接管、冲突恢复、不可变快照事务边界 | 服务端原型和冲突矩阵 | 超时、双开、管理员接管、网络重试、幂等测试 |
| M5-R0-B1 | B | spike：TipTap 结构化块、中文 IME、粘贴清理、锁定/必填块、确定性 JSON、长文档分页 | 编辑器原型、浏览器截图、bundle 和许可证报告 | 中文输入不丢字；锁定块不可编辑；序列化稳定 |
| M5-R0-C1 | C | spike：PDF、Word、PNG 长图、打印、Excel/CSV、中文字体和跨平台生成链 | 导出样例、视觉对比、依赖/许可证/平台结论 | 分页、页眉页脚、表格、图片、字体和大文档可验证 |

退出条件：编辑器和导出链路无阻塞许可证/平台风险；自动保存和发布状态机无歧义；提交 `docs: define M5 bulletin architecture`。

### 8.2 M5-R1 通报领域与结构化编辑器

| 任务包 | 所有者 | 范围 | 交付物 | 局部验证 |
|---|---|---|---|---|
| M5-R1-P1 | P | 生产依赖、迁移、共享合同、路由和懒加载入口 | 独立依赖提交、迁移 revision 和集成骨架 | 许可证、bundle、SQLite/PostgreSQL 升降级 |
| M5-R1-A1 | A | 通报、模板、块、版本、锁、自动保存、回收站和权限服务 | 后端领域/API 与单元测试 | 状态机、30 天回收、并发、权限和引用保护 |
| M5-R1-B1 | B | 标题、段落、列表、表格、图片、指标、图表、目录、分隔、分页块编辑器 | 通报编辑工作台 | 每类块加载/编辑/空/错误；中文 IME；键盘；恢复 |
| M5-R1-B2 | B | 封面、期号、日期、部门变量；固定/可选/重复章节；必填/锁定块；页眉页脚页码水印落款 | 模板设计与实例化 UI | 模板变量校验；既有实例不随模板升级变化 |
| M5-R1-C1 | C | 锁超时、接管、断网自动保存、重复请求、冲突恢复和版本一致性 | 并发集成和浏览器测试 | 不丢内容、不产生双持有者、不静默覆盖 |

两个前端任务包按编辑器核心和模板体验分波次集成，避免同时修改共享编辑器 schema。

退出条件：可以从空白或模板创建草稿；所有结构化块可稳定序列化；锁、自动保存、历史版本和冲突恢复可验证。

### 8.3 M5-R2 图表引用与不可变发布快照

| 任务包 | 所有者 | 范围 | 交付物 | 局部验证 |
|---|---|---|---|---|
| M5-R2-A1 | A | 解析指标/图表引用，刷新草稿数据，生成固定批次/指标版本/筛选/图表配置的发布快照 | 引用解析和发布服务 | 引用失效、越权、质量阻塞、版本漂移和事务回滚测试 |
| M5-R2-A2 | A | 发布、撤回、修订版、资源删除保护和审计事件 | 生命周期 API | 已发布不可覆盖；撤回保留；修订链连续 |
| M5-R2-B1 | B | 实时引用刷新、失效提示、发布预检、质量/权限阻塞、修订与撤回体验 | 编辑器发布流程 | 用户明确看到批次、口径、筛选和失败恢复动作 |
| M5-R2-C1 | C | 快照不可变性、并发发布、引用权限、批次和指标版本金色测试 | 端到端发布证据 | 发布后源数据/配置变化不改变历史快照 |
| M5-R2-P1 | P | 集成发布权限、审计和状态合同 | 可追溯发布闭环 | 编辑者与发布者职责分离，普通用户不能发布 |

退出条件：草稿引用可刷新；发布快照不可变；撤回和修订保留审计；发布权限和行级权限不可绕过。

### 8.4 M5-R3 导出、打印与系统内通知

| 任务包 | 所有者 | 范围 | 交付物 | 局部验证 |
|---|---|---|---|---|
| M5-R3-A1 | A | 后台导出任务、状态、取消、重试、产物存储、权限、过期和审计 | 导出领域、worker、API | 幂等、失败恢复、越权下载、结果清理和任务状态测试 |
| M5-R3-A2 | A | 系统内通知基础与事件：共享/发布、导入结果、质量异常、指标告警、编辑锁、导出完成 | 通知领域和查询 API | 去重、已读状态、权限、事件版本和失败隔离 |
| M5-R3-B1 | B | 导出中心、进度、取消/重试、下载、打印和通知中心 | 前端工作流 | 加载/空/错误/完成、移动查看、过期产物和恢复 |
| M5-R3-C1 | C | 仪表盘 PNG/PDF、单图 PNG/复制图片、通报 PDF/Word/PNG/打印、表格 Excel/CSV | 格式矩阵、视觉回归、中文字体和大文档性能报告 | Chrome/Edge、Windows/Linux 兼容链路和样例可追溯 |
| M5-R3-P1 | P | 收口、完整门禁和 M5 验收 | `docs/verification/m5-verification.md` | 权限、任务、导出样例、浏览器、跨平台结果完整 |

Agent A 的导出和通知任务按独立领域包与提交串行集成；共享后台任务合同由主 Agent 先冻结。

退出条件：全部 V1 导出格式可用；系统内通知覆盖规定事件；发布/撤回/修订、锁和导出形成闭环；提交 `docs: record M5 verification evidence`。

## 9. M6 智能与生产加固

### 9.1 M6-R0 安全、模型与评估基线

进入条件：M5 已验收。可在 M5-R3 中预先构建脱敏规则样例和离线评估数据，但不得发送真实业务数据或接入生产模型。

| 任务包 | 所有者 | 范围 | 交付物 | 局部验证 |
|---|---|---|---|---|
| M6-R0-P1 | P | 冻结公开/内部/敏感/严格敏感分级、确认策略、只读查询计划、证据、保存和失败合同 | M6 安全计划、威胁模型、ADR、模型调用边界 | 模型无数据库凭据；严格敏感禁止问数；保存需用户主动操作 |
| M6-R0-A1 | A | spike：模型请求 -> 意图/指标/筛选 -> M2-M4 查询计划验证 -> 本地执行 -> 脱敏结果 -> 模型解释 | 只读编排原型和结构化失败矩阵 | SQL/任意代码拒绝；权限、复杂度、结果规模和超时生效 |
| M6-R0-B1 | B | spike：对话、计划确认、敏感确认、证据、失败、主动保存和取消体验 | 交互原型和状态机 | 不默认执行敏感查询；不自动保存或发布；证据可见 |
| M6-R0-C1 | C | 脱敏、越权、提示注入、间接注入、幻觉、证据不足、小样本和评估数据集 | 安全/质量评估矩阵和红队夹具 | 每类攻击有预期拒绝或降级结果 |

退出条件：数据边界、模型适配器、人工确认、证据和失败策略冻结；外部模型只接收策略允许且脱敏的数据；提交 `docs: define M6 intelligence security architecture`。

### 9.2 M6-R1 脱敏网关与自然语言问数

| 任务包 | 所有者 | 范围 | 交付物 | 局部验证 |
|---|---|---|---|---|
| M6-R1-P1 | P | 模型适配器依赖/配置、密钥边界、审计字段和共享合同 | 独立依赖/配置提交与安全清单 | 无密钥进入仓库/日志；生产配置显式失败 |
| M6-R1-A1 | A | 字段分类、掩码、泛化、去标识化、聚合、小样本保护和策略决策 | 脱敏网关及测试 | 四级数据策略、组合字段重识别和输出扫描 |
| M6-R1-A2 | A | 自然语言查询编排、指标解析、计划校验、本地只读执行、结果证据和模型解释 | 智能查询任务/API | 模型不可直连 DB；越权、复杂度、规模、超时和取消测试 |
| M6-R1-B1 | B | 问数对话、查询计划确认、敏感确认、证据面板、自动图表预览、主动保存 | 智能分析 UI | 加载/失败/取消/证据不足；保存前二次确认 |
| M6-R1-C1 | C | 提示注入、跨工作区、RLS、敏感数据、输出泄漏、幻觉和任务恢复测试 | 红队与端到端评估报告 | 未授权数据零泄漏；严格敏感请求稳定拒绝 |

Agent A 的网关与问数编排按两个提交串行集成，先建立脱敏/策略边界，再允许模型编排调用。

退出条件：自然语言问数完全复用受控查询；结果展示数据集、口径、筛选、时间和失败原因；敏感确认与严格敏感禁止策略可验证。

### 9.3 M6-R2 摘要、图表、预测、异常与贡献分析

| 任务包 | 所有者 | 范围 | 交付物 | 局部验证 |
|---|---|---|---|---|
| M6-R2-P1 | P | 评估并冻结成熟算法库、版本、许可证、失败策略和结果 schema | 算法评估/ADR 与依赖提交 | 不手写核心统计引擎；Windows/Linux wheels/运行兼容 |
| M6-R2-A1 | A | 自动指标摘要、自动图表建议、趋势预测、异常点检测、贡献度分析任务 | 分析服务、任务状态和 API | 短序列、缺失、常量、高噪声、季节性和超时处理 |
| M6-R2-B1 | B | 结果解释、置信/误差信息、证据、对比、失败原因和主动保存 | 分析结果 UI | 不夸大置信度；失败可理解；移动端可查看 |
| M6-R2-C1 | C | 离线基线、金色数据、准确度/误报漏报、稳定性、性能和脱敏回归 | 评估报告与阈值建议 | 每个能力有可复现指标和不通过阈值 |

退出条件：所有智能能力有可量化评估；错误和证据透明；生成内容只能主动保存，不能自动发布。

### 9.4 M6-R3 审计、安全、备份恢复与跨平台验收

| 任务包 | 所有者 | 范围 | 交付物 | 局部验证 |
|---|---|---|---|---|
| M6-R3-A1 | A | 审计覆盖认证、账号、权限、数据、指标、仪表盘、通报、导出、AI、配置、备份和迁移；180 天保留和 CSV 导出 | 审计领域/API/保留任务 | 普通管理员不可改；无令牌/密码/未脱敏数据 |
| M6-R3-A2 | A | 首次改密、失败锁定、会话过期、强制下线、敏感确认和后台任务可观测性 | 身份安全与结构化日志加固 | 锁定/解锁、会话撤销、错误编号和日志脱敏测试 |
| M6-R3-A3 | A | 压缩、低峰、限速备份；3 个每日+2 个每周保留；恢复和危险迁移前备份 | 运维脚本、恢复验证和文档 | SQLite/PostgreSQL 备份恢复、失败清理、数据校验 |
| M6-R3-B1 | B | 审计检索/导出、成员安全、系统配置、备份状态和敏感确认 UI | 管理界面与组件测试 | 权限、筛选、空/错误、确认、防误操作和无障碍 |
| M6-R3-C1 | C | Windows/Linux、SQLite/PostgreSQL、Chrome/Edge、移动浏览器、20 用户并发、安全、恢复演练 | V1 综合验收报告和证据目录 | 需求第 13 节 8 项全部可追溯 |
| M6-R3-P1 | P | 收口、全量门禁、V1 追踪矩阵和 M6 验收 | `docs/verification/m6-verification.md` | 所有迁移、测试、性能、截图、导出、安全和恢复证据完整 |

Agent A 的三个任务包必须拆成审计、安全、备份三个串行集成波次，或将备份恢复专项交给 Agent C，但不能并发修改共享配置和运维脚本。

退出条件：M6 和需求第 13 节全部通过；Windows/Linux 与双数据库可运行；恢复演练成功；安全负测无阻塞缺陷；提交 `docs: record M6 verification evidence` 后才可宣布 V1 完成。

## 10. 跨里程碑提前验证通道

提前验证只利用空闲并发槽，不得挤占当前里程碑质量任务：

| 当前阶段 | 可提前进行 | 禁止进行 |
|---|---|---|
| M3-R2/R3 | M4 事件场景草案；M5 编辑器/导出资料收集 | M4/M5 生产模型、路由、迁移、生产依赖 |
| M4-R2/R3 | M5 编辑器和导出 spike；M6 脱敏/红队夹具草案 | M5/M6 生产服务、密钥配置、模型调用 |
| M5-R2/R3 | M6 离线安全评估、算法库和跨平台依赖评估 | 真实业务数据外发、生产 AI API、审计迁移 |

提前验证结果必须进入 `docs/architecture/evaluations/` 或当前里程碑明确批准的 spike 目录。当前里程碑出现失败测试、合同变化、迁移冲突或性能回退时，立即停止提前通道，将并发槽归还当前阶段。

## 11. 功能覆盖矩阵

| 需求能力 | 主任务包 | 验收证据 |
|---|---|---|
| 空白/预设/团队模板仪表盘 | M3-R1、M3-R3 | 创建、实例化、保存、重开、模板升级隔离 |
| 桌面编辑与移动只读布局 | M3-R0-B1、M3-R3-B1 | 桌面及 390 px 截图、无重叠/溢出 |
| 核心图表、表格、排行 | M3-R2-B1 | 金色结果、空/错状态、Canvas 非空 |
| 扩展图表、地图、交叉表 | M4-R2-B2、M4-R2-C1 | 图表兼容矩阵、地图许可和视觉回归 |
| 聚合、排序、Top N、单位、图例、标签 | M3-R2-B1 | schema 重放和组件测试 |
| 双轴、堆叠、条件格式、阈值、目标线、参考区间 | M4-R2-B1 | 高级配置序列化和金色结果 |
| 全局/页面/组件/日期筛选 | M3-R2-C1 | 合并优先级、RLS、双数据库 |
| 级联、联动、下钻、穿透、面包屑 | M4-R0、M4-R1 | 交互上下文、权限、竞态和浏览器证据 |
| 参数、个人视图、书签 | M4-R2-A1/B1 | 持久化、共享权限、恢复 |
| 规则告警 | M4-R3-A1/B1 | 规则版本、触发、通知和审计 |
| 通报所有结构化块和模板变量 | M5-R1 | 中文 IME、锁定/必填、确定性重放 |
| 编辑锁、自动保存、历史、接管、冲突恢复 | M5-R0-A1、M5-R1-C1 | 并发和故障恢复测试 |
| 快照发布、撤回、修订 | M5-R2 | 不可变性、权限、审计和版本链 |
| 所有导出格式和打印 | M5-R0-C1、M5-R3 | 格式样例、视觉回归、跨平台 |
| 系统内通知 | M5-R3-A2/B1 | 事件覆盖、权限、去重和状态 |
| 自然语言问数、摘要和自动图表 | M6-R0、M6-R1、M6-R2 | 证据、确认、主动保存和红队测试 |
| 预测、异常、贡献度 | M6-R2 | 离线准确度、误报漏报、性能 |
| 数据分级和脱敏网关 | M6-R0、M6-R1-A1 | 四级策略、小样本、输出扫描 |
| 审计 180 天和 CSV 导出 | M6-R3-A1 | 不可篡改、保留任务、敏感信息检查 |
| 账号安全和可观测性 | M6-R3-A2 | 锁定、过期、下线、错误编号和日志 |
| 备份、保留和恢复 | M6-R3-A3/C1 | Windows/Linux、双数据库恢复演练 |

## 12. 质量与验收门禁

### 12.1 每个任务包

- 运行受影响单元/组件测试。
- 对新 API 添加成功、校验、认证、越权和跨工作区测试。
- 对 UI 添加加载、成功、空和错误状态。
- 执行 `git diff --check`，报告未运行的验证及原因。

### 12.2 每轮集成

```powershell
uv run ruff check backend scripts
uv run ruff format --check backend scripts
uv run basedpyright backend/src backend/tests scripts
uv run pytest backend/tests -q
npm --prefix frontend run check
npm --prefix frontend run build
```

涉及迁移、共享查询、权限、后台任务、导出或 AI 时增加：

```powershell
uv run python scripts/run_postgres_tests.py
```

### 12.3 每个里程碑

```powershell
uv sync --locked --all-groups
uv run pytest backend/tests -q --cov=bi_system
uv run python scripts/run_postgres_tests.py
uv run ruff check backend scripts
uv run ruff format --check backend scripts
uv run basedpyright backend/src backend/tests scripts
npm --prefix frontend ci
npm --prefix frontend run check
npm --prefix frontend run build
uv run pre-commit run --all-files
```

还必须保存：

- Windows 版本、Python/Node/npm/PostgreSQL/浏览器版本。
- SQLite/PostgreSQL 测试数、迁移升降级结果。
- 标准数据集、fixture 版本和人工核算结果。
- 性能 P50/P95、并发数、错误数、超时和截断结果。
- Chrome/Edge 桌面截图及 390 px 移动截图。
- Canvas/图表/编辑器/导出非空和视觉检查结果。
- 权限、跨工作区、RLS、敏感数据和提示注入负测。
- 实际导出样例、安全报告和恢复演练记录。

## 13. 建议提交序列

每个任务包不强制对应一个提交，但每个提交必须聚焦、可审查、可回滚。推荐骨架：

### M3

```text
docs: define M3 dashboard architecture
build(web): add approved dashboard dependencies
feat(db): add dashboard domain foundation
feat(api): add dashboard management
feat(web): add dashboard workspace
feat(analytics): add dashboard queries and filters
feat(web): add dashboard layouts and templates
docs: record M3 verification evidence
```

### M4

```text
docs: define M4 interaction architecture
feat(analytics): add governed interaction queries
feat(web): add dashboard interactions
feat(analytics): add parameters and bookmarks
feat(web): add advanced chart configuration
feat(alerts): add governed metric alerts
perf(analytics): add query cache and tuning
docs: record M4 verification evidence
```

### M5

```text
docs: define M5 bulletin architecture
build(web): add approved editor dependencies
feat(db): add bulletin domain foundation
feat(api): add bulletin management
feat(web): add structured bulletin editor
feat(bulletins): add immutable publication snapshots
feat(exports): add background export workflows
feat(notifications): add in-system notifications
docs: record M5 verification evidence
```

### M6

```text
docs: define M6 intelligence security architecture
build(ai): add approved model and analytics adapters
feat(security): add desensitization gateway
feat(ai): add governed natural language queries
feat(analytics): add forecasting and anomaly analysis
feat(audit): complete audit coverage
feat(ops): add backup and recovery workflows
fix(security): harden identity and session controls
docs: record M6 verification evidence
```

迁移、依赖、后端合同、前端接入和验收记录必须分开；不为了匹配上述示例而合并不相关改动。

## 14. V1 范围排除

以下能力不进入任何 M3-M6 生产任务包：直接数据库连接、现有 API 脚本集成、审核工作流、实时多人协作、外部邮件/短信/企业消息通知、本地大模型、自定义图表插件、移动端编辑、原生移动应用、透视分组、多租户计费和独立 OLAP 引擎。

评估或 spike 发现这些能力可能有价值时，只记录为后续候选需求，不添加兼容层、占位迁移、隐藏路由或未启用生产依赖。

## 15. 风险与停止条件

出现任一情况立即暂停相关并行任务，由主 Agent 缩小范围并恢复稳定基线：

- 当前里程碑合同仍在频繁变化。
- 两个 Agent 需要修改同一文件或同一迁移。
- 工作区出现来源不明或与任务重叠的改动。
- SQLite/PostgreSQL 行为不一致且没有适配器策略。
- 图表、布局、编辑器、导出、模型或算法库未通过许可证/包体积/平台 spike。
- 权限、RLS、批次或版本上下文在任何查询、导出、快照或 AI 路径丢失。
- 性能优化要求引入数据库专属 SQL，但缺少 portable fallback。
- 浏览器证据出现空白 Canvas、文本覆盖、横向溢出或移动布局冲突。
- 导出中文字体、分页或快照不可变性无法稳定重放。
- 外部模型边界可能发送未批准、未脱敏或严格敏感数据。
- 当前轮完整门禁不绿，或 ledger 显示 Agent 已停滞/阻塞。

恢复条件：共享合同重新冻结；重叠文件回到单一所有者；缺陷有回归测试；受影响门禁绿色；计划和任务包重新确认。

## 16. 启动顺序

当前立即执行项只有 M3-R0：

1. 处理 `git status --short` 中现有未跟踪文件的归属，使 M3 基线可判定。
2. 建立 M3 独立活动计划和本地 ledger 策略，冻结本地规划文件的 Git 忽略规则。
3. 主 Agent 执行 M3-R0-P1/P2；并行派发 A1、B1、C1。
4. 汇总图表/布局库、服务端编译、标准数据和验收矩阵证据。
5. 提交 `docs: define M3 dashboard architecture`。
6. 只有 M3-R0 退出条件全部满足，才创建 M3-R1 迁移、路由和生产依赖任务。

本文不提供未经 velocity 校准的日历承诺。M3-R0 完成后，以实际任务包吞吐、审查时间、缺陷返工和门禁耗时建立后续轮次预测；任何日期预测都不能替代阶段退出条件。
