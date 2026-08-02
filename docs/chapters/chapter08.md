# 第 08 章 数据导出与持久化

DuckDB 作为进程内（in-process）分析型数据库，没有独立运行的服务进程，一切表、索引与数据都寄居于单一的数据库文件之中。掌握"如何把内存中的查询结果写成外部文件"以及"如何让数据库文件本身可靠地落盘、并能在多库之间挂载与迁移"，是日常工程里绕不开的两类操作。前者依赖 `COPY ... TO` 这条贯穿 CSV、Parquet、JSON 的导出主路径；后者则涉及持久化文件、ATTACH 挂载、WAL（Write-Ahead Log，预写日志）与 CHECKPOINT 的协作，以及空间回收、全库迁移等运维关切。本章逐一展开这些主题，并澄清一个从 PostgreSQL 迁移过来的用户经常踩中的认知误区。

## 8.1 COPY … TO：把数据写出到文件

`COPY ... TO` 是 DuckDB 把表或查询结果导出为外部文件的核心语句。它的源可以是表名，也可以是一段用括号包裹的查询。目标格式由扩展名推断，也可经 `FORMAT` 显式指定，支持 `csv`、`parquet`、`json`、`blob` 四种。

```sql
-- 直接导出整张表
COPY lineitem TO 'lineitem.csv';

-- 导出查询结果（用括号包裹的 SELECT）
COPY (SELECT l_orderkey, l_comment FROM lineitem) TO 'lineitem_part.parquet' (FORMAT parquet);

-- 仅导出部分列
COPY lineitem(l_orderkey) TO 'orderkey.tbl' (DELIMITER '|');
```

`COPY ... TO` 的通用选项包含 `FORMAT`、`USE_TMP_FILE`、`PARTITION_BY`、`PER_THREAD_OUTPUT`、`FILE_SIZE_BYTES`、`FILENAME_PATTERN`、`RETURN_FILES`、`RETURN_STATS`、`PRESERVE_ORDER` 等。其中 `USE_TMP_FILE` 默认开启，会先写入临时文件再改名，避免写出过程中断导致文件损坏。

### 8.1.1 CSV 写出与压缩

CSV 写出沿用读取端对应的选项：`DELIM`/`SEP`、`QUOTE`、`ESCAPE`、`HEADER`、`DATEFORMAT`、`TIMESTAMPFORMAT`、`NULLSTR`、`NEW_LINE` 等。压缩通过 `COMPRESSION` 控制，取值为 `none`、`gzip`、`zstd`。

```sql
COPY lineitem TO 'lineitem.csv' (HEADER, DELIMITER '|');
COPY lineitem TO 'lineitem.csv.gz' (FORMAT csv, COMPRESSION gzip);
COPY category TO 'categories.csv' (HEADER, COMPRESSION zstd);
```

### 8.1.2 Parquet 写出、自定义元数据与压缩

Parquet 是列式压缩格式，导出时可用丰富的写入选项：`COMPRESSION`（uncompressed/snappy/gzip/zstd/brotli/lz4/lz4_raw，默认 snappy）、`COMPRESSION_LEVEL`（zstd 取 1~22）、`ROW_GROUP_SIZE`（row group 最小行数，默认 122,880，下限为向量大小 2,048）、`ROW_GROUPS_PER_FILE`、`PARQUET_VERSION`（V1/V2）、`FIELD_IDS`、`WRITE_BLOOM_FILTER` 等。

```sql
COPY tbl TO 'result-zstd.parquet' (FORMAT parquet, COMPRESSION zstd);
COPY tbl TO 'result-v2.parquet'  (FORMAT parquet, PARQUET_VERSION 'V2');
COPY (FROM generate_series(100_000)) TO 'rg.parquet'
     (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 100_000);
```

`KV_METADATA {key: 'value'}` 允许往 Parquet 文件的键值元数据区写入自定义信息，便于在文件之外携带来源、作者、版本等附注：

```sql
COPY (SELECT 42 AS i) TO 'file.parquet'
     (FORMAT parquet, KV_METADATA {'author': 'duckdb', 'phase': 'export'});
```

写完后可用 `parquet_kv_metadata('file.parquet')` 把这些信息读回。

### 8.1.3 JSON 写出

JSON 写出默认生成 NDJSON（每行一个 JSON 对象）；置 `ARRAY true` 则写出为单个 JSON 数组。

```sql
COPY (SELECT * FROM range(5) r(i)) TO 'numbers.json' (ARRAY true);
COPY (SELECT 42 AS a, 'hello' AS b) TO 'query.ndjson' (FORMAT json);
```

### 8.1.4 分区写出 PARTITION_BY

`PARTITION_BY` 把数据按指定列写成 Hive 分区目录（`key=value` 形式），目标位置是根目录名而非单个文件。它不能接受表达式，需要派生列时改用子查询。

```sql
COPY orders TO 'orders' (FORMAT parquet, PARTITION_BY (year, month));

COPY (SELECT *, year(timestamp) AS year, month(timestamp) AS month FROM services)
TO 'test' (PARTITION_BY (year, month));
```

