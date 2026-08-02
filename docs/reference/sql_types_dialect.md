# DuckDB 数据类型与 SQL 方言 深度研读笔记（基于官方文档 v1.5.5 / current 分支）

> 本笔记整理自 `duckdb-web-main/docs/current/sql/data_types/` 与 `duckdb-web-main/docs/current/sql/dialect/` 下的全部 `.md` 文件。
> 已忽略 Jekyll frontmatter（`--- ... ---`）与 Liquid 标签（`{% link ... %}` / `{% include ... %}`）。
> 文档版本对应 DuckDB 1.5.x（current）。英文术语保留原样。

---

## 1. 概述（Overview of DuckDB's Type System）

DuckDB 的类型系统分为三大类：

1. **通用标量类型（General-Purpose / Scalar types）**：数字、布尔、字符串、二进制、日期时间、UUID、BIT、JSON、ENUM 等。
2. **嵌套 / 组合类型（Nested / Composite types）**：`ARRAY`、`LIST`、`MAP`、`STRUCT`、`UNION`，以及半结构化的 `VARIANT`。
3. **扩展 / 专用类型**：如 `GEOMETRY`（自 v1.5 成为内置类型，多数能力仍依赖 `spatial` 扩展）。

**关键特性：**

- 类型之间支持显式（`CAST` / `::`）与隐式（implicit）转换，详见 `typecasting.md`。
- 嵌套类型可**任意深度嵌套**，只要遵守各自的类型规则（`overview.md` 的 Nesting 小节）。
- 嵌套类型列做 UPDATE 时，DuckDB 实际执行“先 DELETE 再 INSERT”；若表上有 ART 索引（显式索引或主键/唯一约束），可能导致意外的约束冲突（`overview.md` Notes）。
- 数据类型选择对性能影响很大，官方建议参考 Performance Guide（Schema 部分）。
- DuckDB 的 SQL 方言基于 PostgreSQL，但做了若干对数据分析/DataFrame 交互更友好的差异调整（`dialect/overview.md`）。

**通用类型总览表（节选自 `overview.md`）：**

| Name | Aliases | 说明 |
| :--- | :--- | :--- |
| `BIGINT` | `INT8`, `LONG` | 8 字节有符号整数 |
| `BIT` / `BITSTRING` | | 0/1 字符串 |
| `BLOB` | `BYTEA`, `BINARY`, `VARBINARY` | 变长二进制 |
| `BIGNUM` | | 变长整数（超大数） |
| `BOOLEAN` | `BOOL`, `LOGICAL` | 逻辑布尔 |
| `DATE` | | 日历日期 |
| `DECIMAL(p,s)` | `NUMERIC(p,s)` | 定点数，默认 (18,3) |
| `DOUBLE` | `FLOAT8` | 双精度浮点 |
| `FLOAT` | `FLOAT4`, `REAL` | 单精度浮点 |
| `HUGEINT` | | 16 字节有符号整数 |
| `INTEGER` | `INT4`, `INT`, `SIGNED` | 4 字节整数 |
| `INTERVAL` | | 时间间隔 |
| `JSON` | | JSON 对象（需 json 扩展） |
| `SMALLINT` | `INT2`, `SHORT` | 2 字节整数 |
| `TIME` | | 一天中的时间（无时区） |
| `TIMESTAMP WITH TIME ZONE` | `TIMESTAMPTZ` | 带时区时间戳 |
| `TIMESTAMP` | `DATETIME` | 时间戳 |
| `TINYINT` | `INT1` | 1 字节整数 |
| `UBIGINT` / `UHUGEINT` / `UINTEGER` / `USMALLINT` / `UTINYINT` | | 无符号整数族 |
| `UUID` | | 128 位唯一标识 |
| `VARCHAR` | `CHAR`, `BPCHAR`, `TEXT`, `STRING` | 变长字符串 |

**嵌套类型对照表（`overview.md`）：**

| Name | 说明 | 列内规则 | 值构造 | DDL/CREATE |
| :--- | :--- | :--- | :--- | :--- |
| `ARRAY` | 定长、同类型有序序列 | 每行长度相同、类型相同 | `[1,2,3]` | `INTEGER[3]` |
| `LIST` | 变长、同类型有序序列 | 每行长度可不同 | `[1,2,3]` | `INTEGER[]` |
| `MAP` | 键值字典，键同类型、值同类型 | 各行键可不同 | `map([1,2],['a','b'])` | `MAP(INTEGER, VARCHAR)` |
| `STRUCT` | 命名值字典，键为字符串，各值类型可不同 | 每行键必须相同 | `{'i':42,'j':'a'}` | `STRUCT(i INTEGER, j VARCHAR)` |
| `UNION` | 多个候选项类型的“标签联合” | 每行可设置不同成员 | `union_value(num := 2)` | `UNION(num INTEGER, text VARCHAR)` |
| `VARIANT` | 半结构化，每行自带类型信息 | 每行类型可不同 | `42::VARIANT` | `VARIANT` |

**嵌套类型键名大小写规则（`overview.md` / `keywords_and_identifiers.md`）：**

- `MAP` 的键**区分大小写**。
- `STRUCT` 与 `UNION` 的键**不区分大小写**（例如 `{'key1':1} = {'KEY1':1}` 为 true）。

---

## 2. 所有数据类型逐类说明

### 2.1 数值类型（Numeric Types，`numeric.md`）

#### 2.1.1 定宽整数（Fixed-Width Integer Types）

存储整型（无小数部分的数字）。超出范围赋值会报错。

| Name | Aliases | Min | Max | 字节 |
| :--- | :--- | ---: | ---: | ---: |
| `TINYINT` | `INT1` | -2^7 | 2^7-1 | 1 |
| `SMALLINT` | `INT2`, `INT16`, `SHORT` | -2^15 | 2^15-1 | 2 |
| `INTEGER` | `INT4`, `INT32`, `INT`, `SIGNED` | -2^31 | 2^31-1 | 4 |
| `BIGINT` | `INT8`, `INT64`, `LONG` | -2^63 | 2^63-1 | 8 |
| `HUGEINT` | `INT128` | -2^127 | 2^127-1 | 16 |
| `UTINYINT` | `UINT8` | 0 | 2^8-1 | 1 |
| `USMALLINT` | `UINT16` | 0 | 2^16-1 | 2 |
| `UINTEGER` | `UINT32` | 0 | 2^32-1 | 4 |
| `UBIGINT` | `UINT64` | 0 | 2^64-1 | 8 |
| `UHUGEINT` | `UINT128` | 0 | 2^128-1 | 16 |

**重要陷阱（`UINT8` vs `INT8`）：** `INT8` 是 **64 位（8 字节）** 整数，并不是 8 位有符号整数；8 位有符号是 `TINYINT`/`INT1`。无符号别名 `UINT8`/`UINT16`/... 中的数字表示**位数**（bits），而有符号别名 `INT1`/`INT2`/`INT4` 中的数字表示**字节数**（bytes），`INT16`/`INT32`/`INT64` 又表示位数。详见 `sql_quirks.md` 与 `numeric.md` 提示。

