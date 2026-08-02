# 第 03 章 SQL 基础：数据类型与方言

对任何一门数据库系统而言，类型系统（type system）都是地基。DuckDB 作为一款进程内（in-process）、面向分析型负载（OLAP）的列式（columnar）数据库，其类型体系在 PostgreSQL 之上做了大量对数据分析与 DataFrame 交互友好的改造。理解了这些类型与方言细节，才能避免在建模、聚合与导入数据时踩入那些看似微小却代价高昂的陷阱。本章从标量类型讲起，逐步过渡到嵌套类型（nested type），再讨论类型转换规则与 NULL 三态逻辑（NULL three-valued logic），最后梳理 DuckDB 独有的"友好 SQL"（friendly SQL）语法糖。版本事实均以 DuckDB v1.5.5 为准。

## 3.1 数值类型与布尔

### 3.1.1 定宽整数

DuckDB 提供从 1 字节到 16 字节的定宽有符号整数，以及完整的无符号家族。常见用法中，`INTEGER` 在取值范围、存储与性能之间最为均衡，`SMALLINT` 仅在磁盘吃紧时考虑，`BIGINT` 与 `HUGEINT` 用于值域不足的场景。

| 类型 | 别名 | 字节 | 取值范围 |
| :--- | :--- | ---: | :--- |
| `TINYINT` | `INT1` | 1 | -2⁷ ~ 2⁷-1 |
| `SMALLINT` | `INT2`, `INT16`, `SHORT` | 2 | -2¹⁵ ~ 2¹⁵-1 |
| `INTEGER` | `INT4`, `INT32`, `INT`, `SIGNED` | 4 | -2³¹ ~ 2³¹-1 |
| `BIGINT` | `INT8`, `INT64`, `LONG` | 8 | -2⁶³ ~ 2⁶³-1 |
| `HUGEINT` | `INT128` | 16 | -2¹²⁷ ~ 2¹²⁷-1 |

无符号家族以 `U` 前缀命名：`UTINYINT`、`USMALLINT`、`UINTEGER`、`UBIGINT`、`UHUGEINT`。当数值超出 `HUGEINT` 上限时，可使用变长整数 `BIGNUM`，它用约 0.415×N+3 字节存储 N 位十进制数，最大值约 ±4.27e20201778——虽有上限，并非无限。

**别名陷阱是本章最需要警惕之处。** 有符号别名中的数字含义并不统一：`INT1`/`INT2`/`INT4` 的数字表示字节数（bytes），而 `INT16`/`INT32`/`INT64` 的数字表示位数（bits）；无符号别名 `UINT8`/`UINT16`/`UINT32`/`UINT64` 的数字则一律表示位数。于是极易混淆的两组是：`INT8` 并非 8 位整数，而是 8 字节（64 位）整数，等价于 `BIGINT`；`UINT8` 也不是 8 字节无符号整数，而是 8 位（1 字节）无符号整数，等价于 `UTINYINT`。下面这条查询能直观看清两者的体量差异：

```sql
SELECT typeof(1::INT8)  AS int8,
       typeof(1::UINT8) AS uint8;
-- BIGINT | UTINYINT
```

### 3.1.2 定点小数 DECIMAL

`DECIMAL(WIDTH, SCALE)`（别名 `NUMERIC`）表示精确定点小数，`WIDTH` 为总位数，`SCALE` 为小数位数。这里有三点与 PostgreSQL/Oracle 不同：

- 裸 `DECIMAL` 并非无约束类型，而是固定绑定到 `DECIMAL(18, 3)`；`DECIMAL()` 同样如此。只给 `WIDTH` 时 `SCALE` 默认 0（即 `DECIMAL(18)` = `DECIMAL(18,0)`，会截断小数）。
- `WIDTH` ∈ [1, 38]，`SCALE` ∈ [0, 38] 且 `SCALE ≤ WIDTH`，越界时绑定器（binder）直接报错而非截断。
- 除法产生近似浮点结果，而加、减、乘则返回能容纳精确结果的定点类型。

内部的存储宽度随 `WIDTH` 变化：1–4 位用 `INT16`，5–9 位用 `INT32`，10–18 位用 `INT64`，19–38 位用 `INT128`。由此带来一个性能陷阱：`WIDTH` 超过 19 的 `DECIMAL` 走 `INT128` 路径，运算明显慢于 `INT32`/`INT64`，除非确有需要，建议把 `WIDTH` 控制在 18 以内。

