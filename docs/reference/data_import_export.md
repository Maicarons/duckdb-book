# DuckDB 数据导入与导出（CSV / Parquet / JSON / 多文件 / 分区数据集）

> 基于 DuckDB 1.5.5 官方文档（`docs/current/data/`）整理。
> 说明：文档中的 frontmatter（`--- ... ---`）与 Liquid 标签（`{% ... %}`）已忽略，仅保留正文内容。英文技术术语（如 `auto_detect`、`union_by_name`、`hive_partitioning`、`row group` 等）保持原样以便对照。

---

## 1. 概述（Overview）——"直接读取文件" 的哲学

DuckDB 的核心设计理念之一是：**可以像查询数据库表一样直接查询文件**。用户无需先把数据 `COPY` 或 `IMPORT` 进数据库，而是直接用 SQL 读取磁盘（或远程、或压缩）上的文件。

最常用的"魔法"语法是根据文件扩展名自动识别格式：

```sql
SELECT * FROM 'test.csv';      -- 自动识别为 CSV
SELECT * FROM 'test.parquet';  -- 自动识别为 Parquet
SELECT * FROM 'test.json';     -- 自动识别为 JSON
```

若文件扩展名不标准（例如 Parquet 文件叫 `test.parq`），则必须显式使用读取函数：

```sql
SELECT * FROM read_parquet('test.parq');
```

### 三种加载途径

| 途径 | 适用场景 | 示例 |
|--|--|--|
| **直接文件名查询**（自动识别） | 快速探索、即席查询 | `SELECT * FROM 'flights.csv';` |
| **读取函数**（`read_csv` / `read_parquet` / `read_json`） | 需要传选项、类型覆盖、多文件 | `SELECT * FROM read_csv('f.csv', header=false);` |
| **`COPY` 语句** | 把数据装入已存在/新建的表 | `COPY tbl FROM 'test.csv';` |

### 相对路径与 `file_search_path`

- 相对路径默认相对于"工作目录"（working directory）。
- 可通过配置项 `file_search_path` 指定相对路径扩展到的"根目录"。

### 创建持久表（CTAS）

```sql
CREATE TABLE test AS SELECT * FROM 'test.parquet';
-- 也可省略 SELECT *，使用 FROM-first 语法：
CREATE TABLE ontime AS FROM 'flights.csv';
```

### 压缩文件

DuckDB 能直接读取压缩后的文件（如 gzip）。例如：

```sql
SELECT * FROM 'test.csv.gz';
```

### 虚拟列 `filename`（v1.3.0 重要特性）

自 **DuckDB v1.3.0** 起，CSV、JSON、Parquet 读取器会自动提供 `filename` 虚拟列，标明每行数据来自哪个文件，**无需显式配置**：

```sql
COPY (FROM (VALUES (42), (43)) t(x)) TO 'test.parquet';
SELECT *, filename FROM 'test.parquet';
```

> 早期版本需用 `filename = true` 显式开启；v1.3.0 后该选项仅为兼容性保留。

### 支持的数据源（Data Sources）

除 CSV/Parquet/JSON 外，DuckDB 还能直连：S3 兼容对象存储、Azure Blob、Cloudflare R2、HTTPFS、Delta Lake、DuckLake、Excel、Iceberg、Lance、MySQL、PostgreSQL、SQLite、Blob/Text 文件、Vortex 等（多为扩展）。

### 其他加载方式

- `INSERT` 语句：适合少量数据/原型，批量加载时每行开销大，**不推荐用于大批量**。
- `Appender`：C/C++/Go/Java/Rust 等客户端 API 提供的批量写入类（详见 `appender.md`），默认每 204,800 行提交一次。

---

## 2. CSV 读取（CSV Import）

CSV 是最常见也最容易出问题的数据格式（无 schema、方言多样、常常损坏）。DuckDB 用 **CSV sniffer（嗅探器）** 自动推断配置，绝大多数情况下能直接成功。

### 2.1 基础示例

```sql
-- 自动推断
SELECT * FROM 'flights.csv';

-- 手动传参
SELECT * FROM read_csv('flights.csv',
    delim = '|',
    header = true,
    columns = {
        'FlightDate': 'DATE',
        'UniqueCarrier': 'VARCHAR',
        'OriginCityName': 'VARCHAR',
        'DestCityName': 'VARCHAR'
    });

-- 从 stdin 读
cat flights.csv | duckdb -c "SELECT * FROM read_csv('/dev/stdin')"

-- 读入已存在的表
COPY ontime FROM 'flights.csv';

-- 读入并按推断 schema 建表
CREATE TABLE ontime AS FROM 'flights.csv';
```

### 2.2 完整参数表（`read_csv` / `COPY` 可用）

> 说明：多数参数在 `read_csv` 函数中可用；标注"仅 COPY"的别名只能在 `COPY ... (...)` 语法中使用。`COPY` 语句本身始终使用 `utf-8` 编码（无 `encoding` 选项）。