**默认建议：** `INTEGER` 在范围/存储/性能上最平衡；磁盘吃紧才用 `SMALLINT`；范围不足时用 `BIGINT`/`HUGEINT`。

#### 2.1.2 变长整数 `BIGNUM`（Variable-Length Integers）

当数值超过 `HUGEINT` 上限时可用。`BIGNUM` 存正数，用 3 个额外字节存长度与符号位。N 位十进制数约需 `0.415 * N + 3` 字节。最大值约 ±4.27e20201778（约 2020 万位十进制数字，单值占用高达 8 MB）。**有上限，并非无限。**

#### 2.1.3 定点小数 `DECIMAL` / `NUMERIC`（Fixed-Point Decimals）

`DECIMAL(WIDTH, SCALE)`（别名 `NUMERIC(WIDTH, SCALE)`）表示精确定点小数。`WIDTH` = 总位数，`SCALE` = 小数位数。

- 默认 `DECIMAL(18, 3)`：`DECIMAL`、`DECIMAL()` 都绑定到 (18,3)。
- 只给 `WIDTH` 时 `SCALE` 默认为 0，即 `DECIMAL(18)` = `DECIMAL(18,0)`（截断小数）。
- 写法 `DECIMAL(10,)`、`DECIMAL(10,)` 均合法。

```sql
SELECT
    typeof(1.5::DECIMAL)      AS "DECIMAL",
    typeof(1.5::DECIMAL())    AS "DECIMAL()",
    typeof(1.5::DECIMAL(10))  AS "DECIMAL(10)",
    typeof(1.5::DECIMAL(10,)) AS "DECIMAL(10,)";
-- DECIMAL(18,3) | DECIMAL(18,3) | DECIMAL(10,0) | DECIMAL(10,0)
```

**范围约束（binder 直接报错，不截断）：**

```sql
SELECT 1::DECIMAL(39, 2);        -- Binder Error: width must be between 1 and 38
SELECT 1::DECIMAL(18, 20);       -- Binder Error: scale cannot be greater than width
SELECT 1::DECIMAL(18, -1);       -- Binder Error: scale must be between 0 and 38
```

- `WIDTH` ∈ [1, 38]，`SCALE` ∈ [0, 38] 且 `SCALE <= WIDTH`。
- 与 PostgreSQL/Oracle 不同：**不支持负 SCALE**，且裸 `DECIMAL` 不是“无约束”类型（PG/Oracle 中是无约束，DuckDB 固定为 (18,3)）。
- 加/减/乘返回能容纳精确结果的定点类型，若所需 WIDTH 超过 38 则报错。
- **除法**产生近似浮点结果（见 2.1.4）。
- 内部表示依 WIDTH：

| Width | Internal | 字节 |
| :--- | :--- | ---: |
| 1–4 | `INT16` | 2 |
| 5–9 | `INT32` | 4 |
| 10–18 | `INT64` | 8 |
| 19–38 | `INT128` | 16 |

> **性能陷阱：** WIDTH > 19 的 DECIMAL 使用 `INT128`，运算明显慢于 `INT32`/`INT64`。建议 WIDTH ≤ 18，除非确有需要。

#### 2.1.4 浮点类型 `FLOAT` / `DOUBLE`（Floating-Point Types）

| Name | Aliases | 说明 |
| :--- | :--- | :--- |
| `FLOAT` | `FLOAT4`, `REAL` | 单精度（4 字节） |
| `DOUBLE` | `FLOAT8` | 双精度（8 字节） |

- 通常遵循 IEEE 754。`FLOAT` 范围约 1E-37 ~ 1E+37、精度 ≥ 6 位；`DOUBLE` 范围约 1E-307 ~ 1E+308、精度 ≥ 15 位。越界通常转为 0 或 ±Infinity。
- 特殊值：`Infinity`、`-Infinity`、`NaN`。**字面量须加引号**，可缩写为 `Inf`，大小写不限：

```sql
SELECT sqrt(2) > '-inf', 'nan' > sqrt(2);  -- true, true
```

- 与 PG 差异：DuckDB 对“除零”等遵循 IEEE 754（返回 Infinity/NaN），而 PG 报错（详见第 5 节后文 PostgreSQL 兼容对照）。
- DuckDB 对浮点特殊值的两处偏离 IEEE 754：`NaN` 与 `NaN` 相等且大于任何其它浮点数；`sqrt`/`sin`/`asin` 等对定义域外输入**抛错**而非返回 NaN。

**浮点 vs 定点的选择建议：** 需要精确（金额）且加减小乘精确 → 用 `DECIMAL`/`NUMERIC`；追求速度或复杂数学计算 → 用浮点，但需警惕精度陷阱（如 `1.3::FLOAT - 0.7::FLOAT != 0.6::FLOAT`，而 `(10::FLOAT/3)*3 = 10` 但 `(10::DECIMAL/3)*3 = 9.999`）。

#### 2.1.5 UUID（`numeric.md` 节 “Universally Unique Identifiers”）

128 位，内部以 `HUGEINT` 存储；打印为小写十六进制、以 `-` 分段（36 字符），例如 `4ac7a9e9-607c-4c8a-84f3-843f0191e3fd`。

- 生成 `UUIDv4`：`uuid()` / `uuidv4()` / `gen_random_uuid()`。
- 生成 `UUIDv7`：`uuidv7()`；提取时间戳：`uuid_extract_timestamp(uuidv7())`；查看版本：`uuid_extract_version(uuid)`。

```sql
SELECT uuid_extract_timestamp(uuidv7()) AS ts;
-- 2025-04-19 15:51:20.07+00
```

#### 2.1.6 舍入规则（Rounding，`numeric.md`）

从浮点/定点转整数时舍入：

- `FLOAT`/`DOUBLE` → 整数：**四舍五入到最近整数，平局（.5）向偶数舍入**（银行家舍入）：
  ```sql
  SELECT 2.5::FLOAT::INTEGER;  -- 2
  ```
- `DECIMAL` → 整数：**平局向远离零方向舍入**：
  ```sql
  SELECT 2.5::DECIMAL::INTEGER;         -- 3
  SELECT 2.5::INTEGER;                  -- 3 （数字字面量按 DECIMAL 处理）
  ```
- 非默认舍入请用 `ceil`、`floor`、`round`、`round_even`。

### 2.2 布尔类型（Boolean，`boolean.md`）

| Name | Aliases |
| :--- | :--- |
| `BOOLEAN` | `BOOL`, `LOGICAL` |

- 取值 `true` / `false`，第三态 `NULL`（SQL 中的 “unknown”）。
- 字面量 `true` / `false`；更多时候由比较/连接运算产生（如 `i > 10`）。
- `WHERE`/`HAVING` 中仅 `true` 通过，`false`/`NULL` 被过滤。

**真值表：**

`AND`（x AND y）：

| X | true | false | NULL |
| :--- | :--- | :--- | :--- |
| true | true | false | NULL |
| false | false | false | false |
| NULL | NULL | false | NULL |