```sql
SELECT typeof(1.5::DECIMAL)      AS "DECIMAL",
       typeof(1.5::DECIMAL())    AS "DECIMAL()",
       typeof(1.5::DECIMAL(10))  AS "DECIMAL(10)",
       typeof(1.5::DECIMAL(10,)) AS "DECIMAL(10,)";
-- DECIMAL(18,3) | DECIMAL(18,3) | DECIMAL(10,0) | DECIMAL(10,0)
```

### 3.1.3 浮点与布尔

`FLOAT`（别名 `FLOAT4`、`REAL`）为单精度 4 字节，`DOUBLE`（别名 `FLOAT8`）为双精度 8 字节，通常遵循 IEEE 754。特殊值 `Infinity`、`-Infinity`、`NaN` 必须以引号包裹的字面量书写，可缩写为 `Inf`。需要精确金额且涉及加、减、乘的场景应优先选择 `DECIMAL`；浮点运算则须警惕精度陷阱，例如 `1.3::FLOAT - 0.7::FLOAT` 并不等于 `0.6::FLOAT`。

从浮点/定点转向整数时舍入方向也不同：浮点采用四舍五入到最近、平局向偶数（银行家舍入），而定点在平局时向远离零方向舍入。

```sql
SELECT 2.5::FLOAT::INTEGER;   -- 2 （round to even）
SELECT 2.5::DECIMAL::INTEGER; -- 3 （round away from zero）
```

`BOOLEAN`（别名 `BOOL`、`LOGICAL`）取值 `true`/`false`，第三态为 `NULL`（SQL 中的 "unknown"）。`WHERE`/`HAVING` 中仅 `true` 能通过，`false` 与 `NULL` 均被过滤，这与 3.4 节的三态逻辑一脉相承。

## 3.2 字符串、BLOB 与日期时间

### 3.2.1 字符串与二进制

`VARCHAR`（别名 `CHAR`、`BPCHAR`、`TEXT`、`STRING`）是 DuckDB 唯一的字符串类型，内部以 UTF-8 编码，原生支持 Unicode。值得注意的是 `VARCHAR(n)` 中的长度限制仅作兼容用途，不参与任何性能或存储优化；若要约束数据完整性，应当用 `CHECK` 约束：

```sql
CREATE TABLE strings (val VARCHAR CHECK (length(val) <= 10));
```

`BLOB`（别名 `BYTEA`、`BINARY`、`VARBINARY`）存放任意二进制数据，含义对数据库透明，最大约 4 GB。对于大对象，通常建议存于文件系统、库内只保留路径（`VARCHAR`）：

```sql
SELECT '\xAA'::BLOB;
SELECT 'AB'::BLOB;
```

### 3.2.2 日期时间家族

DuckDB 的日期时间类型相当丰富：`DATE` 为日历日期，`TIME`/`TIME WITH TIME ZONE` 表示一天中的时间，`TIMESTAMP` 系列包含朴素时间戳 `TIMESTAMP`（微秒）、`TIMESTAMP_NS`（纳秒）、`TIMESTAMP_MS`、`TIMESTAMP_S`，以及时区感知的 `TIMESTAMPTZ`。

理解 `TIMESTAMPTZ` 是关键。它**并不存储时区本身**，而是存储"自 Unix 纪元 1970-01-01 00:00:00+00 以来的非闰微秒数（INT64）"，即一个绝对时间点（instant）；"时区感知"仅体现在算术、分箱（binning）与字符串格式化时会使用**配置时区**（默认系统时区，常设为 UTC）。因此跨时区运算应显式用 `timezone()` 函数，而非依赖隐式解释。完整的时区名需依赖 ICU 扩展（Python/R/JDBC/ODBC 客户端已内置）：

```sql
SELECT
    timezone('America/Denver', TIMESTAMP '2001-02-16 20:38:40') AS aware,
    timezone('America/Denver', TIMESTAMPTZ '2001-02-16 04:38:40') AS naive;
```

`DATE` 与 `TIMESTAMP` 都支持 `epoch`、`infinity`、`-infinity` 等特殊值。`TIMESTAMP_NS WITH TIME ZONE` 并不存在——带纳秒精度又带 UTC 的 Parquet 列会被转为 `TIMESTAMPTZ` 并丢失纳秒精度，导入此类数据时需格外留意。

### 3.2.3 1-based 索引

