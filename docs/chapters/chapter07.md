# 第 07 章 数据导入：文件直读

数据工作者的日常，往往是从一份散落在磁盘上的文件开始——CSV 报表、Parquet 数据湖导出、JSON 接口日志。DuckDB 把"先把数据搬进数据库"这一步直接抹去：文件本身就是可查询的对象。这种"以文件为第一公民"（files as first-class query targets）的设计，让即席分析（ad-hoc analysis）的启动成本降到极低——无需建表、无需导入、无需起服务，一句 `SELECT` 即可从原始文件取数。本章沿着 CSV、Parquet、JSON 三条主线，讲清格式自动探测、读取参数与类型推断、下推（pushdown）优化，以及多文件与分区数据集的批量读取，构成后续数据工程章节的方法论基础。

## 7.1 "直接查询文件"哲学与格式自动探测

DuckDB 的核心设计理念之一是：可以像查询数据库表一样直接查询文件。用户无需先把数据 `COPY` 或 `IMPORT` 进数据库，而是直接用 SQL 读取磁盘（或远程、或压缩）上的文件。这一能力在三类最常见的数据格式上开箱即用：CSV、Parquet 与 JSON。

最直觉的用法是根据文件扩展名自动识别格式。引擎见到 `.csv`、`.parquet`、`.json` 后缀，便调用对应的读取器：

```sql
SELECT * FROM 'test.csv';      -- 自动识别为 CSV
SELECT * FROM 'test.parquet';  -- 自动识别为 Parquet
SELECT * FROM 'test.json';     -- 自动识别为 JSON
```

当文件扩展名不标准时——例如某个 Parquet 文件被命名为 `test.parq`——自动识别会失效，此时必须显式调用读取函数：

```sql
SELECT * FROM read_parquet('test.parq');
```

三种加载途径各有侧重，下表归纳其适用场景：

| 途径 | 适用场景 | 示例 |
|---|---|---|
| 直接文件名查询（自动识别） | 快速探索、即席查询 | `SELECT * FROM 'flights.csv';` |
| 读取函数（`read_csv` / `read_parquet` / `read_json`） | 需要传选项、类型覆盖、批量多文件 | `SELECT * FROM read_csv('f.csv', header = false);` |
| `COPY` 语句 | 把数据装入已存在或新建的表 | `COPY tbl FROM 'test.csv';` |

相对路径默认相对于当前工作目录（working directory）；也可以通过配置项 `file_search_path` 指定相对路径所扩展到的"根目录"，从而把文件组织与运行位置解耦。

压缩文件同样能直接读取。DuckDB 识别 `gzip`、`zstd` 等压缩方式，按扩展名自动探测——例如 `test.csv.gz` 会被当作 gzip 压缩的 CSV 透明解压后读取：

```sql
SELECT * FROM 'test.csv.gz';
```

把文件内容固化成持久表，最自然的方式是 CTAS（Create Table As Select）：

```sql
CREATE TABLE test AS SELECT * FROM 'test.parquet';
-- 省略 SELECT * 的 FROM-first 语法同样有效：
CREATE TABLE ontime AS FROM 'flights.csv';
```

自 DuckDB v1.3.0 起，CSV、JSON、Parquet 读取器会自动提供 `filename` 虚拟列，标明每行数据来自哪个文件，无需显式配置：

```sql
COPY (FROM (VALUES (42), (43)) t(x)) TO 'test.parquet';
SELECT *, filename FROM 'test.parquet';
```

早期版本需用 `filename = true` 显式开启，v1.3.0 之后该选项仅为兼容性保留。这一虚拟列在多文件合并与溯源排查时格外有用（详见 7.5 节）。

## 7.2 CSV 读取

CSV 是最常见也最容易出问题的数据格式：它没有 schema、方言（dialect）多样、常常含有损坏行。DuckDB 用一套 CSV sniffer（嗅探器）自动推断配置，绝大多数场景下能直接成功读取。

### 7.2.1 自动检测与采样

