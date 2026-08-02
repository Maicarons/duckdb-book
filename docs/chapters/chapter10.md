# 第 10 章 其他客户端

DuckDB 的进程内（in-process）本质，决定了它交付给使用者的形态是一组被编译进宿主程序的库（library），而非一个需要单独运维的服务器进程。前几章已围绕 CLI（第 2 章）与 Python 客户端（第 9 章）展开，二者覆盖了绝大多数日常交互场景。但 DuckDB 的客户端生态远不止于此：要在 C/C++ 程序里把引擎当作嵌入式组件链接进来，要在 Node.js 服务、ODBC 桥接层或浏览器中复用同一份数据，乃至用 R、Go、Rust、Julia 等语言驱动分析任务，都需要各自的客户端 API（官方称 "drivers"）。这些客户端共享同一套 SQL 语法、同一套磁盘数据库格式（on-disk database format），扩展（extensions）也基本可移植——Wasm 是少数例外。本章逐一拆解除 CLI 与 Python 之外的其余客户端，并明确它们各自在官方支持等级（support tier）中的落位。

## 10.1 CLI 进阶

第 2 章已介绍 CLI 的启动方式、基本点命令（dot command，如 `.tables`、`.schema`、`.exit`）与交互式查询。本节把重点转向两个生产环境常用的方向：用点命令控制输出格式，以及把 CLI 当作批处理工具编排进脚本流水线。

### 10.1.1 输出格式：`.mode` 的 csv / json / markdown

CLI 默认以 `duckbox` 模式呈现结果（一种功能最丰富的 Unicode 方框表格）。借助 `.mode ⟨MODE⟩` 可切换输出形态，便于把结果直接喂给其他程序。三种在集成场景中最常用的格式如下。

`csv` 模式输出逗号分隔值，可与电子表格或下游 ETL 工具无缝衔接；配合 `.separator "|"` 还能改成分隔符（如管道符）：

```bash
duckdb my.db
.mode csv
SELECT id, name FROM users;
-- 1,Alice
-- 2,Bob
```

`json` 模式输出一个 JSON 数组，每个元素是一行记录的键值对，适合被程序解析：

```bash
duckdb my.db
.mode json
SELECT id, name FROM users;
-- [{"id":1,"name":"Alice"},{"id":2,"name":"Bob"}]
```

`markdown` 模式输出 GitHub 风格的 Markdown 表格，常用于把查询结果直接贴进文档或笔记：

```bash
duckdb my.db
.mode markdown
SELECT id, name FROM users;
-- | id | name  |
-- |----|-------|
-- | 1  | Alice |
-- | 2  | Bob   |
```

`.mode` 还支持 `ascii`、`box`、`column`、`html`、`insert ⟨TABLE⟩`、`jsonlines`（NDJSON）、`latex`、`line`、`list`、`table`、`tabs`、`tcl`、`trash`（无输出）等。命令行启动阶段也可直接以参数指定格式，例如 `duckdb -csv -c 'SELECT 42 AS hello'`，且参数按出现顺序逐一生效，因此可在同一条命令里用 `-json` 切换后续查询的格式。

### 10.1.2 批量脚本：`.read` 与重定向

把查询固化成脚本文件后，CLI 提供了多条执行路径。点命令 `.read ⟨FILE⟩` 从文件读取并执行其中的 SQL 与点命令，是最直观的一种：

```bash
duckdb my.db
.read setup.sql
```

`setup.sql` 内部可以混合 SQL 与 `.mode`、`.import` 等点命令，例如：

```sql
-- setup.sql
.mode markdown
.import --csv raw.csv staging
SELECT count(*) FROM staging;
```

若脚本仅含 SQL，也可借助启动参数一次性运行后退出：

```bash
duckdb my.db -f setup.sql
```

更彻底的非交互用法是把脚本经标准输入（stdin）灌入，或把查询作为 `-c` 参数传入：

```bash
duckdb < select_example.sql
duckdb :memory: "SELECT 42 AS the_answer"
```

CLI 同样能接入 Unix 管道（pipeline），把上游程序的输出当作文件来读，把结果写回标准输出（stdout）：

```bash
cat test.csv | duckdb -c "SELECT * FROM read_csv('/dev/stdin')"
duckdb -c "COPY (SELECT 1) TO '/dev/stdout' (FORMAT CSV)"
```

