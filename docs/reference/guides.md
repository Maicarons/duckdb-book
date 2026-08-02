# DuckDB 指南手册（Guides）结构化摘要

> 目标版本：DuckDB 1.5.5
> 来源：`duckdb-web-main/docs/current/guides/` 下全部 `.md` 文件
> 说明：已忽略 Jekyll frontmatter（`--- ... ---`）与 Liquid 标签（`{% ... %}`），仅抽取正文内容。英文术语（如 `row group`、`zonemap`、`ART index`、`ATTACH`、`EXPLAIN ANALYZE`）保留原样以便检索。

本摘要按以下 10 个主题组织：
1. performance（性能）
2. python（Python 集成）
3. database_integration（与其他数据库集成）
4. network_cloud_storage（网络与云存储）
5. file_formats（文件格式）
6. sql_editors / data_viewers（SQL 编辑器与数据查看器）
7. troubleshooting（故障排除）
8. snippets（实用 SQL 片段）
9. sql_features（功能特性）
10. meta（元信息查询）

---

## 1. Performance（性能指南）

### 1.1 概述：DuckDB 为什么快

DuckDB 通过精心选择的默认配置和"宽容（forgiving）"的架构，在大多数场景下能自动达到高性能。性能指南的目标是指导在特定负载下的调优。核心优势包括：

- **列式存储 + 向量化执行（vectorized execution）**：批量处理数据，而非逐行。
- **轻量压缩（lightweight compression）**：持久化数据库默认压缩；内存表默认不压缩（这是反直觉但重要的点，见下）。
- **并行（multi-core）执行**：基于 row group 并行。
- **Out-of-core 处理**：可处理大于内存的数据集（spill to disk）。

### 1.2 性能清单（My Workload Is Slow）

当负载变慢时，官方建议依次检查：

1. 内存是否充足？理想为 **每线程 1–4 GB**。
2. 系统是否在 overcommit 内存导致 swap？尝试**调低** `memory_limit`（默认 80% 总内存）：`SET memory_limit = '...';`。反直觉但有时有效。
3. 是否用快速磁盘？网络附加磁盘（云块存储）会拖慢写密集与超内存负载，云上建议用实例附加存储（NVMe SSD）。
4. 是否使用了索引/约束（主键、唯一等）？尽量禁用以提升加载与更新性能。
5. 是否用了正确的类型？如用 `TIMESTAMP` 编码时间。
6. 是否读取 Parquet？其 row group 是否在 **100k–1M**、单文件 **100 MB–10 GB**？
7. 查询计划是否合理？用 `EXPLAIN` 研究。
8. 负载是否真的在并行？用 `htop` 观察。
9. DuckDB 是否用了**过多线程**（如 HyperThreading 导致）？尝试 `SET threads = X;` 限制。

### 1.3 并行与 Row Group

- DuckDB 的并行以 **row group** 为单位（存储层按行分组存储）。DuckDB 数据库格式的默认 row group 大小为 **122,880 行**。
- 一条查询要跑到 *k* 个线程，需要扫描至少 *k* × 122,880 行。
- 可在 `ATTACH` 时指定 row group 大小：
  ```sql
  ATTACH '/tmp/somefile.db' AS db (ROW_GROUP_SIZE 16384);
  ```
- **线程过多**：HyperThreading 等场景下 DuckDB 可能启动过多线程导致变慢，用 `SET threads = X;` 手动限制（pragmas：`threads`）。
- 远程文件读取使用**同步 IO**：每个线程一次最多一个 HTTP 请求。若查询需发起大量小网络请求，可将 `threads` 设为 CPU 核数的约 **2–5 倍**以提升并行度。

### 1.4 超内存负载（Larger-than-Memory / Out-of-Core）

- 通过 **spill to disk** 支持：默认在持久化模式下创建 `⟨db⟩.tmp` 目录，内存模式下创建 `.tmp` 目录，可用 `temp_directory` 修改：
  ```sql
  SET temp_directory = '/path/to/temp_dir.tmp/';
  ```
- **Blocking operators（阻塞算子）** 需要缓冲全部输入：GROUP BY、JOIN、ORDER BY、`OVER ... (PARTITION BY ... ORDER BY ...)` 窗口函数。DuckDB 对上述全部支持超内存处理。
- **限制**：
  - 同一查询中多个 blocking operator 叠加，仍可能 OOM。
  - 部分聚合函数不支持落盘：`list()`、`string_agg()`。
  - 排序聚合（如 `ORDER BY` 子句的聚合）为 holistic，需全部输入，**可能 OOM**。
  - `PIVOT` 内部使用 `list()`，受同样限制。

### 1.5 `preserve_insertion_order` 调优

导入/导出远超内存的 Parquet/CSV 时可能 OOM：
```sql
SET preserve_insertion_order = false;
```
允许系统对无 `ORDER BY` 的结果重排序，降低内存占用。

### 1.6 持久化 vs 内存表（反直觉点）

- 默认：持久化数据库**启用压缩**，内存表**不启用压缩**。
- 因此磁盘表有时比内存表更快。TPC-H Q1 SF30 实测：

  | 数据库设置 | 命令 | 耗时 |
  |---|---|---|
  | 内存（未压缩） | `duckdb` | 4.22 s |
  | 内存（压缩） | `duckdb -cmd "ATTACH ':memory:' AS db (COMPRESS); USE db;"` | 0.55 s |
  | 持久化（压缩） | `duckdb tpch-sf30.db` | 0.56 s |