| 参数 | 类型 | 默认值 | 含义 |
|--|--|--|--|
| `all_varchar` | BOOL | `false` | 跳过类型推断，所有列当作 `VARCHAR`。仅 `read_csv` 支持。 |
| `allow_quoted_nulls` | BOOL | `true` | 允许把带引号的 `NULL` 字符串转为真正的 `NULL`。 |
| `auto_detect` | BOOL | `true` | 是否启用自动检测（分隔符/引号/转义/表头/类型）。 |
| `auto_type_candidates` | TYPE[] | 见下 | 嗅探器做类型检测时考虑的候选类型（默认总包含 `VARCHAR` 兜底）。 |
| `buffer_size` | BIGINT | `16 * max_line_size` | 读取文件用的缓冲区字节数，须至少容纳 4 行，对性能影响显著。 |
| `columns` | STRUCT | (空) | 列名+类型 struct（如 `{'col1':'INTEGER'}`）。指定后关闭 schema 自动检测。 |
| `comment` | VARCHAR | (空) | 注释起始字符；以该字符开头的行（前导空白可有可无）整行忽略；其余行解析到该字符为止。 |
| `compression` | VARCHAR | `auto` | 压缩方式：`none` / `gzip` / `zstd`（由扩展名自动探测，如 `t.csv.gz`→gzip）。 |
| `dateformat` | VARCHAR | (空) | 解析/写入日期的格式串。 |
| `date_format` | VARCHAR | (空) | `dateformat` 别名，**仅 COPY**。 |
| `decimal_separator` | VARCHAR | `.` | 数值的小数点分隔符。 |
| `delim` | VARCHAR | `,` | 列分隔符，可为最多 4 字节（如 `🦆`）。别名 `sep`。 |
| `delimiter` | VARCHAR | `,` | `delim` 别名，**仅 COPY**。 |
| `escape` | VARCHAR | `"` | 用于在引号值内转义 `quote` 字符的字符串。 |
| `encoding` | VARCHAR | `utf-8` | 文件编码：`utf-8` / `utf-16` / `latin-1`。**COPY 不支持**。 |
| `filename` | BOOL | `false` | 为每行附加来源文件路径字符串列 `filename`。v1.3.0 起作为虚拟列自动提供，此选项仅保留兼容。 |
| `files_to_sniff` | BIGINT | `10` | 多文件读取时用于嗅探 schema 的文件数；`-1` 表示嗅探所有文件。 |
| `force_not_null` | VARCHAR[] | `[]` | 指定列的值不匹配 `NULL` 字符串（默认空串表示该列空值读成零长字符串而非 `NULL`）。 |
| `header` | BOOL | `false` | 每个文件首行是否为列名。 |
| `hive_partitioning` | BOOL | (自动检测) | 是否按 Hive 分区路径解析。 |
| `ignore_errors` | BOOL | `false` | 忽略解析错误（跳过坏行）。 |
| `max_line_size` / `maximum_line_size` | BIGINT | `2000000` | 最大行字节数。**COPY 不支持**。 |
| `names` / `column_names` | VARCHAR[] | (空) | 列名列表（文件无表头时使用）。 |
| `new_line` | VARCHAR | (空) | 换行符：`'\r'` / `'\n'` / `'\r\n'`（解析器不区分 `'\r'` 与 `'\n'`）。 |
| `normalize_names` | BOOL | `false` | 规范化列名：移除非字母数字字符；SQL 保留字前缀加 `_`。 |
| `null_padding` | BOOL | `false` | 行缺列时在右侧补 `NULL`。 |
| `nullstr` / `null` | VARCHAR 或 VARCHAR[] | (空) | 表示 `NULL` 的字符串。 |
| `parallel` | BOOL | `true` | 使用并行 CSV 读取器。 |
| `quote` | VARCHAR | `"` | 引用值的字符串。 |
| `rejects_scan` | VARCHAR | `reject_scans` | 存放"扫描参数"信息的临时表名（见 2.5）。 |
| `rejects_table` | VARCHAR | `reject_errors` | 存放"坏行"信息的临时表名。 |
| `rejects_limit` | BIGINT | `0` | 每个文件记录到 rejects 表的坏行上限；`0` 表示不限。 |
| `sample_size` | BIGINT | `20480` | 自动检测用的采样行数。 |
| `sep` | VARCHAR | `,` | `delim` 别名。 |
| `skip` | BIGINT | `0` | 每个文件开头跳过的行数。 |
| `store_rejects` | BOOL | `false` | 跳过坏行并把它们存入 rejects 表。 |
| `strict_mode` | BOOL | `true` | 严格模式：为 `true` 时遇到任何问题立即报错；为 `false` 时尝试读取结构不正确的文件（有歧义，慎用）。 |
| `thousands` | VARCHAR | (空) | 数值千分位分隔符（单字符，须与 `decimal_separator` 不同）。 |
| `timestampformat` | VARCHAR | (空) | 解析/写入时间戳的格式串。 |
| `timestamp_format` | VARCHAR | (空) | `timestampformat` 别名，**仅 COPY**。 |
| `types` / `dtypes` / `column_types` | VARCHAR[] 或 STRUCT | (空) | 列类型（按位置列表或按名 struct）。 |
| `union_by_name` | BOOL | `false` | 跨文件按列名（而非位置）对齐，内存消耗更高。 |

### 2.3 自动检测（Auto Detection）

`read_csv` 默认用 **CSV sniffer** 推断三类信息：
1. **方言（dialect）**：分隔符、引号规则、转义。
2. **列类型**。
3. **是否有表头行**。

可单独覆盖任意选项（如 `read_csv('file.csv', delim='|')`），覆盖后该参数不再自动检测。

#### 采样大小（Sample Size）

