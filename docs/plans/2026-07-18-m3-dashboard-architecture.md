# M3 仪表盘架构与合同

## 0. 状态

- 状态：M3-R0 技术验证中
- 基线：M2 accepted，`c02061e` 为生产代码验收基线
- 生产实现：未开始
- 允许输出：合同、ADR、评估报告、隔离 spike、测试数据、截图和验收矩阵
- 禁止输出：仪表盘迁移、生产 API/路由、生产前端页面和未经准入的生产依赖

本文在 M3-R0 结束时冻结。所有标记为“待 spike 确认”的内容必须在进入 M3-R1 前变成明确决定或阻塞项。

## 1. M3 边界

M3 交付从已激活数据集创建仪表盘的基础闭环：

- 空白画布、预设模板和团队模板。
- 仪表盘、不可变版本、页面、组件和独立桌面/移动布局。
- KPI、趋势指标、目标进度、表格、排行、柱状/条形/堆叠、折线/面积、饼/环、富文本和图片。
- 字段槽、聚合、排序、Top N、单位、图例、标签、提示和主题。
- 全局、页面、组件和日期筛选。
- 预览、保存、重开、复制粘贴、回收站、引用保护和资源权限。
- 桌面应用编辑两套布局；移动客户端只读查看和筛选。

M3 不实现跨组件联动、级联筛选、下钻、上钻、明细穿透、参数、个人视图、书签、高级图表配置、规则告警、通报和正式导出任务。这些能力分别由 M4 和 M5 交付。

## 2. 固定安全原则

1. 客户端只提交资源 UUID、字段 UUID、指标版本 UUID、强类型配置和强类型筛选，不提交物理表名、物理字段名、SQL、函数名或任意代码。
2. 图表查询必须编译为 M2 `DatasetQueryRequest` 或经单独评审的兼容扩展；不建立第二套 SQL/查询执行器。
3. 工作区、资源权限、RLS、数据集版本、指标版本、来源批次、超时和结果规模限制由服务端强制执行。
4. RLS 在连接和聚合前生效，用户筛选不能覆盖、放宽或绕过 RLS。
5. 仪表盘和模板使用稳定身份与不可变版本；编辑创建新版本或更新受控草稿，不覆盖已激活版本。
6. 所有外部可见错误返回稳定 code、可理解 message 和可执行 action，不暴露 SQL、物理标识或内部堆栈。
7. SQLite 验证单用户正确性；PostgreSQL 验证多用户、并发和生产兼容性。

## 3. 领域合同

### 3.1 聚合与身份

以下名称是合同级概念，表名在 M3-R1 迁移评审时确定：

| 概念 | 稳定身份 | 版本语义 | 关键归属 |
|---|---|---|---|
| Dashboard | `dashboard_id` | 稳定资源身份 | organization、workspace、owner |
| DashboardVersion | `dashboard_version_id` | 不可变激活版本；草稿带并发令牌 | dashboard、version number |
| DashboardPage | `page_id` | 随 dashboard version 固定 | title、ordinal |
| DashboardComponent | `component_id` | 随 dashboard version 固定 | page、type、config version |
| DashboardLayout | `(dashboard_version_id, profile)` | 随版本固定 | desktop/mobile profile |
| DashboardTemplate | `template_id` | 稳定模板身份 | workspace、owner、visibility |
| DashboardTemplateVersion | `template_version_id` | 不可变发布版本 | template、source dashboard version |
| DashboardPermission | `(dashboard_id, subject, capability)` | 受控更新 | user/role/workspace subject |

`component_id` 在同一 dashboard series 的新版本中保持逻辑连续，便于复制、布局和未来 M4 交互引用。复制组件创建新 UUID，不复用来源组件身份。

### 3.2 状态机

Dashboard 状态：

```text
draft -> active -> archived
  |        |          |
  +------> deleted <--+
             |
             +-> restored | permanently_deleted(after retention and reference checks)
```

- 草稿可以保存多个受控修订，但对外查询只读取明确版本。
- 激活产生新的不可变版本，不就地覆盖现有激活版本。
- 删除先进入回收站，默认保留 30 天。
- 内部状态沿用 M2 的 `deleted` 与 `deleted_at`；“回收站”是用户界面语义，不新增 `trashed` 状态。
- 被模板、通报或其他资源引用时，永久删除必须返回影响范围并阻止悬空引用。
- 并发保存携带 `expected_revision`；不匹配返回 409 和最新修订信息。

Template 状态：

```text
draft -> published -> archived
```

