# DuckDB 客户端（Clients）文档精读摘要

> 目标版本：DuckDB 1.5.5
> 来源：`duckdb-web-main/docs/current/clients/` 目录下全部 `.md` 文件
> 说明：英文技术术语（API 名称、SQL、类型名等）保留原文，便于与官方文档对照。

---

## 0. 总体概览（Client Overview）

DuckDB 是 **in-process（进程内）数据库**，提供多种语言的客户端 API（官方称 "drivers"）。

**支持等级（Support Tiers）：**
- **Primary（一级）**：最先获得新特性，受社区支持（community support）。包括 C、CLI、Java/JDBC、Go、Node.js（node-neo）、ODBC、Python、R、Rust、WebAssembly。
- **Secondary（二级）**：会获得新特性，但**不受社区支持**。包括 ADBC（Arrow）、C#（.NET）、C++。
- **Tertiary（三级）**：无支持保证，由社区维护（Julia、Swift、Dart、PHP 等，详见第 7 节）。

**兼容性**：所有客户端使用相同的 SQL 语法、相同的磁盘数据库格式（on-disk database format），DuckDB extensions 也基本可移植（Wasm 例外，见第 6 节）。

---

## 1. CLI（命令行客户端）

### 1.1 安装与启动
- CLI 是**单一、无依赖的可执行文件**，官方为 Windows / macOS / Linux 提供预编译版本（stable 与 nightly）。
- 基于 SQLite 命令行 shell 实现，因此交互方式类同 SQLite，但 SQL 语法遵循 PostgreSQL 约定。
- 启动：`duckdb`（PowerShell 用 `./duckdb`）。

### 1.2 典型用法
```
duckdb ⟨OPTIONS⟩ ⟨FILENAME⟩
```
- 不提供 `FILENAME` → 打开**临时内存数据库（transient in-memory database）**。
- 提供路径（如 `duckdb my_database.duckdb`）→ 打开/创建**持久化数据库**。
- SQL 语句以 `;` 结束；省略分号可输多行。
- 退出：`Ctrl+D`（支持时）、`Ctrl+C` 或 `.exit`。退出持久库时会自动 checkpoint，合并 `.wal` 文件。

### 1.3 常用命令行参数（arguments）
| 参数 | 作用 |
|------|------|
| `-csv` / `-json` / `-ascii` / `-box` / `-markdown` / `-html` / `-table` 等 | 设置输出模式 |
| `-readonly` | 只读模式打开（也支持通过 HTTPS 附加远程库） |
| `-c COMMAND` / `-s COMMAND` | 执行命令后退出 |
| `-f FILENAME` | 运行脚本文件后退出（会先读 `~/.duckdbrc`） |
| `-init FILENAME` | 启动时执行指定脚本（替代 `~/.duckdbrc`） |
| `-ui` | 加载并启动 DuckDB UI（未安装则自动安装 `ui` 扩展） |
| `-unsigned` | 允许加载 unsigned extensions（开发用） |
| `-storage-version VER` | 指定存储兼容版本（最新用 `latest`） |
| `-version` | 显示版本 |

> 参数按出现顺序处理，例如：
> `duckdb -csv -c 'SELECT 42 AS hello' -json -c 'SELECT 84 AS world'`

### 1.4 Dot Commands（点命令）
以点 `.` 开头、后接命令名；参数用空格分隔，含空格的参数用引号包裹；单行输入，结尾无需分号。常用命令：