每个线程会对每个分区目录写一个文件（如 `data_0.parquet`）。可用 `FILENAME_PATTERN` 自定义文件名模式，支持 `{i}`（序号）与 `{uuid}`（128 位 UUID）。分区并非越细越好——每分区至少约 100 MB 数据才能摊薄目录与文件管理开销。

### 8.1.5 PER_THREAD_OUTPUT 与统计返回

`PER_THREAD_OUTPUT` 让每个执行线程各自写出一个文件，在下游不在乎文件数量、只关心总吞吐时显著提升并行性能；常与 `FILE_SIZE_BYTES` 配合，在单文件超过阈值时切割出新文件。

```sql
COPY (SELECT * FROM lineitem) TO 'parts' (FORMAT parquet, PER_THREAD_OUTPUT);
COPY (SELECT * FROM big) TO 'parts' (FORMAT parquet, PER_THREAD_OUTPUT, FILE_SIZE_BYTES '1GB');
```

`RETURN_FILES` 返回本次写出的文件清单，`RETURN_STATS` 额外返回每列的统计信息，便于在导出后立刻核对产物：

```sql
COPY (SELECT l_orderkey, l_comment FROM lineitem) TO 'lineitem_part.parquet' (RETURN_STATS);
```

### 8.1.6 关键限制：COPY 不做表到表复制

`COPY` 在 `FROM` 一侧读文件、`TO` 一侧写文件，两端都是文件系统。**它不能在两张表之间直接复制数据**。若要把一张表的内容搬到另一张表，应使用 `INSERT INTO tbl2 FROM tbl1;`。下一节的 `COPY FROM DATABASE ... TO` 看似"库间复制"，针对的也是整个数据库文件的 schema 与数据，而非单表对单表。

## 8.2 持久化数据库文件与 ATTACH

DuckDB 的数据库是一个单文件，扩展名习惯用 `.duckdb`、`.db` 或 `.ddb`。进程内引擎在打开这个文件后，所有建表、写入、索引都落在该文件内。需要留意的是，默认连接的是一个纯内存数据库（`memory`），关闭连接即丢失；要让数据持久化，必须在连接时直接指向一个文件——例如在 CLI 里执行 `duckdb mydata.duckdb`，或在 Python 里调用 `duckdb.connect('mydata.duckdb')`。

### 8.2.1 ATTACH 多库挂载

已连接到某个库时，可用 `ATTACH` 把更多数据库文件挂载进同一会话，形成多库并存的工作环境：

```sql
ATTACH 'file.db';
ATTACH 'file.db' AS file_db;
ATTACH 'file.db' (READ_ONLY);
ATTACH 'sqlite_file.db' AS sqlite_db (TYPE sqlite);
ATTACH IF NOT EXISTS 'file.db' AS file_db;
ATTACH OR REPLACE 'file2.db' AS file_db;
```

挂载后通过 `catalog.schema.name` 三级限定访问对象，例如 `file_db.main.t`。用 `USE` 切换默认库或 schema，或用 `SET search_path = 'db1, db2'` 调整解析顺序。卸载则用 `DETACH file;`。

`ATTACH` 的常用选项包括：`READ_ONLY`/`READ_WRITE`、`TYPE`（DUCKDB/SQLITE/MySQL/PostgreSQL）、`BLOCK_SIZE`（取 2 的幂，范围 16,384~262,144）、`ENCRYPTION_KEY` 与 `ENCRYPTION_CIPHER`（默认 GCM 模式的 AES-256）、`RECOVERY_MODE`（如 `no_wal_writes`）。其中远程的 HTTP/S3 路径默认只读。

一个容易忽视的事实：附加定义只存活于当前会话，不会随数据库文件持久化；每次重连都需要重新执行 `ATTACH`。

### 8.2.2 storage_compatibility_version 与存储格式版本

DuckDB 的磁盘存储格式会随版本演进。`storage_compatibility_version` 是一项会话级设置，决定创建或附加数据库时采用的存储格式版本——它与 `ATTACH` 的 `STORAGE_VERSION` 选项同源（自 v1.2.0 起可显式指定，取值如 `'v1.2.0'` 或 `'latest'`）。把版本压低，可以让由新版 DuckDB 写出的文件被旧版引擎读取，换取向后兼容。

```sql
-- 会话级：后续新建/附加的库采用该存储格式版本
SET storage_compatibility_version = 'v1.2.0';

-- 或在挂载时显式声明
ATTACH 'legacy.db' AS legacy (STORAGE_VERSION 'v1.2.0');
```

加密功能隐含要求存储版本不低于 v1.4.0，因此一旦启用 `ENCRYPTION_KEY`，该设置会被自动抬高。

## 8.3 Checkpoint、WAL 与空间回收

理解 DuckDB 的磁盘布局，是避免"删了数据文件却没变小"这类困惑的前提。

### 8.3.1 WAL 与 Checkpoint 机制

写入操作先进入 WAL（Write-Ahead Log，预写日志），再由 CHECKPOINT 把 WAL 的内容合并进主数据文件。系统按配置 `wal_autocheckpoint` 自动触发 checkpoint，其默认阈值为 16 MiB——WAL 累积到这一体量就会自动落盘。也可手动执行：