- 仅具备模板发布能力的管理员可以从仪表盘版本创建团队模板版本。
- 实例化复制页面、组件、配置和布局，产生独立 Dashboard/Version/Component UUID。
- 模板后续升级不修改既有仪表盘实例。

### 3.3 权限能力

Dashboard 能力：`view`、`edit`、`share`、`export`。

Template 能力：`view`、`instantiate`、`manage`、`publish`。

- 角色级粗粒度权限使用 `dashboards:view/edit/share/export` 和 `dashboard_templates:manage/publish`；资源级 grant 再限定 user、role 或 workspace subject 对具体资源的能力。
- 默认所有者拥有资源能力，但仍受角色级权限、工作区边界和数据集/RLS 权限约束。
- 查看仪表盘不隐含查看底层未授权数据集；图表查询仍单独执行 M2 权限校验。
- 跨工作区资源返回 404；已知资源但能力不足返回 403。
- 移动客户端没有编辑能力，即使主体拥有 `edit`，服务端写入权限仍不因客户端类型变化。
- M2 当前没有可复用的通用资源 ACL 表；M3-R1 必须实现并测试仪表盘资源 grant，不能只依赖现有 `QueryPrincipal.permissions` 字符串。

## 4. 配置版本合同

所有持久化 JSON 配置包含显式 `schema_version`。未知主版本拒绝读取；兼容小版本由确定性迁移器升级，不在渲染期间静默猜测。

### 4.1 ComponentConfig

```text
schema_version: 1
component_id: UUID
component_type:
  kpi | trend_indicator | target_progress | detail_table | ranking_table |
  bar | horizontal_bar | stacked_bar | line | area | pie | donut |
  rich_text | image
title: string
description: string | null
query: ChartQuerySpec | null
presentation: PresentationSpec
component_filter: FilterExpression | null
```

- `rich_text` 和 `image` 不允许携带查询合同。
- 图片只引用受控文件资源 UUID，不持久化任意外链 HTML。
- 富文本使用受限结构化内容，不接受脚本、任意 HTML 或事件属性。

### 4.2 ChartQuerySpec

```text
schema_version: 1
dataset_id: UUID
dimensions:
  - field_id: UUID
    slot_key: stable_identifier
    time_grain: day | week | month | quarter | year | null
series_dimension:
  field_id: UUID
  slot_key: stable_identifier
  max_series: integer
  # optional; supported only by chart families that declare it
measures:
  - one of:
      field_id: UUID
      aggregate: sum | avg | count | count_distinct | min | max
    or:
      metric_version_id: UUID
    slot_key: stable_identifier
sort:
  - one of:
      field_id: UUID
      aggregate: sum | avg | count | count_distinct | min | max | null
    or:
      metric_version_id: UUID
    direction: asc | desc
top_n: integer | null
query_limit: integer
```

约束：

- 所有 `slot_key` 是组件配置内的逻辑槽身份，在组件内唯一并匹配 `^[a-z][a-z0-9_]{0,62}$`；它不进入 M2 selection alias 或 SQL 标识。
- M2 `query_alias` 只由服务端按已验证槽类型和序号确定性生成，例如 `dimension`、`series`、`value_1`。客户端不能提交或覆盖 alias。
- 维度必须映射为非聚合 selection 并与 `group_by` 完全一致。
- 字段度量映射为带聚合的 selection；公共指标映射为 metric selection。
- 排序只能引用已选输出；Top N 编译为确定性排序和 limit。
- M3-R2 必须为 dataset query 增加判别式排序目标：field sort 只引用已选 field UUID + aggregate，metric sort 只引用已选 metric version UUID。服务端复用已解析指标表达式排序，不接受输出名、客户端公式或函数。
- 时间粒度只允许 `day/week/month/quarter/year`，由数据库方言适配器生成可移植分组表达式并返回规范 ISO bucket key；禁止客户端函数名。
- `series_dimension` 编译为第二个非聚合 selection/group field，并受 `max_series` 和完整结果规模限制。服务端必须从受治理资源解析主分类和系列基数，并在执行前验证 `primary_cardinality * series_cardinality <= effective_limit`；客户端提供的基数不可信。超限返回 `series_result_limit_exceeded`，不执行可能产生半个主分类组的查询。
- M3 拒绝 `series_dimension + top_n`，直到 M4 或独立查询扩展能正确先选主分类再保留其完整系列。系列查询响应若仍出现 `truncated=true`，适配器必须返回 `series_result_truncated` 并拒绝渲染部分堆叠；实际行数超过已解析上界返回 `series_cardinality_evidence_stale`。
- Top N 不生成 `Others` 桶；响应返回截断/warning。V1 需求未要求 Others，不能为它添加未经验证的子查询或 SQL 特例。
- 单组件不得超过 M2 的 100 输出、50 指标、20 分组、10 排序、50 谓词和 10,000 行上限；M3 可以收紧但不能放宽。