`read_csv` 默认启用嗅探器，自动推断三类信息：一是方言——分隔符、引号规则、转义符；二是各列的数据类型；三是首行是否为表头（header）。任意一项都可在调用时显式覆盖，例如 `read_csv('file.csv', delim = '|')` 仅覆盖分隔符，其余仍自动检测：

```sql
SELECT * FROM read_csv('flights.csv',
    delim = '|',
    header = true,
    columns = {
        'FlightDate': 'DATE',
        'UniqueCarrier': 'VARCHAR',
        'OriginCityName': 'VARCHAR',
        'DestCityName': 'VARCHAR'
    });
```

类型检测基于文件采样，默认采样 **20,480 行**；`sample_size = -1` 表示扫描整个文件做推断。采样方式因文件而异：普通磁盘文件会"跳跃"到不同位置取样本，而 `.gz`、stdin 之类不可跳跃的源只在开头采样。若嗅探结果不准，可增大 `sample_size`（或直接设为 `-1`）后再读。

嗅探器也可独立运行，返回一行诊断表，其中 `Prompt` 列给出了可直接复制执行的 `read_csv` 命令：

```sql
FROM sniff_csv('my_file.csv');
FROM sniff_csv('my_file.csv', sample_size = 1000);
```

方言检测的候选值为：分隔符 `,` `|` `;` `\t`，引号 `"` `'`（或无），转义符 `"` `'` `\`（或无）；判定规则是选择"每行列数一致且列数最多"的方言。类型检测的候选类型按优先级从高到低为 `NULL` → `BOOLEAN` → `TIME` → `DATE` → `TIMESTAMP` → `TIMESTAMPTZ` → `BIGINT` → `DOUBLE` → `VARCHAR`（兜底）；`VARCHAR` 永远作为兜底，`all_varchar = true` 可整体跳过类型推断。表头检测通过比较候选表头行与其余行在类型上的差异来判断；当所有列都是 `VARCHAR` 时无法区分，系统会假定有表头，可用 `header = false` 覆盖。无表头时列名自动生成为 `column0, column1, ...`。

### 7.2.2 读取参数

下表列出 `read_csv` 与 `COPY` 读取端常用的参数。标注"仅 COPY"的别名只能在 `COPY ... (...)` 语法中使用；`COPY` 语句本身始终使用 `utf-8` 编码，不提供 `encoding` 选项。

| 参数 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `delim` / `sep` | VARCHAR | `,` | 列分隔符，可为最多 4 字节的串。 |
| `delimiter` | VARCHAR | `,` | `delim` 别名，**仅 COPY**。 |
| `quote` | VARCHAR | `"` | 引用值的字符串。 |
| `escape` | VARCHAR | `"` | 引号值内转义 `quote` 字符的字符串。 |
| `header` | BOOL | `false` | 每个文件首行是否为列名。 |
| `all_varchar` | BOOL | `false` | 跳过类型推断，所有列当作 `VARCHAR`。仅 `read_csv` 支持。 |
| `dateformat` | VARCHAR | （空） | 解析/写入日期的格式串。 |
| `date_format` | VARCHAR | （空） | `dateformat` 别名，**仅 COPY**。 |
| `timestampformat` | VARCHAR | （空） | 解析/写入时间戳的格式串。 |
| `timestamp_format` | VARCHAR | （空） | `timestampformat` 别名，**仅 COPY**。 |
| `nullstr` / `null` | VARCHAR 或 VARCHAR[] | （空） | 表示 `NULL` 的字符串。 |
| `encoding` | VARCHAR | `utf-8` | 文件编码：`utf-8` / `utf-16` / `latin-1`。**COPY 不支持**。 |
| `skip` | BIGINT | `0` | 每个文件开头跳过的行数。 |
| `max_line_size` / `maximum_line_size` | BIGINT | `2000000` | 最大行字节数。**COPY 不支持**。 |
| `sample_size` | BIGINT | `20480` | 自动检测用的采样行数。 |
| `columns` | STRUCT | （空） | 列名+类型 struct，指定后关闭 schema 自动检测。 |
| `types` / `dtypes` / `column_types` | VARCHAR[] 或 STRUCT | （空） | 列类型，按位置列表或按名 struct。 |
| `auto_detect` | BOOL | `true` | 是否启用分隔符/引号/转义/表头/类型的自动检测。 |
| `ignore_errors` | BOOL | `false` | 忽略解析错误（跳过坏行）。 |
| `store_rejects` | BOOL | `false` | 跳过坏行并把它们存入 rejects 表。 |
| `rejects_table` | VARCHAR | `reject_errors` | 存放坏行信息的临时表名。 |
| `rejects_scan` | VARCHAR | `reject_scans` | 存放扫描参数信息的临时表名。 |
| `union_by_name` | BOOL | `false` | 跨文件按列名（而非位置）对齐。 |
| `hive_partitioning` | BOOL | （自动检测） | 是否按 Hive 分区路径解析。 |

