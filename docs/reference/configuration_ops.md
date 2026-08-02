# DuckDB 配置与运维手册 研读摘要（目标版本 1.5.5）

> 资料来源：`duckdb-web-main/docs/current/configuration/` 与 `duckdb-web-main/docs/current/operations_manual/` 下的全部 `.md` 文件。
> 说明：源文档树标记为 `current`，部分页面（如安装脚本示例、User-Agent 字符串）显示的内部版本号（1.4.1、1.4.4）与本书目标版本 1.5.5 不完全一致，属文档滚动更新所致；配置项的默认值与语义以本摘要中的配置参考表为准。
> 已忽略 Jekyll frontmatter（`--- ... ---`）与 Liquid 标签（`{% ... %}`）。

---

## 一、配置（Configuration）

### 1.1 配置项的四种设置方式

DuckDB 的行为可通过配置项（configuration options）调整，共有 4 种设置途径：

| 方式 | 语法 / 说明 | 备注 |
|------|------------|------|
| **SET 语句** | `SET memory_limit = '10GB';`、`SET threads TO 1;` | 最常用；也可写成 `SET threads = 4` |
| **PRAGMA 语句** | `PRAGMA enable_progress_bar;`、`PRAGMA disable_optimizer;` | 源自 SQLite 的扩展；赋值类 PRAGMA 等价于 SET |
| **连接参数（connection parameters）** | 在打开/连接数据库时以参数传入（各语言客户端 API 支持，如 Python `duckdb.connect(configuration={'memory_limit':'10GB'})`） | 在进程启动前生效，部分安全项（如 `allow_unsigned_extensions`）仅能在启动时开启 |
| **环境变量** | 文档未列出具体 env 名；主要通过 SET/连接参数生效 | —— |

- **重置**：`RESET memory_limit;` 将某项配置还原为默认值。
- **查询当前值**：
  - `SELECT current_setting('memory_limit') AS memlimit;`
  - `SELECT value FROM duckdb_settings() WHERE name = 'memory_limit';`
  - 列出全部：`SELECT * FROM duckdb_settings();`

### 1.2 作用域（Scope）：GLOBAL vs LOCAL

配置项分为两类作用域：

- **GLOBAL（全局）**：对整个数据库实例生效（见 1.3 表）。
- **LOCAL（本地）**：仅对当前会话/连接生效，例如 `search_path`、`enable_profiling`、`schema`、`streaming_buffer_size`、`enable_progress_bar` 等（见 1.3.2）。

### 1.3 重要配置项全目录

#### 1.3.1 GLOBAL 配置项（重点摘录 + 完整列表）

下表给出与性能、安全、持久化、时区/排序最相关的项；其后附完整 GLOBAL 列表。

##### （A）性能相关（Performance）

| 名称 | 类型 | 默认值 | 含义 | 何时修改 |
|------|------|--------|------|----------|
| `threads`（别名 `worker_threads`） | BIGINT | CPU 核数 | 系统使用的总线程数（并行查询执行） | 多租户/容器环境限制并发占用；需确定性结果时设为 1 |
| `max_memory`（别名 `memory_limit`） | VARCHAR | 物理内存的 **80%** | 系统可用的最大内存（如 `1GB`、`10GB`） | 限制内存占用、避免 OOM；注意仅约束 buffer manager |
| `max_temp_directory_size` | VARCHAR | 可用磁盘的 **90%** | `temp_directory` 中可存储的最大溢出数据量 | 限制磁盘溢出，防止打满磁盘 |
| `temp_directory` | VARCHAR | `<database_name>.tmp` 或内存模式下的 `.tmp` | 写入临时文件（spill）的目录 | 把溢出目录指向高速/大容量磁盘 |
| `external_threads` | UBIGINT | `1` | 在 DuckDB 任务上工作的外部线程数 | 配合外部/异步执行 |
| `pin_threads` | VARCHAR | `auto`（核数 >64 时开启，仅 Linux） | 是否将线程绑定到 CPU 核 | Linux 大核数机器调优 |
| `scheduler_process_partial` | BOOLEAN | `false` | 任务部分处理后重新调度，提升多查询间调度公平性 | 并发多查询场景 |
| `default_block_size` | UBIGINT | `262144`（256 kB） | 新建数据库文件的默认块大小（必须是 2 的幂，介于 16384–262144） | 小表/特殊存储布局微调 |
| `preserve_insertion_order` | BOOLEAN | `true` | 是否保持插入顺序（false 允许重排无 ORDER BY 的结果） | 追求极致性能、可接受乱序时关 |
| `partitioned_write_max_open_files` | UBIGINT | `100` | `PARTITION_BY` 写时保持打开的最大文件数 | 分区写出调优 |
| `write_buffer_row_group_count` | UBIGINT | `5` | 批量写入时缓冲的 row group 数 | 调小可降低内存占用 |
| `disabled_optimizers` | VARCHAR | 空 | 逗号分隔地禁用指定优化器（如 `filter_pushdown`） | **仅调试用，生产禁用** |