### 4.3 图表字段槽

| 组件 | 必填槽 | 可选槽 | 默认限制 |
|---|---|---|---|
| KPI | 1 measure | comparison/label | 返回 1 行 |
| Trend indicator | time dimension、1 measure | comparison | 时间升序 |
| Target progress | actual measure | target measure | 返回 1 行 |
| Detail table | 1-100 fields/measures | sort | 默认 500 行 |
| Ranking table | 1 dimension、1+ measures | sort | 必须确定性排序 |
| Bar/horizontal | 1 dimension、1+ measures | series dimension | 分类和系列数量受限；有系列时禁用 Top N |
| Stacked bar | 1 dimension、1 measure | series dimension 或额外 measures | 多指标或系列维度二选一 |
| Line/area | time/category dimension、1+ measures | series dimension | 点数受限 |
| Pie/donut | 1 dimension、1 measure | sort | 分类数量和占比一致 |

M3-R0-A1/B1 的支持矩阵是进入 M3-R1 的最终依据。

### 4.4 排序、NULL 与序列化

- 所有 Top N 值排序使用请求方向，随后按主维度规范值升序打破并列；相同数据与版本必须得到稳定顺序。
- NULL 固定排在非 NULL 之后，不依赖 SQLite/PostgreSQL 默认 NULL 顺序；方言适配器必须有双数据库测试。
- M3 响应补充强类型 column metadata。Decimal 使用规范十进制字符串传输，Date/DateTime 使用 ISO 8601，Boolean 使用 JSON boolean，NULL 使用 JSON null。
- 图表适配器可以将已验证的 Decimal 字符串转换为有限绘图数值，但表格、tooltip、导出和人工核对保留原始规范字符串。

## 5. 筛选合同

### 5.1 作用域与合并

服务端最终谓词顺序固定为：

```text
mandatory_active_predicates
AND row_level_security
AND global_filter
AND page_filter
AND component_filter
```

- 不同作用域之间固定 AND。
- 同一筛选控件的多选值使用一个强类型 set predicate 表达 OR 语义。
- global/page/component 各自保留一个现有 M2 单层强类型 `FilterExpression`。M3-R2 在受治理的 M2 请求内增加服务端构造的作用域列表；编译器逐作用域编译后在 SQLAlchemy 根层执行 AND，禁止把多个作用域展平为一个 AST。
- 三个用户作用域合计最多 50 个谓词；mandatory/RLS 使用独立的服务端上限并始终额外 AND，客户端不能覆盖、删除或通过空作用域抵消。
- 同一作用域多个控件默认 AND；多选 OR 使用一个 set predicate。M3 不支持同一作用域内任意嵌套或混合 AND/OR，超出该形状返回 `filter_expression_not_supported`。
- 无权限字段、隐藏字段、跨数据集字段或未知 UUID 返回 422/403/404，不忽略。
- RLS 不返回客户端配置，也不进入可编辑筛选列表。

### 5.2 日期筛选

支持绝对区间和相对日期。相对日期配置持久化语义值，服务端在查询开始时按工作区 IANA 时区解析为闭开区间，并在查询证据中返回实际解析区间。

M3 初始枚举：`today`、`yesterday`、`last_7_days`、`last_30_days`、`this_week`、`last_week`、`this_month`、`last_month`、`month_to_date`、`year_to_date`。

- 周从星期一开始。
- Date 和 DateTime 均编译为 `>= start AND < end`；Date 的 end 是最后一天之后一日，DateTime 的边界先按工作区时区计算再转换到 UTC。
- 单工作区 M3 通过显式配置提供 IANA 时区，默认值必须记录且生产环境可覆盖；不使用浏览器本地时区作为查询语义。
- 服务端解析结果进入 `resolved_filters`，包含语义枚举、时区、UTC start/end 和解析时间。
- SQLite/PostgreSQL 必须使用同一 Python 边界解析结果，避免依赖数据库专属相对日期函数。

## 6. 布局合同

### 6.1 LayoutProfile

```text
schema_version: 1
profile: desktop | mobile
columns: positive integer
row_height: positive integer
items:
  - component_id: UUID
    x: integer
    y: integer
    width: positive integer
    height: positive integer
    min_width: positive integer
    min_height: positive integer
```