`OR`（x OR y）：

| X | true | false | NULL |
| :--- | :--- | :--- | :--- |
| true | true | true | true |
| false | true | false | NULL |
| NULL | true | NULL | NULL |

### 2.3 字符串类型（Text，`text.md`）

| Name | Aliases | 说明 |
| :--- | :--- | :--- |
| `VARCHAR` | `CHAR`, `BPCHAR`, `STRING`, `TEXT` | 变长字符串 |
| `VARCHAR(n)` | `CHAR(n)`... | 长度限制**无效**（仅为兼容） |

- 内部 UTF-8 编码，支持 Unicode。
- 指定长度（`VARCHAR(n)`）**不参与**性能/存储优化，仅兼容其它系统。如需限制长度做数据完整性，用 `CHECK` 约束：
  ```sql
  CREATE TABLE strings (val VARCHAR CHECK (length(val) <= 10));
  ```
- 可指定压缩类型：`CREATE TABLE tbl (s VARCHAR USING COMPRESSION zstd);`
- 特殊字符：用 escape string（`e'...'`）或 dollar-quoted（`$$...$$`），或 `|| chr(10)` 拼接。

```sql
SELECT 'Hello' || chr(10) || 'world' AS msg;
```

### 2.4 BLOB 类型（Binary Large Object，`blob.md`）

| Name | Aliases |
| :--- | :--- |
| `BLOB` | `BYTEA`, `BINARY`, `VARBINARY` |

- 任意二进制数据，含义对数据库透明（常用于图片等）。最大约 4 GB，但大对象通常建议存文件系统、库内只存路径（VARCHAR）。
- 字面量：`'\xAA'::BLOB`（单字节 170）、`'\xAA\xAB\xAC'::BLOB`、`'AB'::BLOB`。

```sql
SELECT '\xAA'::BLOB;
SELECT 'AB'::BLOB;
```

### 2.5 日期 / 时间 / 时间戳（`date.md`, `time.md`, `timestamp.md`, `interval.md`）

#### 2.5.1 `DATE`（`date.md`）

- 日历日期（年/月/日），按 ISO 8601（`YYYY-MM-DD`）。
- 关键字写法：`DATE '1992-09-20'`。
- 特殊值：`epoch`（1970-01-01）、`infinity`、`-infinity`。`∞`/`-∞` 在系统内特殊表示且原样显示；`epoch` 仅为可读简写，读入时即转换。

```sql
SELECT '-infinity'::DATE, 'epoch'::DATE, 'infinity'::DATE;
-- -infinity | 1970-01-01 | infinity
```

#### 2.5.2 `TIME` / `TIMETZ` / `TIME_NS`（`time.md`）

| Name | Aliases | 说明 |
| :--- | :--- | :--- |
| `TIME` | `TIME WITHOUT TIME ZONE` | 一天中的时间 |
| `TIMETZ` | `TIME WITH TIME ZONE` | 带时区偏移的时间 |
| `TIME_NS` | | 纳秒精度时间 |

- 格式 ISO 8601：`hh:mm:ss[.zzzzzz[zzz]][+-TT[:tt]]`。
- `TIMETZ '...-02:00'` 显示时会换算到配置时区（默认 +00）。
- `TIME_NS` 可从 Parquet 的 `TIME(NANOS)` 读取。
- **警告：** 仅当可以忽略日期部分时才用 `TIME`，多数场景应使用 `TIMESTAMP` 类型。

#### 2.5.3 `TIMESTAMP` 家族（`timestamp.md`）

| Name | Aliases | 说明 |
| :--- | :--- | :--- |
| `TIMESTAMP_NS` | | 朴素时间戳，纳秒精度 |
| `TIMESTAMP` | `DATETIME`, `TIMESTAMP WITHOUT TIME ZONE` | 朴素时间戳，微秒精度 |
| `TIMESTAMP_MS` | | 毫秒精度 |
| `TIMESTAMP_S` | | 秒精度 |
| `TIMESTAMPTZ` | `TIMESTAMP WITH TIME ZONE` | 时区感知时间戳，微秒精度 |

- 创建：`TIMESTAMP '1992-09-20 11:30:00.123456789'`（超出精度的小数位被忽略）。
- **`TIMESTAMPTZ` 不存储时区本身**，而是存“自 Unix 纪元 1970-01-01 00:00:00+00 以来的非闰微秒数（INT64）”，即一个绝对时间点（instant）。仅“时区感知”体现在算术/分箱（binning）/字符串格式化时使用**配置时区**（默认系统/UTC）。
- 无 `TIMESTAMP_NS WITH TIME ZONE`；带纳秒+UTC 的 Parquet 列会被转为 `TIMESTAMPTZ` 并**丢失纳秒精度**（`timestamp.md` 警告）。
- 字符串 ↔ 时间戳转换规则：
  - 无 UTC 偏移/时区名的字符串 ↔ `WITHOUT TIME ZONE`：明确直接。
  - 带偏移/时区名的字符串 ↔ `WITH TIME ZONE`：明确，但需 `ICU` 扩展处理时区名。
  - 无偏移字符串 → `WITH TIME ZONE`：按配置时区解释。
  - 带偏移字符串 → `WITHOUT TIME ZONE`：忽略偏移/时区。
  - 带 UTC 之外时区名的字符串 → `WITHOUT TIME ZONE`：**报错**。
  - 两类时间戳互转用配置时区；可用 `timezone()` 函数指定其它时区。

```sql
SELECT
    timezone('America/Denver', TIMESTAMP '2001-02-16 20:38:40') AS aware1,
    timezone('America/Denver', TIMESTAMPTZ '2001-02-16 04:38:40') AS naive1;
```

- 特殊值同 DATE：`epoch` / `infinity` / `-infinity`。
- 时区支持依赖 **ICU 扩展**（Python/R/JDBC/ODBC 客户端已内置）；设置：`INSTALL icu; LOAD icu; SET TimeZone = 'America/Los_Angeles';`。可用 `pg_timezone_names()` 查可用时区、`icu_calendar_names()` 查可用日历，`SET Calendar = 'japanese';` 切非公历。
- 相关配置：`TimeZone`（默认如 `Europe/Amsterdam`）、`Calendar`（默认 `gregorian`）。

#### 2.5.4 `INTERVAL`（`interval.md`）

表示时间段，可加减到 `DATE`/`TIMESTAMP`/`TIMESTAMPTZ`/`TIME`。

- 三个独立基单位：**months / days / microseconds**（因月≠固定天数，天≠固定微秒数，因夏令时）。
- 构造：
  ```sql
  SELECT INTERVAL 1 YEAR,                 -- 存为 12 months
         INTERVAL (random()*10) YEAR,     -- 变量需括号，存为整数 months
         INTERVAL '1 month 1 day',        -- 多单位需字符串
         '16 months'::INTERVAL,
         '48:00:00'::INTERVAL;            -- HH:MM:SS，存为微秒
  ```