- 类型检测基于文件**采样**，默认采样 **20,480 行**。
- `sample_size = -1` 表示采样整个文件。
- 采样方式取决于文件类型：普通磁盘文件会"跳跃"到不同位置采样；而 `.gz`/stdin 等不可跳跃的文件只在开头采样。

#### `sniff_csv` 函数

可单独运行嗅探器，返回单行 table：

```sql
FROM sniff_csv('my_file.csv');
FROM sniff_csv('my_file.csv', sample_size = 1000);
```

返回列包括：`Delimiter`、`Quote`、`Escape`、`NewLineDelimiter`、`Comment`、`SkipRows`、`HasHeader`、`Columns`、`DateFormat`、`TimestampFormat`、`UserArguments`、`Prompt`（可直接复制执行的 `read_csv` 命令）。

#### 方言检测候选值

| 参数 | 候选值 |
|--|--|
| `delim` | `,` `|` `;` `\t` |
| `quote` | `"` `'` (空) |
| `escape` | `"` `'` `\` (空) |

检测规则：选"每行列数一致"且"列数最多"的方言。

#### 类型检测候选类型（按优先级，高→低）

默认候选：`NULL` → `BOOLEAN` → `TIME` → `DATE` → `TIMESTAMP` → `TIMESTAMPTZ` → `BIGINT` → `DOUBLE` → `VARCHAR`（兜底）。

额外可用（`auto_type_candidates` 可指定）：`TINYINT` → `SMALLINT` → `INTEGER` → `DECIMAL` → `FLOAT`。

- `VARCHAR` 永远作为兜底，优先级最低。
- `all_varchar = true` 可整体关闭类型检测。
- **覆盖类型**：`types` 接受按位置列表（`['INTEGER','VARCHAR','DATE']`）或按名 map（`{'quarter':'INTEGER'}`）。`types` 支持任意合法类型定义（比 `auto_type_candidates` 灵活）。

#### 表头检测

- 通过比较候选表头行与其余行在类型上的差异来判断。
- 当所有列都是 `VARCHAR` 时无法区分表头，系统会**假定有表头**；可用 `header=false` 覆盖。
- 无表头时列名自动生成为 `column0, column1, ...`。

#### 日期/时间戳格式偏好（歧义时高优先级优先）

`dateformat` 候选（高→低）：ISO 8601 → `%y-%m-%d` → `%Y-%m-%d` → `%d-%m-%y` → `%d-%m-%Y` → `%m-%d-%y` → `%m-%d-%Y`

`timestampformat` 候选（高→低）：ISO 8601 → `%y-%m-%d %H:%M:%S` → `%Y-%m-%d %H:%M:%S` → `%d-%m-%y %H:%M:%S` → `%d-%m-%Y %H:%M:%S` → `%m-%d-%y %I:%M:%S %p` → `%m-%d-%Y %I:%M:%S %p` → `%Y-%m-%d %H:%M:%S.%f`

> 歧义解析示例：`01-02-2000` 可解析为 1月2日 或 2月1日；若后续出现 `21-02-2000` 则确定格式为 `DD-MM-YYYY`（无第 21 月）。

### 2.4 编码支持

- 原生支持 `UTF-8`（默认）、`UTF-16`、`Latin-1`。
- 其他编码：使用 `encodings` 扩展，或先用 `iconv` 转换：
  ```batch
  iconv -f ISO-8859-2 -t UTF-8 input.csv > input-utf-8.csv
  ```

### 2.5 读取损坏的 CSV（Faulty CSV）

DuckDB 能检测并跳过以下**结构错误**：

| 错误类型 | 说明 |
|--|--|
| `CAST` | 列值无法转为目标 schema 类型（如 `"The 90s"` 转 `DATE`）。 |
| `MISSING COLUMNS` | 行中列数少于预期。 |
| `TOO MANY COLUMNS` | 行中列数多于预期。 |
| `UNQUOTED VALUE` | 引号值未正确结束。 |
| `LINE SIZE OVER MAXIMUM` | 行超过 `max_line_size`（默认 2,097,152 字节）。 |
| `INVALID ENCODING` | 含 UTF-8/UTF-16/Latin-1 之外的字符。 |

**错误信息**非常详尽，包含行号、原始行、出错列、自动检测到的配置与解决建议。

#### `ignore_errors` 选项

```sql
FROM read_csv('faulty.csv',
    columns = {'name':'VARCHAR','age':'INTEGER'},
    ignore_errors = true);