- 结论：压缩使查询约快 **8×**。

### 1.7 连接（Connection）最佳实践

- 复用同一连接最佳；频繁断开重连有开销。
- 单连接通常最好；也可用连接池。
- 多连接可并行部分操作，但通常非必需（DuckDB 已在单查询内尽力并行）。

### 1.8 Schema 设计

**类型（Types）**：
- 使用正确类型（`BIGINT`、`DATE`、`TIMESTAMP` 等）。用 `VARCHAR` 编码数值会更占空间且更慢。
- 内存受限时用小类型（`TINYINT`）可减少内存/磁盘占用。bitpacking 压缩使"小数值存大类型"磁盘不变大，但**处理时内存仍大**，故建列时用最受限类型。

实测（LDBC Comment `creationDate`，5.54 亿行）：
| 列类型 | 存储 | 查询耗时 |
|---|---|---|
| `DATETIME` | 3.3 GB | 0.9 s |
| `VARCHAR` | 5.2 GB | 3.9 s |

自连接实测（BIGINT vs VARCHAR 编码同一值）：BIGINT 1.2 s vs VARCHAR 2.1 s（约 **1.8×** 差距）。

**约束（Constraints）**：
- `UNIQUE`/`PRIMARY KEY`/`FOREIGN KEY` 保证数据完整性，但**损害加载性能**（需建索引+检查），且**几乎不提升查询性能**（DuckDB 不靠它们做 join/聚合）。
- 最佳实践：不为完整性以外的目的定义约束。加载主键实测（LDBC 5.54 亿行，`.csv.gz`）：
  | 操作 | 耗时 |
  |---|---|
  | 带主键加载 | 461.6 s |
  | 无主键加载 | 121.0 s |
  | 无主键加载后加主键 | 242.0 s |
- 最佳实践：批量加载避免主键；若必需，**加载后再加**。

### 1.9 索引（Indexing）

DuckDB 两类索引：**zonemap** 与 **ART index**。

**Zonemap（min-max index）**：
- 对所有 general-purpose 类型列自动创建。
- 过滤器（如 `WHERE col = 123`）可跳过 min-max 不含该值的 row group。
- **数据有序性**影响巨大：`DATETIME` 升序 vs 无序（同 LDBC 数据）：
  | 列类型 | 有序 | 存储 | 查询 |
  |---|---|---|---|
  | `DATETIME` | 是 | 1.3 GB | 0.6 s |
  | `DATETIME` | 否 | 3.3 GB | 0.9 s |
  有序使存储小 **2.5×**、查询快 **1.5×**。
- 实践：对用选择性过滤的列，**插入前预排序**；用 `INTEGER` 自增替代 `UUID` 做过滤列（有序 INTEGER 可跳过除目标外所有 row group）。

**ART（Adaptive Radix Tree）索引**：
- 隐式创建于 `PRIMARY KEY`/`FOREIGN KEY`/`UNIQUE` 约束；或显式 `CREATE INDEX`。
- 代价：约束检查 + 索引维护使变更变慢；**不影响 join/聚合/排序**性能。
- 仅**单列、无表达式**的 ART 索引可用于 index scan（等值/`IN`/动态过滤下推）。多列或表达式索引不符合：
  ```sql
  CREATE INDEX idx ON tbl (col1);              -- 可用于 index scan
  CREATE INDEX idx_multi ON tbl (col1, col2);  -- 不可
  CREATE INDEX idx_expr ON tbl (col1 + 1);     -- 不可
  ```
- index scan 默认阈值 `MAX(2048, 0.001 * table_cardinality)`，可用 `index_scan_percentage`/`index_scan_max_count` 配置，设为 0 关闭。用 `EXPLAIN ANALYZE` 验证。
- **内存注意**：索引缓冲尚未被 buffer manager 回收，可能占用大量内存；`DETACH`+`ATTACH` 可缓解（懒加载）；打开数据库不受影响（懒反序列化）。
- 最佳实践：仅在必需约束时用主键/外键/唯一；除非高度选择性查询且有足够内存否则不显式建索引；若建，在**批量加载之后**建。

### 1.10 文件格式对性能的影响

见第 5 节"file_formats"。要点：
- Parquet 优于直接查 CSV；TPC-H 在 Parquet 上比 DuckDB 原生库慢 **1.1–5.0×**。
- Parquet row group 理想 **100K–1M**；<5,000 行 group 使运行时间劣化 5–10×。
- 单 Parquet 文件理想 **100 MB–10 GB**；并行跨文件也有效（总 row group 数 ≥ 线程数）。
- Hive 分区提升 filter pushdown，尤其远程文件。
- CSV：`.csv.gz` 直接加载通常**比先解压再加载更快**（减少 IO）。大量小 CSV 可关闭 sniffer，用 `read_csv(..., auto_detect=false, ...)`。

### 1.11 Join 操作调优

- DuckDB 用基于代价的优化器（依赖统计估计基数）。
- **强制 join 顺序**：关闭 join order 优化器：
  ```sql
  SET disabled_optimizers = 'join_order,build_side_probe_side';
  -- 此时按 JOIN 书写顺序构建 left-deep join tree
  SET disabled_optimizers = '';
  ```
- 或用临时表拆分：
  ```sql
  CREATE OR REPLACE TEMPORARY TABLE t1 AS ...;
  CREATE OR REPLACE TEMPORARY TABLE t2 AS SELECT * FROM t1 ...;
  DROP TABLE IF EXISTS t1, t2;
  ```