| 命令 | 说明 |
|------|------|
| `.mode ⟨MODE⟩` | 设置输出格式（见 1.5） |
| `.tables [PATTERN]` | 列出表（含列名、类型、行数，按库/schema 分组），支持 `LIKE` 模式 |
| `.schema [PATTERN]` | 显示匹配表的 `CREATE` 语句 |
| `.dump [PATTERN]` | 将库内容导出为 SQL（schema+data），`--newlines` 保留真实换行 |
| `.open [OPTIONS] ⟨FILE⟩` | 关闭当前库并打开新库；`--readonly`、`--sql`、`--new` 等选项 |
| `.read ⟨FILE⟩` | 从文件读取并执行 SQL / 点命令 |
| `.output ⟨FILE⟩` / `.once ⟨FILE⟩` | 重定向结果到文件（`.once` 仅下一次查询） |
| `.import ⟨FILE⟩ ⟨TABLE⟩` | 从文件导入数据（支持 `--csv/--json/--parquet`，自动推断 schema） |
| `.headers on/off` | 显示/隐藏表头 |
| `.maxrows ⟨COUNT⟩` / `.maxwidth ⟨COUNT⟩` | duckbox 模式下最大行/列宽 |
| `.timer on/off` | 显示 SQL 计时 |
| `.safe_mode` | 进入安全模式（见 1.6） |
| `.prompt` / `.highlight` / `.progress_bar` | 提示符、语法高亮、进度条自定义 |
| `.bail on/off` | 出错即停 |

> 点命令支持**简写（shorthands）**——只要前缀能唯一补全即可，如 `.mo ma` ≡ `.mode markdown`（脚本中不建议用简写）。

### 1.5 输出格式（Output Formats）
`.mode` 支持的格式：`ascii`、`box`（Unicode 方框）、`csv`、`column`、`duckbox`（默认，功能最丰富）、`html`、`insert ⟨TABLE⟩`（生成 INSERT 语句）、`json`、`jsonlines`（NDJSON）、`latex`、`line`、`list`、`markdown`、`quote`、`table`、`tabs`、`tcl`、`trash`（无输出）。
- `.separator` 可改分隔符（如 `.mode csv` 后 `.separator "|"` 变为管道分隔）。
- **Paging**：`.pager on|off|automatic`，`automatic` 可配 `set_row_threshold`/`set_column_threshold`；也可 `.pager less -RS` 自定义。
- **duckbox 大数渲染**：`.large_number_rendering off|footer|all`，`footer`（默认）在单行结果下方附加人类可读数字（如 `(3.14 billion)`）。

### 1.6 安全模式（Safe Mode）
`.safe_mode` 下 CLI 禁止访问除初始数据库文件以外的外部文件/宿主文件系统：禁用 `.cd/.excel/.import/.log/.once/.open/.output/.read/.sh/.system` 等点命令；关闭文件系统自动补全；禁用 `getenv`；`enable_external_access=false`（即 `ATTACH` 文件、`COPY` 文件读写、`read_csv/read_parquet/read_json` 均不可用）。**一旦开启无法在同一会话关闭。**

### 1.7 其它实用特性
- **非交互用法**：`duckdb < select_example.sql`；或 `duckdb :memory: "SELECT 42 AS the_answer"`。
- **stdin/stdout 管道**：`cat test.csv | duckdb -c "SELECT * FROM read_csv('/dev/stdin')"`；写回用 `/dev/stdout`。
- **环境变量**：`getenv('HOME')`（仅 CLI 支持，且需 `enable_external_access=true`）。
- **Prepared Statements**：`PREPARE` + `EXECUTE`。
- **Query Completion ETA（1.5.x 新特性）**：CLI 用 **Kalman 滤波** 估算查询剩余时间，显示在进度条上。内存压力大、I/O 瓶颈、网络延迟等场景下估算会更不准（可能不单调递减）。可用 `duckdb_settings()` 查 `enable_progress_bar`、`progress_bar_time`（触发进度条的最小毫秒数）。

---

## 2. Python 客户端

### 2.1 安装与版本
- `pip install duckdb`（或 `conda install python-duckdb -c conda-forge`）。
- 要求 **Python ≥ 3.9**。
- 包名 `duckdb`，GitHub：`duckdb/duckdb-python`。