这类写法让 CLI 成为数据流水线里一个轻量、无依赖的环节，既可作为临时的查询入口，也可嵌入定时任务或 CI 脚本。

## 10.2 C / C++ API

把 DuckDB 嵌入到自有系统中，最直接的方式是 C API。它对应 Primary（一级）支持层级，是稳定且有长期兼容承诺的接口。

### 10.2.1 C API（libduckdb）

C API 的头文件为 `duckdb.h`，整体模拟 SQLite 的 C API 风格，甚至提供了 SQLite API 的封装（wrapper），使得已有 SQLite 程序只需重新链接即可迁移。打开与关闭数据库的四个核心函数构成完整生命周期：

```c
duckdb_database db;
duckdb_connection con;

duckdb_open(NULL, &db);          /* NULL 或 ":memory:" 打开内存库 */
duckdb_connect(db, &con);
/* ... 在此执行查询 ... */
duckdb_disconnect(&con);
duckdb_close(&db);               /* 必须显式关闭，避免句柄与内存泄漏 */
```

`duckdb_query` 执行一条 SQL 并把结果物化（materialize）到 `duckdb_result` 中；无论成败，都必须调用 `duckdb_destroy_result` 释放，以回收内部字符串与缓冲区。取数的高性能路径是 `duckdb_fetch_chunk`，它直接返回原生列式结构 DataChunk，与 DuckDB 内部的向量化（vectorized）执行自然衔接——文档中的 `duckdb_value` 便捷函数虽更易用，但已废弃且因类型/边界检查而偏慢。

参数化查询走 prepared statement 路径：

```c
duckdb_prepared_statement stmt;
duckdb_prepare(con, "INSERT INTO integers VALUES ($1, $2)", &stmt);
duckdb_bind_int32(stmt, 1, 42);   /* 参数索引从 1 开始 */
duckdb_execute_prepared(stmt, NULL);
duckdb_destroy_prepare(&stmt);
```

批量写入最快的路径是 Appender，它对行式追加做了极致优化：

```c
duckdb_appender appender;
duckdb_appender_create(con, NULL, "people", &appender);
duckdb_append_int32(appender, 1);
duckdb_append_varchar(appender, "Mark");
duckdb_appender_end_row(appender);    /* 逐行提交 */
duckdb_appender_destroy(&appender);   /* 刷新缓冲并释放，务必调用 */
```

Appender 提供覆盖全类型的 `duckdb_append_*` 函数族，并支持 `duckdb_appender_create_ext`（按 catalog.schema.table 定位）、`duckdb_appender_create_query`（对 INSERT/DELETE/UPDATE/MERGE 追加）与 `duckdb_append_data_chunk`（直接追加强预填充的 chunk）。同进程重复打开同一文件时，可用 `duckdb_create_instance_cache` / `duckdb_get_or_create_from_cache` 复用实例缓存，避免重复初始化的开销。

### 10.2.2 C++ API（内部接口，不稳定）

C++ API 的头文件为 `duckdb.hpp`，以 `DuckDB`（实例）、`Connection`、`QueryResult` 等类封装了更贴近 C++ 习惯的用法：

```cpp
DuckDB db(nullptr);            /* nullptr 打开内存库 */
Connection con(db);
auto result = con.Query("SELECT * FROM integers");
if (result->HasError()) {
    /* 通过 GetErrorType / GetErrorObject 检视错误 */
}
```

但官方明确将 C++ API 归入 Secondary（二级）并标注为内部接口：它**不保证稳定**，可能在不另行通知的情况下改动。任何面向生产的程序都应坚持使用 C API；C++ API 仅适合实验性代码或紧跟特定 DuckDB 版本的内部工具。

## 10.3 Node.js、ODBC、Wasm

这三类客户端面向不同的集成目标：Node.js 服务化、面向既有 BI/报表系统的 ODBC 桥接、以及浏览器内的纯前端分析。

### 10.3.1 Node.js（@duckdb/node-api）

Node.js 客户端属于 Primary 层级，主包 `@duckdb/node-api` 提供高层应用 API，底层 `@duckdb/node-bindings` 紧贴 C API。建立实例与连接的写法如下：

```javascript
import { DuckDBConnection, DuckDBInstance } from '@duckdb/node-api';

const connection = await DuckDBConnection.create();        // 默认实例
const instance = await DuckDBInstance.create(':memory:'); // 或 'my.duckdb'、带 {threads:'4'}
const conn = await instance.connect();
conn.disconnectSync();   // 或 closeSync()
```