### 1.12 Prepared Statements

- 同查询多次运行、仅参数不同：`PREPARE` 缓存解析/计划，提升小查询（<100ms）性能。
- DuckDB **不**以"快速并发执行大量小查询"为主要设计目标，而是优化大、低频查询。

### 1.13 远程文件读取

- 同步 IO → 若需大量小网络请求，增加 `threads` 到 2–5× CPU 核。
- **避免读不必要数据**：`SELECT` 只选需要的列（DuckDB 只下载所需列）；对远程 Parquet 应用过滤（filter pushdown）；按常用过滤列排序或分区。
- 用 `EXPLAIN ANALYZE` 查看远程请求数与传输数据量。
- **缓存**：1.3.0 起支持远程数据缓存（`duckdb_external_file_cache()`）。

### 1.14 环境（Environment）

- **CPU 架构**：官方支持 AMD64（x86_64）与 ARM64（AArch64）。其他（LoongArch、RISC-V）无性能保证。
- **内存**：
  - 最佳实践：**每线程 1–4 GB**。
  - 最低：每线程 125 MB（如 8 线程至少 1 GB）；受限环境用 `SET threads = 4;`。
  - 聚合密集：每线程 1–2 GB；join 密集：每线程 3–4 GB。
- **本地磁盘**：SSD/NVMe 最佳；HDD 支持但慢（尤其写）。
- **文件系统**：Linux 上 **XFS 最佳**（也良好支持 ext4）；Windows 用 NTFS，避免 FAT32。DuckDB 数据库自带 checksum，无需文件系统完整性检查。
- **网络附加磁盘**：AWS EBS 可；**避免**在 NAS（NFS/SMB/Samba）上以读写模式用 DuckDB 原生格式——慢且易错；读-only 可用；大数据存储建议用 **DuckLake** lakehouse 格式。
- **操作系统**：macOS/Windows/Linux 均可，建议最新稳定版；Linux 推荐 Ubuntu LTS。
- **glibc vs musl**：musl libc 构建性能**显著更低**（计算密集负载可能慢 >5×），性能负载用 glibc 发行版。
- **内存分配器**：jemalloc 默认平台可启用后台线程（`jemalloc` background threads）。

### 1.15 OOM 配置与排查

- 调参：
  ```sql
  SET threads = ⟨低于可用线程⟩;
  SET memory_limit = ⟨低于 80% 系统内存⟩;   -- 如 50–60%，因部分操作绕过 buffer manager
  SET preserve_insertion_order = false;
  ```
- 受限环境用更小类型（`TINYINT`）；避免索引（不 buffer-managed，占内存）。

### 1.16 巨型数据库（Huge Databases）

- 原生格式支持超大文件无实质限制（1% 用户用 ≥2 TB 文件，约 10 TB CSV）。
- 注意：对象存储单文件上限（S3 5 TB）；checkpoint 可能慢（TPC-H SF1000 加几行约 5 s）；Linux 大文件用 XFS；大数据存储考虑 **DuckLake**。

### 1.17 Benchmarks（基准）

- 数据集：TPC-H（tpch 扩展生成）、LDBC Social Network BI SF300 `Comment` 表（`.tar.zst`、`.parquet`）。
- 注意：这些是 microbenchmark，**非官方 TPC/LDBC 结果**；建议用最新版（含 preview）跑基准。

---

## 2. Python 集成

### 2.1 安装与执行

```batch
pip install duckdb
pip install duckdb --upgrade --pre   # 预览/夜版
```
执行 SQL：
```python
import duckdb
duckdb.sql("SELECT 42").show()          # 默认返回 relation
duckdb.sql("SELECT 42").fetchall()       # -> [(42,)]
duckdb.sql("SELECT 42").df()             # -> Pandas DataFrame
con = duckdb.connect("file.db")          # 持久化连接
con.sql("CREATE TABLE integers (i INTEGER)")
```

### 2.2 Pandas 集成

- 通过 **replacement scan**：DataFrame 在进程内按名可见，无需手动注册。
  ```python
  duckdb.sql("CREATE TABLE my_table AS SELECT * FROM my_df")
  duckdb.sql("INSERT INTO my_table SELECT * FROM my_df")
  duckdb.sql("INSERT INTO my_table BY NAME SELECT * FROM my_df")  # 按列名
  con.append("my_table", my_df)                 # 直接追加
  con.append("my_table", my_df, by_name=True)   # 按名列名匹配
  ```
- 导出：`results.df()`。
- SQL on Pandas：`duckdb.sql("SELECT * FROM my_df").df()`（replacement scan 机制）。

### 2.3 Apache Arrow 集成

- 导入：`CREATE TABLE ... AS SELECT * FROM my_arrow`（Arrow Table/Array 等）。
- 导出：
  ```python
  results = duckdb.sql("SELECT * FROM my_arrow_table").to_arrow_table()
  reader = duckdb.sql("SELECT * FROM my_arrow_table").to_arrow_reader(chunk_size)
  # 弃用：fetch_arrow_table / fetch_record_batch / fetch_arrow_reader
  ```
- Relational API 也可导出 Arrow；关系可延迟求值（lazy）。

### 2.4 Polars 集成

- 需 `pyarrow`：`pip install -U duckdb 'polars[pyarrow]'`。
- Polars → DuckDB：按名引用 Polars DataFrame（`duckdb.sql("SELECT * FROM df")`）。
- DuckDB → Polars：`.pl()`；`lazy=True` 返回 LazyFrame。