### 2.2 基础用法（Relation API 与全局库）
最简单方式：`duckdb.sql("SELECT 42").show()`。
- 结果返回 **Relation（关系）**——查询的"符号化表示"，**惰性求值**，直到取数/打印才真正执行。
- Relation 可作为表用于后续查询：`r1 = duckdb.sql("SELECT 42 AS i"); duckdb.sql("SELECT i*2 FROM r1").show()`。
- `duckdb` 模块与连接对象方法基本相同，但模块使用**全局共享内存库**（开发可复用库时不推荐，易冲突，应自建连接）。

### 2.3 连接方式（connect）
```python
con = duckdb.connect()                  # 内存库
con = duckdb.connect("file.db")         # 持久库
con = duckdb.connect(config={'threads':1})                       # 配置
con = duckdb.connect(config={'storage_compatibility_version':'latest'})
with duckdb.connect("file.db") as con:  # 上下文管理器自动关闭
    ...
```
- `duckdb.connect()`、`duckdb.connect(':default:')`、`duckdb.sql()` 都用全局内存连接，**非线程安全**；并行应每线程各建连接。
- `cursor()` 只是同一连接上的新句柄，**不能并发查询**（单连接查询时加锁，串行化访问）。

### 2.4 直接查询 DataFrame / Arrow
```python
duckdb.sql("SELECT * FROM pandas_df")      # Pandas（只读）
duckdb.sql("SELECT * FROM polars_df")      # Polars
duckdb.sql("SELECT * FROM arrow_table")    # PyArrow
```
- 通过 **replacement scan** 实现，仅对 `sql()/execute()` 调用处可见的变量有效；可用 `SET python_enable_replacements=false` 关闭。
- 注册为虚拟表：`duckdb.register("view_name", df)`；或建持久表 `CREATE TABLE t AS SELECT * FROM df`。
- 优先级：`register()` 显式注册 > 原生表/视图 > replacement scan。
- Pandas `object` 列转换前会采样分析（默认 `pandas_analyze_sample=1000`），可用 `SET GLOBAL pandas_analyze_sample=100000` 调大。

### 2.5 DB-API（execute / fetch）
```python
con.execute("CREATE TABLE items (...)")
con.execute("INSERT INTO items VALUES (?,?,?)", ["laptop", 2000, 1])   # 占位符 ? 或 $1
con.executemany("INSERT INTO items VALUES (?,?,?)", [[...],[...]])      # 批量（勿用于大量数据！）
print(con.fetchall())      # 全部
print(con.fetchone())      # 逐行，取完返回 None 才关闭事务
```
- 占位符支持 `?`（顺序）与 `$1`（可复用）；**命名参数**如 `$my_param` 用 dict：`con.execute("SELECT $p", {"p":5})`。
- `description` 属性包含列名。
- ⚠️ **不要**用 `executemany` 灌大量数据，应使用 Appender 或 `COPY`/readers。

### 2.6 Relational API（关系 API）
围绕 `DuckDBPyRelation`，**惰性求值**——调用 `show()`/`print()` 时仅取前 10K 行。
- **创建**：`sql/query/from_query`、`read_csv/read_json/read_parquet`、`from_df`、`from_arrow`、`table`、`view`、`values`、`table_function`。
- **检视**：`columns`、`dtypes/types`、`shape`、`describe`、`explain()`、`sql_query()`、`alias/set_alias`。
- **转换（Transformation，链式、惰性）**：`filter`、`project/select`、`aggregate`、`order/sort`、`limit`、`join`（inner/left/right/outer/semi/anti）、`union/except_/intersect`、`cross`、`apply`、`insert/insert_into`、`update`。
- ⚠️ 关系 API 的 `sql()/query()/from_query()` 传参有**显著性能开销**（约 5x 处理、近 2x 内存），应改用 `execute()` 做参数化查询，再用 replacement scan 接入关系 API。

