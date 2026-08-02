# DuckDB 1.5.5 高级原理与开发指南 · 文档研究摘要

> 来源：DuckDB 官方文档 `duckdb-web-main/docs/current/` 下的 `internals/`、`connect/`、`quack/`、`dev/` 四个目录树。
> 版本基准：**DuckDB v1.5.5**（文档中涉及的版本事实见文末"版本专属事实"）。
> 说明：已忽略 Jekyll 前导（`--- ... ---`）与 Liquid 标签（`{% ... %}`），仅提取正文内容。
> 术语约定：中文叙述为主，关键英文术语（如 DataChunk、Vector、MVCC、ART、WAL、Row Group 等）保留原文以便对照。

---

## 0. 阅读范围与版本专属事实速览

| 主题 | 关键版本事实（来自文档） |
|---|---|
| 存储格式（Storage Version） | 版本号 **68** 对应 v1.5.x；67→v1.4.x；66→v1.3.x；65→v1.2.x；64→v0.9.x / v0.10.x / v1.0.0 / v1.1.x。v1.0–v1.5 默认创建 storage version 64（即 v1.0.0 格式）。 |
| 向后兼容 | 自 v0.10 起存储格式向后兼容（新版本可读旧文件）。v0.10 可读 v0.9 写出的文件。 |
| 显式存储版本 | v1.2.0 引入 `STORAGE_VERSION` 选项；可用 `'latest'` 或具体版本（如 `'v1.2.0'`）。`storage_compatibility_version` 配置项同等作用。 |
| jemalloc | 自 **v1.5.3** 起由"扩展"改为作为第三方库（third-party library）分发，静态链接，不可运行时加载。 |
| Quack 远程协议 | 于 2026-05-12 发布；beta 版随 **v1.5.3** 通过 `core` 仓库提供；v1.5.2 起以 beta 形态出现，预计在 v2.0（2026 秋）成熟。 |
| 构建语言要求 | 当前需要 C++11 兼容编译器；**v2.0 将要求 C++17**。 |
| DuckLake | v1.0 规范与其 DuckDB 实现于 2026-04 发布，用于生产级多进程并发写（PostgreSQL 作 catalog）。 |

---

# 1. 内部原理（internals）

本章是面向"高级概念"章节的原理材料，覆盖：查询执行流水线、向量化执行模型、内存 Vector 格式、列式磁盘存储与压缩、事务/MVCC 并发模型、catalog、索引（ART）以及 PIVOT 内部实现。

## 1.1 查询执行的完整流水线

DuckDB 把一个 SQL 字符串变成结果，依次经过下列阶段（见 `internals/overview.md`）：

1. **Parser（解析器）**：把查询字符串转换为若干 token——
   - `SQLStatement`、`QueryNode`、`TableRef`、`ParsedExpression`。
   - 解析器**不感知 catalog**，也不解析列类型；即使表不存在也不会报错，仅做语法层面的 token 化。
   - `ParsedExpression` 没有类型（除显式 `CAST`），类型在 Binder 阶段解析。
   - `TableRef` 表示一切表来源（基表、join、表生成函数、子查询）。
   - `QueryNode` 表示 `SELECT` 或集合操作（`UNION`/`INTERSECT`/`DIFFERENCE`）。
   - `SQLStatement` 表示一条完整语句；一条 SQL 字符串可拆成多条语句。
2. **Binder（绑定器）**：把上述节点转换为**绑定（bound）**等价物，并用 catalog 解析表与列、解析类型、抽取聚合/窗口函数。
   - `SQLStatement → BoundStatement`，`QueryNode → BoundQueryNode`，`TableRef → BoundTableRef`，`ParsedExpression → Expression`。
3. **Logical Planner（逻辑规划器）**：由 bound statement 构造 `LogicalOperator` 节点树，形成逻辑查询树。
4. **Optimizer（优化器）**：对逻辑查询树运行一系列优化（见 1.2）。
5. **Column Binding Resolver（列绑定解析）**：把逻辑层引用"某表某列"的 `BoundColumnRefExpression` 转换为引用执行引擎中 `DataChunk` 具体下标的 `BoundReferenceExpression`。
6. **Physical Plan Generator（物理计划生成器）**：把逻辑算子树转换为 `PhysicalOperator` 树。
7. **Execution（执行）**：运行物理算子产生结果（见 1.3 向量化执行）。

> 文字流程图（建议书中配图）：
> `SQL 字符串 → Parser(tokens) → Binder(bound) → Logical Planner(LogicalOperator 树) → Optimizer(优化后的逻辑树) → Column Binding Resolver → Physical Plan Generator(PhysicalOperator 树) → 向量化执行(DataChunk 在算子间流动) → 结果`

## 1.2 优化器（Optimizer）

DuckDB 运行以下查询优化器（按文档列举）：

- **Expression Rewriter**：简化表达式，做常量折叠（constant folding）。
- **Filter Pushdown（谓词下推）**：把过滤条件下推进计划树，并在等价集（equivalency sets）上复制过滤条件；同时剪掉"静态求值为 false"而必然为空的子树。
- **Join Order Optimizer（连接顺序优化）**：使用动态规划重排 join 顺序，具体采用论文《Dynamic Programming Strikes Back》中的 **DPhyp** 算法。
- **Common Sub Expressions（公共子表达式提取）**：从 projection 与 filter 节点抽取公共子表达式，避免重复执行。
- **In Clause Rewriter**：把大的静态 `IN` 子句重写为 MARK join 或 INNER join。