##### （B）安全相关（Security）

| 名称 | 类型 | 默认值 | 含义 | 何时修改 |
|------|------|--------|------|----------|
| `enable_external_access` | BOOLEAN | `true` | 是否允许访问外部状态（加载/安装扩展、COPY、CSV/Parquet 读取、pandas replacement scan 等） | 不可信环境设为 `false`，用 `allowed_directories`/`allowed_paths` 白名单 |
| `allow_unsigned_extensions` | BOOLEAN | `false` | 是否允许加载签名无效/缺失的扩展 | 扩展开发才开；**仅启动时可设**，属提权风险 |
| `allow_community_extensions` | BOOLEAN | `true` | 是否允许加载社区扩展 | 不可信 SQL 场景设为 `false`；该设置会**自我锁定**（运行后不能改回 true） |
| `autoload_known_extensions` | BOOLEAN | `true` | 查询依赖时是否自动加载已知扩展 | 需完全控制加载项时设 `false` |
| `autoinstall_known_extensions` | BOOLEAN | `true` | 查询依赖时是否自动安装已知扩展 | 同上 |
| `lock_configuration` | BOOLEAN | `false` | 锁定后任何配置都不可再改 | 自定义配置完成后锁定，防篡改 |
| `allowed_configs` | VARCHAR[] | `[]` | `lock_configuration=true` 时仍允许改的配置白名单 | 如 `['memory_limit','threads']` |
| `allowed_directories` | VARCHAR[] | `[]` | 即便 `enable_external_access=false` 也始终允许访问的目录 | 配合安全模式做白名单 |
| `allowed_paths` | VARCHAR[] | `[]` | 即便 `enable_external_access=false` 也始终允许访问的文件 | 同上 |
| `disabled_filesystems` | VARCHAR | 空 | 禁用指定文件系统（如 `LocalFileSystem`） | 彻底禁本地文件访问 |
| `allow_unredacted_secrets` | BOOLEAN | `false` | 是否明文显示 secret 内容 | 不可信 SQL 场景保持 `false` |
| `allow_persistent_secrets` | BOOLEAN | `true` | 是否允许创建持久化 secret | 安全场景可禁 |
| `force_mbedtls_unsafe` | BOOLEAN | `false` | 启用 mbedtls 加密（警告：不安全） | 一般不动 |
| `enable_server_cert_verification` | BOOLEAN | `false` | 是否校验服务端证书 | 对外通信建议 `true` |
| `enable_curl_server_cert_verification` | BOOLEAN | `true` | CURL 后端是否校验服务端证书 | 默认已开 |

##### （C）持久化 / 存储 / WAL

| 名称 | 类型 | 默认值 | 含义 | 何时修改 |
|------|------|--------|------|----------|
| `checkpoint_threshold`（别名 `wal_autocheckpoint`） | VARCHAR | `16.0 MiB` | 触发自动 checkpoint 的 WAL 大小阈值（如 `1GB`） | 写多场景调大以减少 checkpoint 频率 |
| `wal_autocheckpoint_entries` | UBIGINT | `0`（禁用） | WAL 条目数达到 N 时触发自动 checkpoint | 按条目数而非大小触发 |
| `auto_checkpoint_skip_wal_threshold` | UBIGINT | `100000` | 估计 WAL 写入量超过此值时跳过写 WAL 直接 checkpoint（会阻塞并发提交） | 特定写负载调优 |
| `access_mode` | VARCHAR | `automatic` | 数据库访问模式：`AUTOMATIC`/`READ_ONLY`/`READ_WRITE` | 只读共享场景设 `READ_ONLY` |
| `storage_compatibility_version` | VARCHAR | `v0.10.2` | checkpoint 时序列化兼容的 DuckDB 版本 | 需与旧版本互操作时设 |
| `default_block_size` | UBIGINT | `262144` | 见性能表 | —— |
| `temp_file_encryption` | BOOLEAN | `false` | 若数据库加密，则加密所有临时文件 | 加密库场景 |
| `block_allocator_memory` | VARCHAR | `0 bytes` | block allocator 可用物理内存（永不释放、不可缩减） | 高级调优 |