### 2.7 结果转换（Conversion）
```python
duckdb.sql("SELECT 42").fetchall()      # Python 对象
duckdb.sql("SELECT 42").df()            # Pandas DataFrame（别名 fetchdf / fetch_df）
duckdb.sql("SELECT 42").pl()            # Polars DataFrame
duckdb.sql("SELECT 42").arrow()         # Arrow（建议用 to_arrow_reader）
duckdb.sql("SELECT 42").fetchnumpy()    # NumPy 字典
```
- Arrow：`to_arrow_table()`、`to_arrow_reader(chunk_size)`、`arrow()`（推荐 `to_arrow_reader`）。`fetch_arrow_table/fetch_record_batch` 已废弃。
- `fetch_df_chunk(vector_multiple)` 分块取 DataFrame（块大小 = 2048 × vector_multiple）。

### 2.8 类型与对象转换规则
**Python → DuckDB**（节选）：`None→NULL`、`bool→BOOLEAN`、`str→VARCHAR`、`bytes/bytearray→BLOB`、`decimal.Decimal→DECIMAL/DOUBLE`、`uuid.UUID→UUID`、`datetime` 带 tz→`TIMESTAMPTZ` 否则 `TIMESTAMP`、`date→DATE`、`time→TIME/TIMETZ`、`list→LIST(最兼容子类型)`、`dict→MAP 或 STRUCT`、`tuple→LIST`（构造 Value 时→STRUCT），`numpy.ndarray`/`datetime64` 经 `tolist()` 转换。
**DuckDB → Python**：`df()`、`fetchnumpy()`（masked array）、`to_arrow_table()`、`pl()` 等。
- `duckdb.sqltypes` 提供类型构造：`BIGINT`、`VARCHAR`、`DECIMAL` 等常量；`list_type/array_type`、`struct_type/row_type`、`map_type`、`decimal_type(width,scale)`、`union_type`、`string_type`。
- 内置类型映射：`int→BIGINT`、`float→DOUBLE`、`str→VARCHAR`、`bool→BOOLEAN`；Numpy：`int8→TINYINT`、`int32→INTEGER`、`int64→BIGINT`、`float32→FLOAT`、`float64→DOUBLE`、`uint8→UTINYINT` 等。

### 2.9 数据摄入（Data Ingestion）
- `read_csv("example.csv")` / 通配 `folder/*.csv`；可传 `header/sep/dtype` 等；SQL 内 `SELECT * FROM 'example.csv'` 或 `read_csv(...)`。
- `read_parquet(...)` 支持本地、HTTPS、列表、文件夹通配。
- `read_json(...)` 自动识别 newline-delimited / 普通 JSON 并推断 schema。
- 写盘：`write_parquet/write_csv`，或用 `COPY ... TO`。

### 2.10 Appender / 扩展 / 其它
- **Appender**（高效批量插入）在 Python 中可用 `con.append`（关系 API 的 `insert`），但文档明确建议大数据用 Appender（见 C 章 `appender` 思路，Python 封装为 `con.cursor`/`relation.insert` 或直接使用 C API 的 Appender）。
- **Community extensions**：`con.install_extension("h3", repository="community"); con.load_extension("h3")`。
- **Unsigned extensions**：`duckdb.connect(config={"allow_unsigned_extensions":"true"})`（仅加载可信来源）。
- 已知问题：Windows 上缺 MSVC Redistributable 会导致导入崩溃（装最新 VC++ 运行库，或 `pip install duckdb --no-binary duckdb`）；多线程取 Numpy 需先 `import numpy.core.multiarray`；`EXPLAIN` 输出含 `\n` 需 `print(...explain())`；Jupyter 中 `DESCRIBE/SUMMARIZE` 返回空表需包子查询 `FROM (DESCRIBE tbl)`。

---

## 3. C / C++ API

### 3.1 C API（libduckdb，Primary）
- 头文件 `duckdb.h`，模拟 SQLite C API，并提供 SQLite API wrapper（可 re-link 已有 SQLite 程序）。
- 安装：`libduckdb` 包（archive）。