- desktop 和 mobile 分别持久化，不在运行时按视口缩放同一坐标。
- 新组件先生成确定性默认 desktop/mobile 位置；保存时校验边界和重叠。
- 桌面应用允许编辑 desktop 和 mobile profile；移动客户端只读。
- 标签、加载、空状态、错误和 hover 不得改变网格 item 外部尺寸。
- 布局库不得成为领域合同；服务端只接受上述中立网格数据。

M3-R0-B1 冻结 desktop editor 为 12 列、44 px 行高、禁止重叠和纵向压缩。React Grid Layout 2.2.3 是实现 winner；GridStack 12.6.0 仅保留 spike fallback。服务端合同和持久化数据不得出现任一库的专有字段。1/20/50 组件在 Chrome/Edge 均通过边界、无重叠和真实缩放证据。

## 7. 图表查询编译边界

编译管线：

```text
ComponentConfig
  -> schema validation
  -> field-slot validation
  -> resolve dataset/field/metric UUIDs
  -> validate scoped user filters and shared predicate budget
  -> build DatasetQueryRequest
  -> M2 permission/RLS/version/batch validation
  -> compile each scope independently and SQLAlchemy-AND with mandatory/RLS
  -> timeout-limited execution
  -> evidence-preserving serialization
```

禁止：

- 图表库 option 直接转换为 SQL。
- 客户端发送 SQL、物理标识、任意表达式或服务端函数名。
- 为图表建立绕过 `execute_dataset_query` 的快捷执行器。
- 查询完成后在前端执行影响权限或 Top N 正确性的二次过滤。

## 8. 查询响应与错误合同

### 8.1 ChartQueryResponse

```text
request_id: UUID
component_id: UUID
columns:
  - slot_key: stable_identifier
    query_alias: server_generated_identifier
    resource_kind: field | metric
    resource_id: UUID
    aggregate: sum | avg | count | count_distinct | min | max | null
    label: string
    data_type: string | integer | decimal | boolean | date | datetime
    unit: string | null
rows: object[]
truncated: boolean
elapsed_ms: number
dataset_version: number
metric_version_ids: UUID[]
source_batch_ids: UUID[]
resolved_filters: ResolvedFilterEvidence[]
warnings: QueryWarning[]
```

`rows` 只使用服务端 `query_alias` 作为键；`columns` 返回 `slot_key -> query_alias/resource UUID` 映射，前端不得从 alias 反推资源身份。M2 已提供字符串 columns、rows、truncated、elapsed、dataset version、metric version IDs 和 source batch IDs；M3 将 columns 丰富为强类型元数据，并包裹组件与筛选证据，不丢弃原证据。

### 8.2 结构化错误

```text
code: stable_identifier
message: localized_user_message
action: localized_recovery_action
location:
  component_id: UUID | null
  config_path: string | null
```

最小错误矩阵：

| HTTP | 场景 | 示例 code |
|---:|---|---|
| 404 | 跨工作区或资源不存在 | `dashboard_not_found`、`dataset_not_found` |
| 403 | 仪表盘或底层数据能力不足 | `dashboard_forbidden`、`dataset_query_forbidden` |
| 409 | 草稿并发冲突、版本冲突、引用删除 | `dashboard_revision_conflict` |
| 422 | 配置、字段槽、筛选或查询形状非法 | `chart_config_invalid`、`chart_slot_invalid` |
| 422 | 系列完整分组无法在限制内返回 | `series_result_limit_exceeded`、`series_result_truncated`、`series_cardinality_evidence_stale` |
| 504 | 查询超时 | `dataset_query_timeout` |

前端必须分别展示加载、成功、无数据、截断、错误和无权限状态；错误不能被空图表替代。

## 9. API 合同

M3-R1/R2 的候选 API 形状如下，最终路径在生产实现计划中逐项测试：

```text
POST   /api/v1/dashboards
GET    /api/v1/dashboards
GET    /api/v1/dashboards/{dashboard_id}
POST   /api/v1/dashboards/{dashboard_id}/versions
POST   /api/v1/dashboards/{dashboard_id}/activate
DELETE /api/v1/dashboards/{dashboard_id}
POST   /api/v1/dashboards/{dashboard_id}/restore
PUT    /api/v1/dashboards/{dashboard_id}/permissions

POST   /api/v1/dashboard-templates
GET    /api/v1/dashboard-templates
GET    /api/v1/dashboard-templates/{template_id}
POST   /api/v1/dashboard-templates/{template_id}/versions
POST   /api/v1/dashboard-templates/{template_id}/publish
POST   /api/v1/dashboard-templates/{template_id}/instantiate

POST   /api/v1/dashboard-chart-queries/validate
POST   /api/v1/dashboard-chart-queries
```