## 1.3 向量化执行引擎：Volcano 模型 vs 向量化模型

DuckDB 使用**基于推送（push-based）的向量化执行模型**（见 `internals/overview.md` 与其引用的演讲 *Push-Based Execution in DuckDB*）。要点：

- **Volcano / Iterator 模型**（传统）：每个算子实现 `next()`，一次返回一行（tuple-at-a-time），频繁虚函数调用、分支预测差、CPU 缓存利用率低。
- **DuckDB 向量化模型**：算子以**固定大小的向量（Vector）**为批处理单位，整批数据在算子树间流动。
- **推送式（push-based）**：`DataChunk` 被"推送"穿过算子树（与某些"拉取式/pipeline"实现相对）。
- **`STANDARD_VECTOR_SIZE`**：默认 **2048 行**（元组）。所有算子都针对这个固定大小优化。
- 优势：① 减少解释/虚调用开销；② 对整批数据做循环，利于 CPU 流水线与 SIMD；③ 支持"压缩执行"——某些向量格式（见 1.4）可在不解压的情况下直接参与计算。

## 1.4 内存中的数据表示：Vector 与 DataChunk

（见 `internals/vector.md`）

- **`DataChunk`**：一组 `Vector` 的集合，例如 `PhysicalProjection` 算子用来表示一个列列表。它是执行期间在算子间传递的基本单位。
- **`Vector`**：保存执行期内存中单类型数据的容器。DuckDB 支持多种**向量格式（vector formats）**，同一逻辑数据可用不同物理表示，从而更紧凑，并可能实现"压缩执行"。

### 1.4.1 向量格式（Vector Formats）

1. **Flat Vector（扁平向量）**：物理上就是连续数组，标准未压缩格式；逻辑与物理表示一致。
2. **Constant Vector（常量向量）**：物理上只存一个常量值。适合重复值（如 `SELECT lst || 'duckdb'` 中的字面量）；也由存储层从"常量压缩"解压时产生。
3. **Dictionary Vector（字典向量）**：由一个 child vector + 一个指向 child 的 selection vector（下标数组）组成。存储层从"字典压缩"解压时产生，使数据在执行期保持压缩。
4. **Sequence Vector（序列向量）**：由一个 offset 与 increment 值表示，适合存储递增序列（通常用于行标识符 rowid）。
5. **Unified Vector Format（统一向量格式）**：为简化编程而生——任何 Vector 都可转换为这种"通用视图"，避免为每种向量格式组合写特化代码（否则会组合爆炸）。

> 书中可配图：Flat（连续数组）、Constant（单值）、Dictionary（child+selection vector）、Sequence（offset+increment）四种内存布局示意。

### 1.4.2 复杂类型的内存布局

- **String Vector（字符串）**：使用 `string_t` 结构。短字符串（≤12 字节）**内联（inlined）**进结构体；长字符串用指针指向 auxiliary string buffer。结构含 `length` 与 4 字节 `prefix`（用于比较时的 early-out 优化，前缀不符即可免追指针）。避免 `strlen` 与空指针检查。
- **List Vector**：由若干 `list_entry_t {offset, length}` + 一个 child Vector（存实际值）组成；可递归嵌套（list 的 child 还是 list）。
- **Struct Vector**：存一组 child vector，数量与类型由 schema 决定。
- **Map Vector**：内部存为 `LIST[STRUCT(key KEY_TYPE, value VALUE_TYPE)]`。
- **Union Vector**：内部结构同 Struct；第一个 child 是 Tag Vector，记录每行对应 Union 的哪种类型。

## 1.5 列式磁盘存储格式（Storage）

（见 `internals/storage.md`）

### 1.5.1 列式（Columnar）与压缩（Compressed on Disk）

- DuckDB 的数据文件是**列式存储**，并按 **Row Group（行组）** 做水平分区——概念等价于 Parquet 的 row group。
- 默认**仅对持久化数据库做压缩，内存数据库不压缩**；可用 `ATTACH ... (COMPRESS)` 为内存库开启压缩。
- 可用压缩算法取决于 storage version；某些算法需显式设定 storage version 才能用。
- 压缩算法清单：Constant Encoding、RLE、Bit Packing、Frame of Reference (FOR)、Dictionary Encoding、FSST（VLDB 2020）、ALP 自适应无损浮点压缩（SIGMOD 2024）、Chimp（VLDB 2022）、Patas、Zstd（v1.2.0 引入）。
- **轻量压缩（lightweight compression）**：文档明确 DuckDB 采用"轻量压缩"策略，追求压缩与解压/执行的低开销平衡。

### 1.5.2 存储文件头（Storage Header）

- 文件以 `uint64_t` 校验和开头 → 4 个魔数字节 `DUCK` → `uint64_t` 存储版本号。
- 可用 `hexdump -n 20 -C file.db` 或 Python `struct` 读取魔数与版本。

### 1.5.3 存储版本与兼容策略