##### （D）时区 / 排序 / 日历

| 名称 | 类型 | 默认值 | 含义 | 何时修改 |
|------|------|--------|------|----------|
| `TimeZone` | VARCHAR | 系统（locale）时区 | 当前时区 | 需固定时区结果时显式设置 |
| `Calendar` | VARCHAR | 系统（locale）日历 | 当前日历 | 特定地区日历需求 |
| `default_order` | VARCHAR | `ASCENDING` | 未指定时的排序方向（`ASC`/`DESC`） | 业务默认降序时 |
| `default_null_order`（别名 `null_order`） | VARCHAR | `NULLS_LAST` | 未指定时 NULL 的排序位置（`NULLS_FIRST`/`NULLS_LAST` 等） | 与上游系统对齐 |
| `default_collation` | VARCHAR | 空 | 未指定时使用的排序规则（collation） | 需要大小写不敏感等 |
| `preserve_identifier_case` | BOOLEAN | `true` | 是否保留标识符大小写（否则非引号标识符一律小写） | 兼容其他数据库行为 |

##### （E）日志相关（详见第二章 2.3）

| 名称 | 类型 | 默认值 | 含义 |
|------|------|--------|------|
| `enable_logging` | BOOLEAN | `1`（开启） | 是否启用 logger |
| `logging_level` | VARCHAR | `WARNING` | 记录到日志的级别 |
| `logging_mode` | VARCHAR | `LEVEL_ONLY` | 决定记录哪些类型日志消息 |
| `logging_storage` | VARCHAR | `shell_log_storage` | 日志存储（memory/stdout/file/&lt;custom&gt;） |
| `log_query_path` | VARCHAR | 空 | 查询日志写入路径（空=不记录） |
| `disabled_log_types` / `enabled_log_types` | VARCHAR | 空 | 禁用/启用的 logger 列表 |

##### （F）扩展 / 网络 / S3 / HTTP（摘选）

| 名称 | 类型 | 默认值 | 含义 |
|------|------|--------|------|
| `extension_directory` / `extension_directories` | VARCHAR / VARCHAR[] | 空 / `[]` | 扩展存放目录 |
| `custom_extension_repository` / `autoinstall_extension_repository` | VARCHAR | 空 | 远程扩展安装的自定义端点 |
| `enable_external_file_cache` | BOOLEAN | `true` | 是否缓存外部文件（如 Parquet）于内存 |
| `http_timeout` | UBIGINT | `30`（秒） | HTTP 读/写/连接/重试超时 |
| `http_retries` | UBIGINT | `3` | I/O 错误重试次数 |
| `http_proxy` / `http_proxy_username` / `http_proxy_password` | VARCHAR | 空 | HTTP 代理 |
| `s3_region` / `s3_endpoint` / `s3_use_ssl` / `s3_url_style` 等 | VARCHAR/BOOLEAN | 各为空/`true`/`vhost` | S3 兼容存储连接参数 |
| `ca_cert_file` | VARCHAR | 空 | 自签名证书的自定义证书文件路径 |
| `custom_user_agent` | VARCHAR | 空 | 调用方元数据（User-Agent） |

> **完整 GLOBAL 列表**（文档生成的配置参考，共 100+ 项）还包含：`__delta_only_variant_encoding_enabled`、`allocator_background_threads`、`allocator_bulk_deallocation_flush_threshold`、`allocator_flush_threshold`、`allow_asterisks_in_http_paths`、`allow_extensions_metadata_mismatch`、`allow_parser_override_extension`、`allow_unredacted_secrets`、`arrow_*` 系列、`asof_loop_join_threshold`、`catalog_error_max_schemas`、`disable_*` 系列、`duckdb_api`、`dynamic_or_filter_threshold`、`enable_*` 系列（如 `enable_geoparquet_conversion`、`enable_global_s3_configuration`、`enable_http_metadata_cache`、`enable_macro_dependencies`、`enable_object_cache`[占位/无效]、`enable_view_dependencies`、`errors_as_json`、`experimental_metadata_reuse`、`explain_output`、`file_search_path`、`force_download*`、`geometry_minimum_shredding_size`、`home_directory`、`ieee_floating_point_ops`、`immediate_transaction_mode`、`index_scan_*`、`integer_division`、`lambda_syntax`、`late_materialization_max_rows`、`max_expression_depth`(默认 1000)、`max_vacuum_tasks`、`merge_*`、`merge_join_threshold`、`nested_loop_join_threshold`、`old_implicit_casting`、`order_by_non_integer_literal`、`ordered_aggregate_threshold`、`parquet_metadata_cache`、`perfect_ht_threshold`、`pivot_*`、`prefer_range_joins`、`prefetch_all_parquet_files`、`produce_arrow_string_view`、`s3_*` 系列、`scalar_subquery_error_on_multiple_rows`、`secret_directory`(默认 `~/.duckdb/stored_secrets`)、`storage_block_prefetch`(默认 `REMOTE_ONLY`)、`unsafe_disable_etag_checks`、`user`(`username`)、`vacuum_rebuild_indexes`、`validate_external_file_cache`、`variant_minimum_shredding_size`、`warnings_as_errors`、`zstd_min_string_length`(默认 4096) 等。以 `duckdb_settings()` 查询本机实际值为准。