DuckDB 对字符串、`LIST` 等采用**从 1 开始（1-based）**的索引规则，唯独 `JSON` 对象沿用 PostgreSQL 习惯使用 0-based 索引。这一差异在混合处理列表与 JSON 时极易出错：

```sql
SELECT ['first', 'second', 'third'][1];                       -- 'first'
SELECT '["first","second","third"]'::JSON -> 1;               -- "second"
```

## 3.3 嵌套与复杂类型

DuckDB 允许嵌套类型（nested type）任意深度嵌套，只要遵守各自的类型规则。理解每一种嵌套类型的语义边界，是写出正确且高效查询的前提。

`LIST` 是变长、同类型的有序序列，每行长度可以不同，这正是多数情形下需要的"数组"。`ARRAY` 则相反，是**定长**、同类型的序列，所有行长度与类型必须一致，适合存放词嵌入、图像嵌入等向量。这是与 PostgreSQL 最反直觉的一点：PG 的 `ARRAY` 是变长的，而 DuckDB 把"定长"赋予了 `ARRAY`、把"变长"赋予了 `LIST`。

```sql
SELECT [1, 2, 3];            -- LIST，每行长度可不同
SELECT [3, 2, 1]::INTEGER[3]; -- ARRAY，定长 3
```

`STRUCT` 是命名值字典，键为字符串、各值类型可不同，且每一行的键必须相同（键是 schema 的一部分），类似 PG 的 `ROW`。`MAP` 是键值字典，键同类型、值同类型，但各行键可以不同，适合 schema 未知或每行不同的场景。两者另有细微差别：`MAP` 的键区分大小写，而 `STRUCT`、`UNION` 的键不区分；`MAP` 缺键返回 `NULL`，`STRUCT` 缺键则报错。

`UNION` 是标签联合（tagged union），可持有多个候选项类型之一，并始终携带"tag"标识当前成员；由于不能无损地隐式转回成员类型，取值须用 `union_extract` 显式提取。`ENUM` 是字典类型，把低基数列的可能取值集中存放，列内仅保留数字引用，可显著节省存储并提速，但排序按枚举定义顺序而非字母序，比较时需注意类型安全。`UUID` 为 128 位唯一标识，内部以 `HUGEINT` 存储，可用 `uuid()`、`uuidv4()`、`uuidv7()` 等生成。

`GEOMETRY` 几何类型自 DuckDB v1.5 起成为内置类型（此前属于 `spatial` 扩展）；多数收益（存储优化、统计）需 storage version v1.5+ 的库才能享用，而距离、面积、相交等函数仍位于 `spatial` 扩展中：

```sql
CREATE TABLE geometries (id INTEGER, geom GEOMETRY);
INSERT INTO geometries VALUES (1, 'POINT (30 10)'),
       (2, 'POLYGON ((30 10, 40 40, 20 40, 10 20, 30 10))');
```

一个隐蔽的工程风险是：对嵌套类型列执行 `UPDATE` 时，DuckDB 实际上执行的是"先 DELETE 再 INSERT"。若表上建有 ART 索引（显式索引或主键/唯一约束），这一内部重写可能触发意料之外的约束冲突，设计更新逻辑时需有所防备。

## 3.4 类型转换与 NULL 三态逻辑

### 3.4.1 显式转换

DuckDB 提供 `CAST(expr AS type)` 与 `expr::type` 两种等价的显式转换写法。`TRY_CAST` 则在转换失败（如溢出）时不报错而返回 `NULL`，适合清洗来源不可信的数据：

```sql
SELECT CAST(999 AS TINYINT);      -- Conversion Error: value out of range for INT8
SELECT TRY_CAST(999 AS TINYINT);  -- NULL
```

隐式转换只在"不会失败"的组合间自动发生（如 `INTEGER`→`DOUBLE` 可行，反向不可）；可用 `can_cast_implicitly(source, target)` 检测。需要把多种类型合并为共同父类型时（如比较、`UNION`、嵌套构造），DuckDB 会采用更宽松的"组合转换（combination casting）"。

### 3.4.2 NULL 三态逻辑

SQL 中 `NULL` 表示"未知"，任何与 `NULL` 的比较——**包括 `NULL = NULL`——结果都是 `NULL`**，而非 `true`。这正是三态逻辑的核心：谓词可能为真、为假，或为未知。判定空值必须改用 `IS NULL`，而要把 `NULL` 当作相等来处理则用 `IS NOT DISTINCT FROM`：

```sql
SELECT NULL = NULL;                        -- NULL
SELECT NULL IS NOT DISTINCT FROM NULL;     -- true
```