同进程内若需多个实例指向同一文件，可使用 Instance Cache 复用：`DuckDBInstance.fromCache('my.duckdb')` 或自建 `DuckDBInstanceCache`。查询侧支持 `run`（执行不取行）、`runAndRead`/`runAndReadAll`、`stream`/`streamAndRead*` 以及 `prepare` + 分步求值；取结果既能按行（`reader.getRows()`）、也能按 chunk（`result.fetchChunk()` / `fetchAllChunks()`，再经 `chunk.getColumnVector(i).getItem(j)` 访问）。批量写入沿用 Appender 思路：

```javascript
const appender = await connection.createAppender('tbl');
appender.appendInteger(1);
appender.appendVarchar('duck');
appender.endRow();
appender.flushSync();   // 或 closeSync()
```

### 10.3.2 ODBC

ODBC 驱动遵循 **ODBC 3.0 Core Interface Conformance**，跨平台（Linux / macOS / Windows）可用。它通过 Driver Manager（如 unixODBC）按 DSN（Data Source Name，数据源名）定位具体驱动，因此必须正确配置两个文件。

`odbc.ini`（或用户级 `.odbc.ini`）定义 DSN：

```ini
[DuckDB]
Driver = DuckDB Driver
Database = :memory:
access_mode = read_only
```

`odbcinst.ini`（或 `.odbcinst.ini`）登记已安装的驱动：

```ini
[ODBC]
Trace = yes
TraceFile = /tmp/odbctrace
[DuckDB Driver]
Driver = /path/to/libduckdb_odbc.dylib
```

应用只需引用 DSN 名称（上例的 `DuckDB`），Driver Manager 便据此找到对应的 `libduckdb_odbc` 动态库。各平台的路径与 Driver Manager 安装细节略有差异，需参考对应平台的专用说明。

### 10.3.3 DuckDB-Wasm

DuckDB 可被编译为 WebAssembly（Wasm），从而运行在任意浏览器或边缘设备。核心包为 `@duckdb/duckdb-wasm`（JS + WASM 库）与 `@duckdb/duckdb-wasm-shell`（Web shell），在线体验地址为 shell.duckdb.org。

实例化（instantiation）依赖所选的 bundle。DuckDB-Wasm 提供 **mvp** 与 **eh** 两种包：mvp 对应基础的 WASM 特性集，eh（exception handling，异常处理）则在支持该特性的环境下提供更完整的异常语义。通过 `duckdb.selectBundle(...)` 选定后，交由 `AsyncDuckDB(logger, worker)` 与 `db.instantiate(...)` 完成加载。查询既可物化取回，也可流式遍历 chunk：

```javascript
const conn = await db.connect();
await conn.query(`SELECT * FROM generate_series(1, 100) t(v)`);
for await (const batch of await conn.send(`SELECT * FROM generate_series(1, 100)`)) {
    /* 逐 batch 处理 Arrow 数据 */
}
const stmt = await conn.prepare(`SELECT v + ? FROM generate_series(0, 10000) t(v)`);
await stmt.query(234);
```

Wasm 版本有两条硬限制需时刻记牢：默认**单线程**（single-threaded）执行，无法利用多核；内存受 WASM 上限约束，容量封顶 **4 GB**，部分浏览器还会施加更严格的限制。因此 Wasm 适合中等规模的交互式分析与前端嵌入，而非替代服务端的大规模 OLAP。

## 10.4 第三方客户端

DuckDB 的客户端版图由一套明确的三级支持等级（support tier）组织。厘清层级，才能判断某语言绑定在排期与稳定性上的预期：

- **Primary（一级）**：最先获得新特性，受社区支持（community support）。包括 C、CLI、Java/JDBC、Go、Node.js、ODBC、Python、R、Rust、WebAssembly。
- **Secondary（二级）**：会获得新特性，但**不受社区支持**。包括 ADBC（Arrow）、C#（.NET）、C++。
- **Tertiary（三级）**：无支持保证，由社区维护。包括 Julia、Swift、Dart、PHP 等。

需要特别说明：R、Go、Rust、Java/JDBC 虽常被泛称为"第三方语言绑定"，但官方将其归入 **Primary 层级**并受社区支持，并非 Tertiary。本节的"第三方"取其宽泛含义——即除 CLI 与 Python 之外的其余语言生态；其中真正属于 Tertiary 层级、无官方支持保证的，是 Julia、Swift、Dart、PHP 等。