#### 1.3.2 LOCAL 配置项（会话级）

| 名称 | 类型 | 默认值 | 含义 |
|------|------|--------|------|
| `schema` | VARCHAR | `main` | 默认搜索 schema（等价于单值 search_path） |
| `search_path` | VARCHAR | 空 | 默认 catalog 搜索路径（逗号分隔） |
| `enable_profiling` | VARCHAR | 空 | 启用 profiling 及格式（`JSON`/`QUERY_TREE`/`QUERY_TREE_OPTIMIZER`） |
| `profiling_output`（`profile_output`） | VARCHAR | 空 | profile 输出文件（空=打印到终端） |
| `profiling_coverage` | VARCHAR | `SELECT` | profiling 覆盖范围（`SELECT`/`ALL`） |
| `profiling_mode` | VARCHAR | 空 | profiling 模式（`STANDARD`/`DETAILED`/`ALL`） |
| `custom_profiling_settings` | VARCHAR | JSON（默认开启除 detailed 外的全部指标） | 逐项开关 profiling 指标 |
| `enable_progress_bar` | BOOLEAN | `true` | 长查询是否显示进度条 |
| `enable_progress_bar_print` | BOOLEAN | `true` | 进度条是否打印（当 `enable_progress_bar=true`） |
| `progress_bar_time` | BIGINT | `2000`（毫秒） | 查询耗时超过该值才显示进度条 |
| `enable_caching_operators` | BOOLEAN | `true` | 缓存中间结果的算子 |
| `enable_http_logging`（已废弃） | BOOLEAN | `true` | 启用 HTTP 日志 |
| `http_logging_output`（已废弃） | VARCHAR | 空 | HTTP 日志输出文件 |
| `streaming_buffer_size` | VARCHAR | `976.5 KiB` | 流式结果抓取间缓冲的最大内存 |

### 1.4 PRAGMA 用法补充（来自 pragmas.md）

- **内存限制警告**：`memory_limit` 仅作用于 **buffer manager**。多数查询数据由它管理，但向量（vectors）、查询结果、以及复杂状态的聚合函数（`list`、`mode`、`quantile`、`string_agg`、`approx` 等）使用的内存**在 buffer manager 之外**，实际占用可能高于设定值。
  ```sql
  SET memory_limit = '1GB';
  ```
- **线程**：
  ```sql
  SET threads = 4;
  ```
- **默认排序/空值顺序**：
  ```sql
  SET default_null_order = 'NULLS_FIRST';
  SET default_order = 'ASCENDING';
  ```
- **EXPLAIN 输出**：`physical_only`（默认）/`optimized_only`/`all`。
- **Profiling**：`PRAGMA enable_profiling;` 是启用前提；格式 `query_tree`(默认)/`json`/`query_tree_optimizer`/`no_output`；输出默认到 stdout，可用 `SET profiling_output='/path.json'` 写文件（每次覆盖）。
- **禁用优化器**：`PRAGMA disable_optimizer;` / `PRAGMA enable_optimizer;`。
- **选择性禁用优化器**：`SET disabled_optimizers = 'filter_pushdown,statistics_propagation';`（仅调试）。
- **强制 checkpoint / 关闭时 checkpoint**：`PRAGMA force_checkpoint;` / `PRAGMA enable_checkpoint_on_shutdown;`。
- **压缩控制**：`PRAGMA force_compression='bitpacking';`、`PRAGMA disabled_compression_methods='fsst,rle';`。
- **临时目录（spill）**：
  ```sql
  SET temp_directory = '/path/to/temp_dir.tmp/';
  ```
  默认 spill 目录为 `<database_file_name>.tmp`（与库文件同目录）；内存模式为 `.tmp`。