### 2.5 NumPy 集成

- 导入：按名引用 numpy 数组（replacement scan）。
- 导出：`my_arr = duckdb.sql("SELECT unnest([1,2,3]) AS x, 5.0 AS y").fetchnumpy()`。

### 2.6 PyTorch 集成

- 用 Arrow 流式：`con.execute(...).to_arrow_reader(batch_size=2)`，逐 batch 转 tensor。
- DuckDB 将 `WHERE label = 1` 过滤与列选择下推到 dataset scan，只转换所需行列。

### 2.7 多 Python 线程

- 同一进程内多 reader/writer：每个线程用 `.cursor()` 创建线程本地连接到同一文件（内存库也适用）。
- 示例：50 writer + 5 reader 线程并发插入/查询同一 DuckDB 文件。

### 2.8 Jupyter Notebooks

- 原生：`%load_ext sql` + `conn = duckdb.connect()` + `%sql conn --alias duckdb`。
- 经 SQLAlchemy（duckdb-engine）：`%sql duckdb:///:memory:`、`:default:`、`path/to/file.db`。
- 增强库：`jupysql`、`pandas`、`matplotlib`、`duckdb-engine`。配置 `%config SqlMagic.autopandas = True` 等。
- 可视化：`%sqlplot boxplot/histogram` 在 SQL 引擎内计算，避免全量加载到 Pandas，可绘超大数据集。
- httpfs：`INSTALL httpfs; LOAD httpfs;` 后可远程查 Parquet。
- 注意：原生连接不识别 Variables；SQLAlchemy 需 `%sql SET python_scan_all_frames=true` 使 Pandas 可查。

### 2.9 marimo Notebooks

- 响应式 notebook，序列化为纯 Python（`mo.sql(...)`），git 友好。
- 自定义连接：`conn = duckdb.connect("path")` 自动发现；SQL 单元格可引用本地 DataFrame；UI 元素（slider）参数化 SQL；lazy 运行时避免昂贵查询自动重算。

### 2.10 Relational API（Pandas）

```python
rel = con.from_df(input_df)
transformed = rel.filter('i >= 2').project('i, j, i*2 AS two_i').order('i DESC').limit(2)
output_df = transformed.df()
```
延迟求值，可链式 group/aggregate/distinct/join/union，也可直接写入表或 CSV。

### 2.11 fsspec 文件系统

- Python 专属：`duckdb.register_filesystem(filesystem('gcs'))` 可查 GCS 等 httpfs 不支持的 FS。
- 注意：这些是 Python 实现，性能可能不如 httpfs 的 C++ 实现，且可能为第三方 bug。

### 2.12 Ibis

- Python dataframe 库，DuckDB 为默认后端。`pip install 'ibis-framework[duckdb,examples]'`。
- 懒求值；`to_pandas()` 才真正取数（计算由 DuckDB 执行）。支持 `filter`/`select`/`mutate`/`group_by`/`aggregate`/`order_by`/`selectors` 等，可链式。

---

## 3. Database Integration（与其他数据库集成）

### 3.1 概述与导入优先级

导入数据推荐顺序：
1. 用 DuckDB scanner 扩展（MySQL / PostgreSQL / SQLite，以及通用 ODBC scanner）。
2. 源系统支持批量导出 → 导出为 Parquet/CSV，再用 DuckDB loader 加载。
3. 以上都不行 → 用 **appender**（C/C++/Go/Java/Rust API）。
- **避免**：循环逐行插入（即使 prepared statement），数据不小（<100k 行）时不要用循环插入。

### 3.2 PostgreSQL

```sql
INSTALL postgres; LOAD postgres;
-- 单表扫描
SELECT * FROM postgres_scan('host=localhost port=5432 dbname=mydb', 'public', 'mytable');
-- 附加整个库
ATTACH 'host=localhost port=5432 dbname=mydb' AS test (TYPE postgres);
SELECT * FROM test.tbl_name;
USE test; SHOW TABLES;
```
连接串为 PostgreSQL 风格 `{key}={value}`（host/port/user/password/dbname/passfile）。

### 3.3 SQLite

```sql
INSTALL sqlite; LOAD sqlite;
SELECT * FROM sqlite_scan('test.db', 'tbl_name');
ATTACH 'test.db' AS test (TYPE sqlite);
```

### 3.4 MySQL

```sql
INSTALL mysql; LOAD mysql;
ATTACH 'host=localhost user=root port=0 database=mysqlscanner' AS mysql_db (TYPE mysql, READ_ONLY);
USE mysql_db;
```
注意：连接串是 **PostgreSQL 风格**（非 MySQL 风格）`{key}={value}`（database/host/password/port/socket/user）。支持直接读写。

### 3.5 Amazon RDS / Aurora IAM 认证

- 用 `postgres` + `aws` 扩展，aws 扩展用 AWS credential chain 生成短期 IAM token 作为密码并自动刷新。
```sql
INSTALL postgres; INSTALL aws; LOAD postgres; LOAD aws;
CREATE SECRET aws_rds_secret (TYPE rds, PROVIDER credential_chain, CHAIN 'env;sso',
    REGION 'eu-west-1', RDS_USER 'postgres', RDS_HOST '...rds.amazonaws.com', RDS_PORT '5432');
CREATE SECRET pg_rds_secret (TYPE postgres, HOST '...', PORT '5432', USER 'postgres',
    DATABASE 'postgres', SSLMODE require, AWS_RDS_SECRET aws_rds_secret);
ATTACH '' AS rds_db (TYPE postgres, SECRET pg_rds_secret);
SELECT * FROM rds_db.public.tbl_name;
```