**启动与关闭**
```c
duckdb_database db; duckdb_connection con;
duckdb_open(NULL, &db);          // NULL / ":memory:" => 内存库
duckdb_connect(db, &con);
// ... 查询 ...
duckdb_disconnect(&con);
duckdb_close(&db);               // 必须显式关闭，避免句柄/内存泄漏
```
- 多连接线程安全但查询时加锁；建议每线程独立连接。
- 另有 **instance cache**：`duckdb_create_instance_cache` / `duckdb_get_or_create_from_cache`（同进程重复开同一文件时用）。

**查询**
- `duckdb_query(con, sql, &result)` → 物化结果；`duckdb_destroy_result(&result)` 释放（即使失败也要调用以释放错误串）。
- 取数两种：**`duckdb_fetch_chunk`**（原生列式 `DataChunk`，高性能）+ `duckdb_value` 便捷函数（已**废弃**，做类型/边界检查，慢）。
- 元数据：`duckdb_column_count`、`duckdb_row_count`（废弃）、`duckdb_column_name`、`duckdb_column_type`、`duckdb_column_logical_type`、`duckdb_rows_changed`、`duckdb_result_error`。

**Prepared Statements**
```c
duckdb_prepare(con, "INSERT INTO integers VALUES ($1,$2)", &stmt);
duckdb_bind_int32(stmt, 1, 42);   // 参数索引从 1 开始
duckdb_execute_prepared(stmt, NULL);
duckdb_destroy_prepare(&stmt);
```
- 可 `duckdb_nparams`、`duckdb_param_type`、`duckdb_prepare_error` 检视；类型自动 cast。
- ⚠️ **不要用 prepared statement 插大量数据**，用 Appender。

**Appender（最高效批量写入）**
```c
duckdb_appender_create(con, NULL, "people", &appender);
duckdb_append_int32(appender, 1);
duckdb_append_varchar(appender, "Mark");
duckdb_appender_end_row(appender);   // 逐行
duckdb_appender_destroy(&appender);  // 刷新并释放（务必调用）
```
- 丰富类型函数：`duckdb_append_bool/int8..int64/uint8..uint64/hugeint/uhugeint/float/double/date/time/timestamp/interval/varchar/blob/null/value/data_chunk`。
- 还有 `duckdb_appender_create_ext`（catalog.schema.table）、`duckdb_appender_create_query`（对 INSERT/DELETE/UPDATE/MERGE 查询追加）、`duckdb_appender_flush/close`、`duckdb_append_data_chunk`（直接追加预填充 chunk）。

### 3.2 C++ API（Secondary / 内部，不稳定）
- **警告**：C++ API 是内部接口，**不保证稳定**，可能随时改动；正式应用请用 C API。
- 头文件 `duckdb.hpp`，围绕 `DuckDB`（实例）、`Connection`、`QueryResult`。
```cpp
DuckDB db(nullptr);            // nullptr => 内存库
Connection con(db);
auto result = con.Query("SELECT * FROM integers");
if (result->HasError()) { /* GetErrorType / GetErrorObject */ }
```
- `MaterializedQueryResult` 含 `success`、`error`、`statement_type`、`types`、`names`，多结果用 `next` 链。
- 流式 API 可用（避免全物化）。
- Prepared：用命名空间 `duckdb` 的 `con.Prepare(...)->Execute(...)`。
- **UDF API**：`CreateScalarFunction`（自动向量化，支持模板类型推断，最多三元参数）、`CreateVectorizedFunction`（指针式向量化 UDF，处理 `DataChunk`/`Vector`）。

---

## 4. Node.js（node-neo，Primary）

- 主包 `@duckdb/node-api`（高层应用 API），底层 `@duckdb/node-bindings` 紧贴 C API。
- 维护者：Jeff Raymakers（社区）。

**安装**：npm 包 `@duckdb/node-api`。
**平台**：`linux_amd64/arm64`、`osx_amd64/arm64`、`windows_amd64`（`windows_arm64` 暂不支持）。