- **块大小**：`SET default_block_size = '16384';`（须为 2 的幂，范围 16384–262144）。
- **错误以 JSON 返回**：`SET errors_as_json = true;`（便于机器解析）。
- **IEEE 浮点语义**：`SET ieee_floating_point_ops = false;` 时除零返回 `NULL`。
- **时间旅行/验证类 PRAGMA**（开发用）：`verify_external`、`verify_serializer`、`enable_verification`、`verify_parallelism`。

### 1.5 Secrets Manager（密钥管理）

- 为各后端（AWS S3、Azure、GCS、HTTP、HuggingFace、Iceberg、MySQL、PostgreSQL、R2、DuckLake、Quack 等）提供统一密钥接口；可带 scope（路径前缀），最长前缀匹配优先。
- **临时 secret**：默认，存于内存，随实例生命周期。
  ```sql
  CREATE SECRET my_secret (TYPE s3, KEY_ID '...', SECRET '...', REGION '...');
  ```
- **持久 secret**：`CREATE PERSISTENT SECRET ...`，以**未加密二进制**写入 `~/.duckdb/stored_secrets`（权限 600，等同 SSH key）。可用 `SET secret_directory='...'` 改目录（仅当前实例生效）。
- 列出：`FROM duckdb_secrets();`（敏感信息默认脱敏）。
- 查看某路径用哪个 secret：`FROM which_secret('s3://bucket/file.parquet', 's3');`
- ⚠️ 持久 secret 以**未加密二进制**落盘——安全敏感场景谨慎使用。

---

## 二、运维手册（Operations Manual）

### 2.1 安装 DuckDB（Installing DuckDB）

- **Linux / macOS 安装脚本**（安装最新稳定版 CLI 到 `~/.duckdb/cli/latest/duckdb`）：
  ```bash
  curl https://install.duckdb.org | sh
  ```
  安装后把 `export PATH="~/.duckdb/cli/latest":$PATH` 加入 shell 配置。
- **安装历史版本**（可回溯到 v1.0.0）：
  ```bash
  curl https://install.duckdb.org | DUCKDB_VERSION=1.2.2 sh
  ```
- **Windows（beta 脚本）**：
  ```powershell
  powershell -NoExit iex (iwr "https://install.duckdb.org/install.ps1").Content
  ```
- **Docker 官方镜像** `duckdb/duckdb`（支持 ARM64 / x86_64）：
  ```bash
  docker run --rm -it -v "$(pwd):/workspace" -w /workspace duckdb/duckdb
  ```
  使用 DuckDB UI 需 `--net host`（会转发容器所有端口，安全环境避免使用）。
- **版本策略（versioning policy）**：提供“past releases”（历史发布版），安装脚本通过 `DUCKDB_VERSION` 指定；文档示例中出现 1.4.1 / 1.4.4 等内部版本号。
- 各语言客户端（Python、R、Java、Node 等）通过各自包管理器安装；CLI 主要用于交互，不推荐用于嵌入。

### 2.2 DuckDB 的足迹（Footprint of DuckDB）

DuckDB 是**嵌入式（embedded / in-process）分析型数据库**，采用**单文件存储格式**——库文件可以是任意扩展名（常见 `.duckdb`、`.db`、`.ddb`），无独立服务进程。

**（1）DuckDB 创建的文件（Files Created by DuckDB）**

全局文件（用户 home 目录 `~`）：

| 位置 | 说明 | 跨版本共享 | 跨客户端共享 |
|------|------|-----------|--------------|
| `~/.duckdbrc` | CLI 启动时执行的命令（点命令 + SQL），类似 `.bashrc` | 是 | 仅 CLI |
| `~/.duckdb_history` | 历史文件，类似 `.bash_history` | 是 | 仅 CLI |
| `~/.duckdb/extensions` | 已安装扩展的二进制 | 否 | 是 |
| `~/.duckdb/stored_secrets` | 持久 secret | 是 | 是 |

本地文件（工作目录或库文件相对路径）：

| 名称 | 说明 | 示例 |
|------|------|------|
| `<database_filename>` | 数据库文件（仅磁盘模式） | `weather.duckdb` |
| `.tmp/` | 临时目录（仅内存模式） | `.tmp/` |
| `<database_filename>.tmp/` | 临时目录（仅磁盘模式） | `weather.tmp/` |
| `<database_filename>.wal` | 预写日志（WAL）；正常退出时删除，崩溃时用于恢复 | `weather.wal` |

**（2）Gitignore 配置（Gitignore for DuckDB）**
- 仅忽略临时文件、保留库文件：
  ```
  *.wal
  *.tmp/
  ```