```
> 注意：CSV 解析受**投影下推**影响。若只 `SELECT name`，`age` 的 CAST 错误不会发生，两行都会作为有效行返回。

#### Rejects 表（数据清洗用）

设置 `store_rejects = true` 时创建两个临时表：
- `reject_scans`：扫描参数信息（scan_id, file_id, file_path, delimiter, quote, escape, newline_delimiter, skip_rows, has_header, columns, date_format, timestamp_format, user_arguments）。
- `reject_errors`：每个坏行详情（scan_id, file_id, line, line_byte_position, byte_position, column_idx, column_name, error_type, csv_line, error_message）。

相关参数：`store_rejects`、`rejects_scan`（默认 `reject_scans`）、`rejects_table`（默认 `reject_errors`）、`rejects_limit`（默认 `0` 不限）。

### 2.6 写入 CSV（`COPY ... TO`）

```sql
COPY tbl TO 'result.csv' (HEADER, DELIMITER '|');
```

`COPY ... TO` 支持的 CSV 相关选项（与读取端对应，含仅 COPY 别名）：`DELIMITER`/`delim`、`QUOTE`、`ESCAPE`、`HEADER`、`DATE_FORMAT`/`dateformat`、`TIMESTAMP_FORMAT`/`timestampformat`、`NULL_STRING`/`nullstr`、`FORCE_QUOTE`、`FORCE_NOT_NULL`、`ENCODING`（注：COPY 写入端详见 `COPY` 语句文档，本节仅列 data/ 范围内已知项）。

- **行顺序保持**：CSV 读取器遵守 `preserve_insertion_order` 配置项（默认 `true`），保证结果行序与文件中行序一致；设为 `false` 则不保证。

### 2.7 最佳实践与陷阱

| 场景 | 建议 |
|--|--|
| 表头检测失败（全字符串列） | 显式 `header = true` |
| 文件无表头 | `names = ['DateOfFlight','CarrierName']` |
| 仅覆盖个别列类型 | `types = {'FlightDate':'DATE'}` |
| 装入已有表（更快更稳） | 用 `COPY tbl FROM 'test.csv';`（用表 schema，不做类型嗅探） |
| 多文件 schema 不同 | `union_by_name = true` |
| 类型嗅探不准 | 增大 `sample_size` 或 `sample_size = -1` |
| 大批量加载 | 避免逐行 `INSERT`，优先 `COPY` 或 `read_csv` + CTAS |

---

## 3. Parquet

Parquet 是**列式压缩**格式，加载与处理高效。DuckDB 对 Parquet 的读写都做了优化，并支持把 filter 与 projection **下推（pushdown）** 到文件扫描层。

### 3.1 读取示例

```sql
SELECT * FROM 'test.parquet';                       -- 扩展名自动识别
DESCRIBE SELECT * FROM 'test.parquet';              -- 查看列/类型
CREATE TABLE test AS SELECT * FROM 'test.parquet';  -- 建表
SELECT * FROM read_parquet('test.parq');            -- 扩展名不标准时
SELECT * FROM read_parquet(['f1.parquet','f2.parquet','f3.parquet']);
SELECT * FROM 'test/*.parquet';                     -- glob
SELECT *, filename FROM read_parquet('test/*.parquet'); -- v1.3.0 起 filename 自动
SELECT * FROM read_parquet('https://some.url/some_file.parquet'); -- 远程
```

相关函数：`read_parquet(path)`，`parquet_scan(path)` 为其别名。

### 3.2 读取参数表（`read_parquet` / `COPY`）

| 参数 | 类型 | 默认值 | 含义 |
|--|--|--|--|
| `binary_as_string` | BOOL | `false` | 旧版 writer 未正确设置 `UTF8` 标志导致字符串列读成 `BLOB` 时，设为 `true` 可当字符串读。 |
| `can_have_nan` | BOOL | `false` | `FLOAT`/`DOUBLE` 列是否可能含 `NaN`。为 `true` 时读取器在利用 min/max 统计做 filter pushdown 时考虑 `NaN`（NaN 不参与有序比较）。 |
| `encryption_config` | STRUCT | - | Parquet 加密配置（见 3.6）。 |
| `filename` | BOOL | `false` | 是否附加 `filename` 列（v1.3.0 起自动提供，仅兼容保留）。 |
| `file_row_number` | BOOL | `false` | 是否附加 `file_row_number` 列。 |
| `hive_partitioning` | BOOL | (自动检测) | 是否按 Hive 分区路径解析。 |
| `union_by_name` | BOOL | `false` | 多文件 schema 按列名而非位置统一。 |
| `schema` | MAP | `NULL` | 以指定 schema 读取（重命名/增删/重排/cast 列）。**需要 field IDs**。 |

#### `schema` 参数（重定义读取结构）

```sql
-- 写 Parquet 时声明 field IDs
COPY (SELECT 42::INTEGER AS i) TO 'integers.parquet' (FIELD_IDS {i: 0});

-- 读时重命名/新增列
SELECT * FROM read_parquet('integers.parquet', schema = MAP {
    0: {name: 'renamed_i', type: 'BIGINT', default_value: NULL},
    1: {name: 'new_column', type: 'UTINYINT', default_value: 43}
});
```
> `schema` 不可与 `union_by_name = true` 同时使用。

### 3.3 部分读取（Partial Reading）—— Pushdown

- **Projection pushdown**：只读取查询所需的列。
- **Filter pushdown**：对列的过滤会下推到扫描层，并借助内建 **zonemap（min/max 统计）** 跳过文件/row group 中不需要的部分。
- 性能收益显著（官方博客 "Querying Parquet with Precision Using DuckDB"）。

### 3.4 写入 Parquet（`COPY ... TO`）

```sql
COPY (SELECT * FROM tbl) TO 'result-snappy.parquet' (FORMAT parquet);  -- 默认 Snappy
COPY tbl TO 'result-zstd.parquet' (FORMAT parquet, COMPRESSION zstd);
COPY tbl TO 'result-zstd.parquet' (FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL 1);
COPY tbl TO 'result-v2.parquet' (FORMAT parquet, PARQUET_VERSION 'V2');
COPY tbl TO 'result-uncompressed.parquet' (FORMAT parquet, COMPRESSION uncompressed);
COPY (FROM generate_series(100_000)) TO 'rg.parquet'
     (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 100_000);