**连接与实例**
```ts
import { DuckDBConnection } from '@duckdb/node-api';
const connection = await DuckDBConnection.create();                 // 默认实例
const instance = await DuckDBInstance.create(':memory:');          // 或 'my.duckdb'、带 {threads:'4'}
const conn = await instance.connect();
conn.disconnectSync();   // 或 closeSync()
```
- 同进程多实例可用 **Instance Cache**：`DuckDBInstance.fromCache('my.duckdb')` 或自建 `DuckDBInstanceCache`。

**查询与参数化**
```ts
await connection.run('from test_all_types()');
const prepared = await connection.prepare('select $1, $2, $3');
prepared.bindVarchar(1, 'duck'); prepared.bindInteger(2, 42);
const result = await prepared.run();
// 也支持命名参数 {a,b,c} 与类型 {a:VARCHAR,...}，未指定类型自动推断
```
- 多种运行方式：`run`（执行完不取行）、`runAndRead`/`runAndReadAll`、`runAndReadUntil`、`stream`/`streamAndRead*`、`prepare`+`start`（pending result，用 `runTask()` 分步求值）。

**结果获取与转换**
- `reader.getRows()` / `getRowObjects()` / `getColumns()` / `getColumnsObject()`，及 `...Json()` 系列（无损序列化，`bigint` 转字符串等）。
- 按 chunk 取：`result.fetchChunk()` / `fetchAllChunks()`；`chunk.getColumnVector(i).getItem(j)`。
- 特殊类型值构造器：`arrayValue/bitValue/blobValue/dateValue/decimalValue/intervalValue/listValue/mapValue/structValue/timeValue/timestampValue/uuidValue` 等。
- `TIMESTAMP_TZ` 字符串转换受 `DuckDBTimestampTZValue.timezoneOffsetInMinutes` 影响，可对齐 DuckDB `TimeZone`。

**Appender**：`connection.createAppender('tbl')` → `appendInteger/appendVarchar/...` → `endRow()` → `flushSync()/closeSync()`；亦可 `appendDataChunk(chunk)`。

> Roadmap 未完项：MAP/UNION 的绑定与追加、行级默认追加、UDF、profiling、Arrow API 等。

---

## 5. ODBC

- API 遵循 **ODBC 3.0 Core Interface Conformance**；Driver 跨平台（Linux/macOS/Windows）。
- 架构：Driver Manager（如 unixODBC）通过 **DSN** 找到正确 driver。

**配置文件**
- `odbc.ini` / `.odbc.ini`：定义 DSN。
  ```ini
  [DuckDB]
  Driver = DuckDB Driver
  Database = :memory:
  access_mode = read_only
  ```
- `odbcinst.ini` / `.odbcinst.ini`：已安装 driver 的通用配置。
  ```ini
  [ODBC]
  Trace = yes
  TraceFile = /tmp/odbctrace
  [DuckDB Driver]
  Driver = /path/to/libduckdb_odbc.dylib
  ```
- 平台细节见 `linux.md` / `macos.md` / `windows.md`（路径与 DM 安装差异）。

---

## 6. WebAssembly（Wasm）

- DuckDB 编译为 WASM，可在任意浏览器/设备运行。包：`@duckdb/duckdb-wasm`（JS+WASM 库）、`@duckdb/duckdb-wasm-shell`（Web shell），或源码构建。
- 在线 shell：https://shell.duckdb.org

**实例化（Instantiation）**：基于 bundle 选择（mvp / eh 异常处理版本），通过 `duckdb.selectBundle(...)` + `AsyncDuckDB(logger, worker)` + `db.instantiate(...)`。提供 cdn(jsdelivr)、webpack、vite、statically served 四种示例。