- 同时忽略库文件与临时文件（以 `.duckdb` 为例）：
  ```
  *.duckdb*
  *.wal
  *.tmp/
  ```

**（3）回收空间（Reclaiming Space）**
- DuckDB 单文件格式在回收磁盘空间上有固有限制。
- 删除行后回收空间：使用 `CHECKPOINT;`。
- `VACUUM` **不会**回收删除产生的空间（不产生 vacuum 式收缩）。
- 压缩数据库（彻底compact）：用 `COPY FROM DATABASE` 生成全新副本：
  ```sql
  ATTACH 'db1.db' AS db1;
  ATTACH 'db2.db' AS db2;
  COPY FROM DATABASE db1 TO db2;
  ```

**（4）数据库文件大小（Limits 页）**
- 单库文件无实际大小上限（已有 15 TB+ 的库文件正常运行）；但连接超大库可能耗时数秒，checkpoint 更慢。
- **二进制体积/内存占用**：本版 operations_manual 的 footprint 小节未单列“二进制大小”专页；但已知 DuckDB 以极小的嵌入式库著称（CLI 为单可执行文件），内存默认上限为物理内存 80%（见 `memory_limit`）。
- 其他内建上限：数组大小 100000；BLOB/字符串大小 4 GB；向量内存分配 128 GB；表达式深度 1000（`max_expression_depth`）；临时目录大小默认不限（`max_temp_directory_size`）。

### 2.3 日志（Logging）

- **基础**：通过 `enable_logging`（`1` 默认开启）控制；日志存入特殊视图 `duckdb_logs`，可像表一样查询。
  ```sql
  CALL enable_logging();
  SELECT * FROM duckdb_logs;
  CALL disable_logging();
  CALL truncate_duckdb_logs();   -- 清空当前日志
  ```
- **日志级别（Log Level）**：`ERROR` < `WARN` < `INFO` < `DEBUG` < `TRACE`（配置参考默认 `WARNING`）。
  ```sql
  CALL enable_logging(level = 'debug');
  ```
- **日志类型（Log Types）**：用于细粒度控制 + 结构化日志。
  - 按类型启用：`CALL enable_logging('HTTP');` 或 `CALL enable_logging(['HTTP','QueryLog']);`
  - 可用类型（非穷举）：`QueryLog`、`FileSystem`(结构化)、`HTTP`(结构化)、`PhysicalOperator`(结构化)、`Metrics`(结构化)。
  - 结构化日志可用 `duckdb_logs_parsed('HTTP')` 宏解析，并用 `DESCRIBE FROM duckdb_logs_parsed('HTTP')` 查看 schema。
  - 结构化 schema 示例：`HTTP` = `request STRUCT(type,url,start_time,duration_ms,headers), response STRUCT(status,reason,headers)`。
- **日志存储（Log Storages）**：`memory`(默认)、`stdout`(CSV)、`file`(CSV 文件)。
  ```sql
  CALL enable_logging(storage = 'stdout');
  CALL enable_logging(storage = 'file', storage_config = {'path':'path/to/logs'});
  -- 简写：
  CALL enable_logging(storage_path = 'path/to/logs');
  ```
  `duckdb_logs` 视图会自动指向当前活动存储。
- **规范化 vs 非规范化（Normalized vs Denormalized）**：
  - `memory`=规范化；`file`=可配置；`stdout`=非规范化。
  - `file` 存储：路径以 `.csv` 结尾=规范化（生成 `..._contexts.csv` 与 `..._entries.csv`）；无 `.csv`=非规范化（生成单个 `logs.csv`，推荐，性能更好且体积小）。
- **缓冲区大小（Buffer Size）**：日志有缓冲，可能延迟写入（崩溃前日志可能丢失）；调试崩溃时设 `buffer_size=0`：
  ```sql
  CALL enable_logging(storage_config = {'buffer_size': 0});
  ```
  默认缓冲：`memory`/`file` = `STANDARD_VECTOR_SIZE`(2048)；`stdout` = 0(禁用)。为 `stdout` 开启缓冲可提速 >10x。

### 2.4 安全加固（Securing DuckDB）

**核心理念**：DuckDB 像 bash/Python 一样以运行它的用户权限执行 SQL。把 SQL 当作代码对待——不要在未沙箱化情况下执行不可信来源的 SQL。配置项属于**纵深防御（defense-in-depth）**，不能替代操作系统/容器级沙箱。