COPY (FROM generate_series(100_000)) TO 'result-lz4.parquet' (FORMAT parquet, COMPRESSION lz4); -- 等价于 lz4_raw
COPY (FROM generate_series(100_000)) TO 'result-brotli.parquet' (FORMAT parquet, COMPRESSION brotli);
```

**压缩算法**：`snappy`（默认）、`zstd`、`lz4`/`lz4_raw`、`brotli`、`uncompressed`、`gzip` 等。

**关键写入选项**：
- `COMPRESSION` / `COMPRESSION_LEVEL`
- `ROW_GROUP_SIZE`：row group 最小行数（下限 = DuckDB vector size 2,048，默认 122,880）。
- `ROW_GROUPS_PER_FILE`：当前文件达到指定 row group 数时新建文件。
- `PARQUET_VERSION`：`V1` / `V2`。
- `STRING_DICTIONARY_PAGE_SIZE_LIMIT`：字典页大小（默认 1 MB）。
- `KV_METADATA {key: 'value'}`：写入自定义键值元数据。
- `FIELD_IDS {col: id}`：为列声明 field ID（供 `schema` 参数读取用）。
- `PER_THREAD_OUTPUT`：每线程写一个文件，可显著提升性能（文件总数不再重要时）。
- `EXPORT DATABASE 'target' (FORMAT parquet)`：把整个数据库导出为一系列 Parquet 文件。

#### `ROW_GROUP_SIZE` 权衡（Parquet Tips）

- 压缩按 row group 进行：row group 越大，压缩机会越多。
- 但 row group 越大，流式写出时每线程在 flush 前需缓存更多数据。
- 小 row group 利于并行读取与 predicate pushdown（仅扫描匹配 WHERE 的 row group）。
- 经验法则：每文件 row group 数 ≥ 查询该文件的 CPU 线程数；超过线程数可加速高选择性查询，但全表扫描（聚合）会变慢。

#### 排序以改善 Row Group Pruning

DuckDB 为每个 row group 写 min/max 统计，读取时据此跳过不匹配的 row group。按常用过滤列**预先排序**可使 min/max 范围紧致且不重叠：

```sql
COPY (FROM 'events.parquet' ORDER BY event_time)
TO 'events-sorted.parquet' (FORMAT parquet);
```

### 3.5 元数据查询（Metadata）

| 函数 | 作用 | 主要返回列 |
|--|--|--|
| `parquet_metadata('f.parquet')` | row group / 列级统计 | file_name, row_group_id, row_group_num_rows, column_id, type, **stats_min, stats_max, stats_null_count, stats_distinct_count, stats_min_value, stats_max_value**, compression, encodings, total_compressed_size, total_uncompressed_size, key_value_metadata, bloom_filter_offset, min_is_exact, max_is_exact, ... |
| `parquet_schema('f.parquet')` | 内部 schema | file_name, name, type, type_length, repetition_type, num_children, converted_type, scale, precision, field_id, logical_type |
| `parquet_file_metadata('f.parquet')` | 文件级元数据 | file_name, created_by, num_rows, num_row_groups, **format_version**, encryption_algorithm, footer_signing_key_metadata, file_size_bytes, footer_size, column_orders |
| `parquet_kv_metadata('f.parquet')` | 自定义键值元数据 | file_name, key (BLOB), value (BLOB) |
| `parquet_full_metadata('f.parquet')` | 上述四者合并为单行嵌套 struct | parquet_file_metadata, parquet_metadata, parquet_schema, parquet_kv_metadata |
| `parquet_bloom_probe(filename, col, value)` | 显示某值能否用 Bloom filter 排除 row group | file_name, row_group_id, bloom_filter_excludes |

- 都支持 glob（如 `parquet_metadata('data/*.parquet')`）并行查询多文件。
- **Bloom filter**：支持 `TINYINT/UTINYINT/SMALLINT/USMALLINT/INTEGER/UINTEGER/BIGINT/UBIGINT`、`FLOAT/DOUBLE`、`VARCHAR`、`BLOB`；用于高选择性查询的 row group 裁剪。

### 3.6 加密（Encryption，自 v0.10.0）

遵循 Parquet Modular Encryption 规范，部分限制。

```sql
-- 添加会话内密钥（128/192/256 位，内存存储）
PRAGMA add_parquet_key('key256', '01234567891123450123456789112345');

-- 写加密文件
COPY tbl TO 'tbl.parquet' (ENCRYPTION_CONFIG {footer_key: 'key256'});

-- 读加密文件
SELECT * FROM read_parquet('tbl.parquet', encryption_config = {footer_key: 'key256'});
```

- **互操作性**：可读取 Arrow C++（如 PyArrow）写的"统一加密" Parquet（footer 与所有列用同一密钥）。
- **限制**：当前仅支持用 `footer_key` 加密 footer 与所有列；**不支持** `column_keys`（逐列不同密钥），会报 `Not implemented Error`。
- **性能**：TPC-H SF1 `lineitem`（6M 行、15 列）读写约慢 2.5×。

### 3.7 扩展加载

`parquet` 扩展几乎随所有客户端捆绑；若未捆绑需手动 `INSTALL parquet;`。

---

## 4. JSON

JSON 由 `json` 扩展支持（多数发行版默认捆绑，首次使用自动加载）。除读取 JSON 文件外，DuckDB 还提供丰富的 JSON 处理函数。

### 4.1 读取示例

```sql
SELECT * FROM 'todos.json';   -- 自动识别