- **陷阱：** 用单位关键字时**小数值截断为整数**（除非是 `SECONDS`/`MILLISECONDS`）：`INTERVAL '1.5' YEARS` → 12 months。要更高精度请用 `INTERVAL '1.5 years'` 或更小单位。
- `datepart` 拆解：months → 年+月；microseconds → 时+分+微秒（**不是秒**）；days 不再拆分。
- 加减：`DATE + INTERVAL` 即便无微秒分量也返回 `TIMESTAMP`（等价于先把 DATE 补 00:00:00）。
- 两 `TIMESTAMP` 相减得到 `INTERVAL`，**只含 days 和 microseconds**；两 `DATE` 相减返回整数天数（非 INTERVAL）。
- **相等/排序陷阱：** 比较时把 days 视作 24h、months 视作 30 天换算成总微秒。于是 `INTERVAL 30 DAYS = INTERVAL 1 MONTH`（true），但 `DATE '2020-01-01' + INTERVAL 30 DAYS != DATE '2020-01-01' + INTERVAL 1 MONTH`。`datediff('day', ...)` 与 `datepart('day', ts1-ts2)` 结果也可不同（前者数边界、后者数微秒/天）。
- `INTERVAL` 差值不等同于 `datediff` 的分区边界数（详见 `interval.md` 警告示例）。

### 2.6 复杂 / 嵌套类型

#### 2.6.1 `LIST`（`list.md`）

变长、同类型有序序列（类似 PG 的 `ARRAY`，但 DuckDB 用 `LIST` 术语；同时提供 `array_*` 兼容函数）。

- 构造：`[1,2,3]`、`list_value(1,2,3)`；聚合：`list(...)`。
- 列定义：`INTEGER[]`、`VARCHAR[]`。
- 取值：`[i]`（1 基）、负索引、`[a:b]` 切片、`list_extract`/`array_slice`（兼容别名）。
  ```sql
  SELECT ['a','b','c'][3], ['a','b','c'][-1], ['a','b','c'][1:2];
  -- 'c' | 'c' | ['a','b']
  ```
- 比较：位置式字典序；`NULL` 按 PG 语义处理；低层嵌套用于打破平局。
- 可嵌套（含 `NULL`）：`[['duck','goose','heron'], NULL, ['frog','toad'], []]`。

#### 2.6.2 `ARRAY`（`array.md`）

**定长**、同类型序列。所有行长度/类型必须一致。适合存向量（词嵌入、图像嵌入）。

- 构造：`array_value(1,2,3)`；列定义 `INTEGER[3]`；`[3,2,1]::INTEGER[3]`。
- 可隐式转 `LIST`（再用 `[i]`/`list_extract`）；`LIST`→`ARRAY` 需维度匹配。
- 取值同 LIST；切片返回 `LIST`。
- 有 `array_cross_product`、`array_cosine_similarity` 等原生函数，`LIST` 函数也适用。
- 排序用字典序；`NULL` 大于一切且彼此相等。
- **注意：** PG 的 `ARRAY` 是变长，DuckDB 的 `ARRAY` 是定长。

#### 2.6.3 `MAP`（`map.md`）

有序键值对；键同类型、值同类型（键与值类型可不同）。**各行键可不同** → 适合 schema 未知/每行不同的场景。

- 构造：`MAP {'key1':10,'key2':20}`、`map_from_entries([(...),(...)])`、`MAP(['k1','k2'], [10,20])`。
- 列定义：`MAP(INTEGER, DOUBLE)`。
- 取值：`map_extract_value` 或 `['key']`（无此键返回 `NULL`）；`map_extract`/`element_at` 返回**单元素列表**（无键返回空列表 `[]`）。
- **陷阱：** 键类型不对 → 报错；键类型对但不存在 → `NULL`（不像 STRUCT 报错）。
- 键**区分大小写**：`MAP(['key1'],[1]) = MAP(['KEY1'],[1])` → false。
- `MAP` 不允许重复键。

#### 2.6.4 `STRUCT`（`struct.md`）

有序命名列（entries），键为字符串，各值类型可不同。**每行键必须相同**（键是 schema 的一部分）。类似 PG 的 `ROW`，但 DuckDB 要求同行同键以换取向量化性能与类型一致。

- 构造：`struct_pack(key1 := 'value1', key2 := 42)`、`{'key1':'value1','key2':42}`、`row(...)`、行变量。
- 取值：点号 `a.x`、括号 `a['x space']`（单引号，常量）、`struct_extract`；空格键用双引号 `a."x space"`。
- 展开：`unnest(a)` 或 `a.*`（支持 `EXCLUDE`/`REPLACE`，但仅限顶层 struct 列与非聚合表达式）。
- 点号优先级（歧义解析）：先找列，再找列内的 struct 键（`struct.md` 的 Dot Notation Order of Operations 详述 0/1/2+ 个点的情况）。
- 更新字段：`struct_update({'a':1,'b':2}, b := 3, c := 4)`；`struct_insert` 仅新增不可改。
- 比较：字典序，`NULL` 视为大于一切；不同类型 struct 会按“组合转换”规则转为键的并集。
- **v1.3.0 起** 可用 `ALTER TABLE ... ADD/DROP/RENAME COLUMN s.<field>` 修改 struct 子 schema（例：`ALTER TABLE test ADD COLUMN s.k INTEGER; FROM test;`）。
- 陷阱：struct 间转换至少需要一个同名字段；key 用 `row` 函数构造无名 struct 不能用于建表（`Invalid Input Error: A table cannot be created from an unnamed struct`）。

#### 2.6.5 `UNION`（`union.md`）

**标签联合（tagged union）**：可持有多个候选项类型之一，始终带“tag”判别当前成员（类似 C++ `std::variant`、Rust `Enum`）。至少 1 个成员，tag 名必须唯一，最多 256 个成员。底层基于 `STRUCT` 实现（tag 为首个 entry）。

- 构造：`union_value(num := 2)`、或成员类型隐式转换。
- 取值：`union_extract(u, 'str')` 或点号 `u.str`；`union_tag(u)` 返回当前 tag（ENUM）。
- 转换：
  - 任意类型可隐式转为“包含该类型的 UNION”（候选多时按隐式转换优先级，仍歧义则报错；相同类型多成员时用 `union_value(tag := ...)` 消歧）。
  - UNION→UNION：源是目标的子集（所有 tag 存在、类型可隐式转换）才可转，即**对成员协变**。
  - **不能**一般地把 UNION 隐式转回成员类型（会丢信息），须用 `union_extract` 显式取；唯一例外是转 `VARCHAR`（各成员用各自 VARCHAR cast）。
- 比较/排序：同 STRUCT 语义，先按 tag 排序（因 tag 是首个 entry）。

#### 2.6.6 `VARIANT`（`variant.md`）

半结构化类型，每行自带类型信息（受 Snowflake VARIANT 启发，Parquet 自 2025 起支持）。与 `JSON`（以文本存储）不同，`VARIANT` 二进制存储、压缩与查询性能更好。

```sql
CREATE TABLE events (id INTEGER, data VARIANT);
INSERT INTO events VALUES
    (1, 42::VARIANT),
    (2, 'hello world'::VARIANT),
    (3, [1,2,3]::VARIANT),
    (4, {'name':'Alice','age':30}::VARIANT);
```