### 7.2.3 读取损坏的 CSV

DuckDB 能检测并跳过结构错误，包括 `CAST`（列值无法转为目标类型）、`MISSING COLUMNS`（列数偏少）、`TOO MANY COLUMNS`（列数偏多）、`UNQUOTED VALUE`（引号未正确结束）、`LINE SIZE OVER MAXIMUM`（超过 `max_line_size`）、`INVALID ENCODING`（含非法字符）。错误信息包含行号、原始行、出错列、自动检测到的配置与解决建议，定位问题极为便利。

应急跳过坏行可用 `ignore_errors`：

```sql
FROM read_csv('faulty.csv',
    columns = {'name': 'VARCHAR', 'age': 'INTEGER'},
    ignore_errors = true);
```

需要系统清洗数据时，设置 `store_rejects = true` 会创建两个临时表：`reject_scans` 记录扫描参数（scan_id、file_path、delimiter、columns 等），`reject_errors` 记录每个坏行的详情（line、column_idx、error_type、csv_line、error_message）。相关参数 `rejects_table`、`rejects_scan`、`rejects_limit`（默认 `0` 不限）可用于自定义表名与上限。需留意 CSV 解析受投影下推影响——若只 `SELECT name`，`age` 列的 `CAST` 错误不会发生，被投影掉的列不会触发解析校验。

## 7.3 Parquet 读取与下推

Parquet 是列式压缩（columnar compressed）格式，加载与处理都极为高效。DuckDB 对 Parquet 的读写做了深度优化，并支持把 filter 与 projection **下推（pushdown）** 到文件扫描层。

### 7.3.1 读取与下推优化

直接读取与建表：

```sql
SELECT * FROM 'test.parquet';                       -- 扩展名自动识别
DESCRIBE SELECT * FROM 'test.parquet';              -- 查看列与类型
CREATE TABLE test AS SELECT * FROM 'test.parquet';  -- 建表
SELECT * FROM read_parquet('test.parq');            -- 扩展名不标准时
SELECT * FROM read_parquet(['f1.parquet', 'f2.parquet', 'f3.parquet']);
SELECT * FROM 'test/*.parquet';                     -- glob
SELECT * FROM read_parquet('https://some.url/some_file.parquet'); -- 远程
```

`read_parquet(path)` 与别名 `parquet_scan(path)` 等价。两类下推是 Parquet 性能的关键：

- **Projection pushdown（投影下推）**：只读取查询实际引用的列，未引用的列不被加载。
- **Filter pushdown（过滤下推）**：对列的过滤条件下沉到扫描层，借助内建的 **zonemap（min/max 统计）** 跳过 file / row group 中不满足条件的部分；对高选择性（highly selective）过滤，Bloom filter 可进一步排除无关的 row group。每行 group 写入的 min/max 统计，正是 row group pruning（行组裁剪）的依据。

写入时若按常用过滤列预先排序，可使 min/max 范围紧致且不重叠，显著提升裁剪效果：

```sql
COPY (FROM 'events.parquet' ORDER BY event_time)
TO 'events-sorted.parquet' (FORMAT parquet);
```

### 7.3.2 用 `schema` 重定义读取结构

Parquet 自带 schema，但当需要重命名、增删、重排或 cast 列时，可使用 `read_parquet` 的 `schema` 参数。**行级 schema 重定义依赖 field IDs（字段标识）**：写入时需用 `FIELD_IDS` 为列声明 ID，读取时才能按 ID 映射。