SELECT * FROM read_json('todos.json',
    format = 'array',
    columns = {userId:'UBIGINT', id:'UBIGINT', title:'VARCHAR', completed:'BOOLEAN'});

-- 从 stdin
cat data/json/todos.json | duckdb -c "SELECT * FROM read_json('/dev/stdin')"

-- 建表（手动 schema）
CREATE TABLE todos (userId UBIGINT, id UBIGINT, title VARCHAR, completed BOOLEAN);
COPY todos FROM 'todos.json' (AUTO_DETECT true);

-- 自动推断建表
CREATE TABLE todos AS SELECT * FROM 'todos.json';

-- v1.3.0 起返回 filename 虚拟列
SELECT filename, * FROM 'todos-*.json';
```

#### JSON 数据类型（JSON Type）

- 逻辑类型 `JSON`，物理存储为 `VARCHAR`，且必须是合法 JSON。
- 空格/键顺序敏感（`'{"a":5}'::JSON = '{"a": 5}'::JSON` → false；`'{"a":1,"b":2}' = '{"b":2,"a":1}'` → false）。
- 允许重复键（如 `{"a":1,"a":2}`）。
- 任何 DuckDB 类型都可 cast 到 JSON，反之亦然（`'{"duck":42}'::JSON::STRUCT(duck INTEGER)`）。
- **0-based 索引**（与 `ARRAY`/`LIST` 的 1-based 不同，遵循 PostgreSQL 约定）。

### 4.2 以表形式读取：`read_json`

| 函数 | 说明 |
|--|--|
| `read_json(filename)` | 读 JSON 为表；filename 可为列表或 glob |
| `read_json_auto(filename)` | `read_json` 别名 |
| `read_ndjson(filename)` | `read_json` 且 `format='newline_delimited'` |
| `read_ndjson_auto(filename)` | 同上 |

**参数**：

| 参数 | 类型 | 默认值 | 含义 |
|--|--|--|--|
| `auto_detect` | BOOL | `true` | 是否自动检测键名与值类型 |
| `columns` | STRUCT | (空) | 指定键名与值类型（如 `{key1:'INTEGER'}`）；指定子集时仅返回这些列 |
| `compression` | VARCHAR | `auto_detect` | `none`/`gzip`/`zstd`/`auto_detect` |
| `dateformat` | VARCHAR | `iso` | 日期格式 |
| `filename` | BOOL | `false` | 附加 `filename` 列（v1.3.0 起自动） |
| `format` | VARCHAR | `array` | `auto`/`unstructured`/`newline_delimited`/`array` |
| `hive_partitioning` | BOOL | (自动检测) | Hive 分区路径解析 |
| `ignore_errors` | BOOL | `false` | 忽略解析错误（仅 `format='newline_delimited'` 时） |
| `maximum_depth` | BIGINT | `-1` | 类型自动检测的最大嵌套深度；`-1` 完全检测 |
| `maximum_object_size` | UINTEGER | `16777216` | **单个 JSON 对象的最大字节数（16 MB）** |
| `maximum_sample_files` | BIGINT | `32` | 自动检测时采样的最大文件数 |
| `map_inference_threshold` | BIGINT | `200` | 子字段超过此数时推断为 `MAP` 而非 `STRUCT`；`-1` 关闭 MAP 推断 |
| `field_appearance_threshold` | DOUBLE | `0.1` | 字段出现频率均值低于此阈值时默认用 `MAP`（值类型为合并的字段类型） |
| `records` | VARCHAR | `auto` | `auto`/`true`/`false`：是否把 JSON 对象拆为各列 |
| `sample_size` | UBIGINT | `20480` | 类型检测采样对象数；`-1` 扫描整个文件 |
| `timestampformat` | VARCHAR | `iso` | 时间戳格式；`iso` 时自动推断带时区偏移/小数秒的 ISO 8601 为 `TIMESTAMP` |
| `union_by_name` | BOOL | `false` | 多文件 schema 按名统一 |

> JSON 数组可直接转 `LIST`；缺失键变 `NULL`。

### 4.3 读取为对象：`read_json_objects`

| 函数 | 说明 |
|--|--|
| `read_json_objects(filename)` | 读 JSON 对象（filename 可为列表/glob） |
| `read_ndjson_objects(filename)` | 别名，`format='newline_delimited'` |
| `read_json_objects_auto(filename)` | 别名，`format='auto'` |

`format` 取值含义：
- `unstructured`：顶层为多个独立 JSON 对象（连续书写）。
- `newline_delimited`（NDJSON）：每行一个 JSON。
- `array`：JSON 数组，每个元素为一个对象。

### 4.4 格式与 `records`（`format_settings`）

- `format='auto'` 时 DuckDB 多数情况能正确推断，无需显式设置。
- `records=true`：把 JSON 对象字段拆为各列。
- `records=false`：不拆顶层对象，生成 `STRUCT` 列（对非对象 JSON 如纯数组尤其有用）。

### 4.5 用 `COPY` 读写 JSON

```sql
-- 读（默认期望 NDJSON；数组需 ARRAY true）
COPY numbers FROM 'numbers.json' (ARRAY true);
COPY numbers FROM 'numbers.json' (AUTO_DETECT true);