聚合函数大多忽略 `NULL`（`min`/`max` 等），但 `first`、`last`、`list`、`array_agg` 不忽略，可用 `FILTER` 子句排除。输入含 `NULL` 的函数通常返回 `NULL`，例外是 `coalesce` 返回第一个非 `NULL` 值。

### 3.4.3 隐式转换的收紧

自 v0.10.0 起，DuckDB 不再允许向 `VARCHAR` 的任意隐式转换——早期版本中任何类型在绑定期都能隐式转为 `VARCHAR`，这一行为已被移除（可用 `old_implicit_casting` 配置回退，但已被标记为弃用）。数字字面量本身带有特殊的 `INTEGER_LITERAL` 类型，可隐式转为任意能容纳它的整数类型；要把它显式定型，仍需用 `::`：

```sql
SELECT 2.5::DECIMAL(10, 2);
```

## 3.5 友好 SQL 与方言特性

DuckDB 最讨数据分析者喜欢的，是大量为降低书写负担而设计的语法糖，其中部分（如 `GROUP BY ALL`）由 DuckDB 首创后被其他系统效仿。

类型推断（type inference）贯穿其中。例如省略 `SELECT` 直接以 `FROM` 开头即等价于 `SELECT *`，配合 `GROUP BY ALL` 可让分组列由 SELECT 列表自动推断，`ORDER BY ALL` 则对所有列排序以保证结果确定的顺序。字符串字面量也能隐式解析为目标类型——`d > '1992-01-01'` 对 `DATE` 列成立，因为 `STRING_LITERAL` 可隐式转为任意类型；但已是 `VARCHAR` 的值不能反向享受此便利，否则触发 binder 报错。

前缀别名（prefix alias）用 `x: 42` 代替 `42 AS x`，读起来更贴近"变量赋值"的直觉；尾逗号（trailing comma）在列列表、`LIST` 构造中均被允许；`INSERT INTO ... BY NAME` 按列名而非位置插入，`UNION BY NAME` 同理；`SELECT * EXCLUDE`/`REPLACE` 则可便捷地删减或替换列：

```sql
FROM tbl;                                   -- FROM-first，等价于 SELECT *
SELECT * FROM t GROUP BY ALL;               -- 自动推断分组列
SELECT x: 42, y: 'hello';                   -- 前缀别名
SELECT a, b EXCLUDE (c) FROM t;             -- 排除列
```

此外，列别名可在 `WHERE`/`GROUP BY`/`HAVING` 中直接引用，`COLUMNS()` 表达式可配合正则批量处理多列，可复用列别名（lateral column aliases）让后续表达式直接引用前面刚定义的别名——这些特性让 DuckDB 在处理宽表与探索性查询时格外顺手。

## 3.6 本章小结

本章梳理了 DuckDB 类型系统与方言的关键事实，几条真正值得牢记的要点如下：

- **别名陷阱**：`INT8` 是 8 字节（= `BIGINT`），`UINT8` 是 8 位（= `UTINYINT`），混用会酿成大错；无符号别名 `UINTn` 的数字表示位数，有符号 `INTn`（小写）多表示字节数。
- **DECIMAL 默认 (18,3)**：裸 `DECIMAL` 不是无约束类型，`WIDTH`/`SCALE` 越界直接报错；`WIDTH > 19` 走 `INT128` 性能明显下降，建议控制在 18 以内。
- **TIMESTAMPTZ 不存时区**：它只存纪元微秒，显示与算术依赖配置时区；不存在 `TIMESTAMP_NS WITH TIME ZONE`，纳秒+UTC 会被降级。
- **LIST 与 ARRAY 语义相反**：DuckDB 的 `LIST` 变长、`ARRAY` 定长，恰好与 PostgreSQL 相反。
- **NULL 三态逻辑**：`NULL = NULL` 的结果是 `NULL`，判等须用 `IS NULL` / `IS NOT DISTINCT FROM`；自 v0.10.0 起不再允许任意隐式转 `VARCHAR`。
- **嵌套类型 UPDATE 实为 DELETE+INSERT**：带 ART 索引/主键/唯一约束时需警惕意外冲突。
- **友好 SQL**：自动类型推断、`FROM`-first、`GROUP BY ALL`、前缀别名等语法糖，是 DuckDB 提升分析效率的利器。

下一章将从这些基础类型出发，进入表的创建、约束与模式的实践。