```sql
-- 写 Parquet 时声明 field IDs
COPY (SELECT 42::INTEGER AS i) TO 'integers.parquet' (FIELD_IDS {i: 0});

-- 读时重命名/新增列（按 field ID 寻址）
SELECT * FROM read_parquet('integers.parquet', schema = MAP {
    0: {name: 'renamed_i', type: 'BIGINT', default_value: NULL},
    1: {name: 'new_column', type: 'UTINYINT', default_value: 43}
});
```

`schema` 不可与 `union_by_name = true` 同时使用。

### 7.3.3 元数据查询

Parquet 文件内嵌丰富的统计与结构信息，DuckDB 提供一组元数据函数便于检视：

| 函数 | 作用 |
|---|---|
| `parquet_metadata('f.parquet')` | row group / 列级统计（stats_min、stats_max、stats_null_count、compression 等） |
| `parquet_schema('f.parquet')` | 内部 schema（name、type、field_id、logical_type 等） |
| `parquet_file_metadata('f.parquet')` | 文件级元数据（num_rows、num_row_groups、format_version、encryption_algorithm 等） |
| `parquet_kv_metadata('f.parquet')` | 自定义键值元数据（key、value 均为 BLOB） |
| `parquet_full_metadata('f.parquet')` | 上述四类合并为单行嵌套 struct |
| `parquet_bloom_probe(filename, col, value)` | 显示某值能否用 Bloom filter 排除对应 row group（返回 bloom_filter_excludes） |

这些函数都支持 glob（如 `parquet_metadata('data/*.parquet')`）并行查询多文件。Bloom filter 适用于 `TINYINT/UTINYINT/SMALLINT/USMALLINT/INTEGER/UINTEGER/BIGINT/UBIGINT`、`FLOAT/DOUBLE`、`VARCHAR`、`BLOB` 类型的高选择性查询裁剪。

### 7.3.4 加密

自 DuckDB v0.10.0 起，Parquet 读取与写入支持 Parquet Modular Encryption 规范：

```sql
-- 在会话内添加密钥（128/192/256 位，内存存储）
PRAGMA add_parquet_key('key256', '01234567891123450123456789112345');

-- 写加密文件
COPY tbl TO 'tbl.parquet' (ENCRYPTION_CONFIG {footer_key: 'key256'});

-- 读加密文件
SELECT * FROM read_parquet('tbl.parquet', encryption_config = {footer_key: 'key256'});
```

当前实现仅支持用 `footer_key` 加密 footer 与所有列，**不支持** `column_keys`（逐列不同密钥），使用后者会报 `Not implemented Error`。加密后的 Parquet 可读取 Arrow C++（如 PyArrow）写的"统一加密"文件。性能上，TPC-H SF1 的 `lineitem`（600 万行、15 列）读写约慢 2.5 倍。

## 7.4 JSON 读取

JSON 由 `json` 扩展支持（多数发行版默认捆绑，首次使用时自动加载）。DuckDB 既能读取 JSON 文件，也提供一整套 JSON 处理函数。

### 7.4.1 读取函数与格式

基础读取与建表：

```sql
SELECT * FROM 'todos.json';   -- 自动识别

SELECT * FROM read_json('todos.json',
    format = 'array',
    columns = {userId: 'UBIGINT', id: 'UBIGINT', title: 'VARCHAR', completed: 'BOOLEAN'});

-- 自动推断建表
CREATE TABLE todos AS SELECT * FROM 'todos.json';

-- v1.3.0 起返回 filename 虚拟列
SELECT filename, * FROM 'todos-*.json';
```

`read_json` 的 `format` 参数决定如何解析顶层结构，取值为 `auto` / `array` / `newline_delimited` / `unstructured`：

- `auto`：自动推断，多数情况下无需显式设置。
- `array`：顶层为 JSON 数组，每个元素为一个对象。
- `newline_delimited`（NDJSON）：每行一个 JSON 对象。
- `unstructured`：顶层为多个连续书写的独立 JSON 对象。