### 10.4.1 Primary 层级的语言绑定

**R**（Primary）：经 `install.packages("duckdb")` 安装，遵循 DBI 接口，`dbplyr` / `duckplyr` 兼容 dplyr 语法；`dbWriteTable` 写表，`duckdb_register` 注册虚拟表，`memory_limit` 可限定 DuckDB 自身内存。

**Go**（Primary）：包 `duckdb-go` 经标准 `database/sql` 接口接入，用 `sql.Open("duckdb", "")` 建立连接，并提供 `NewAppenderFromConn` 做高效批量写入。

**Rust**（Primary）：`duckdb-rs` 是基于 C API 的易用封装，`Connection::open_in_memory()` 打开内存库，`conn.execute` / `conn.prepare` + `query_map` 取结果，亦支持 `conn.appender("foo")` 做 Appender 写入。

**Java / JDBC**（Primary）：Maven 依赖 `org.duckdb:duckdb_jdbc`，`DriverManager.getConnection("jdbc:duckdb:")` 连内存库（`jdbc:duckdb:/path` 连持久库，`?duckdb.read_only=true` 只读）；支持 Arrow 导入导出、`jdbc_stream_results=true` 流式结果、Appender 与 Batch Writer，`DuckDBConnection#duplicate()` 可低成本克隆连接。

### 10.4.2 Tertiary 层级与社区维护的绑定

Tertiary 层级由社区维护、无支持保证。代表性成员包括：

- **Julia**（DuckDB.jl）：虽由 DuckDB 团队维护，官方仍将其列入 Tertiary；`Pkg.add("DuckDB")` 后可用 `DBInterface.connect(DuckDB.DB, ":memory:")` 连接，并提供 `DuckDB.register_data_frame` 与 Appender API 高效写入。
- **Swift**（duckdb-swift）：`Database(store: .inMemory)` 或 `.file(at:)` 建库，`database.connect()` 取连接，结果经 `result[i].cast(to:)` 转为原生类型。
- **Dart**（dart_duckdb，TigerEye 维护）：`flutter pub add dart_duckdb` 后，`duckdb.open(":memory:")` → `duckdb.connect(db)` → `connection.query(...).fetchAll()` → `dispose()`，每连接自动管理独立后台 isolate 以支持并发。

完整的 Tertiary 列表还包括 Common Lisp、Crystal、Elixir（Duckdbex / QuackDB）、Erlang、Haskell、Perl、PHP、PHP(PDO)、Pyodide、Raku、Ruby、Scala、Zig 等。无论哪一层级，所有客户端都遵循同一套跨客户端一致性约定：`:memory:` 或 NULL 开内存库、文件路径开持久库；多进程并发读须 `read_only`；**Appender 始终是批量写入的最快路径**（prepared statement 的 `executemany` / `addBatch` 仅适合小量数据）；Apache Arrow 在 Python、Java、Node、Wasm 间深度互通。

## 10.5 本章小结

本章 surveyed CLI 之外的 DuckDB 客户端生态，要点可归纳为四组：

- **CLI 进阶**：`.mode csv/json/markdown` 把结果导出为可机读或文档友好的格式；`.read`、`-f`、stdin 重定向与 Unix 管道让 CLI 成为批处理流水线的轻量环节，与第 2 章的基础交互形成互补。
- **C / C++ API**：C API（`duckdb_open` / `duckdb_query` / `duckdb_prepare` / `duckdb_appender`）属 Primary 层级、稳定可用，是嵌入自有系统的首选；C++ API 仅为内部接口、随时可能变动，生产代码不应依赖。
- **Node.js / ODBC / Wasm**：Node.js 经 `@duckdb/node-api` 提供实例缓存、Appender 与 chunk 流式取数；ODBC 驱动遵循 3.0 规范，须靠 `odbc.ini` / `odbcinst.ini` 的 DSN 配置接驳；DuckDB-Wasm 有 mvp / eh 两种包，但受单线程与 4 GB 内存上限约束。
- **第三方客户端**：R、Go、Rust、Java/JDBC 实为 Primary 层级并受社区支持；Julia、Swift、Dart、PHP 等才是 Tertiary 层级、由社区维护。无论层级，Appender 都是批量写入的最快路径，且所有客户端共享同一 SQL 语法、磁盘格式与 Arrow 互操作能力。