- 查底层类型：`variant_typeof(data)` → 如 `INT32`/`VARCHAR`/`ARRAY(3)`/`OBJECT(name, age)`。
- 取值：点号 `data.name` 或 `variant_extract(data, 'name')`。
- Parquet 支持读写，含 **shredding**（按首行组结构自动拆为类型化列，或用 `SHREDDING {...}` 复制选项显式指定），并可读取 Snowflake 生成的 shredded VARIANT。

#### 2.6.7 `ENUM`（`enum.md`）

字典类型，存某列全部可能唯一字符串值（低基数列可大幅省存储、提速，列内只存字典中的数字引用）。

- 创建：
  ```sql
  CREATE TYPE mood AS ENUM ('sad','ok','happy');
  CREATE TYPE region AS ENUM (SELECT region FROM sales_data);  -- 去重、忽略 NULL
  SELECT 'clubs'::ENUM ('spades','hearts','diamonds','clubs');  -- 匿名 enum（转换时即时建）
  ```
- 使用：建表后可在任何内置类型可用的地方使用；自动转 `VARCHAR`。
- 值**区分大小写**：`'maltese'::breed = 'Maltese'::breed` → false；`'MALTESE'::breed` → 报错。
- **排序陷阱：** 按枚举定义顺序排序（非字母序）：`'low'::priority < 'high'::priority` 为 true，但 `'low'::VARCHAR < 'high'::VARCHAR` 为 false。
- 与 `VARCHAR`/其它 enum 比较时会先转 `VARCHAR` 做字典序比较 → 可能漏结果（例：`priority_level >= 'medium'` 漏掉 `'high'`）。要做类型安全比较须显式 `::priority`。
- **重要陷阱：** 常量字符串与 enum 比较会被优化为 `try_cast(常量, enum)`，故比较一个根本不存在的字符串只返回 false 不报错；要强制类型安全请显式 `::mood`（会 Conversion Error）。
- 函数：`enum_range(NULL::mood)` → `[sad, ok, happy]`。删除：`DROP TYPE <enum>`，当前即使表在用也可删（行为未来可能改为需 `CASCADE`）。

#### 2.6.8 `BITSTRING` / `BIT`（`bitstring.md`）

| Name | Aliases |
| :--- | :--- |
| `BITSTRING` | `BIT` |

- 变长 0/1 字符串；每 8 位占 1 字节 + 元数据；默认不补零；大小限制同 BLOB。
- 创建：`'101010'::BITSTRING`；`bitstring('0101011', 12)`（左补零）；整数/浮点也可转 BITSTRING（`123::BITSTRING`）。

### 2.7 `GEOMETRY`（几何类型，`geometry.md` 节选）

- `GEOMETRY` 在 **DuckDB v1.5 成为内置类型**（此前属于 `spatial` 扩展）。多数收益（存储优化、统计）仅对 storage version v1.5+ 的库可用；相关函数（距离、面积、相交等）仍在 `spatial` 扩展。
- 7 种形状：Point / LineString / Polygon / MultiPoint / MultiLineString / MultiPolygon / GeometryCollection。文本用 WKT（Well-Known Text），可来回 cast。
- 支持多维度顶点：Z（高程）、M（测量）、ZM；同一几何体内维度须一致（否则 `Invalid Input Error: Geometry has inconsistent Z/M dimension`）。
- 可为“空”（`POINT EMPTY` 等）。
- 存储：字节序列（类 BLOB），v1.5 起基于小端 WKB；支持 **shredding** 压缩（同类型同维度的列拆为 STRUCT/LIST/DOUBLE 段独立压缩）。

### 2.8 字面量类型（Literal Types，`literal_types.md`）

DuckDB 有特殊字面量类型：`NULL`、`INTEGER_LITERAL`、`STRING_LITERAL`，各有绑定/转换规则（0.10.0 前整数/字符串字面量直接等同 `INTEGER`/`VARCHAR`）。

- **NULL 字面量**：关键字 `NULL`，可隐式转任意类型。
- **整数字面量**：一串十进制数字 → `INTEGER_LITERAL`，可隐式转任意能容纳它的整数类型（如 `42`→`TINYINT`，`1000`→不可）。
  - 不支持十六/二进制字面量直接写；但 `'0xFF'::INT = 255`、`0b101::INT = 5`（用字符串 cast）。
- **其它数字字面量**：小数点（`.` 可省略任一侧），E 记法（`e`/`E`，如 `1e2`、`6.02214e23`、`1e-10`）。
- **数字中的下划线分隔符**：`100_000_000`、`'0xFF_FF'::INTEGER`、`1_2.1_2E0_1`、`'0b0_1_0_1'::INTEGER`。规则：整数/小数/十六/二进制中可用；不可在首尾；不能连续或紧贴小数/指数。
- **字符串字面量**：用单引号 `'`；双引号 `"` 用于标识符（见 4.2）。
  - **隐式字符串拼接**：仅由空白（且至少含一个换行）分隔的相邻单引号字符串自动拼接（`'Hello' ' ' 'World'` 仅当含换行时成立；无换行报错）。
  - **隐式字符串转换**：`STRING_LITERAL` 可隐式转**任意**类型（如 `d > '1992-01-01'` 对 DATE 成立），但已是 `VARCHAR` 的值不能（需显式 cast，否则 Binder Error）。
  - **转义**：单引号内用 `''` 转义；`e'...'`/`E'...'` 启用 `\n \t \r \b \f` 等。
  - **Dollar-quoted**：`$$...$$`；可加标签 `$tag$...$tag$` 以在内包含 `$$`。

### 2.9 NULL 值（`nulls.md`）

- 任何类型列都可含 `NULL`（表示“未知”）。无 `NOT NULL` 即可插入。
- **任何与 NULL 的比较都返回 NULL**，包括 `NULL = NULL`。
- 相等比较用 `IS NOT DISTINCT FROM`（NULL=NULL 为 true）；判空用 `IS (NOT) NULL`。
- 函数：输入含 NULL **通常**返回 NULL（例外：`coalesce` 返回第一个非 NULL，`ifnull` 是其两参数版）。
- 聚合：大多忽略 NULL（`min`/`max` 等）；**不忽略**的有 `first`、`last`、`list`、`array_agg`（可用 `FILTER` 排除）。

---

## 3. 类型转换规则（Typecasting，`typecasting.md`）