-- 写（默认 NDJSON；数组用 ARRAY true）
COPY (SELECT * FROM range(5) r(i)) TO 'numbers.json' (ARRAY true);
```

`COPY ... FORMAT json` 支持 `FROM`/`TO`、`IMPORT DATABASE`/`EXPORT DATABASE`。`COPY` 时 JSON 参数：`auto_detect`(默认 `false`)、`columns`、`compression`、`convert_strings_to_integers`、`dateformat`、`filename`、`format`、`hive_partitioning`、`ignore_errors`、`maximum_depth`、`maximum_object_size`、`records`、`sample_size`、`timestampformat`、`union_by_name`。

### 4.6 创建与写入 JSON

- 创建函数：`to_json`/`json_quote`、`array_to_json`、`row_to_json`、`json_array`、`json_object`、`json_merge_patch`。
- 写入文件：`COPY ... TO 'file.json';`（默认 NDJSON）。
- SQL ↔ JSON 序列化：`json_serialize_sql`、`json_deserialize_sql`、`json_execute_serialized_sql`（用于把 SELECT 语句在 SQL 与 JSON AST 间互转/执行）。

### 4.7 JSON 处理函数速览（读者提示）

本 digest 聚焦"读取器"，JSON 处理函数（提取/标量/聚合/转换/表函数）详见 `json_functions.md`：

- 提取：`json_extract`(`->`)、`json_extract_string`(`->>`)、`json_exists`、`json_value`。
- 标量：`json_array_length`、`json_contains`、`json_keys`、`json_structure`、`json_type`、`json_valid`、`json`。
- 聚合：`json_group_array`、`json_group_object`、`json_group_structure`。
- 转换嵌套类型：`json_transform`/`from_json`、`json_transform_strict`/`from_json_strict`。
- 表函数：`json_each`、`json_tree`（横向连接遍历）。
- 路径语法：**JSONPath**（`$.duck[0]`，支持 `*` 与从尾部索引 `$-1`，0-based）与 **JSON Pointer**（`/duck/0`）。

### 4.8 Caveats（注意事项）

- **相等比较不一致**：JSON 相等有时基于原始文本、有时基于逻辑内容。例如 `'[]'::JSON != '[ ]'::JSON` 为 true（空格属于物理内容）；而 `c[0] = d[0]`（去空格后）为 true。编写涉及 JSON 相等的逻辑时需谨慎。

---

## 5. 多文件读取（Multiple Files）

DuckDB 可同时读取**多种类型**（CSV/Parquet/JSON）的多个文件，方式有两种：**glob 语法**或**文件列表**。

### 5.1 示例

```sql
-- CSV
SELECT * FROM 'dir/*.csv';
SELECT * FROM '*/*/*.csv';          -- 两层深
SELECT * FROM 'dir/**/*.csv';       -- 任意深度
SELECT * FROM read_csv(['f1.csv','f2.csv']);
SELECT * FROM read_csv(['f1.csv','f2.csv'], union_by_name=true, filename=true);

-- Parquet
SELECT * FROM 'test/*.parquet';
SELECT * FROM read_parquet(['f1.parquet','f2.parquet','f3.parquet']);
SELECT * FROM read_parquet(['folder1/*.parquet','folder2/*.parquet']);
SELECT * FROM read_parquet('dir/**/*.parquet');
```

### 5.2 Glob 通配符

| 通配符 | 含义 |
|--|--|
| `*` | 匹配任意数量任意字符（含无） |
| `**` | 匹配任意数量子目录（含无） |
| `?` | 匹配任意单个字符 |
| `[abc]` | 匹配括号内任一字符 |
| `[a-z]` | 匹配括号内范围内任一字符 |

> 注：S3 读取因 HTTP 编码问题**不支持 `?` 通配符**。

- **列表参数**：`read_parquet(['f1','f2','f3'])`。
- **glob 列表组合**：`read_parquet(['folder1/*.parquet','folder2/*.parquet'])`。
- 要求被合并的 Parquet 文件 **schema 相同**（否则用 `union_by_name`）。

### 5.3 `filename` 列

`filename=true` 附加来源文件路径列；还可传字符串自定义列名（`filename='input_file'`）以避免与源数据已有 `filename` 列冲突。

### 5.4 `glob` 表函数（查找文件名）

```sql
SELECT * FROM glob('*');
```

### 5.5 Schema 合并（Combining Schemas）

读取多文件时必须合并各文件 schema，DuckDB 提供两种方式：

| 方式 | 行为 | 适用 |
|--|--|--|
| **按位置（union by position，默认）** | 第一个文件的 schema 为准，后续文件按列位置对齐 | 所有文件 schema 相同 |
| **按名（union by name，`union_by_name=true`）** | 按列名构建统一 schema，缺失列补 `NULL` | 文件 schema 不同（增列/改名） |

```sql
SELECT * FROM read_csv('flights*.csv');                  -- 按位置
SELECT * FROM read_csv('flights*.csv', union_by_name=true); -- 按名
```

> `union_by_name` 会增加内存消耗。

---

## 6. 分区数据集（Partitioned Datasets）

分区是把大表按"分区键"拆成多文件、组织到多层文件夹中的策略。DuckDB 原生支持 **Hive 分区**（`key=value` 目录名）的读取与写入，并支持 filter 下推到分区键。

### 6.1 Hive 分区读取

目录结构示例（按 `year`、`month` 两级分区）：

```
orders
├── year=2021
│    ├── month=1
│    │   ├── file1.parquet
│    │   └── file2.parquet
│    └── month=2
│        └── file3.parquet
└── year=2022
     ├── month=11
     │   ├── file4.parquet
     │   └── file5.parquet
     └── month=12
         └── file6.parquet