- 创建版本提交完整 page/component/layout 聚合、`base_version` 和 `expected_revision`；服务端原子校验并生成新版本，不开放可产生半版本的逐组件持久化 API。
- 已保存查看查询只提交 dashboard/version/page/component UUID 与运行时筛选值；服务端加载持久化配置。
- 编辑预览可以提交 `preview_config`，但必须同时提交 dashboard/page/component 上下文并具备 `edit` 与底层 `datasets:query` 权限。
- `preview_config` 使用与持久化配置相同的 extra-forbid schema，不落库、不改变版本、不允许绕过资源引用解析。
- validate 返回输出列、版本证据和 warning，不执行完整结果读取；execute 返回第 8 节证据响应。
- 列表 API 使用稳定分页和状态筛选；默认排除 `deleted`，回收站必须显式请求。

## 10. 前端渲染边界

- 图表配置和领域状态独立于 ECharts option；适配器单向生成 option。
- 图表组件固定容器尺寸，ResizeObserver 只触发图表 resize，不修改网格尺寸。
- 每个 Canvas 图表提供等价标题、摘要和可访问表格/文本替代。
- M3 点击事件只产出标准化 event context 用于调试和未来 M4，不在 M3 触发跨组件过滤。
- PNG 2x 导出在 spike 中验证，正式后台导出归 M5。
- 主题通过应用 token -> 图表主题适配，不在组件内硬编码一套独立设计系统。

## 11. 候选库准入

### 11.1 图表库

ECharts 6.1.0 通过 M3-R0 技术选型，但只允许动态加载：

- React 19、Chrome 149、Edge 150 和 390 px 视口均完成实测。
- 核心 Canvas、2x PNG、UUID 事件上下文、ResizeObserver、主题、中文文本、可访问表格和 reduced-motion 通过。
- ECharts 552,727 bytes raw / 187,470 bytes gzip，超过 500 kB 警告阈值；`React.lazy` 已证明它可从初始 manifest 闭包移除。
- 生产仪表盘必须保留动态 chart boundary，并在正式入口重跑 bundle；禁止把 ECharts 放回首包或仅抬高 warning 阈值。

### 11.2 布局库

React Grid Layout 2.2.3 是 winner；GridStack 12.6.0 因命令式生命周期和适配成本保持 spike-only fallback。两者均完成真实拖动，winner 另完成快照保存/重载与 1/20/50 压力证据。生产 M3-R3 仍必须增加键盘 move/resize 命令，不能只提供 pointer drag。

版本、拒绝理由、许可证、raw/gzip/brotli baseline、Chrome/Edge/移动/Canvas/console/stress 证据见 `docs/architecture/evaluations/m3-chart-layout-spike.md` 和 `docs/verification/m3-r0-*.json`。

## 12. M3-R0 验收矩阵

M3-R0-C1 维护详细矩阵，至少覆盖：

- 三源星型数据集和人工金色结果。
- Decimal、Date/DateTime、Boolean、NULL、排序和 Top N。
- 管理员、编辑者、受限查看者、跨工作区和 RLS 聚合前生效。
- SQLite/PostgreSQL 查询和迁移预期。
- 页面 2 秒、缓存首屏 3 秒、常规查询 5 秒、20 并发的测量方法。
- Chrome/Edge、桌面和 390 px、Canvas 非空、无重叠/溢出/控制台错误。
- loading、success、empty、error、forbidden、timeout、truncated 状态。
- 许可证、bundle、截图、命令和环境版本证据。

## 13. M3-R0 退出清单

- [x] 后端图表配置编译 spike 通过，支持/错误矩阵完整。
- [x] 指标排序、时间粒度、系列维度、Top N Others、NULL 排序和序列化差距已形成明确 M3 实现合同。
- [x] ECharts 和布局 winner 有版本、许可证、bundle、截图和浏览器证据。
- [x] desktop/mobile profile、碰撞规则和移动只读行为已冻结。
- [x] 标准数据集、金色结果、权限主体和验收矩阵可复现。
- [x] dashboard、version、page、component、template、layout、permission 和 trash 合同无阻塞项。
- [x] 筛选合并、日期解析、查询响应和错误合同无歧义。
- [x] `docs/architecture/adr/0004-dashboard-domain-and-query-contracts.md` 变为 Accepted。
- [x] `docs: define M3 dashboard architecture` 聚焦提交通过文本和相关测试门禁。