- **显式转换**：`CAST(col AS VARCHAR)` 或 `col::VARCHAR`。
- **隐式转换**：系统自动添加，仅限“不会失败”的组合（如 `INTEGER`→`DOUBLE` 可，`DOUBLE`→`INTEGER` 不可）。函数如 `sin(DOUBLE)` 接受整数参数会自动转。可用 `can_cast_implicitly(source, target)` 检测。
- **组合转换（Combination Casting）**：当不同类型需合并为共同父类型时（比较 `=`/`<`/`>`、`UNION`/`EXCEPT`/`INTERSECT`、嵌套构造 `list_value`/`[...]`/`MAP`），隐式转换更宽松，例如 `BOOL` 可转 `INT`（`true`→1，`false`→0，普通隐式转换不允许）。
- **转换矩阵**：除 `NULL` 外，并非任意类型都能互转；隐式允许意味着显式也允许。
- **有损转换（Lossy Casts）**：允许，会舍入：
  ```sql
  SELECT CAST(3.1 AS INTEGER);  -- 3
  SELECT CAST(3.5 AS INTEGER);  -- 4
  SELECT CAST(-1.7 AS INTEGER); -- -2
  ```
  舍入规则见 2.1.6。
- **溢出（Overflows）**：溢出抛 `Conversion Error`；可用 `TRY_CAST` 转 `NULL` 而非报错。
  ```sql
  SELECT CAST(999 AS TINYINT);  -- Conversion Error: value out of range for INT8
  ```
- **VARCHAR 万能目标**：任何类型都能 cast 到 `VARCHAR`（显示用），且一般可逆；从 `VARCHAR` 转出若无法解析则运行时报错。
- **列表/数组**：`CAST([1,2,3] AS VARCHAR[])` 对子元素逐个转换；`ARRAY` 可隐式转 `LIST`。
- **STRUCT 转换**：需至少一个同名字段；目标有而源无的字段补 `NULL`；源有而目标无的忽略；字段顺序可不同（按名重排）；组合转换取字段并集（递归）。
- **UNION 转换**：见 2.6.5。
- **破坏性变更（历史）**：v0.10.0 起不再允许向 `VARCHAR` 的隐式转换（之前任何类型在绑定期都能隐转 VARCHAR）；可用配置 `old_implicit_casting` 回退（将被弃用）。

---

## 4. 友好 SQL（Friendly SQL）方言特性（`friendly_sql.md`，`keywords_and_identifiers.md` 等）

DuckDB 提供大量“语法糖”让 SQL 更简洁（部分为 DuckDB 首创，如 `GROUP BY ALL`，后被其它系统效仿）。

### 4.1 子句（Clauses）

- `CREATE OR REPLACE TABLE`：脚本中免 `DROP TABLE IF EXISTS`。
- `CREATE TABLE ... AS SELECT`（CTAS）：无需手写 schema。
- `INSERT INTO ... BY NAME`：按列名而非位置插入。
- `INSERT OR IGNORE INTO ...` / `INSERT OR REPLACE INTO ...`：依 `UNIQUE`/`PRIMARY KEY` 处理冲突。
- `DESCRIBE` / `SUMMARIZE`：表/查询的 schema 摘要与统计。
- **FROM-first 语法**：`FROM tbl` 等价于 `SELECT *`。
- **`GROUP BY ALL`**：从 SELECT 列表推断分组列。
- **`ORDER BY ALL`**：对所有列排序（保证确定性结果）。
- **`SELECT * EXCLUDE` / `SELECT * REPLACE`**：排除/替换列。
- **`UNION BY NAME`**：按列名而非位置 union。
- **前缀别名**：`x: 42` 代替 `42 AS x`。
- **`LIMIT n%`**：按表大小百分比限制（如 `LIMIT 10%`）。
- `PIVOT` / `UNPIVOT`：长表↔宽表。
- `SET VARIABLE` / `RESET VARIABLE`：SQL 级变量。
- **尾逗号（trailing commas）**：列/表名列表、LIST 项构造均可带尾逗号。

### 4.2 标识符与引号（`keywords_and_identifiers.md`）

- 未加引号标识符：不能是保留字、不能以数字/特殊字符开头、不能含空白。
- 加双引号 `"..."` 可用任意关键字/空白/特殊字符（如 `"SELECT"`、`" § 🦆 ¶ "`）；双引号内用 `""` 转义（如 `"IDENTIFIER ""X"""`）。
- **自动去重标识符**：冲突列重命名为 `name_1`、`name_2`...（`unnest` 嵌套结构时常见）。
- 数据库名遵循标识符规则；避免内部 schema 名 `system` / `temp`（可用 `ATTACH 'temp.db' AS temp2` 加别名规避）。
- **大小写规则：**
  - 关键字与函数名大小写不敏感。
  - 标识符**整体大小写不敏感**（类似 PG），但 **DuckDB 连双引号标识符也视为不敏感**（PG 中双引号保留大小写）。
  - 比较用 ASCII 规则：`col_A` = `col_a`，但 `col_á` ≠ 它们。
  - **保留原大小写**：用户写的 `CosineOfPi` 仍以该形式展示（见下例），查询用不同大小写也能匹配。
    ```sql
    CREATE TABLE tbl AS SELECT cos(pi()) AS CosineOfPi;
    SELECT cosineofpi FROM tbl;  -- 仍显示 CosineOfPi 列名
    ```
  - 配置 `preserve_identifier_case = false` 可将所有标识符转小写（兼容 PG 行为）。
- **冲突处理**：同名不同大小写时随机选一个（如 `NATURAL JOIN` 两表 `idfield`/`IdField` 会冲突）。
- **嵌套键大小写**：`MAP` 区分；`STRUCT`/`UNION` 不区分（再次强调）。

### 4.3 字面量与数字友好特性

- 标识符大小写不敏感但保留原样（见上）。
- 标识符去重（见上）。
- 数字字面量下划线分隔符（见 2.8）。

### 4.4 查询特性（Query Features）

- `WHERE`/`GROUP BY`/`HAVING` 中可用列别名（JOIN 的 `ON` 不行）。
- `COLUMNS()` 表达式（配合正则、`EXCLUDE`/`REPLACE`、lambda）批量处理多列。
- **可复用列别名（lateral column aliases）**：`SELECT i + 1 AS j, j + 2 AS k FROM range(0,3) t(i)`。
- 高级聚合：`FILTER` 子句、`GROUPING SETS`/`CUBE`/`ROLLUP`。
- `count()` 为 `count(*)` 简写。
- `IN` 运算符支持 list 和 map。
- CTE（`WITH`）指定列名；`JOIN` 子句指定列名；`VALUES` 可用于 JOIN 与 CTE 锚点。
- `SWITCH` 作为 `CASE` 的语法糖。

### 4.5 函数与表达式糖

- 点号函数链：`SELECT ('hello').upper()`。
- 字符串格式化：`format()`（`fmt` 语法）、`printf()`。
- 列表推导（list comprehensions）、列表切片、从尾部索引 `[-1]`、字符串切片。
- `STRUCT.*` 展开。
- 中括号 `[...]` 直接构造 `LIST`；简单 `LIST`/`STRUCT` 构造。
- struct schema 更新（见 2.6.4）。

### 4.6 索引（Indexing，`indexing.md`）

- DuckDB 用 **1-based 索引**（字符串、list 等）；但 **JSON 对象用 0-based 索引**（与 PostgreSQL 一致）。
  ```sql
  SELECT list[1] FROM (SELECT ['first','second','third'] AS list);   -- 'first'
  SELECT json[1] FROM (SELECT '["first","second","third"]'::JSON AS json);  -- "second"
  ```

