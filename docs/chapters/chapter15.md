# 第 15 章 配置与性能调优

DuckDB 在大多数场景下依靠精心选择的默认配置即可达到良好性能，但当数据规模、并发环境或硬件条件偏离典型负载时，理解并主动调整配置仍是工程落地的必要能力。本章系统梳理配置机制、内存与线程资源、性能最佳实践、执行计划分析方法，以及常见性能陷阱与排查手段，目标是在不臆造命令与参数的前提下，提供可直接套用的调优指引。

## 15.1 配置机制

DuckDB 的行为由一组配置项（configuration options）控制，共有四种设置途径。

| 方式 | 语法 / 说明 | 备注 |
|------|------------|------|
| **SET 语句** | `SET memory_limit = '10GB';`、`SET threads TO 1;` | 最常用；赋值类 PRAGMA 等价于 SET |
| **PRAGMA 语句** | `PRAGMA enable_progress_bar;` | 源自 SQLite 扩展；赋值类 PRAGMA 等价于 SET |
| **连接参数（connection parameters）** | 打开数据库时以参数传入（如 Python `duckdb.connect(configuration={'memory_limit':'10GB'})`） | 进程启动前生效；安全项 `allow_unsigned_extensions` 仅能在启动时开启 |
| **环境变量** | 文档未列出具体名称 | 主要通过前三种方式生效 |

SET 与 PRAGMA 是最常用的交互方式，二者在赋值时等价。连接参数用于进程启动前就必须确定的项（例如 `allow_unsigned_extensions` 只能在启动时开启）；环境变量在当前文档体系中并未列出具体名称，配置主要通过前三种方式落地。

```sql
SET memory_limit = '10GB';
SET threads TO 4;
PRAGMA enable_progress_bar;
```

任意一项配置若需还原为默认值，使用 RESET 语句：

```sql
RESET memory_limit;
```

查询当前生效值有两种手段。其一是 `current_setting()` 函数，按名称取单项：

```sql
SELECT current_setting('memory_limit') AS mem_limit;
```

其二是 `duckdb_settings()` 表函数，可列出全部配置项及其默认值、取值范围与当前值：

```sql
SELECT value FROM duckdb_settings() WHERE name = 'memory_limit';
SELECT * FROM duckdb_settings();
```

配置项按作用域分为 GLOBAL 与 LOCAL 两类。GLOBAL 配置对整个数据库实例生效，例如 `threads`、`memory_limit`、`checkpoint_threshold` 等；LOCAL 配置仅对当前会话或连接生效，例如 `schema`、`search_path`、`enable_profiling`、`enable_progress_bar`、`streaming_buffer_size` 等。在同一进程内服务多个连接时，LOCAL 项可为不同连接定制行为而不影响全局。

## 15.2 内存与线程配置

内存上限由 `memory_limit`（别名 `max_memory`）控制，默认值为物理内存的 80%，以字符串形式指定，例如 `'1GB'`、`'10GB'`。一个容易被忽视的事实是，该限制只约束 buffer manager（缓冲管理器）——多数查询的中间数据由它托管，但向量（vectors）、查询结果以及状态复杂的部分聚合函数（如 `list`、`mode`、`quantile`、`string_agg` 等）所使用的内存在 buffer manager 之外分配。因此实际占用可能高于设定值，不能把 `memory_limit` 当作硬性内存上限。在内存受限或容器环境中，可将该值降至 50%~60% 以预留缓冲。

```sql
SET memory_limit = '4GB';
```

并行度由 `threads`（别名 `worker_threads`）控制，默认等于 CPU 核数。在容器或多租户环境中，默认占满全部核会挤占其他负载，应显式限制；若需要确定性结果（并行浮点聚合可能引入约 1e-16 量级的微小差异，且集合语义不保证行序），则设为 1。

```sql
SET threads = 4;
```

当内存不足以容纳中间数据时，DuckDB 将数据 spill to disk（溢写到磁盘），溢出目录由 `temp_directory` 指定，默认位于库文件同名的 `.tmp` 目录（内存模式下为 `.tmp`），可用 `max_temp_directory_size` 限制其体积，默认值为可用磁盘的 90%。将溢出目录指向高速或大容量磁盘有助于提升大查询的稳定性。

```sql
SET temp_directory = '/path/to/temp_dir.tmp/';
SET max_temp_directory_size = '4GB';
```

持久化相关的自动检查点由 `checkpoint_threshold`（别名 `wal_autocheckpoint`）控制，默认值为 16 MiB——当预写日志（WAL）达到该体积时触发自动 checkpoint。写密集场景下可调大以减低 checkpoint 频率，例如设为 `'1GB'`。

