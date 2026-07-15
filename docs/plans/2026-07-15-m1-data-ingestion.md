# M1 数据接入实现计划

## 目标

交付从原始文件到可追溯导入批次的完整闭环：CSV/XLSX 上传、内容去重、工作表和字段预览、模板映射、质量校验、追加/业务主键更新/全量替换、错误报告、取消与失败重试。普通请求不得读取完整文件；后台处理按提交块恢复。

M1 不实现外部数据库连接、现有 API 脚本接入、数据集关联、指标、行级权限或 BI 图表。接口暂以默认单工作区运行，但所有资源保留 `workspace_id`。

## 固定约束

- 单文件最大 100 MB，最多 1,000,000 条数据行；默认处理块 2,000 行，预览最多 100 行。
- 支持 UTF-8/UTF-8 BOM CSV 和 `.xlsx`；中文 CSV 可显式选择 GB18030。拒绝 `.xls`、`.xlsm`、加密或损坏工作簿，并返回转换建议。
- 原始 blob 按 SHA256 寻址并永久不可变；上传临时文件和失败产物定期清理。
- 文件名只作为元数据，不参与磁盘路径；阻止路径穿越、空文件、伪装类型和 XLSX 解压炸弹。
- 质量错误阻止提交，警告需显式确认。数据库只保留有上限的问题样本，完整错误行输出为 CSV 文件。
- 导入状态、计数和错误码可查询；日志不得包含 Cookie、令牌或未脱敏行数据。

## 领域与表

- `file_blobs`：SHA256、字节数、媒体类型、存储键和创建时间。
- `source_files`：工作区、blob、原始文件名、文件类型、上传状态和上传时间。
- `import_templates`：模板名称、版本、工作表选择、字段映射和目标定义。
- `quality_rules`：规则类型、严重级别、字段、参数、版本和启用状态。
- `import_targets` / `import_columns`：系统生成的物理表名和稳定字段定义。
- `import_batches`：来源、模式、状态、租约、重试、进度、计数和时间戳。
- `import_issue_samples`：批次、行号、字段、规则、级别、错误码和截断值。

UUID 由应用生成，状态与规则类型保存为受校验的 `String`，配置保存为通用 `JSON`。不使用 PostgreSQL enum、JSONB、数组或数据库专属默认值。

## API 合同

```text
POST   /api/v1/source-files                 流式上传并返回去重结果
GET    /api/v1/source-files/{id}            获取文件元数据
POST   /api/v1/source-files/{id}/preview    工作表、字段、类型和样例预览
POST   /api/v1/import-templates             创建版本化模板
POST   /api/v1/import-batches               校验配置并创建待处理批次
GET    /api/v1/import-batches/{id}          查询状态、进度和质量摘要
POST   /api/v1/import-batches/{id}/cancel   请求取消
POST   /api/v1/import-batches/{id}/retry    从安全检查点重试
GET    /api/v1/import-batches/{id}/issues   查询有上限的问题样本
GET    /api/v1/import-batches/{id}/report   下载完整错误报告
```

## 实施任务

### 任务 1：依赖与流式能力验证

加入 `python-multipart` 和只读 XLSX 解析依赖，使用生成的 CSV/XLSX 测试数据验证常量内存读取、中文标题、空值、日期、公式不执行及损坏文件错误。记录锁定版本与许可证。

提交：`build(api): add ingestion parsing dependencies`

### 任务 2：存储配置与内容寻址服务

增加上传根目录、大小、行数、块大小和预览上限配置。实现临时写入、边写边哈希、原子落盘、去重和安全删除；覆盖超限、空文件、重复内容、异常清理和路径边界测试。

提交：`feat(storage): add content addressed file storage`

### 任务 3：领域模型与双数据库迁移

实现上述元数据表、约束和索引，添加 `0002_ingestion_foundation`。SQLite 与 PostgreSQL 均验证 upgrade、downgrade、re-upgrade；状态机和租约字段添加单元测试。

提交：`feat(db): add ingestion domain foundation`

### 任务 4：上传与预览 API

上传端点使用 `UploadFile` 分块复制，不信任客户端 MIME。CSV 逐行采样；XLSX 使用只读工作簿并限制工作表尺寸和解压比。响应返回稳定字段候选、推断类型、空值计数和至多 100 行样例。

提交：`feat(api): add source file upload and preview`

### 任务 5：模板与质量规则

实现固定模板和通用映射合同。首批规则覆盖必填、唯一、类型、长度、范围、枚举、正则和业务主键重复；跨字段与批次波动使用独立执行接口。验证规则配置时拒绝任意代码和未知操作符。

提交：`feat(ingestion): add templates and quality rules`

### 任务 6：可恢复导入执行器

实现数据库租约 worker、块级检查点、取消和重试。数据先写批次 staging 表，通过错误门槛后再执行追加、业务主键更新或全量替换。所有不可逆步骤在状态机中显式标记。

提交：`feat(ingestion): add recoverable import worker`

### 任务 7：错误报告与清理

生成 UTF-8 BOM CSV 错误报告，限制数据库样本数量，增加过期临时文件和失败产物清理命令。清理必须验证路径位于存储根目录且不得删除被批次引用的 blob。

提交：`feat(ingestion): add quality reports and cleanup`

### 任务 8：前端导入工作台

使用 Ant Design Steps 构建上传、预览、映射、规则、导入模式、执行进度和结果页面。大表使用服务端分页；本阶段不引入数据网格候选。覆盖加载、空、成功、警告确认、失败和取消状态，并验证 390 px 与桌面布局。

提交：`feat(web): add data ingestion workspace`

### 任务 9：M1 验收

用固定模板和通用向导分别导入 CSV/XLSX，验证三种模式、严重错误阻断、警告确认、取消、进程重启后恢复、错误报告、重复上传和 100 MB 压力场景。保存 SQLite/PostgreSQL 测试结果、峰值内存、耗时与浏览器截图。

提交：`docs: record M1 verification evidence`

## 验收门槛

- 100 MB 或 1,000,000 行标准 CSV 导入期间 API 就绪探针持续成功，峰值内存不随文件完整大小线性增长。
- 同一核心导入用例在 SQLite 和 PostgreSQL 结果一致；PostgreSQL 多 worker 不会重复领取批次。
- 重试不会重复写入已提交块，取消不会留下可查询的半成品目标数据。
- 原始文件、批次、模板版本、规则版本、错误报告和最终行数可追溯。
- 前端明确展示当前步骤、进度、错误影响和可执行恢复动作。