### 4.7 顺序保持（Order Preservation，`order_preservation.md`）

- 为兼容 DataFrame 库，DuckDB 默认保持行序。
- **保证保序**：`COPY`、`FROM` 单表、`LIMIT`、`OFFSET`、`SELECT`、`UNION ALL`、`WHERE`、空 `OVER` 窗口函数、仅含上述成分的 CTE/子查询。可用 `row_number() OVER ()` 或物化表的 `rowid` 把顺序显式化。
- **不保证保序**：`FROM` 多表/子查询、`JOIN`、`UNION`、`USING SAMPLE`、整表聚合（顺序敏感聚合需显式指定）、`GROUP BY`、`ORDER BY`（可能不稳定排序）、标量子查询。
- 读取器（CSV/JSON/Parquet）默认保插入顺序。由配置 `preserve_insertion_order`（默认 `true`）控制；`SET preserve_insertion_order = false;` 可关闭。

---

## 5. 重要参数 / 配置（含默认值与适用版本）

| 配置项 | 默认值 | 说明 | 适用/来源 |
| :--- | :--- | :--- | :--- |
| `TimeZone` | 系统/如 `Europe/Amsterdam` | 时区感知时间戳的算术/格式化时区 | 需 ICU 扩展；`timestamp.md` |
| `Calendar` | `gregorian` | 非公历支持（如 `japanese`） | 需 ICU 扩展 |
| `preserve_identifier_case` | `true` | 标识符保留原大小写；`false` 则全转小写（兼容 PG） | `keywords_and_identifiers.md` |
| `preserve_insertion_order` | `true` | 读入/查询是否保持插入顺序 | `order_preservation.md` |
| `old_implicit_casting` | （默认新行为） | 回退到 v0.10.0 之前“任意类型隐式转 VARCHAR”的行为（将被弃用） | `typecasting.md` |

> 配置查询：`SELECT * FROM duckdb_settings() WHERE name = 'TimeZone';`

---

## 6. 代码示例（保留原文 SQL）

下面汇集文档中的关键示例（原文摘录）。

**数值 / 舍入：**
```sql
SELECT 2.5::FLOAT::INTEGER AS result;  -- 2  (round to even)
SELECT 2.5::DECIMAL::INTEGER AS result; -- 3 (round away from zero)
```

**DECIMAL 绑定：**
```sql
SELECT typeof(1.5::DECIMAL) AS c;       -- DECIMAL(18,3)
SELECT typeof(1.5::DECIMAL(10)) AS c;   -- DECIMAL(10,0)
```

**UUIDv7：**
```sql
SELECT uuid_extract_timestamp(uuidv7()) AS ts;
```

**BLOB：**
```sql
SELECT '\xAA'::BLOB;
SELECT 'AB'::BLOB;
```

**DATE / TIMESTAMP 特殊值：**
```sql
SELECT '-infinity'::DATE, 'epoch'::DATE, 'infinity'::DATE;
SELECT '-infinity'::TIMESTAMP, 'epoch'::TIMESTAMP, 'infinity'::TIMESTAMP;
```

**TIMESTAMPTZ 与 timezone：**
```sql
SELECT
    timezone('America/Denver', TIMESTAMP '2001-02-16 20:38:40') AS aware1,
    timezone('America/Denver', TIMESTAMPTZ '2001-02-16 04:38:40') AS naive1;
```

**INTERVAL：**
```sql
SELECT INTERVAL 1 YEAR, INTERVAL '1 month 1 day', '48:00:00'::INTERVAL;
SELECT DATE '2000-01-01' + INTERVAL (i) MONTH FROM range(12) t(i);
SELECT TIMESTAMP '2000-02-06 12:00:00' - TIMESTAMP '2000-01-01 11:00:00';  -- 36 days 1 hour
```

**LIST / ARRAY / MAP / STRUCT：**
```sql
SELECT [1, 2, 3];
SELECT list_value(1, 2, 3);
SELECT ['a','b','c'][3], ['a','b','c'][-1], ['a','b','c'][1:2];
SELECT array_value(1, 2, 3)[2];
SELECT [3, 2, 1]::INTEGER[3];
SELECT MAP {'key1': 10, 'key2': 20};
SELECT MAP(['key1','key2'], [10, 20]);
SELECT struct_pack(key1 := 'value1', key2 := 42);
SELECT {'x': 1, 'y': 2, 'z': 3};
SELECT a.x FROM (SELECT {'x': 1, 'y': 2, 'z': 3} AS a);
SELECT unnest(a) FROM (SELECT {'x': 1, 'y': 2, 'z': 3} AS a);
SELECT {'key1': 0, 'k2': 0} < {'k1': 1, 'k2': 0};  -- true
```

**UNION：**
```sql
CREATE TABLE tbl1 (u UNION(num INTEGER, str VARCHAR));
INSERT INTO tbl1 VALUES (1), ('two'), (union_value(str := 'three'));
SELECT union_tag(u) FROM tbl1;
SELECT u.str FROM tbl1;
```

**VARIANT：**
```sql
CREATE TABLE events (id INTEGER, data VARIANT);
INSERT INTO events VALUES
    (1, 42::VARIANT),
    (2, 'hello world'::VARIANT),
    (3, [1, 2, 3]::VARIANT),
    (4, {'name': 'Alice', 'age': 30}::VARIANT);
SELECT data.name FROM events WHERE id = 4;
SELECT variant_typeof(data) FROM events;
```

**ENUM：**
```sql
CREATE TYPE mood AS ENUM ('sad', 'ok', 'happy');
CREATE TYPE region AS ENUM (SELECT region FROM sales_data);
SELECT 'low'::priority < 'high'::priority;  -- true (按定义序)
SELECT enum_range(NULL::mood);              -- [sad, ok, happy]
```

**BITSTRING：**
```sql
SELECT '101010'::BITSTRING;
SELECT bitstring('0101011', 12);
SELECT 123::BITSTRING;
```

**GEOMETRY：**
```sql
CREATE TABLE geometries (id INTEGER, geom GEOMETRY);
INSERT INTO geometries VALUES (1, 'POINT (30 10)'), (3, 'POLYGON ((30 10, 40 40, 20 40, 10 20, 30 10))');
```

**Friendly SQL：**
```sql
FROM tbl;                                  -- FROM-first
SELECT * FROM t GROUP BY ALL;
SELECT * FROM t ORDER BY ALL;
SELECT a, b EXCLUDE (c) FROM t;
SELECT 42 AS x, ['a','b','c',] AS y, 'hello';  -- 尾逗号
SELECT max(val, 3) FROM t1 GROUP BY grp;    -- top-3 in group
```

**NULL / 隐式字符串转换：**
```sql
SELECT NULL IS NOT DISTINCT FROM NULL;      -- true
SELECT d > '1992-01-01' FROM (VALUES (DATE '1992-01-01')) t(d);  -- 隐式转 DATE 成功
SELECT d > '1992-01-01'::VARCHAR ...;       -- Binder Error
```

