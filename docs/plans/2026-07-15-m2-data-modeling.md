# M2 数据建模实现计划

## 目标

交付从 M1 活跃导入目标到可复用语义模型、数据集、计算字段、公共指标、行级权限和受控查询服务的完整闭环。M2 采用单事实表加多维表模型，支持 INNER/LEFT 连接以及 1:1、N:1 基数；禁止原始 SQL、多事实表、多对多和任意代码。

M2 不实现仪表盘、图表、联动下钻、异步查询缓存、外部数据源、AI、导出或通报。移动端提供数据集查看和查询预览，不提供复杂建模编辑。

## 固定约束

- 客户端只提交资源 UUID、字段 UUID、指标版本 UUID 和强类型表达式 AST，不得提交物理表名、物理字段名、SQL 或函数名字符串。
- 查询编译使用 SQLAlchemy Core，所有 literal 使用绑定参数；每个来源强制追加 `_active = true`。
- 行级权限在连接和聚合前注入。同一主体的 allow 策略使用 OR 合并，不同强制约束使用 AND；存在策略但无匹配时默认拒绝。
- SQLite 保证单用户正确性；PostgreSQL 承担多人和性能验收。数据库专属超时与日期函数放在适配器中。
- 同步查询默认返回 500 行、最大 5,000 行，聚合最大 10,000 行，执行上限 10 秒。
- 单查询最多 8 个来源、7 个连接、100 个输出字段、20 个分组字段、50 个过滤条件和 50 个指标。
- 关系模型、数据集、计算字段、指标和行策略版本不可变；编辑创建新版本，引用方固定版本。
- 被引用资源不得产生悬空删除；删除先进入 30 天回收站。

## 领域与表

- `users`、`roles`、`user_roles`：最小本地账号、角色和主体上下文，为资源权限与行级策略提供稳定 UUID。
- `semantic_models`、`semantic_model_versions`：稳定模型身份、不可变版本、事实源和状态。
- `semantic_model_sources`：引用 `import_targets`，保存事实/维度角色、别名和顺序。
- `semantic_model_joins`、`semantic_model_join_keys`：连接类型、基数和成对字段外键。
- `datasets`、`dataset_versions`：数据集身份、模型版本、所有者和生命周期。
- `dataset_fields`：来源字段、显示名、维度/度量角色、可见性和顺序。
- `calculated_fields`：行级或聚合级强类型表达式 AST。
- `metrics`、`metric_versions`、`metric_dimensions`：公共指标身份、公式、单位、负责人、适用维度和历史。
- `row_policies`、`row_policy_versions`、`row_policy_bindings`：版本化谓词及用户/角色绑定。

共享表使用应用生成 UUID、受 CheckConstraint 约束的 String 状态、通用 JSON 和 UTC 时间，不使用 JSONB、数组或数据库 enum。

## API 合同

```text
GET    /api/v1/data-sources
GET    /api/v1/data-sources/{id}/schema

POST   /api/v1/semantic-models
GET    /api/v1/semantic-models
GET    /api/v1/semantic-models/{id}
POST   /api/v1/semantic-models/{id}/validate
POST   /api/v1/semantic-models/{id}/versions

POST   /api/v1/datasets
GET    /api/v1/datasets
GET    /api/v1/datasets/{id}
POST   /api/v1/datasets/{id}/versions
POST   /api/v1/datasets/{id}/activate

POST   /api/v1/metrics
GET    /api/v1/metrics
GET    /api/v1/metrics/{id}
POST   /api/v1/metrics/{id}/versions

POST   /api/v1/row-policies
GET    /api/v1/row-policies
POST   /api/v1/row-policies/{id}/versions
POST   /api/v1/row-policies/{id}/bindings

POST   /api/v1/dataset-queries/validate
POST   /api/v1/dataset-queries
```

查询响应包含字段定义、行、是否截断、耗时、数据集版本、指标版本和实际来源批次。跨工作区资源统一返回 404；权限拒绝返回 403；非法模型或表达式返回 422；基数膨胀和版本冲突返回 409；超时返回 504。

## 实施任务

### 任务 1：M2 架构与合同

固定功能边界、星型/雪花拓扑、身份主体、表达式 AST、版本语义、权限合并、查询护栏和双数据库验收矩阵。

提交：`docs: define M2 data modeling architecture`

### 任务 2：身份与元数据基础

实现最小用户/角色主体、建模元数据表和 `0003_modeling_foundation`。覆盖约束、外键、工作区隔离、版本不可变性以及 SQLite/PostgreSQL 迁移升降级。

提交：`feat(db): add modeling domain foundation`

### 任务 3：表达式与查询合同

实现 extra-forbid 的强类型 AST，覆盖字段、literal、比较、布尔、四则、安全除法、CASE、基础聚合、分组、过滤、排序和限制。拒绝未知操作符、任意函数、物理标识和过度复杂请求。

提交：`feat(modeling): add typed query contracts`

### 任务 4：数据源与关系模型 API

提供活跃导入目标目录、字段 schema、关系模型创建/读取/校验和版本 API。保存时验证单事实表、无环、有键连接、字段类型兼容和基数风险。

提交：`feat(api): add semantic model management`

### 任务 5：安全查询编译器

从服务端元数据解析字段 UUID，构造 SQLAlchemy Core 查询，自动注入 `_active`、受限连接、过滤、聚合、排序和分页。实现 SQLite/PostgreSQL 超时适配和结果序列化。

提交：`feat(modeling): add secure dataset query compiler`

### 任务 6：数据集、计算字段与指标

实现数据集版本、字段目录、行级/聚合级计算字段和公共指标版本。首批指标覆盖 sum、avg、count、count distinct、min、max、四则、安全占比及目标完成率；时间窗口指标在后续子任务扩展。

提交：`feat(modeling): add datasets and metrics`

### 任务 7：权限与查询 API

实现资源能力权限和行级谓词绑定，查询编译前解析 CurrentActor，在聚合前强制注入策略。提供 validate/execute API、稳定分页、截断、超时和结构化错误。

提交：`feat(api): add governed dataset queries`

### 任务 8：前端数据建模工作台

拆分懒加载路由，新增数据集列表、关系编辑、字段目录、计算字段、指标、查询预览和权限页面。桌面使用密集工作台；移动端显示只读摘要和查询预览。

提交：`feat(web): add data modeling workspace`

### 任务 9：M2 验收

使用事实表和两个维表验证 INNER/LEFT、1:1/N:1、聚合正确性、非法 fanout、版本稳定、行级权限、非法 AST、超时、分页和双数据库一致性。保存常规查询 P95、20 并发 PostgreSQL 结果和桌面/移动截图。

提交：`docs: record M2 verification evidence`

## 验收门槛

- 事实表与维度表连接结果、基础指标和计算字段与人工 SQL 核算一致。
- 失败批次、暂存行和非活跃数据不能通过任何数据集查询暴露。
- 不同用户和角色查询同一数据集只能获得授权行；查询、未来导出和 AI 可复用同一编译入口。
- 任意 SQL、未知操作符、跨工作区 UUID、循环关系、多对多和无键连接均被拒绝。
- SQLite 与 PostgreSQL 的 Decimal、NULL、日期、布尔、排序、连接和聚合结果一致。
- 标准数据集常规查询 P95 小于 5 秒；复杂查询在 10 秒内完成或返回可定位超时。
- 前端明确展示模型健康、基数风险、字段口径、查询耗时、截断状态和权限影响。