```sql
CHECKPOINT;
CHECKPOINT file_db;
FORCE CHECKPOINT;   -- v1.4 起：等待获取 checkpoint 锁再执行，旧版会中止进行中的事务
```

默认情况下，若有正在运行的事务，手动 `CHECKPOINT` 会失败；`FORCE CHECKPOINT`（自 v1.4.0 引入）改为排队等待锁释放。自 v1.4.0 起，内存表也支持 checkpoint，既能压缩内存占用，也能回收已删除行的空间。

### 8.3.2 关键误区：VACUUM 不回收空间

这是从 PostgreSQL 转来的用户最常误解的一点。在 DuckDB 中，`DELETE` 与 `UPDATE` 只把旧行**标记为删除（marked as deleted）**，并不会立即归还磁盘空间。真正能回收这部分空间的手段是 CHECKPOINT——它会合并相邻 row group 中删除率约 25% 的数据，从而部分腾出空间。

`VACUUM` 在 DuckDB 里主要是为兼容 PostgreSQL 而保留的语句，语义与其在 PostgreSQL 中截然不同：

```sql
VACUUM;                      -- 空操作（No-op）
VACUUM my_table(my_column);  -- 重建该列的 distinct 统计，而非回收空间
VACUUM FULL;                 -- 不支持，报 "Not implemented Error"
```

`VACUUM` **不回收任何磁盘空间**，默认还会跳过带 ART 索引（Adaptive Radix Tree，自适应基数树索引）的表。想要彻底回收被删除数据占据的空间，可靠路径只有两条：一是 `CHECKPOINT`（部分回收），二是用 `COPY FROM DATABASE ... TO` 把数据重建到一个全新的库文件（完整回收）。`DROP TABLE` 同理——它释放内存，但磁盘空间往往仅被标记为 `free` 块，需借助 CHECKPOINT 或重建才能实际缩容。

## 8.4 数据库迁移

迁移整个 DuckDB 数据库时，最稳妥的方式是 `COPY FROM DATABASE ... TO`：先后挂载源库与目标库，再执行整库复制。

```sql
ATTACH 'db1.db' AS db1;
ATTACH 'db2.db' AS db2;
COPY FROM DATABASE db1 TO db2;            -- 含 schema、约束、索引、序列、宏与数据
COPY FROM DATABASE db1 TO db2 (SCHEMA);   -- 仅复制 schema，不含数据
```

整库复制会保留表结构之外的约束、索引、序列与宏，比手工逐表重建更完整。另一种目录形式的方案是 `EXPORT DATABASE 'target'`（生成 `schema.sql` + `load.sql` + 数据文件）配合 `IMPORT DATABASE 'source'`，适合需要把数据库转存为可审阅文本的场景。

跨版本迁移时还须留意扩展的兼容性：扩展二进制严格绑定具体的 DuckDB 版本与平台，升级引擎后旧扩展往往无法加载，必须重装匹配版本。重装可用 `FORCE INSTALL` 强制覆盖，或用 `UPDATE EXTENSIONS` 让其按 ETag 条件请求、仅对确有变更的扩展执行 `FORCE INSTALL`：

```sql
FORCE INSTALL httpfs;
UPDATE EXTENSIONS;                 -- 更新全部
UPDATE EXTENSIONS (name_a, name_b);-- 更新指定
```

需要提醒的是，扩展在运行时不可热重载，更新后须重启进程方能生效。

## 8.5 本章小结

- `COPY ... TO` 同时承担 CSV、Parquet、JSON 的文件导出，源可以是表或括号包裹的查询；`COMPRESSION` 控制压缩算法，`PARTITION_BY` 写出 Hive 分区目录，`PER_THREAD_OUTPUT` 提升并行吞吐，`RETURN_STATS`/`RETURN_FILES` 回传统计与清单，`KV_METADATA` 写入自定义键值元数据。
- `COPY` 两端都是文件系统，不能在两张表之间直接复制；表到表应改用 `INSERT INTO tbl2 FROM tbl1`。
- 持久化依赖单文件数据库（`.duckdb`/`.db`/`.ddb`），默认连接为内存库，必须连到文件才会落盘；`ATTACH` 挂载多库，经 `catalog.schema.name` 限定访问，`storage_compatibility_version` 与 `ATTACH` 的 `STORAGE_VERSION` 共同决定磁盘格式版本以换取兼容。
- 写入先入 WAL，由 CHECKPOINT 合并进主文件，`wal_autocheckpoint` 默认 16 MiB 自动触发；`DELETE`/`UPDATE` 仅标记删除，空间回收靠 CHECKPOINT 或整库重建，而 `VACUUM` 不回收空间——这一点与 PostgreSQL 语义不同。
- 全库迁移用 `COPY FROM DATABASE ... TO`（或 `EXPORT/IMPORT DATABASE`）；跨 DuckDB 版本时须以 `FORCE INSTALL` / `UPDATE EXTENSIONS` 重装匹配版本的扩展。