**（1）不可信输入**
- 不可信 SQL：用 duckdb-wasm 沙箱、隔离容器（Docker 限制能力）、虚拟机/最小权限进程、OS 级沙箱、网络隔离防外泄、应用层严格超时。
- 不可信非 SQL 输入：文件路径（`read_csv`/`read_parquet` 可读取 `/etc/passwd` 或远程 URL）、表/列名、过滤表达式（常编译为含任意 SQL 的子查询）。务必校验与清洗所有用户输入。

**（2）扩展签名与安全级别（Securing Extensions）**
扩展与 DuckDB 进程同权。每次加载都做二进制签名校验，分三类：
- `core` key 签名（DuckDB 团队审核）
- `community` key 签名（第三方、由 DuckDB 团队构建/签名分发）
- 无签名

安全级别矩阵：

| 可加载扩展 | 说明 | 配置 |
|-----------|------|------|
| 仅 `core` | 只加载 core key 签名扩展 | `SET allow_community_extensions = false` |
| `core` + `community` | 默认安全级别 | 默认 |
| 任意（含无签名） | 可加载任何扩展 | `SET allow_unsigned_extensions = true` |

- 安全相关设置会**自我锁定**：设 `allow_community_extensions=false` 后，运行期内不能再改回 `true`（报 `Cannot upgrade ... while database is running`）。`allow_unsigned_extensions` 仅能在**启动时**开启。
- 社区扩展仓库类似 pip/npm，本质是“远程代码执行设计”——务必只从可信源安装；运行不可信 SQL 的 Web 服务建议 `SET allow_community_extensions=false`。
- 关闭自动安装/加载：`SET autoinstall_known_extensions=false; SET autoload_known_extensions=false;`（再用 `lock_configuration=true` 锁定）。

**（3）CLI 安全模式（Safe Mode）**
```batch
duckdb -safe ...
```
或点命令 `.safe_mode`——禁止访问数据库文件以外的外部文件。

**（4）限制文件访问**
- 禁用单个文件系统：`SET disabled_filesystems='LocalFileSystem';`
- 彻底关闭外部访问：`SET enable_external_access=false;`（此后 `ATTACH` 文件、`COPY` 文件、`read_csv/read_parquet/read_json` 等均不可用）。
- 白名单目录/文件（即便 `enable_external_access=false` 也放行）：
  ```sql
  SET allowed_directories = ['/tmp'];
  SET enable_external_access = false;
  ```

**（5）锁定配置（Locking Configurations）**
```sql
SET allowed_configs = ['memory_limit','threads'];  -- 锁定时仍可调的项
SET lock_configuration = true;                      -- 此后所有配置不可改
```

**（6）Secrets**
- `duckdb_secrets()` 默认脱敏；`allow_unredacted_secrets=true` 才显明文（不可信 SQL 场景勿开）。
- 持久 secret 以未加密二进制落盘，权限 600（同 SSH key）。

**（7）预编译语句防 SQL 注入**
- 推荐用 prepared statements 防注入（你控制查询结构、只接收不可信数据值时）。若用户能提交整条 SQL，等价于允许执行任意代码。
  ```python
  # 危险：字符串拼接
  duckdb.execute("... WHERE x = " + str(42))
  # 安全：预编译
  duckdb.execute("... WHERE x = ?", [42])
  ```

**（8）限制资源占用（Constrain Resource Usage）**
```sql
SET threads = 4;
SET memory_limit = '4GB';
SET max_temp_directory_size = '4GB';
```

**（9）嵌入 DuckDB（Embedding）**
- CLI 客户端面向交互，含 `.sh` 等可被执行任意 shell 命令的特性（**仅 CLI 有**，其他客户端无）。
- 嵌入时**不要**通过 shell 调用 CLI；应使用客户端库（Python/R/Java/Node 等）。

**（10）权限**
- 避免以 root（`sudo`）运行 DuckDB。

---

## 三、线程与并行模型、内存管理基础

### 3.1 多线程与并行（Threading & Parallelism）

- DuckDB 是多线程分析引擎，`threads`（默认 = CPU 核数）控制并行查询执行的总线程数。另有 `external_threads`（默认 1）表示在 DuckDB 任务上工作的外部线程数。
- `pin_threads`（默认 `auto`）：Linux 下核数 >64 时自动将线程绑定到核，减少上下文切换。
- 调度器：`scheduler_process_partial`（默认 false）让任务部分处理后重新调度，提升多查询间的调度公平性。
- **非确定性来源**：并行执行会利用 SQL 集合语义（结果顺序不保证），且多线程浮点聚合（`stddev`、`corr` 等）可能因浮点误差产生微小差异（`0 <= z < 1e-16`）。需要确定性时：`SET threads=1;` 或显式 `ORDER BY ALL` / `list_sort`。
- 各 Join 策略阈值：`merge_join_threshold`(1000)、`nested_loop_join_threshold`(5)、`asof_loop_join_threshold`(64)、`index_scan_max_count`(2048)、`perfect_ht_threshold`(12) 等，用于执行器在并行/算法间抉择。