```

```sql
SELECT * FROM read_parquet('orders/*/*/*.parquet', hive_partitioning = true);
-- hive_partitioning = false 时不包含分区列（year, month）
```

#### Filter Pushdown（分区裁剪）

对分区键的过滤会自动下推，跳过无关文件：

```sql
SELECT * FROM read_parquet('orders/*/*/*.parquet', hive_partitioning = true)
WHERE year = 2022 AND month = 11;
-- 仅读取 orders/year=2022/month=11/ 下文件
```

#### 自动检测

默认会尝试推断路径是否为 Hive 层级（查找 `'key' = 'value'` 模式），命中则自动开启 `hive_partitioning`。可用 `SET hive_partitioning = false;` 覆盖。

#### 分区列类型（`hive_types`）

`hive_types` 用 struct 指定分区列逻辑类型：

```sql
SELECT * FROM read_parquet('dir/**/*.parquet',
    hive_partitioning = true,
    hive_types = {'release': DATE, 'orders': BIGINT});
```
- 自动检测类型：`DATE`、`TIMESTAMP`、`BIGINT`。
- 关闭自动检测：`SET hive_types_autocast = 0;`

### 6.2 分区写入（Partitioned Writes）

`COPY ... PARTITION_BY (...)` 把文件写成 Hive 层级，目标为根目录名：

```sql
COPY orders TO 'orders' (FORMAT parquet, PARTITION_BY (year, month));
COPY orders TO 'orders' (FORMAT csv, PARTITION_BY (year, month), OVERWRITE_OR_IGNORE);
COPY orders TO 'orders' (FORMAT csv, PARTITION_BY (year, month),
    COMPRESSION gzip, FILE_EXTENSION 'csv.gz');
```

- `PARTITION_BY` **不能**用表达式；需临时列时用子查询：
  ```sql
  COPY (SELECT *, year(timestamp) AS year, month(timestamp) AS month FROM services)
  TO 'test' (PARTITION_BY (year, month));
  ```
- 每个线程对每个目录写一个文件（如 `data_1.parquet`、`data_2.parquet`）。
- 限制同时打开文件数：`SET partitioned_write_max_open_files = 10;`（默认 100）。
- **最佳实践**：写太多小分区代价高，建议每分区至少约 **100 MB** 数据。

#### 文件名模式（`FILENAME_PATTERN`）

默认 `data_0.parquet` / `data_0.csv`；可用 `{i}`（索引）或 `{uuid}`（128 位 UUID）：

```sql
COPY orders TO 'orders' (FORMAT parquet, PARTITION_BY (year, month),
    OVERWRITE_OR_IGNORE, FILENAME_PATTERN 'orders_{i}');
COPY orders TO 'orders' (FORMAT parquet, PARTITION_BY (year, month),
    OVERWRITE_OR_IGNORE, FILENAME_PATTERN 'file_{uuid}');
```

#### 覆盖与追加

- `OVERWRITE` / `OVERWRITE_OR_IGNORE`：本地文件系统移除已存在目录；远程文件系统不支持覆盖。
- `APPEND`：追加到现有 Hive 目录（类似 `OVERWRITE_OR_IGNORE + FILENAME_PATTERN '{uuid}'`，但会检查并重生成冲突 UUID）。

#### 列中含斜杠

用 `url_encode` 函数做 Percent-Encoding 处理。

---

## 附录：跨格式通用能力对照

| 能力 | CSV | Parquet | JSON |
|--|--|--|--|
| 扩展名自动识别 | ✅ | ✅ | ✅ |
| 压缩读取（gzip/zstd） | ✅ | ✅（内置） | ✅ |
| `auto_detect` | ✅（sniffer） | N/A（自带 schema） | ✅ |
| `union_by_name` | ✅ | ✅ | ✅ |
| `filename` 虚拟列（v1.3.0） | ✅ | ✅ | ✅ |
| `hive_partitioning` | ✅ | ✅ | ✅ |
| glob / 文件列表 | ✅ | ✅ | ✅ |
| filter/projection pushdown | 有限 | ✅（zonemap + Bloom） | 有限 |
| 加密 | ❌ | ✅（v0.10.0+） | ❌ |
| 分区写入 `PARTITION_BY` | ✅（CSV） | ✅ | — |

### 版本相关的关键事实（针对 1.5.5）

- **v1.3.0**：CSV/JSON/Parquet 读取器新增自动 `filename` 虚拟列（无需 `filename=true`）。
- **Parquet 加密**自 v0.10.0 起支持（footer + 全列统一密钥；不支持逐列 `column_keys`）。
- **JSON `maximum_object_size`** 默认 16 MB（16,777,216 字节）。
- **`sample_size`** 默认：CSV 20,480 行；JSON 20,480 个对象；`-1` 表示全量扫描。
- **`ROW_GROUP_SIZE`** 下限 2,048，默认 122,880。
- **Bloom filter** 支持整数/浮点/`VARCHAR`/`BLOB` 类型的 row group 裁剪。
- 元数据函数 `parquet_full_metadata` 将文件/行组/schema/kv 四类元数据合并为单行嵌套 struct。