- **向后兼容（Backward Compatibility）**：新版本能读旧版本写的文件。自 v0.10 起保证。
- **向前兼容（Forward Compatibility）**：旧版本读新版本文件，仅"尽力而为（best effort）"，可能（部分）破坏。
- 跨版本迁移：用旧版 `EXPORT DATABASE 'tmp'`，再用新版 `IMPORT DATABASE 'tmp'`。
- 显式存储版本：`ATTACH 'file.db' (STORAGE_VERSION 'v1.2.0')` 或 `'latest'`；CLI 用 `-storage-version`。设置项 `storage_compatibility_version` 亦可（`SET storage_compatibility_version='latest'` 或 Python 连接时 `config={'storage_compatibility_version':'latest'}`）。
- 版本互转：`ATTACH 'file1.db'; ATTACH 'converted_file.db' (STORAGE_VERSION 'v1.0.0'); COPY FROM DATABASE file1 TO converted_file;`
- 查询数据库 storage 版本：`SELECT database_name, tags FROM duckdb_databases();`（tags 含 `storage_version=...`）。

### 1.5.4 磁盘占用与行组大小

- 经验：`100 GB` 未压缩 CSV 载入 DuckDB 约需 `25 GB`；`100 GB` Parquet 载入约需 `120 GB`（取决于类型、分布、压缩方法）。
- Row Group 大小可用 `ATTACH '/tmp/somefile.db' AS db (ROW_GROUP_SIZE 16384)` 指定。

## 1.6 事务与并发模型：MVCC + 乐观并发控制

（主要见 `connect/concurrency.md`，与存储/WAL 相关）

- DuckDB 在**进程内模式（in-process）**下提供两类并发选项：
  1. **读写模式（read-write）**：一个进程可读可写。
  2. **只读模式（read-only）**：多个进程可同时读，但无人能写（`access_mode='READ_ONLY'`）。
- 读写模式下，DuckDB 用 **MVCC（多版本并发控制）+ 乐观并发控制（optimistic concurrency control）** 支持多线程写入，但全部发生在**单一写进程**内。
  - 动机：把数据缓存在 RAM 以加速分析查询，并缓存函数指针、catalog 等，使同连接后续查询更快。
- **单进程内并发规则**：只要没有写冲突，多个并发写都会成功；append 永不冲突（即便同一表）；多线程可同时更新不同表或同一表的不同子集。当两个线程试图同时编辑（update/delete）同一行时，乐观并发控制生效——第二个线程以冲突错误失败。
- **多进程写**：DuckDB 原生格式不支持多进程并发写；需经 **Quack 远程协议**（把 DuckDB 变成客户端-服务器数据库，beta）或 **DuckLake + PostgreSQL catalog**（稳定生产方案）。
- **乐观并发控制**：适合读密集的分析系统。同时修改同一行的事务会触发冲突错误：`Transaction conflict: cannot update a table that has been altered!` 常见应对是**重跑事务**。
- **文件锁**：DuckDB 用文件锁处理并发访问请求；在网络存储/共享目录访问时需格外小心。
- 与 WAL 的关系：Quack 文档提到请求/响应使用 DuckDB 内部序列化原语，"与 Write-Ahead Log（WAL）所用代码路径相同"。存储测试默认 `SET wal_autocheckpoint='0KB'`（每条语句后做 checkpoint），WAL 测试则用 `PRAGMA disable_checkpoint_on_shutdown` + `PRAGMA wal_autocheckpoint='1TB'` 关闭该行为。

## 1.7 Catalog（目录）

- Binder 阶段通过 **catalog** 解析表、列与类型（`internals/overview.md`）。
- catalog 在进程内被缓存以加速查询（见 1.6 并发动机）。
- 文档在 `internals/` 树中未给出 catalog 的深层实现章节；更深入内容指向《Design and Implementation of DuckDB Internals》（DiDi）库条目。本书可把 catalog 描述为"内存中维护的表/视图/函数/模式的元数据索引，由 Binder 在绑定阶段查询"。

## 1.8 索引：Adaptive Radix Tree（ART）

- `internals/` 文档树中**没有**独立的 ART 深度章节；ART 作为 DuckDB 索引结构的知识来自其设计文献（overview.md 引用的 DiDi 库条目）与社区共识。
- 可安全陈述的要点（与文档一致/不冲突）：DuckDB 使用 **Adaptive Radix Tree（自适应基数树）** 作为索引的原生数据结构，主要用于主键/等值查找等场景；其设计目标是在分析负载下保持低内存占用与高查找效率。
- 书中若需展开 ART，建议引用 DiDi（Design and Implementation of DuckDB Internals）作为权威来源，本批文档未包含其逐节点实现细节。

## 1.9 PIVOT / UNPIVOT 内部实现

（见 `internals/pivot.md`）

- **`PIVOT`**：实现为"SQL 重写 + 专用 `PhysicalPivot` 算子"组合。做法：先把 PIVOT 重写为"聚合进 list"，再由 `PhysicalPivot` 把 list 转换为列名与值。
  - 动态检测列（未用 `IN` 子句时）：先建临时 `ENUM` 类型（`CREATE TEMPORARY TYPE __pivot_enum_0_0 AS ENUM (SELECT DISTINCT ...)`），把去重值注入 `IN` 子句，再重写为聚合进 list 的查询。
  - 例：`PIVOT cities ON year USING sum(population)` → 先注入 ENUM → 重写为 `SELECT country, name, list(year), list(population_sum) ... GROUP BY ALL`，最后 `PhysicalPivot` 把 list 展开成 `2000/2010/2020` 各列。