**查询**
```ts
const conn = await db.connect();
await conn.query(`SELECT * FROM generate_series(1,100) t(v)`);   // 物化
for await (const batch of await conn.send(`...`)) { ... }          // 流式 chunk
// 预处理
const stmt = await conn.prepare(`SELECT v + ? FROM generate_series(0,10000) t(v)`);
await stmt.query(234);
```
- 支持 Arrow Table → JSON、导出 Parquet（`COPY ... TO` + `copyFileToBuffer`）。
- 查询顺序执行。

**限制（Limitations）**
- 默认**单线程**。
- 内存受限：WASM 上限 **4 GB**，浏览器可能更严。

**扩展（Extensions）**：Wasm 的扩展可用性有例外（部分官方扩展不可用），详见 Wasm extensions 文档。

---

## 7. 三级客户端（Tertiary Clients，无支持保证）

官方维护的三级客户端包括 **Julia、Swift、Dart**（由 DuckDB team 维护），其余由社区维护。完整列表：Common Lisp、Crystal、Dart、Elixir（Duckdbex / QuackDB）、Erlang、Haskell、**Julia**、Perl、PHP、PHP(PDO)、Pyodide、Raku、Ruby、Scala、Swift、Zig。

### 7.1 Julia（`DuckDB.jl`，DuckDB team）
- 安装：`Pkg.add("DuckDB")`。进程内、支持多线程（`JULIA_NUM_THREADS`）。
- 用法：`DBInterface.connect(DuckDB.DB, ":memory:")`、`DBInterface.execute`、`DBInterface.prepare`。
- 可 `DuckDB.register_data_frame(con, df, "my_df")` 注册 DataFrame 为视图（只读）。
- 支持 **Appender API** 高效写入；并发要求每任务独立连接。
- 注意：`PIVOT`、`IMPORT DATABASE` 等多语句需用 `DuckDB.query()`（返回物化结果）。

### 7.2 Swift（`duckdb-swift`，DuckDB team）
- `Database(store: .inMemory)` 或 `.file(at:)`；`database.connect()` 获连接。
- 异步：`try connection.query(...)` 后用 `result[i].cast(to: Int.self)` 转 Swift 原生类型，可包装为 TabularData `DataFrame`。

### 7.3 Dart（`dart_duckdb`，TigerEye 维护）
- `flutter pub add dart_duckdb`；`import 'package:dart_duckdb/dart_duckdb.dart'`。
- `duckdb.open(":memory:")` → `duckdb.connect(db)` → `connection.query(...).fetchAll()` → `dispose()`。
- 每连接自动管理独立后台 isolate，支持并发；Web 平台经 DuckDB WASM 支持（需在 `web/index.html` 配 importmap）。

### 7.4 其它常用一级客户端速览
- **Go**（`duckdb-go`，Primary）：经 `database/sql` 接口；`go get github.com/duckdb/duckdb-go/v2`；`sql.Open("duckdb","")`；支持 Appender（`NewAppenderFromConn`）。
- **Rust**（`duckdb-rs`，Primary）：基于 C API 的 ergonomic wrapper；`Connection::open_in_memory()`；`conn.execute` / `conn.prepare` + `query_map`；支持 Appender（`conn.appender("foo")`）。
- **Java / JDBC**（Primary）：Maven `org.duckdb:duckdb_jdbc`；`DriverManager.getConnection("jdbc:duckdb:")`（`jdbc:duckdb:/path` 持久、`?duckdb.read_only=true` 只读）；支持 Arrow import/export、流式结果（`jdbc_stream_results=true`）、Appender、Batch Writer；`DuckDBConnection#duplicate()` 高效建连接。
- **R**（Primary）：`install.packages("duckdb")`，DBI 接口；`dbplyr`/`duckplyr` 兼容 dplyr；`dbWriteTable` 写表、`duckdb_register` 注册虚拟表；`memory_limit` 可限内存（仅限 DuckDB 自身）。

### 7.5 二级（Secondary）
- **C#（.NET）**：https://duckdb.net （Giorgi 维护），NuGet 包。
- **ADBC（Arrow）**：Arrow Database Connectivity，Primary 功能级、Secondary 支持级。
- **C++**：见第 3.2 节（不稳定）。