---

## 4. Network / Cloud Storage（网络与云存储）

### 4.1 概述

所有远程访问依赖 `httpfs` 扩展（`INSTALL httpfs; LOAD httpfs;`）。DuckDB 支持 S3、GCS、Azure（见各子页）、HTTP(S)、Cloudflare R2、Fastly、Tigris、S3 Express One、Iceberg on S3。

### 4.2 S3 导入/导出

```sql
CREATE SECRET (TYPE s3, KEY_ID '...', SECRET '...', REGION 'us-east-1');
-- 或用 credential_chain 自动获取
CREATE SECRET (TYPE s3, PROVIDER credential_chain);
-- 导入
SELECT * FROM read_parquet('s3://bucket/file');
-- 导出
COPY tbl TO 's3://bucket/file.parquet';
```
- 若 `Connection error for HTTP HEAD`：显式设置 `ENDPOINT 's3.⟨region⟩.amazonaws.com'`。

### 4.3 GCS（Google Cloud Storage）

- 经 S3 互操作 API：用 **HMAC keys** 建 `TYPE gcs` secret。
  ```sql
  CREATE SECRET (TYPE gcs, KEY_ID '...', SECRET '...');
  SELECT * FROM read_parquet('gs://bucket/file.parquet');
  COPY tbl TO 'gs://bucket/file.parquet';
  ```
- 附加数据库（只读）：`ATTACH 'gs://bucket/file.duckdb' AS db (READ_ONLY);`（GCS 上只能只读附加）。

### 4.4 HTTP(S) 直接读取

```sql
SELECT * FROM read_parquet('https://domain/path/file.parquet');
SELECT * FROM 'https://duckdb.org/data/holdings.parquet';  -- replacement scan 省略函数
```

### 4.5 附加远程 DuckDB 数据库

```sql
ATTACH 'https://blobs.duckdb.org/databases/stations.duckdb' AS stations_db;
SELECT count(*) FROM stations_db.stations;
```
- 仅**只读**；写回不支持。S3/GCS 兼容 API 同样支持。

### 4.6 S3 Express One

- 需指定 endpoint：`s3express-⟨az⟩.⟨region⟩.amazonaws.com`（如 `s3express-use1-az5.us-east-1.amazonaws.com`）。
- 最佳实践：EC2 实例与 bucket 同可用区。LDBC SF300 实测：仅加载 4.1 GB Parquet 3.5 s；建本地表 5.1 s。

### 4.7 S3 Iceberg

```sql
INSTALL httpfs; INSTALL iceberg; LOAD httpfs; LOAD iceberg;
CREATE SECRET (TYPE s3, ...);
SELECT * FROM iceberg_scan('s3://bucket/iceberg_table_folder/metadata/⟨id⟩.metadata.json');
```
- 必须直接指向 manifest（`metadata/⟨id⟩.metadata.json`），否则报 `version-hint.text` 找不到。

### 4.8 Cloudflare R2

```sql
CREATE SECRET (TYPE r2, KEY_ID '...', SECRET '...', ACCOUNT_ID '...');
SELECT * FROM read_parquet('r2://bucket/file');
```

### 4.9 Fastly Object Storage

```sql
CREATE SECRET my_secret (TYPE s3, KEY_ID '...', SECRET '...',
    URL_STYLE 'path', REGION 'us-east', ENDPOINT 'us-east.object.fastlystorage.app');
SELECT * FROM 's3://bucket/file.csv';
```

### 4.10 Tigris

```sql
CREATE SECRET my_secret (TYPE s3, KEY_ID 'tid_...', SECRET 'tsec_...',
    REGION 'auto', ENDPOINT 'fly.storage.tigris.dev');
SELECT * FROM 's3://bucket/file.csv';
```
- 单 endpoint 服务所有区域，`REGION` 仅用于签名设为 `auto`；Fly.io 上请求留本地网络。

### 4.11 远程性能要点（与第 1 节呼应）

- 同步 IO → 小请求多时增 `threads` 到 2–5× CPU。
- `SELECT` 只取所需列；filter 下推；Hive 分区；`EXPLAIN ANALYZE` 查看传输量；1.3.0+ 远程缓存。

---

## 5. File Formats（文件格式）

### 5.1 概述与推荐

DuckDB 支持 CSV、Parquet、JSON、Arrow、Excel（`.xlsx`，**不支持 `.xls`**）、DuckDB 原生库、文本/BLOB 直接读。详见各子页。

### 5.2 Parquet

- 导入：`SELECT * FROM read_parquet('input.parquet')` 或省略函数 `FROM 'input.parquet'`；`CREATE TABLE ... AS` / `INSERT INTO` / `COPY tbl FROM 'input.parquet' (FORMAT parquet)`。
- 动态改 schema（如加列）：用 `UNION ALL BY NAME` 技巧。
- 导出：`COPY tbl TO 'output.parquet' (FORMAT parquet)`；可带 `compression`、`row_group_size` 等选项。
- 直查：`read_parquet` 内并行，filter pushdown，只读所需列。
- **性能**（见 1.10）：Parquet 比 DuckDB 库慢 1.1–5.0×；row group 100K–1M 最佳；单文件 100 MB–10 GB 最佳；缺乏 hyperloglog 统计（join 顺序估计不如原生库，join 密集建议先加载）。