### 3.2 内存管理（Memory Management）

- **`memory_limit` / `max_memory`**（默认物理内存 80%）：仅约束 **buffer manager**。向量、查询结果、复杂状态聚合函数所用内存在其之外，实际占用可能超过设定值——因此不能把它当作硬性内存上限。
- **溢出（spilling）到磁盘**：当内存不足，数据 spill 到 `temp_directory`（默认 `<db>.tmp` 或内存模式的 `.tmp`），可用 `max_temp_directory_size`（默认可用磁盘 90%）限制。调大 `temp_directory` 到高速磁盘可提升大查询稳定性。
- **内存分配相关**：`block_allocator_memory`（永不释放、不可缩减的物理内存）；`allocator_background_threads` / `allocator_flush_threshold`(128 MiB) / `allocator_bulk_deallocation_flush_threshold`(512 MiB) 控制分配器后台行为。
- **写缓冲**：`write_buffer_row_group_count`(5)、`write_buffer_row_group_memory_limit`（默认 memory_limit 的 20% / 线程数）控制批量写入缓冲，调小可降低内存峰值。

---

## 四、版本相关事实（v1.5.5 源文档中观察到）

- 配置参考默认 `storage_compatibility_version = v0.10.2`（checkpoint 序列化兼容版本）。
- `enable_logging` 默认 `1`（开）；`logging_level` 默认 `WARNING`（注：logging 概览页称默认 INFO，二者以配置参考表为准）。
- `allow_unsigned_extensions` 默认 `false`，且**仅在启动时**可开；`allow_community_extensions` 默认 `true` 但可运行期关、关后不可再开（自我锁定）。
- `autoload_known_extensions` / `autoinstall_known_extensions` 默认 `true`。
- `checkpoint_threshold` / `wal_autocheckpoint` 默认 `16.0 MiB`；`wal_autocheckpoint_entries` 默认 `0`（禁用，即按大小而非条目数触发）。
- `threads` 默认 = CPU 核数；`memory_limit` 默认 = 物理内存 80%；`max_temp_directory_size` 默认 = 可用磁盘 90%。
- `default_null_order` 默认 `NULLS_LAST`；`default_order` 默认 `ASCENDING`。
- `default_block_size` 默认 262144（256 kB）；合法范围 16384–262144（2 的幂）。
- `secret_directory` 默认 `~/.duckdb/stored_secrets`；持久 secret **未加密二进制**、权限 600。
- 文档示例内部版本号：安装脚本 1.4.1、User-Agent `duckdb/v1.4.4(...)`（源树为 current，可能略新于 1.5.5）。
- `enable_object_cache` 为**占位/无效**设置（文档明确标注 [PLACEHOLDER] Legacy setting - does nothing）。
- `VACUUM` 在 DuckDB 中**不**回收删除空间；回收须用 `CHECKPOINT` 或 `COPY FROM DATABASE` 重建。

---

## 五、给 1.5.5 中文书的最关键配置旋钮（速查）

**性能向（Performance）**
1. `memory_limit` / `max_memory` —— 控制内存上限（记住仅约束 buffer manager）。
2. `threads` —— 并行度（容器/多租户务必限制；要确定性设 1）。
3. `temp_directory` + `max_temp_directory_size` —— 大查询 spill 落盘的位置与上限。
4. `checkpoint_threshold` / `wal_autocheckpoint` —— WAL 自动 checkpoint 频率。
5. `preserve_insertion_order` / `disabled_optimizers`（调试） —— 执行行为调优。

**安全向（Security）**
1. `enable_external_access` + `allowed_directories`/`allowed_paths` —— 最小权限文件访问。
2. `allow_unsigned_extensions`（启动期才可调）、`allow_community_extensions`（关后锁死）—— 扩展签名管控。
3. `autoload_known_extensions` / `autoinstall_known_extensions` —— 关闭自动加载/安装，防供应链风险。
4. `lock_configuration` + `allowed_configs` —— 锁定配置防篡改。
5. CLI `-safe` / `.safe_mode` —— 交互安全模式。
6. prepared statements —— 防 SQL 注入（结构由你控制、值来自不可信输入时）。
7. 不以 root 运行；嵌入用客户端库而非 CLI 的 `.sh`。