```sql
SET checkpoint_threshold = '1GB';
```

存储层方面，`default_block_size` 默认 262144（256 kB），取值范围须为 2 的幂且介于 16384~262144 之间，仅在新建库文件时生效。`preserve_insertion_order` 默认开启，关闭后允许系统对无 `ORDER BY` 的结果重排，从而降低内存占用（详见 15.5）。

## 15.3 性能最佳实践

类型选择对性能影响显著。用 `VARCHAR` 编码本应以数值或时间表示的列，既浪费空间又拖慢计算。在 LDBC 社交网络数据集的 5.54 亿行 `creationDate` 列上，`DATETIME` 占用 3.3 GB、查询耗时 0.9 s，而 `VARCHAR` 占用 5.2 GB、耗时 3.9 s。自连接测试中，用 `BIGINT` 编码值的耗时为 1.2 s，用 `VARCHAR` 则为 2.1 s，差距约 1.8×；聚合场景下 `VARCHAR` 的劣势往往放大到数倍。原则是优先使用 `TIMESTAMP`、`BIGINT`、`DATE` 等恰当类型，内存受限时选用最受限的小类型（如 `TINYINT`），因为即便 bitpacking 压缩使磁盘占用不变，处理时仍需按完整类型占用内存。

```sql
-- 推荐：以 TIMESTAMP 存储时间，以 BIGINT 存储整数编码，避免 VARCHAR 编码数值
CREATE TABLE events (ts TIMESTAMP, user_id BIGINT, value DOUBLE);
```

主键、唯一、外键等约束（constraints）与索引（indexes）仅服务于数据完整性，几乎不提升查询性能。DuckDB 的 join 与聚合并不依赖它们来加速。约束检查与索引维护反而会拖慢写入：同一份 LDBC 5.54 亿行数据，带主键加载耗时 461.6 s，无主键加载仅需 121.0 s；若先无主键加载再补加主键，耗时为 242.0 s。因此批量加载应避免主键，确有完整性需要时应在加载完成后追加。ART 索引（Adaptive Radix Tree）隐式建于约束之上或显式 `CREATE INDEX` 创建，仅当单列、无表达式且查询高度选择性时才可能走 index scan（索引扫描），且索引缓冲尚未被 buffer manager 回收，可能占用可观内存。

压缩是另一个反直觉却关键的要点。持久化数据库默认启用压缩，而内存表默认不压缩。TPC-H Q1（SF30）实测显示：未压缩内存库耗时 4.22 s，压缩内存库 0.55 s，压缩持久化库 0.56 s——压缩使查询提速约 8×。因此在内存充足且追求性能时，使用压缩的持久化库往往比未压缩的内存表更优。

并行以 row group（行组）为单位，DuckDB 原生格式的默认 row group 大小为 122,880 行。一条查询要利用 k 个线程，至少需要扫描 k × 122,880 行。可在 `ATTACH` 时调整：

```sql
ATTACH '/tmp/somefile.db' AS db (ROW_GROUP_SIZE 16384);
```

内存规划上，理想状况是每线程分配 1–4 GB。聚合密集负载每线程 1–2 GB，join 密集则建议 3–4 GB。当 HyperThreading 等因素导致线程过多反而变慢时，应手动下调 `threads`。远程小文件请求密集时，由于同步 IO，可将 `threads` 设为 CPU 核数的 2–5 倍以提升并发。

文件格式方面，Parquet 普遍优于直接查询 CSV（TPC-H 在 Parquet 上比原生库慢 1.1~5.0×，但仍是首选外部格式）。理想的 Parquet row group 规模为 100K~1M 行，单文件 100 MB~10 GB；group 小于 5000 行会使运行时间劣化 5~10×。Hive 分区（Hive partitioning）能使 filter pushdown（又称 predicate pushdown，谓词下推/过滤器下推）跨越分区边界生效，在远程文件场景下尤为显著。

```sql
-- Hive 分区读取：分区列作为过滤条件下推，减少远程传输与扫描量
SELECT * FROM read_parquet('s3://bucket/data/dt=*/part-*.parquet');
```

## 15.4 执行计划分析

理解查询为何慢，离不开对执行计划的审视。`EXPLAIN` 仅打印物理计划（physical plan）而不实际执行，输出中给出估计基数（EC，estimated cardinality），用于判断优化器对数据规模的估计是否合理。

```sql
EXPLAIN
SELECT u.user_id, count(*)
FROM users u
JOIN events e ON u.user_id = e.user_id
GROUP BY u.user_id;
```

`EXPLAIN ANALYZE` 则会真正执行查询并逐算子统计累计耗时、估计基数与真实基数。在多线程下各算子时间之和会大于总时长；远程读取场景还会报告请求数与传输量，是定位网络瓶颈的直接依据。