### 5.3 CSV

- 导入：`read_csv` 或 `FROM 'input.csv'`；`CREATE TABLE ... AS FROM read_csv(...)`（可用 FROM-first 语法省 `SELECT *`）；`COPY tbl FROM 'input.csv'`。
- 导出：`COPY tbl TO 'output.csv' (HEADER, DELIMITER ',')`。
- `.csv.gz` 直接加载通常快于先解压。大量小文件关 sniffer。

### 5.4 JSON

- 导入：`read_json`；`COPY tbl FROM 'input.json'`。
- 导出：`COPY tbl TO 'output.json'`（默认 NDJSON/JSON Lines）；`ARRAY` 选项写单数组。

### 5.5 Excel（`.xlsx`）

- 导入：`read_xlsx('f.xlsx')`；选项 `sheet`、`range`（如 `'A1:B2'`、`'A5:Z'`、`'1:100'`）、`stop_at_empty`、`header`、`empty_as_varchar`、`all_varchar`、`ignore_errors`。类型推断：TIMESTAMP/TIME/DATE/BOOLEAN 据 number format；空单元格默认 DOUBLE。
- 导出：需 `excel` 扩展：`INSTALL excel; LOAD excel;`；`COPY tbl TO 'output.xlsx' WITH (FORMAT xlsx, HEADER true, SHEET 'Sheet1')`。
- 类型转换：数值→DOUBLE；时间→Excel 序列号；TIMESTAMP_TZ/TIME_TZ 转 UTC（丢时区）；BOOLEAN→1/0；其余→VARCHAR。

### 5.6 直接读文本/BLOB

- `read_text`：读为 VARCHAR，schema 含 `filename`、`content`、`size`、`last_modified`；最大 3.9 GiB；支持 `/dev/stdin`、管道。
- `read_blob`：读为 BLOB，同 schema 同大小上限。
- 支持 Hive 分区 glob；支持 projection pushdown（只取 `size` 时不读内容）。

### 5.7 直接读 DuckDB 数据库

```sql
SELECT r_regionkey, r_name FROM read_duckdb('https://blobs.duckdb.org/data/tpch-sf10.db', table_name='region');
FROM read_duckdb('my-*.duckdb', table_name='numbers');  -- glob 多库
FROM read_duckdb('my-2.duckdb');                        -- 单表库可省 table_name
FROM 'my-2.duckdb';                                     -- .db/.duckdb 可省函数
```
- 限制：仅支持读表，**不支持视图**。

### 5.8 `file:` 协议

- 支持 `file:/some/path`、`file:///some/path`、`file://localhost/some/path`。
- **不支持** `file:some/relative/path`（相对）、`file://some/path`（双斜杠）。不支持远程（非 localhost）主机。

---

## 6. SQL Editors / Data Viewers（SQL 编辑器与数据查看器）

### 6.1 DBeaver（SQL IDE）

- 用 DuckDB **JDBC 连接器**（`org.duckdb:duckdb_jdbc`）查询 DuckDB 文件及 DuckDB 能访问的任何文件（如 Parquet）。
- 步骤：新建连接 → 搜 DuckDB → 填入 `.db` 路径或 `:memory:` → Test Connection 自动下载 JDBC 驱动（企业/防火墙环境先配 proxy）→ 写 SQL 执行。
- 替代：若未提示装驱动，从 Driver Manager 编辑 DuckDB 驱动 Libraries 下载。

### 6.2 Tableau（数据可视化）

- 两种版本：Desktop（嵌入式，类似 Python）；Online/Server（数据需在 server 或远程可访问处，因 DuckDB 是 in-process）。
- 推荐用 **DuckDB Taco connector**（`duckdb_jdbc.taco`，MotherDuck 提供），比 PostgreSQL dialect 更兼容（PG dialect 缺 `median`/`percentile`）。
- JDBC 驱动：下载 `duckdb_jdbc-⟨version⟩.jar` 放到对应 Drivers 目录（macOS `~/Library/Tableau/Drivers/`、Windows `C:\Program Files\Tableau\Drivers`、Linux `/opt/tableau/tableau_driver/jdbc`）；改驱动后需重启。
- 可用 PostgreSQL dialect 临时连接：`jdbc:duckdb:/path/db`，Dialect 选 PostgreSQL（功能缺失）。
- 建议先建 view 指向 Parquet 等，用全路径；驱动版本须与建库文件版本兼容。

### 6.3 YouPlot（CLI 绘图）

- Ruby CLI，终端绘图。`brew install youplot`。
- 把 DuckDB 查询输出到 stdout：`COPY (query) TO '/dev/stdout' WITH (FORMAT csv, HEADER)`，再管道给 `uplot bar -d, -H -t "..."`。
- 可结合 `/dev/stdin` 与 `curl`（如 GitHub events）做实时分析。

---

## 7. Troubleshooting（故障排除）

### 7.1 命令行已知问题（版本相关）

- **v1.5.2 附加 HTTPS 数据库失败**：`duckdb https://...` 报 `httpfs` autoloading `Schema with name main does not exist!`。绕过：前缀 `duckdb:` → `duckdb duckdb:https://...`。
- **v1.5.0 管道脚本不执行**（Linux/macOS）：`duckdb < test.sql` 不运行。绕过：加 `| cat`，或用 `-f test.sql`。

### 7.2 崩溃（Crashes）