`records` 选项控制是否把 JSON 对象字段拆为各列（`records = true` 拆列，`records = false` 保留为 `STRUCT` 列）。若只需原始对象而不拆列，可用 `read_json_objects`（及其别名 `read_ndjson_objects`、`read_json_objects_auto`）。

### 7.4.2 关键读取参数

| 参数 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `format` | VARCHAR | `array` | `auto` / `unstructured` / `newline_delimited` / `array` |
| `maximum_object_size` | UINTEGER | `16777216` | 单个 JSON 对象的最大字节数（16 MB） |
| `map_inference_threshold` | BIGINT | `200` | 子字段数超过此值时推断为 `MAP` 而非 `STRUCT`；`-1` 关闭 MAP 推断 |
| `auto_detect` | BOOL | `true` | 是否自动检测键名与值类型 |
| `columns` | STRUCT | （空） | 指定键名与值类型；指定子集时仅返回这些列 |
| `sample_size` | UBIGINT | `20480` | 类型检测采样的对象数；`-1` 扫描整个文件 |
| `maximum_depth` | BIGINT | `-1` | 类型自动检测的最大嵌套深度；`-1` 完全检测 |
| `dateformat` / `timestampformat` | VARCHAR | `iso` | 日期 / 时间戳格式，`iso` 时自动推断 ISO 8601 |
| `compression` | VARCHAR | `auto_detect` | `none` / `gzip` / `zstd` / `auto_detect` |
| `ignore_errors` | BOOL | `false` | 忽略解析错误（仅 `format = 'newline_delimited'` 时） |
| `union_by_name` | BOOL | `false` | 多文件 schema 按列名统一 |
| `hive_partitioning` | BOOL | （自动检测） | Hive 分区路径解析 |

`maximum_object_size` 默认 16 MB（16,777,216 字节），限制单个 JSON 对象的体积；超出会在解析阶段报错。`map_inference_threshold` 默认 200：当某个对象的子字段超过 200 个时，DuckDB 推断其为 `MAP` 而非 `STRUCT`，以避免生成过于宽大的结构类型；设为 `-1` 可关闭 MAP 推断。

需留意 JSON 逻辑类型 `JSON` 的物理存储为 `VARCHAR`，且对空格与键顺序敏感——`'{"a":5}'::JSON` 与 `'{"a": 5}'::JSON` 不相等，重复键（如 `{"a":1,"a":2}`）亦被允许。其数组索引为 0-based，与 `ARRAY`/`LIST` 的 1-based 不同（遵循 PostgreSQL 约定）。

## 7.5 多文件与 glob、分区数据集

DuckDB 可同时读取多种类型（CSV/Parquet/JSON）的多个文件，途径有两种：**glob 语法**或**文件列表**。

### 7.5.1 Glob 通配符

| 通配符 | 含义 |
|---|---|
| `*` | 匹配任意数量任意字符（含无） |
| `**` | 匹配任意数量子目录（含无） |
| `?` | 匹配任意单个字符 |
| `[abc]` | 匹配括号内任一字符 |
| `[a-z]` | 匹配括号内范围内任一字符 |

```sql
SELECT * FROM 'dir/*.csv';         -- 当前目录
SELECT * FROM 'dir/**/*.csv';      -- 任意深度子目录
SELECT * FROM read_csv(['f1.csv', 'f2.csv']);
SELECT * FROM read_parquet(['folder1/*.parquet', 'folder2/*.parquet']);
```

S3 等远程读取因 HTTP 编码限制**不支持 `?` 通配符**。除 glob 外，也可直接传文件列表；列表与 glob 还能组合使用。合并的 Parquet 文件要求 schema 相同，否则改用 `union_by_name`。

若要查找匹配的文件名而非读取内容，可用 `glob` 表函数：

```sql
SELECT * FROM glob('*');
```

### 7.5.2 按列名合并：`union_by_name`

读取多文件时必须合并各自 schema，DuckDB 提供两种方式。默认按位置（union by position）对齐——以第一个文件的 schema 为准，后续文件按列位置对齐，适用于所有文件 schema 相同。当文件 schema 不一致（增列或改名）时，用 `union_by_name = true` 改为按列名构建统一 schema，缺失列补 `NULL`：