```sql
EXPLAIN ANALYZE
SELECT u.user_id, count(*)
FROM users u
JOIN events e ON u.user_id = e.user_id
GROUP BY u.user_id;
```

分析时重点关注两类问题。其一是连接策略：应争取 hash join，避免 nested loop join（嵌套循环连接）。当统计信息缺失或估计严重偏差时优化器可能误选嵌套循环，此时可临时关闭相关优化器以强制连接顺序（仅调试用，生产应恢复）：

```sql
SET disabled_optimizers = 'join_order,build_side_probe_side';
-- 按 JOIN 书写顺序构建 left-deep join tree
SET disabled_optimizers = '';
```

其二是 cardinality explosion（基数爆炸）：多表连接或不当的笛卡尔积会使中间结果行数指数膨胀，即便单个算子看似高效，整体也会因数据量失控而极慢。通过对比 `EXPLAIN ANALYZE` 中的估计基数与真实基数，可快速识别估计失准的环节，辅以更精准的统计信息或重写查询来纠正。

## 15.5 常见性能陷阱与排查

超内存（larger-than-memory）负载依赖 spill to disk 支持，`GROUP BY`、`JOIN`、`ORDER BY` 以及带 `OVER (PARTITION BY ... ORDER BY ...)` 的窗口函数均可在内存不足时落盘。但仍有若干情形会突破这一机制而引发 OOM（内存溢出）：

- 同一查询中多个 blocking operator（阻塞算子）叠加，各自需要缓冲全部输入，内存峰值叠加；
- 部分聚合函数不支持落盘，典型如 `list()` 与 `string_agg()`；
- 排序聚合（在 `ORDER BY` 子句中做聚合）属于 holistic 算子，需容纳全部输入；
- `PIVOT` 内部使用 `list()`，受同样的限制。

缓解 OOM 的常用手段是关闭 `preserve_insertion_order` 以降低内存占用，并适度下调 `memory_limit`（因为部分操作绕过 buffer manager，留出余量反而更稳）：

```sql
SET preserve_insertion_order = false;
SET memory_limit = '50%';
SET threads = 4;
```

除性能陷阱外，命令行工具存在两个版本相关的已知坑。v1.5.0 在 Linux/macOS 下以管道方式执行的脚本（如 `duckdb < test.sql`）不会运行，绕过方法是改用 `-f test.sql` 或将输出管道到 `cat`：

```bash
duckdb -f test.sql
duckdb < test.sql | cat
```

v1.5.2 中直接以命令行附加 HTTPS 数据库会失败（httpfs 自动加载时报告 `Schema with name main does not exist!`），解决方式是在 URL 前加 `duckdb:` 前缀：

```bash
duckdb duckdb:https://blobs.duckdb.org/databases/stations.duckdb
```

排查 OOM 时还需区分两类错误：DuckDB 抛出的 `OutOfMemoryException`，以及 Linux OOM reaper 直接杀死进程（可用 `dmesg` 查 `Killed`）。崩溃前若存在 WAL 文件，新会话打开即自动重放并 checkpoint 恢复，无需人工干预。

## 15.6 本章小结

本章梳理了 DuckDB 的配置与性能调优要点。配置上，SET/PRAGMA、连接参数与环境变量四途并用，RESET 还原默认值，`current_setting()` 与 `duckdb_settings()` 用于查询，GLOBAL 与 LOCAL 区分实例级与会话级作用域。内存与线程方面，`memory_limit` 仅约束 buffer manager、实际可超，`threads` 默认占满核数需在容器与多租户场景中限制，`temp_directory` 与 `max_temp_directory_size` 管控 spill to disk 落盘，`checkpoint_threshold` 默认 16 MiB。性能实践上，恰当类型（如 `TIMESTAMP`、`BIGINT`）远优于 `VARCHAR`，约束与索引只保完整性、应在批量加载后追加，压缩持久化库常比未压缩内存表快约 8×，并行以 row group（122,880 行）为单位、每线程规划 1–4 GB，Parquet 宜采用 100K~1M 的 row group 与 100 MB~10 GB 单文件并借 Hive 分区助 filter pushdown。分析执行计划应善用 `EXPLAIN` 与 `EXPLAIN ANALYZE`，规避 nested loop join 与 cardinality explosion。面对 OOM 风险，须识别多 blocking operator 叠加、`list()`/`string_agg()`、排序聚合与 `PIVOT` 等不受落盘保护的场景，并以 `preserve_insertion_order=false` 与下调 `memory_limit` 缓解；v1.5.0 与 v1.5.2 的命令行已知坑亦需掌握对应绕过方式。