- 类型：终止信号（SIGSEGV/SIGABRT，应提 issue）；Internal Error（如 `Attempted to access index 3 within vector of size 3`），之后进入受限模式 `FATAL Error: database has been invalidated...`；OOM（OS 杀进程）。
- 恢复：崩溃前有 WAL 文件 `⟨db⟩.wal`，新会话打开即 replay + checkpoint 恢复。
- 排查：升级到最新 stable/preview；搜索已有 issue；`PRAGMA disable_optimizer;` 判断是否优化器导致，再选择性关规则；用 CLI 纯 SQL 复现（排除客户端库）；换硬件（过热/超频）；拆解查询（如下载 S3 数据分步 join）。提交带最小可复现例的 issue。

### 7.3 OOM 错误

- 两类：`OutOfMemoryException`；Linux OOM reaper（`dmesg` 查 `Killed`）。
- 预防见 1.15（调 `threads`/`memory_limit`/`preserve_insertion_order`；小类型；避索引）。
- 多 blocking operator、特定聚合、`PIVOT` 易 OOM。

---

## 8. Snippets（实用 SQL 片段）

- **内存库持久化**：
  ```sql
  ATTACH 'my_database.db';
  COPY FROM DATABASE memory TO my_database;
  DETACH my_database;   -- 确保目标文件不存在
  ```
- **生成合成数据**：`range`/`generate_series`、hash 函数、`CROSS JOIN`；Python 用 Faker + `con.create_function(..., type="native", side_effects=True)`。
- **分析 Git 仓库**：用 4 字节分隔符（v1.2.0+ 支持，如 emoji 🍥）导出 `git log` 为 CSV 再 `read_csv(delim='🍥')`；`regexp_extract` 主题；`NATURAL ANTI JOIN` 去停用词；`num_commits.bar(0, 20000)` 终端条形图。
- **导入 Duckbox 表格**（CLI 默认输出格式）：用 `sed` 清理为 `│` 分隔，或 `shellfs` 社区扩展 + table macro `read_duckbox(path)`（注意安全：社区扩展，输入须净化）。
- **共享宏**：macro 可持久化并托管到 HTTPS 共享：
  ```sql
  ATTACH 'https://blobs.duckdb.org/data/pretty_print_integer_macro.duckdb' AS m;
  SELECT m.pretty_print_integer(42123);
  ```
  标量宏与 table 宏（`checksum` 示例用 `bit_xor(md5_number(COLUMNS(*)::VARCHAR))`）均可。
- **荷兰铁路数据集**：文档常用示例，`https://blobs.duckdb.org/nl-railway/services-YYYY-MM.csv.gz` 等下载链接（含 80 个月、逐年、逐月）。

---

## 9. SQL Features（功能特性）

- **AsOf Join**（时态模糊查找）：`holdings h ASOF JOIN prices p ON h.ticker = p.ticker AND h.when >= p.when`；可 `ASOF LEFT JOIN`；`USING (ticker, "when")`（末字段为 `>=`）。注意 `USING` 合并列，`when` 取左表，需显式列名看两表时间。
- **MERGE**（v1.4.0 引入，SCD Type 2）：单语句 INSERT/UPDATE/软 DELETE；`MERGE INTO target USING source ON ... WHEN MATCHED THEN UPDATE ... WHEN NOT MATCHED BY TARGET THEN INSERT ... WHEN NOT MATCHED BY SOURCE THEN UPDATE/DELETE ... RETURNING merge_action, *`。最佳实践：TARGET=主表，SOURCE=新数据；当前行 `end_date` 置 NULL 更快；需要时用事务包裹；用主键/代理键唯一；先 `RETURNING` 测试。
- **Full-Text Search**：`fts` 扩展；`PRAGMA create_fts_index('corpus','line_id','text_entry')`；`fts_main_corpus.match_bm25(line_id, 'butter')` 返回 BM25 分数（NULL 为无匹配）。**不自动更新**，需 `PRAGMA drop_fts_index` 重建。需唯一 id 列。
- **Timestamps（时区陷阱）**：`DATE` 到 `TIMESTAMPTZ` 的提升转换按**当前时区**午夜，导致 `WHERE t <= '2025-08-30'` 结果随时区变化（甚至 0 行）。建议：除需时区显示/分箱外用普通 `TIMESTAMP`（更快）。ICU 时区库性能不高，可建 calendar 表（~700K 行覆盖到 2100）join 提速，并用 `date_part(['year','month','day','hour'], ts)` 一次提取全部部分。避免 `BETWEEN`（闭区间），用显式半开区间 `begin <= x AND x < end`。
- **Graph Queries**：DuckPGQ 社区扩展（SQL/PGQ，SQL:2023）。`INSTALL duckpgq FROM community; LOAD duckpgq;`。`CREATE PROPERTY GRAPH ... VERTEX TABLES(...) EDGE TABLES(...)`；`GRAPH_TABLE(... MATCH (a:Person)-[k:Knows]->(b:Person) COLUMNS(...))`；路径 `ANY SHORTEST ... -[k:Knows]->{1,3}(b:Person)`；算法 `pagerank`/`local_clustering_coefficient`/`weakly_connected_component`。
  - **版本注意（重要）**：DuckPGQ **不在最新 1.5.x 发布中**，需用 **DuckDB v1.4.4**；且可能遇 `csr_cte does not exist` 已知问题。