---

## 7. 常见陷阱与最佳实践

1. **`INT8` ≠ `UINT8`**：`INT8` 是 8 字节（= `BIGINT`），`UINT8` 是 8 位（= `UTINYINT`）。混用会大错。见 `sql_quirks.md`、`numeric.md`。
2. **DECIMAL 默认 (18,3)**：裸 `DECIMAL` 不是无约束类型；`WIDTH`/`SCALE` 越界直接 binder 报错；`WIDTH > 19` 用 INT128 明显更慢，建议 ≤ 18。
3. **浮点非精确**：`1.3::FLOAT - 0.7::FLOAT != 0.6::FLOAT`；金额用 `DECIMAL`。除零在 DuckDB 返回 Infinity/NaN（PG 报错）。
4. **舍入方向不同**：浮点→整数用银行家舍入；DECIMAL→整数向远离零舍入。
5. **TIMESTAMPTZ 不存时区**：只存纪元微秒；显示/算术依赖 `TimeZone` 配置（默认系统/UTC）。跨时区明确用 `timezone()`。无 `TIMESTAMP_NS WITH TIME ZONE`，纳秒+UTC 会丢精度。
6. **INTERVAL 比较陷阱**：`30 DAYS = 1 MONTH` 为 true，但加到日期上结果不同；`datediff('day',...)` 与 `datepart('day', ts1-ts2)` 语义不同。
7. **MAP vs STRUCT 键查找**：MAP 缺键返回 `NULL`，STRUCT 缺键报错（struct_extract）；MAP 键区分大小写，STRUCT/UNION 不区分。
8. **ENUM 比较**：与 `VARCHAR`/其它 enum 比较会转成字典序字符串，可能漏掉高优先级项；要类型安全须显式 `::enum`。常数比较被优化为 try_cast，不存在的字符串只返回 false 不报错。
9. **UNION 不能随便隐式转回成员**：用 `union_extract` 显式取；多相同类型成员时用 `union_value(tag := ...)` 消歧。
10. **隐式字符串转换的边界**：`STRING_LITERAL` 可隐式转任意类型（`d > '1992-01-01'` 成立），但已是 `VARCHAR` 的值不行（需显式 cast）。v0.10.0 后不再允许任意类型隐式转 VARCHAR。
11. **NULL 三态逻辑**：`NULL = NULL` 是 NULL；用 `IS NULL` / `IS NOT DISTINCT FROM`。聚合大多忽略 NULL。
12. **大小写与标识符**：DuckDB 标识符整体不敏感但保留原大小写；冲突时随机选一个，跨大小写 `NATURAL JOIN` 要小心。
13. **0-based vs 1-based**：常规索引 1 基；仅 JSON 0 基。
14. **嵌套类型 UPDATE = DELETE+INSERT**：有 ART 索引/主键/唯一约束时可能产生意外约束冲突。
15. **顺序不保证**：`JOIN`/`GROUP BY`/`UNION`/`ORDER BY` 不保证稳定顺序；需确定序用 `row_number() OVER ()` 或显式 `ORDER BY`。`USING SAMPLE` 语义位置在 LIMIT 处但实际应用早于 WHERE/GROUP BY。
16. **ARRAY 定长 vs LIST 变长**：DuckDB 的 `ARRAY` 是定长（与 PG 变长 ARRAY 不同）。
17. **GEOMETRY 是 v1.5 新内置类型**：函数仍在 `spatial` 扩展；存储优化需 storage v1.5+。
18. **`==` 比较**：DuckDB 支持 `==` 与 `=`，PG 只支持 `=`（可移植性差，不鼓励）。
19. **`-2^2 = 4.0`**：一元负号优先级高于 `^`（PG 兼容）；写成 `-(2^2)` 或 `pow(2,2)` 避免错误。
20. **正则 POSIX 运算符**：DuckDB 的 `~` 等价于 `regexp_full_match`，`~*`/`!~*` 不支持；不要照搬 PG 的正则写法。

---

## 8. 跨章节引用提示（Cross-References）

- **类型总览 / 嵌套类型对比**：`data_types/overview.md`（含嵌套类型规则、大小写规则、嵌套与性能）。
- **数值细节**：`data_types/numeric.md`（整数/DECIMAL/浮点/UUID/舍入）；别名陷阱见 `dialect/sql_quirks.md`。
- **字符串字面量 / 转义 / 下划线**：`data_types/literal_types.md`；字符串函数见 `functions/text.md`。
- **类型转换矩阵与规则**：`data_types/typecasting.md`；`TRY_CAST`、`can_cast_implicitly` 见 `expressions/cast.md`、`functions/utility.md`。
- **时区**：`data_types/timestamp.md`（instants/binning/ICU）、完整时区名列表 `data_types/timezones.md`（即 IANA 列表，可由 `pg_timezone_names()` 获取）；日历 `icu_calendar_names()`。
- **INTERVAL**：`data_types/interval.md`；日期部分函数 `functions/datepart.md`；`datediff` 见 `functions/date_functions`。
- **嵌套类型函数**：`functions/list.md`（含 `array_*` 兼容）、`functions/array.md`、`functions/map.md`、`functions/struct.md`、`functions/union.md`、`functions/enum.md`、`functions/bitstring.md`、`functions/blob.md`。
- **NULL 行为**：`data_types/nulls.md`；`IN`/`NOT IN` 的 NULL 行为见 `expressions/in.md`；聚合 NULL 见各聚合函数文档。
- **Friendly SQL 全集**：`dialect/friendly_sql.md`；及下属 `query_syntax`（from/groupby/orderby/limit/with/setops）、`expressions/star.md`（EXCLUDE/REPLACE/COLUMNS）、`expressions/case.md`（SWITCH）。
- **PostgreSQL 差异全集**：`dialect/postgresql_compatibility.md`（浮点除零、整数除法、UNION 布尔/整数、隐式转换、大小写、VACUUM、正则运算符、GROUP BY 函数依赖等）。
- **SQL 怪癖**：`dialect/sql_quirks.md`（空组聚合、索引基、UINT8/INT8、意外结果表、NaN、age、extract 等）。
- **标识符/大小写**：`dialect/keywords_and_identifiers.md`；`duckdb_keywords()` 查保留字。
- **配置**：`configuration/overview.md`（配置参考）、`configuration/pragmas.md`（`old_implicit_casting`）。
- **JSON 类型**：`data/json/json_type.md`（与 VARIANT 对比）。
- **GEOMETRY**：`core_extensions/spatial/overview.md`（函数）、`internals/storage.md`（storage v1.5）。
- **性能**：`guides/performance/schema.md`（类型选择对性能影响）。

---

> 整理完成。以上覆盖两个目录下除 `timezones.md`（纯 IANA 时区名参考表，无额外叙述）外的全部 `.md` 文件。版本相关新增点：`GEOMETRY` 在 v1.5 成为内置类型、`VARIANT` 支持 Parquet shredding（2025 Parquet Variant 标准）、struct 子 schema 可用 `ALTER TABLE` 修改（v1.3.0 起）。