- **`UNPIVOT`**：完全以 SQL 重写实现，用一组 `unnest` 函数作用于"列名 list"与"列值 list"；动态 unpivot 时先求 `COLUMNS` 表达式得到列列表。

## 1.10 jemalloc 内存分配器

（见 `internals/jemalloc.md`）

- `jemalloc` 把系统内存分配器替换为 [jemalloc](https://jemalloc.net/)；自 v1.5.3 起作为**第三方库**分发（此前为扩展），静态链接，不可运行时加载。
- 平台：Linux 版默认带 jemalloc；macOS 需 `GEN=ninja BUILD_JEMALLOC=1 make` 自行构建；Windows 不可用。
- 配置：环境变量 `DUCKDB_JE_MALLOC_CONF`（避免与系统 `MALLOC_CONF` 冲突）；后台线程默认关闭，可 `SET allocator_background_threads=true;` 开启以减少前台分配开销（多核收益明显）。

---

# 2. 连接（connect）

（见 `connect/overview.md`、`connect/concurrency.md`）

## 2.1 连接或创建数据库

- 使用 DuckDB 前必须先建立到数据库的连接；具体语法随客户端 API 而异，通常传一个参数配置**持久化（persistence）**。

## 2.2 持久化 vs 内存模式

- **持久数据库（Persistent）**：传数据库文件路径（如 `my_database.duckdb`）创建/打开；扩展名任意，常见 `.db`/`.duckdb`/`.ddb`。文件不存在则新建。
- **内存数据库（In-Memory）**：传特殊值 `:memory:` 或省略路径；数据不落盘，进程结束即丢失。
- **重要**：两种模式都支持**溢出到磁盘（spilling to disk）**以支持超内存（out-of-core）工作负载。
- 存储格式自 v0.10 起向后兼容（见 1.5.3）。

## 2.3 进程内（In-Process）vs 客户端-服务器（Client-Server）

- DuckDB 本质是**嵌入式（in-process / 进程内）**数据库：引擎运行在调用方进程内，没有独立的服务器进程。这与 PostgreSQL/MySQL 等客户端-服务器数据库不同。
- 差异要点（适合书中对比表）：
  - 进程内：零网络开销、数据本地、单进程读写 + 多写线程（MVCC+乐观并发）；没有独立的"服务端"或连接池概念。
  - 多进程并发写：原生不支持；需 Quack（beta，把 DuckDB 变成 C/S）或 DuckLake（生产稳定）。
- 各语言连接：文档中 `connect/overview.md` 仅概述"连接语法随客户端 API 而异"，具体连接示例分散在 `clients/` 各客户端文档（Python/R/Java/ODBC/CLI/Node/Wasm 等）。本书撰写时建议从 `clients/overview.md` 引用各语言 `connect()` 实例；本批 `connect/` 文档未逐语言展开。

## 2.4 并发小结（与 1.6 互补）

- 单进程：读写模式（一进程可读写，多写线程）+ 只读模式（多进程只读）。
- 多进程写：经 Quack（beta）或 DuckLake + PostgreSQL。

---

# 3. Quack 远程协议（quack）

（见 `quack/overview.md`、`reference.md`、`security.md`、`setup/*.md`、`troubleshooting.md`）

## 3.1 它是什么

- **Quack 扩展把一个 DuckDB 实例变成服务器**，其他 DuckDB 实例（客户端）可通过 HTTP 连接。发布于 2026-05-12；beta 版随 **v1.5.3**（`core` 仓库）提供。
- 本质：让 DuckDB 获得"客户端-服务器"能力，从而支持多进程/远程访问（见 2.3、1.6）。

## 3.2 协议要点（In a Nutshell）

- **基于 HTTP**：消息走明文 HTTP 或 HTTPS（经反向代理）。标准负载均衡、防火墙、反向代理按普通 HTTP 服务处理，无自定义传输层。
- **客户端驱动**：每次交互由客户端发起，服务端不主动推送。
- **`application/duckdb` 序列化**：请求/响应用 DuckDB 内部序列化原语编码（与 WAL 同一代码路径），复杂类型（嵌套、decimal、interval 等）无损跨线。
- **每查询单往返**：握手后一条查询只需一次请求-响应；大结果通过后续 `FETCH` 分块流式返回，可多线程并行。
- **默认端口 9494**；URI 使用 `quack:` scheme（如 `quack:hostname:port`），默认端口 9494。

## 3.3 服务端使用

- 启动服务器（从已有 DuckDB 会话）：`CALL quack_serve('quack:localhost');`
  - 返回监听 URI、HTTP URL，以及（默认认证下）客户端所需 `auth_token`。
  - 默认仅绑定 localhost；要监听外部地址需 `allow_other_hostname => true`：`CALL quack_serve('quack:0.0.0.0:9494', allow_other_hostname => true);`
  - 建议外部暴露时前置 TLS 终止的反向代理。
- 停止：`CALL quack_stop('quack:localhost');`
- URI 示例：`quack:localhost`（9434? 默认 9494）、`quack:myhost:9000`、`quack:[::1]:1234`（IPv6）。可用 `quack_uri_parser(uri, ssl)` 校验。

## 3.4 客户端使用

两种方式：

1. **`quack_query(uri, query)`**：无状态查询，不需 attach。
   ```sql
   FROM quack_query('quack:localhost', 'SELECT 42', token='⟨TOKEN⟩');
   ```
   远程默认 HTTPS；明文可加 `disable_ssl => true`。
2. **`ATTACH 'quack:host' AS name`**：把远程作为完整 catalog 挂载，远程表像本地表一样使用：
   ```sql
   ATTACH 'quack:localhost' AS remote_db (TOKEN '⟨TOKEN⟩');
   CREATE TABLE remote_db.t AS FROM range(10) r(i);  -- 远程 DDL
   INSERT INTO remote_db.t VALUES (42);              -- 远程写
   FROM remote_db.t WHERE i = 42;                    -- 远程过滤
   BEGIN; ...; COMMIT;                                -- 事务转发
   DETACH quack;
   ```
   挂载后还暴露 `query` 表宏：`FROM remote_db.query('SELECT 42');`

- **认证**：客户端通过 `quack` secret（按 URI 作用域）或显式 `TOKEN` 选项传 token。推荐 secret 方式：
  ```sql
  CREATE SECRET (TYPE quack, TOKEN '⟨TOKEN⟩', SCOPE 'quack:localhost');
  ATTACH 'quack:localhost' AS remote_db (TYPE quack);
  ```
- **HTTP 连接缓存**：`SET httpfs_connection_caching = true;` 复用连接，降低重复 TLS 握手延迟。
- **节点身份 `whoami()`**：`FROM remote_db.query('FROM whoami()');` 返回 name/provider/hostname/region/uptime/版本/平台等；用 `quack_identify(...)` 或 `whoami_*` 选项设置。

## 3.5 认证与授权（Security）

- 暴露模型：Quack 服务端暴露底层 DuckDB 的**完整 SQL 面**（含读写），故默认保守：
  - 启动时生成**随机认证 token**，客户端每次连接必须提供。
  - 仅绑定 localhost；非本地主机名需显式 `allow_other_hostname => true`。
  - 服务端**自身不启用 TLS**（localhost 通信加 TLS 无收益）；非本地 URI 时客户端默认假设 HTTPS。
- 两道钩子（hooks）：
  - **Authentication（认证）**：`quack_authentication_function`（默认 `quack_check_token`），在 `CONNECTION_REQUEST` 时调用，签名 `(sid, client_token, server_token) -> BOOLEAN`。
  - **Authorization（授权）**：`quack_authorization_function`（默认 `quack_nop_authorization`，放行一切），在 `PREPARE_REQUEST` 时调用，签名 `(sid, query) -> BOOLEAN`。
  - 两设置均为 **global 作用域**（`SET GLOBAL`）；回调在**全新临时服务端连接**中执行，不能依赖会话局部状态。
  - 可用 SQL `MACRO` 或 C++/Rust/Go 等扩展注册的标量函数替换（Python UDF 因连接作用域问题**不可用**作回调）。
  - 示例：多 token 表认证、只读授权（`regexp_matches(upper(trim(query)), '^(SELECT|FROM|WITH|EXPLAIN|DESCRIBE|SHOW)\b')`）——文档提醒该正则仅示意，生产应挂载为只读模式或检查解析后的语句类型。

## 3.6 安全部署（反向代理）

- Quack 只说明文 HTTP，默认绑 localhost；任何非本地部署都建议前置成熟 HTTP 反向代理终止 TLS。
- 三种方案：① Caddy 本地 TLS 测试；② nginx + Let's Encrypt（最常见）；③ Caddy + Let's Encrypt。
- 关键 nginx 配置：`client_max_body_size 256M`（PREPARE/APPEND 体大）、`proxy_read_timeout 600s`/`proxy_send_timeout 600s`（长查询）、`proxy_http_version 1.1` + `proxy_set_header Connection ""`（保持长连，维持 `quack_connection_id` 状态）、`proxy_buffering off`（不缓冲流式 FETCH）。
- AWS EC2 一键 CloudFormation 模板：起一个小 EC2，跑 DuckDB + Quack + nginx + Let's Encrypt；输出每实例 token 与连接 URI。

## 3.7 参考：函数 / 设置 / 日志

- **服务端管理**：`quack_serve(uri, token, allow_other_hostname, disable_ssl)`、`quack_stop(uri)`、`quack_identify(...)`、`whoami()`。
- **客户端查询**：`quack_query(uri, query, token, disable_ssl)`、`quack_query_by_name(catalog, query)`。
- **工具**：`quack_uri_parser(uri, ssl)`、`quack_check_token(...)`、`quack_nop_authorization(...)`。
- **ATTACH 选项**：`TOKEN`(VARCHAR)、`DISABLE_SSL`(BOOLEAN，本地默认 true 否则 false)、`TYPE`(VARCHAR)。
- **FETCH 批处理**：`quack_fetch_batch_chunks`(UBIGINT，默认 12) —— 每个 FETCH 响应批量的 DataChunk 数。
- **日志**：`enable_logging('Quack')` / `enable_logging('HTTP')`，经 `duckdb_logs_parsed(...)` 查询；可持久化到文件（`storage=>'file'`）。

## 3.8 版本状态

- Quack 当前为 **beta**，生产前不成熟、可能有破坏性变更，预期在 **DuckDB v2.0** 稳定。问题排查：`FORCE INSTALL quack;` 升级扩展。

---

# 4. 开发（dev）：从源码构建与测试

（见 `dev/building/*`、`dev/sqllogictest/*`）

## 4.1 何时需要从源码构建

- 稳定/预览版二进制已在安装页提供，**多数情况建议直接用二进制**。
- 需自行构建的场景：实验性平台（如 Raspberry Pi）、为未合并的 PR 构建、需要特定扩展/定制。

## 4.2 前置依赖

- **CMake** + **C++11 兼容编译器**（GCC / Apple-Clang / MSVC）。
- 推荐 **Ninja** 构建系统（自动并行化）。
- 注：v2.0 将要求 **C++17**。

## 4.3 Makefile 构建目标（顶层）

```bash
make                 # 等价于 make release
make release         # 发布版（去断言/调试符号，性能优化）
make relassert       # 保留 D_ASSERT 与调试符号，比 debug 快很多
make debug           # 全调试信息，二进制慢；需 ≥25 GB 磁盘
GEN=ninja make       # 使用 Ninja
BUILD_BENCHMARK=1 make   # 含基准测试套件
```
- 其他构建类型（`build_configuration.md`）：`reldebug`（类似 relassert 但去掉断言）、`benchmark`（= release + BUILD_BENCHMARK=1）、`tidy-check`（clang-tidy 静态分析）、`format-fix/format-changes/format-main`（仅格式检查）。
- 加速后续构建：用 **ccache**（macOS：`brew install ccache; ccache -M 50G`）。

## 4.4 平台具体步骤

### Linux
- Ubuntu/Debian：`sudo apt-get install -y git g++ cmake ninja-build libssl-dev libcurl4-openssl-dev`，然后 `git clone ...; cd duckdb; GEN=ninja make`。
- Fedora/CentOS/RHEL：`sudo yum install -y git g++ cmake ninja-build openssl-devel`（老版本把 `g++` 换 `gcc-c++`，可跳过 Ninja 用 `mkdir build && cd build && cmake .. && make -j$(nproc)`）。
- Arch：`sudo pacman -S git gcc cmake ninja openssl`。
- Alpine（musl libc）：性能比 glibc 低（部分负载慢 5×+），性能负载建议 glibc；Python 包需源码编译。
- 产物：`build/release/duckdb`。
- 构建扩展：`BUILD_EXTENSIONS='autocomplete;httpfs;icu;json;tpch' GEN=ninja make`。
- 故障：httpfs 构建失败多因缺 OpenSSL（`sudo apt-get install -y libssl-dev`）；AArch64 上 R 包 `too many GOT entries` 需在 `~/.R/Makevars` 加 `-fPIC`。

### macOS
- `brew install git cmake ninja`，然后 `git clone ...; cd duckdb; GEN=ninja make`；产物 `build/release/duckdb`。
- 故障：① `'string' file not found` → 重装 Xcode（`sudo rm -rf /Library/Developer/CommandLineTools; xcode-select --install`，谨慎）；② debug 构建 malloc 警告 → `MallocNanoZone=0 make debug`。

### Windows
- 需要 **Microsoft Visual C++ Redistributable**（构建期与运行期依赖）。Windows 直接调 CMake（不像 UNIX 用 Makefile 包装）：
  ```bash
  python scripts/windows_ci.py
  cmake -DCMAKE_BUILD_TYPE=Release -DCMAKE_GENERATOR_PLATFORM=x64 \
        -DENABLE_EXTENSION_AUTOLOADING=1 -DENABLE_EXTENSION_AUTOINSTALL=1 \
        -DDUCKDB_EXTENSION_CONFIGS="..." -DDISABLE_UNITY=1 -DOVERRIDE_GIT_DESCRIBE="$..." 
  cmake --build . --config Release --parallel
  ```
- 也可用 **MSYS2 + MinGW64**：`pacman -Syu git mingw-w64-x86_64-toolchain mingw-w64-x86_64-cmake mingw-w64-x86_64-ninja`，然后 `cmake -G "Ninja" -DCMAKE_BUILD_TYPE=Release -DBUILD_EXTENSIONS="icu;parquet;json"` + `cmake --build . --config Release`；产物 `./duckdb.exe`。

## 4.5 扩展构建与配置

（见 `building_extensions.md`、`build_configuration.md`）

- 选扩展：`BUILD_EXTENSIONS='tpch;httpfs;fts;json;parquet' make`。
- 特殊标志：`BUILD_JEMALLOC`（构建 jemalloc，macOS 用）、`BUILD_TPCE`（TPC-E，非真正扩展）。
- 调试标志：`CRASH_ON_ASSERT`（断言触发直接崩溃）、`DISABLE_STRING_INLINE`（禁用 12 字节内联）、`DISABLE_MEMORY_SAFETY`、`DESTROY_UNPINNED_BLOCKS`、`DEBUG_STACKTRACE`。
- CMake 配置文件法：写 `extension_config.cmake`（`duckdb_extension_load(...)` 列表），用 `GEN=ninja EXTENSION_CONFIGS="extension_config.cmake" make` 构建，再 `INSTALL '.../ext.duckdb_extension';` 安装。
- 包标志：`BUILD_PYTHON=1`、`BUILD_SHELL`（默认开）、`BUILD_BENCHMARK=1`、`BUILD_JDBC=1`、`BUILD_ODBC=1`，如 `BUILD_PYTHON=1 make debug`。
- 其它：`DISABLE_UNITY`（关闭 unity build 以暴露 include bug）、`DISABLE_SANITIZER`、`OVERRIDE_GIT_DESCRIBE=v0.10.0-...`（非完整 git 仓库时覆盖版本）。

## 4.6 故障排查（构建）

- **内存不足**：Ninja 并行导致 OOM（Alpine 小内存机常见）。解决：关闭 Ninja —— `GEN= make`。

## 4.7 Amalgamation 构建

- 可生成单一对 `.hpp`/`.cpp`（`duckdb.hpp`、`duckdb.cpp`，约 50 万行）便于嵌入：`python scripts/amalgamation.py`。属尽力而为（best-effort），非官方支持。
- 已知限制：不支持 `-march=native`（本地原生指令集）编译。

## 4.8 测试：sqllogictest 框架

（见 `dev/sqllogictest/*`）

### 4.8.1 测试哲学与框架
- 原则：尽量把所有测试走 **SQL**（避免单独测组件，便于日后改动）。例外用 **Catch**（C++ 测试）测 C++ API。
- 纯 SQL 测试用 **sqllogictest**（源自 SQLite 的扩展版）；每条测试是自包含文件，位于 `test/sql`。
- 运行器：`unittest` 程序，位于 `build/release/test/unittest` 或 `build/debug/test/unittest`。

### 4.8.2 测试文件格式
- 每个文件顶部注释写 `# name:`（相对路径）与 `# group [`（所在目录）。
- 语句：`statement ok`（期望成功）、`statement error`（期望失败，可跟期望错误文本）。
- 查询：`query II`（结果列数用 `I` 表示，如两列写 `II`），随后 `----` 与制表符分隔的结果值。
- 扩展名：`.test`（快测集）或 `.test_slow`（慢测，仅 `unittest *` 全跑时执行）。
- 示例：
  ```sql
  # name: test/sql/projection/test_simple_projection.test
  # group [projection]
  statement ok
  PRAGMA enable_verification
  statement ok
  CREATE TABLE a (i INTEGER, j INTEGER);
  statement ok
  INSERT INTO a VALUES (42, 84);
  query II
  SELECT * FROM a;
  ----
  42	84
  ```
- **Query Verification**：多数简单测试开头 `PRAGMA enable_verification`，它同时跑"未优化"与"优化"两版查询并比对结果，从而捕捉优化器/连接实现的 bug（大数据集会很慢，故 >10–100 行时不建议开）。
- 临时文件：用 `__TEST_DIR__` 占位符指向临时测试目录。
- `require` 字段：如 `require parquet` / `require icu`；扩展未加载则跳过后续语句。`require vector_size 512` 限制仅在向量大小≥512 时运行（CI 用向量大小 2 跑测试）。

### 4.8.3 结果验证细则（`result_verification.md`）
- 列类型字母：`I`（推荐，唯一应使用）、历史遗留 `R`/`T`。
- NULL/空串：空行在 runner 中有特殊含义（语句分隔），故 NULL 用 `NULL`、空串用 `(empty)` 表示。
- 错误验证：`statement error` + `----` 下期望错误文本；只要错误消息**包含**该文本即通过（建议只写片段以免格式变动致测试失效）。
- 正则：`<REGEX>:...`（结果需匹配）、`<!REGEX>:...`（结果不能包含）。
- 文件：`<FILE>:path` 从仓库相对路径读期望结果（用于大结果复用）。
- 排序：列描述处可写 `nosort`/`rowsort`/`valuesort`（与 connection label 互斥）；推荐用 `ORDER BY` 而非该字段。
- 行序 vs 值序：结果可按行（制表符分隔）或按值（每行一个值）给出。
- 哈希：`200 values hashing to <md5>` 用 MD5 比对（省空间但不利调试）；`mode output_hash` 让 runner 打印各查询哈希，`mode output_result` 打印结果。
- 查询标签（query labels）：给等价但写法不同的查询打同一标签，互相比对结果（如 `query I nosort r43` 两个查询结果互相校验）。
- 连接标签（connection label）：见 4.8.6。

### 4.8.4 单元测试器配置（`test_configuration.md`）
- 三种设置方式：命令行参数、`--test-config` 的 JSON 文件、`DUCKDB_TEST_` 前缀环境变量。
- 常用选项（节选）：`--test-dir`/`--data-dir`、`--force-storage`（用持久存储文件测试）、`--storage-version`、`--block-size`（块分配大小，须为 2 的幂）、`--checkpoint-wal-size`、`--max-threads`/`--max-test-threads`、`--autoloading`、`--require`、`--skip-tag`/`--select-tag`、`--verify-vector`（向量验证：dictionary_expression 等）、`--test-memory-leaks`、`--stdin`（从标准输入读单脚本）、`--storage-fuzzer`。
- JSON 配置支持 `extends`、`inherit_skip_tests`、`skip_tests`（含 reason 与 paths）。

### 4.8.5 循环（`loops.md`）
- `loop i 0 100 ... endloop`：重复执行，`${i}` 替换常量。`foreach a b c ... endloop` 遍历值集。
- 预设：`⟨compression⟩`(none uncompressed rle bitpacking dictionary fsst chimp patas)、`⟨signed⟩`/`⟨unsigned⟩`/`⟨integral⟩`/`⟨numeric⟩`/`⟨alltypes⟩`。
- 建议：少用大循环；勿用循环插入数据（慢），改用 `range()`/`repeat()` 或读 CSV/Parquet/TPC-H・TPC-DS(`CALL dbgen(sf=1)`) 生成数据。

### 4.8.6 多连接与并发（`multiple_connections.md`）
- connection label：`statement ok con1` / `query I con2` —— 同标签的语句在同一连接执行，用于事务可见性测试（如 con1 `BEGIN`+`CREATE TABLE`，con2 查询应报"表不存在"直到提交）。
- `concurrentloop i 0 10 ... endloop`：在多线程**并发**跑多连接代码（仍逐一写标签则只顺序单线程）。
- `statement maybe`：接受成功或特定错误（如 `write-write conflict`），应对并发冲突的不确定性。

### 4.8.7 持久化测试（`persistent_testing.md`）
- 默认内存模式；用 `load <db>` 加载磁盘库、`restart` 重新加载以测持久性。
- 默认 `SET wal_autocheckpoint='0KB'`（每语句后 checkpoint）。WAL 测试用 `PRAGMA disable_checkpoint_on_shutdown` + `PRAGMA wal_autocheckpoint='1TB'` 关闭。

### 4.8.8 Catch C++ 测试（`catch.md`）
- 当纯 SQL 不够（测 C++ API）时用 Catch。示例 `TEST_CASE("Test simple storage", "[storage]")`，用 C++ API 建库/查询，以 `REQUIRE_NO_FAIL`/`REQUIRE_FAIL`（对应 statement ok/error）与 `REQUIRE(CHECK_COLUMN(...))`（对应 query 结果）校验。每个测试须加入对应 `CMakeLists.txt`。

### 4.8.9 调试（`debugging.md`）
- 建议 `make debug` 后只跑失败测试：`build/debug/test/unittest test/sql/projection/test_simple_projection.test`。
- 跑目录：`build/debug/test/unittest "[projection]"`；全跑（含慢测）：`unittest "*"`；子集：`--start-offset`/`--end-offset`（支持百分比）；从文件列表：`-f test.list`。
- 断点：每执行查询会调 `query_break(line)`，可在 gdb/lldb 设条件断点（`break query_break if line==43`）。`mode skip` / `mode unskip` 可跳过部分查询。

---

# 5. 关键术语表（Glossary）

| 术语 | 含义 |
|---|---|
| **DataChunk** | 执行期在算子间传递的基本单位，一组 Vector 的集合。 |
| **Vector** | 执行期单类型内存数据容器；支持 flat/constant/dictionary/sequence 等格式。 |
| **STANDARD_VECTOR_SIZE** | 向量固定大小，默认 2048 行。 |
| **Push-based execution** | DuckDB 的推送式向量化执行模型。 |
| **LogicalOperator / PhysicalOperator** | 逻辑/物理算子树节点。 |
| **MVCC** | 多版本并发控制，与乐观并发控制配合支持单进程内多写线程。 |
| **Optimistic Concurrency Control** | 乐观并发控制；写冲突时第二个事务失败。 |
| **Row Group** | 存储层的水平分区（等同 Parquet row group）。 |
| **Lightweight Compression** | DuckDB 采用的低开销压缩策略。 |
| **WAL (Write-Ahead Log)** | 预写日志；Quack 序列化复用其代码路径。 |
| **ART (Adaptive Radix Tree)** | DuckDB 索引使用的自适应基数树（详见 DiDi 文献）。 |
| **Catalog** | 内存中维护表/视图/函数/模式元数据的目录，Binder 阶段查询。 |
| **Quack** | 把 DuckDB 变成 HTTP 服务器的远程协议扩展（beta，v1.5.3+）。 |
| **sqllogictest** | DuckDB 的 SQL 测试框架（源自 SQLite）。 |
| **unittest** | 构建出的测试运行器程序。 |
| **Catch** | C++ 单元测试框架，用于测 C++ API。 |
| **Amalgamation** | 单一 `.hpp`/`.cpp` 嵌入构建（约 50 万行）。 |
| **jemalloc** | 第三方内存分配器（v1.5.3 起作库分发）。 |

---

# 6. 给"高级概念"章节的写作建议

1. **架构原理主线**：Parser→Binder→Logical Planner→Optimizer→Physical Plan→向量化执行，配文字流程图；强调"列式存储 + 向量化执行 + 轻量压缩 + MVCC"四大支柱。
2. **Volcano vs 向量化**：用 1.3 的对比说明为何 DuckDB 选向量化（批处理、SIMD 友好、压缩执行）。
3. **存储章**：强调 Row Group、磁盘压缩算法族（Constant/RLE/BitPacking/FOR/Dictionary/FSST/ALP/Chimp/Patas/Zstd）、存储版本与向后兼容。
4. **事务章**：单进程 MVCC+乐观并发；多进程写经 Quack（beta）或 DuckLake。
5. **连接章**：进程内 vs 客户端-服务器对比表；各语言连接指向 `clients/` 文档。
6. **Quack 章**：作为"DuckDB 走向 C/S"的新能力，标注 beta 与 v2.0 成熟预期、安全部署要点。
7. **开发章**：从源码构建（CMake/Make/Ninja + 平台命令）、sqllogictest 测试编写与运行、Catch 与调试。

> 注意：本批 `internals/` 文档未含 ART 索引、Buffer Manager、catalog 深层实现的独立章节；如需深入，引用《Design and Implementation of DuckDB Internals (DiDi)》库条目及对应源码（`src/storage`、`src/execution`、`src/planner` 等）。