- **`query` 与 `query_table` 函数**：动态 SQL，`query_table($1)` 接受表名常量，`query` 接受查询字符串常量；配合 `COLUMNS(*)` 写通用 SQL macro（如自定义 `my_summarize`、pandas 风格 `stack`/`UNPIVOT`）。

---

## 10. Meta（元信息查询）

- **DESCRIBE / DESC / SHOW**：看表 schema；`DESCRIBE SELECT ...` 看查询结果的 schema（丢 null/key 信息）；可作子查询 `CREATE TABLE ... AS SELECT * FROM (DESCRIBE tbl)`；可远端 `DESCRIBE TABLE 'https://...csv'`（需 httpfs）。
- **DuckDB Environment**：
  - `version()` / `PRAGMA version`（含 `library_version`、`source_id`）。
  - `PRAGMA platform`（如 `osx_arm64`、`windows_amd64`、`linux_arm64`）。
  - `duckdb_extensions()` 列扩展及状态。
  - 元表函数：`duckdb_columns()`、`duckdb_constraints()`、`duckdb_databases()`、`duckdb_dependencies()`、`duckdb_extensions()`、`duckdb_functions()`、`duckdb_indexes()`、`duckdb_keywords()`、`duckdb_optimizers()`、`duckdb_schemas()`、`duckdb_sequences()`、`duckdb_settings()`、`duckdb_tables()`、`duckdb_temporary_files()`、`duckdb_types()`、`duckdb_views()`。
- **EXPLAIN**：仅打印**物理计划**（不执行），显示估计基数（EC）；`PRAGMA explain_output = 'physical_only' | 'optimized_only' | 'all'` 控制输出。
- **EXPLAIN ANALYZE**：执行并剖析，显示每算子累计耗时、EC 与真实基数；多线程下各算子时间和 > 总时长；多文件读取含文件名；远程读取含请求数/传输量。
- **List Tables**：`SHOW TABLES`（当前 schema）；`SHOW ALL TABLES`（所有库/schema）；`SHOW TABLES FROM db` / `FROM db.s1`。另有 `information_schema`、`sqlite_master`、PostgreSQL 系统目录兼容视图。
- **Summarize**：`SUMMARIZE tbl` / `SUMMARIZE SELECT ...` 计算每列 min/max/approx_unique/avg/std/q25/q50/q75/count 及 NULL 百分比（分位数/百分位为近似值）；可作子查询；可远端 `SUMMARIZE TABLE 'https://...csv'`（需 httpfs）。

---

## 11. ODBC（附录）

- ODBC 是标准接口，但比原生驱动慢（额外抽象层；DuckDB 列式 vs ODBC 行式有低效）。
- 句柄：Environment(`SQL_HANDLE_ENV`)、Connection(`SQL_HANDLE_DBC`)、Statement(`SQL_HANDLE_STMT`)、Descriptor(`SQL_HANDLE_DESC`)。
- 连接：`SQLConnect`（DSN）或 `SQLDriverConnect`（连接串，可带 DuckDB 配置如 `access_mode=READ_ONLY`）。
- 错误处理：返回码 `SQL_SUCCESS`/`SQL_SUCCESS_WITH_INFO`/`SQL_ERROR`/`SQL_INVALID_HANDLE`/`SQL_NO_DATA`/`SQL_NEED_DATA`/`SQL_STILL_EXECUTING`；用 `SQLGetDiagRec` 取诊断。
- 缓冲区绑定：`SQLBindCol`/`SQLBindParameter`。C++ 示例含分配句柄→连接→执行→绑定→获取→释放。
- 安装需 unixODBC（`brew install unixodbc` / `apt-get install unixodbc-dev` 等），链接 `libduckdb_odbc`。

---

## 关键要点速览（Best Practices 汇总）

1. **类型正确**：用 `TIMESTAMP`/`BIGINT` 等，避免 VARCHAR 编码数值（join 慢 1.8×，聚合慢数倍）。
2. **少用约束/索引**：主键等仅用于完整性；批量加载后加主键；ART 索引只在高度选择性查询且有内存时建，且须单列。
3. **压缩与存储**：持久化库默认压缩反而常快于内存表；大负载用 NVMe/XFS，避免 NAS 读写。
4. **Parquet 优先**：row group 100K–1M，单文件 100 MB–10 GB，Hive 分区助力 filter pushdown。
5. **并行**：每线程 1–4 GB 内存；HyperThreading 过多线程时 `SET threads`；远程小请求多时 threads 提到 2–5× CPU。
6. **超内存**：spill to disk；避免多 blocking operator 叠加、`list()`/`string_agg()`、`PIVOT`、排序聚合；用 `preserve_insertion_order=false` 与降 `memory_limit` 缓解 OOM。
7. **剖析**：`EXPLAIN` 看计划、`EXPLAIN ANALYZE` 看耗时；避免 nested loop join，争取 hash join，pushdown filter，避免基数爆炸。
8. **连接复用**：同一连接/连接池，避免频繁断开。
9. **集成模式**：Postgres/SQLite/MySQL 用对应 scanner `ATTACH`；云用 `httpfs` + Secret（S3/GCS/R2/Iceberg/S3 Express One）；RDS 用 IAM token 自动刷新。
10. **版本注意**：MERGE 自 v1.4.0；远程缓存自 v1.3.0；CSV 4 字节分隔符自 v1.2.0；DuckPGQ 图查询**仅 v1.4.4 可用、不在 1.5.x**；v1.5.0 管道脚本、v1.5.2 HTTPS 附加各有已知坑（见第 7 节）。