---

## 8. 跨客户端一致性要点（写书重点）

1. **内存 vs 持久化**：所有客户端均支持 `:memory:`（或 NULL）内存库与文件路径持久库；持久库文件扩展名任意（`.db`/`.duckdb`/其它均可以）。
2. **只读模式**：多进程并发读同一文件需 `read_only`；CLI 用 `-readonly`/`.open --readonly`，Python `read_only=True`，Java `duckdb.read_only`，R `read_only=TRUE`。
3. **Prepared Statements 通用**：`?` / `$1` 占位符、`executemany`/`addBatch` 仅适合小量；**大量数据务必用 Appender 或 COPY**（文档多次强调）。
4. **Appender 是批量写入最快路径**，C/C++/Go/Rust/Java/Julia/Node 均提供；行式追加 + `end_row` + 刷新/关闭。
5. **Arrow 互操作**：Python/Java/Node/Wasm 均深度支持 Apache Arrow，便于与大数据生态 interchange。
6. **扩展性**：所有客户端 SQL 语法、磁盘格式一致，extensions 可移植（Wasm 例外）。
7. **版本相关（1.5.x）**：CLI 新增基于 Kalman 滤波的 **Query Completion ETA**；CLI 默认进度条与 duckbox 大数渲染；建议书中注明读者以实际 1.5.5 发布说明为准核对细节。

---

## 9. 关键 API 速查表

| 客户端 | 安装 | 连接（内存） | 执行查询 | 取结果 | 批量写入 |
|--------|------|--------------|----------|--------|----------|
| CLI | 下载可执行文件 | `duckdb`（无参） | 直接 SQL / 点命令 | 终端表格 | `.import` / `COPY` |
| Python | `pip install duckdb` | `duckdb.connect()` | `duckdb.sql()` / `con.execute()` | `.df()/.pl()/.arrow()/.fetchall()` | Appender / `COPY` / `read_*` |
| C | `libduckdb` | `duckdb_open(NULL,&db)` | `duckdb_query` | `duckdb_fetch_chunk` | `duckdb_appender_*` |
| C++ | `libduckdb` | `DuckDB db(nullptr)` | `con.Query()` | `result->ToString()` | `CreateVectorizedFunction`/Appender |
| Node | `@duckdb/node-api` | `DuckDBInstance.create(':memory:')` | `connection.run()` | `reader.getRows()` | `createAppender` |
| ODBC | driver + DM | DSN `Database=:memory:` | ODBC SQLExec | ODBC ResultSet | SQLBulkOperations/Appender |
| Wasm | `@duckdb/duckdb-wasm` | `AsyncDuckDB` + bundle | `conn.query()` | Arrow chunk | `COPY` |
| Go | `go get .../duckdb-go/v2` | `sql.Open("duckdb","")` | `db.Exec/Query` | `row.Scan` | `NewAppenderFromConn` |
| Rust | crates.io `duckdb` | `Connection::open_in_memory()` | `conn.execute` | `stmt.query_map` | `conn.appender` |
| Java | Maven `duckdb_jdbc` | `jdbc:duckdb:` | `stmt.executeQuery` | `ResultSet` | `DuckDBAppender`/Batch |
| R | `install.packages("duckdb")` | `dbConnect(duckdb())` | `dbGetQuery` | data.frame | `dbWriteTable` |
| Julia | `Pkg.add("DuckDB")` | `DBInterface.connect(DuckDB.DB,":memory:")` | `DBInterface.execute` | DataFrame | `DuckDB.Appender` |
| Swift | `duckdb-swift` | `Database(store:.inMemory)` | `connection.query` | `result[i].cast` | — |
| Dart | `flutter pub add dart_duckdb` | `duckdb.open(":memory:")` | `connection.query` | `fetchAll()` | — |