```sql
SELECT * FROM read_csv('flights*.csv');                   -- 按位置
SELECT * FROM read_csv('flights*.csv', union_by_name = true); -- 按名
```

按名合并会增加内存消耗，应在确有 schema 差异时才启用。

### 7.5.3 Hive 分区与分区键下推

分区是把大表按"分区键"拆成多文件、组织到多层文件夹的策略。DuckDB 原生支持 Hive 分区（`key=value` 目录名）的读取，并支持把过滤条件**下推（pushdown）** 到分区键，自动跳过无关文件。默认会尝试推断路径是否为 Hive 层级（查找 `'key' = 'value'` 模式），命中则自动开启 `hive_partitioning`：

```sql
SELECT * FROM read_parquet('orders/*/*/*.parquet', hive_partitioning = true);

-- 对分区键的过滤自动下推，仅读取匹配子目录
SELECT * FROM read_parquet('orders/*/*/*.parquet', hive_partitioning = true)
WHERE year = 2022 AND month = 11;
-- 仅读取 orders/year=2022/month=11/ 下文件
```

分区列的类型默认自动推断为 `DATE`、`TIMESTAMP` 或 `BIGINT`；可用 `hive_types` 显式指定逻辑类型，或用 `SET hive_types_autocast = 0;` 关闭自动推断。设置 `hive_partitioning = false` 则不附加分区列。

配合 v1.3.0 起自动提供的 `filename` 虚拟列，多文件与分区读取都能精确定位每一行数据的来源：

```sql
SELECT *, filename FROM read_parquet('orders/*/*/*.parquet', hive_partitioning = true);
```

对于分区写入（把数据落成 Hive 层级），可用 `COPY ... PARTITION_BY (...)`，目标参数为根目录名；每分区建议至少约 100 MB 数据以摊薄小文件开销，必要时用 `FILENAME_PATTERN` 定制文件名、用 `OVERWRITE_OR_IGNORE` 控制覆盖行为。

## 7.6 本章小结

本章建立了 DuckDB 数据导入的主线认知：文件即表，"直接查询文件"是贯穿全章的设计哲学。要点如下：

- **格式自动探测**基于扩展名（`.csv` / `.parquet` / `.json`）识别读取器；扩展名不标准时改用 `read_csv` / `read_parquet` / `read_json`；压缩文件（gzip、zstd）透明读取，`CTAS` 一句话即可把文件固化为持久表。
- **CSV** 依赖 sniffer 自动推断方言、类型与表头，`sample_size` 默认 20,480 行（`-1` 全量）；读取参数丰富，其中 `delimiter`、`date_format`、`timestamp_format` 为 `COPY` 专用别名；损坏文件可用 `ignore_errors` 跳过，或用 `store_rejects` 配合 `reject_errors` / `reject_scans` 临时表做系统化清洗。
- **Parquet** 的标志性能力是下推优化——projection 与 filter pushdown 借助 zonemap（min/max 统计）与 Bloom filter 裁剪 row group；按 field ID 的 `schema` 重定义可改名增列；元数据函数族（`parquet_metadata` / `parquet_schema` / `parquet_file_metadata` / `parquet_kv_metadata` / `parquet_bloom_probe` / `parquet_full_metadata`）便于检视；自 v0.10.0 起支持 Modular Encryption。
- **JSON** 经 `json` 扩展读取，`format` 区分 `auto` / `array` / `newline_delimited` / `unstructured`；`maximum_object_size` 默认 16 MB，`map_inference_threshold` 默认 200 控制 MAP 与 STRUCT 的推断边界，`union_by_name` 解决多文件 schema 差异。
- **多文件与分区**：glob（`*` / `**` / `?` / `[abc]`）与文件列表批量读取；`union_by_name` 按列名合并；Hive 分区自动检测并支持分区键下推（partition pruning）；`filename` 虚拟列（v1.3.0+）为每行标注来源文件，是溯源与排查的有力工具。

掌握这些直读能力后，数据工程中的"取数"环节几乎零门槛；下一章起将转向数据的写出与跨源交换。
