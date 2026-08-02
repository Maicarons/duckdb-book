# 第 06 章 SQL 进阶：函数与表达式

SQL 真正的表现力，并不在 `SELECT`、`FROM` 这类骨架关键字上，而在表达式（expression）与函数（function）之中。前几章已经用到了 `count`、`sum`、`strftime` 等函数，本章则系统梳理 DuckDB 的函数与表达式体系：从运算符优先级、类型转换、lambda 这类通用表达式机制，到聚合、字符串、日期时间、嵌套类型、JSON 等分类函数，再到条件、哈希、系统信息这类工具函数与元数据探查。读完本章，读者应能判断"该用哪个函数、为什么这样写"，而不再是零散地记忆语法。

## 6.1 表达式与运算符

表达式是把列、常量、运算符和函数组合成单个值的最小计算单元。DuckDB 的表达式体系有几个容易踩坑、却又极其关键的点，值得优先讲清。

**运算符优先级与三值逻辑。** 算术运算符（`+ - * / % **`）优先级高于比较运算符（`< > <= >= = <> !=`），比较又高于逻辑运算符（`NOT`、`AND`、`OR`）。例如 `3 + 4 * 2` 得到 11，因为乘法先算。比较运算中，只要任一操作数为 `NULL`，结果即为 `NULL`；若希望把 `NULL` 当作可比较的"值"来对待，应使用 `IS DISTINCT FROM` / `IS NOT DISTINCT FROM`。逻辑运算遵循三值逻辑：`NULL AND false` 结果为 `false`，`NULL OR true` 结果为 `true`。`BETWEEN x AND y` 等价于 `x <= a AND a <= y`，区间两端均含。

DuckDB 有一项与 PostgreSQL 不同的特性——**组合类型转换（combination casting）**：不同类型比较时会自动转换，于是 `1 = true`、`1 = '1.1'` 都为真。这带来便利，却也削弱了类型严格性，编写条件时应心里有数。

**CASE 与条件表达式。** `CASE` 是 SQL 中最通用的条件结构，可链式书写，缺省 `ELSE` 时返回 `NULL`：

```sql
SELECT
  CASE
    WHEN score >= 90 THEN 'A'
    WHEN score >= 60 THEN 'B'
    ELSE 'C'
  END AS grade
FROM grades;
```

`COALESCE(a, b, ...)` 返回参数列表中第一个非 `NULL` 的值；`NULLIF(a, b)` 在 `a = b` 时返回 `NULL`，否则返回 `a`，常用来把"无意义值"归一为 `NULL`：

```sql
SELECT COALESCE(phone, email, 'no contact') FROM users;
SELECT NULLIF(score, 0);   -- 分数为 0 时返回 NULL
```

**CAST 与 TRY_CAST。** 类型转换用 `CAST(x AS TYPE)`，也支持 PostgreSQL 风格的 `x::TYPE`：

```sql
SELECT CAST('42' AS INTEGER);
SELECT '42'::INTEGER;
SELECT TRY_CAST('abc' AS INTEGER);   -- NULL，解析失败时返回 NULL 而非报错
```

`TRY_CAST` 在解析失败时返回 `NULL`，非常适合清洗来源不可信的数据；与之同源的 `TRY(expr)` 也能让会抛错的表达式在该行降级为 `NULL`（但不能包裹易变函数、聚合或标量子查询）。

**Lambda 表达式（版本敏感）。** 列表变换、列批量处理等场景会用到匿名函数 lambda。DuckDB 采用 Python 风格的双冒号写法：

```sql
SELECT list_transform([1, 2, 3], x : x + 1);          -- [2, 3, 4]
SELECT list_transform([1, 2, 3], lambda x : x * x);   -- [1, 4, 9]
```

单箭头写法 `x -> x + 1` **已在 v1.3 弃用**。其弃用路线图值得记牢：v1.3 起弃用单箭头；**v1.5 是最后一个默认仍可在不开开关的情况下使用单箭头的版本**；v2.0 起默认禁用单箭头；v2.1 移除 `lambda_syntax` 开关。因此面向未来，一律推荐 `x : x + 1` 或 `lambda x : x + 1`。如需临时恢复旧写法，可用设置项 `lambda_syntax = ENABLE_SINGLE_ARROW`。

**星号与 COLUMNS()。** `*` 及其变体是列选择的有力工具：`SELECT * EXCLUDE (secret)` 排除某列，`REPLACE (...)` 替换某列表达式，`RENAME (...)` 重命名；`SELECT * LIKE 'col%'`、`* GLOB 'col*'`、`* SIMILAR TO 'col.'` 支持模式匹配。`COLUMNS(...)` 则对多列批量套用同一表达式，可接收正则、列名列表，或 `lambda c: c LIKE '%num%'` 这样的列过滤：

```sql
SELECT * EXCLUDE (secret) FROM users;
SELECT COLUMNS('.*_id') FROM orders;
SELECT COLUMNS(lambda c : c LIKE '%num%') FROM metrics;
```

**排序规则（collation）。** 字符串比较默认使用 `BINARY`（别名 `C`/`POSIX`），速度最快但非区域感知。内置还提供 `NOCASE`、`NOACCENT`、`NFC`，并可点式组合（如 `NOCASE.NOACCENT`）；区域相关的规则（如德语 `de`、中文 `zh`）需加载 ICU 扩展。collation 可在列级声明（`VARCHAR COLLATE NOACCENT`），也可用 `PRAGMA default_collation` 设置全局默认。

```sql
CREATE TABLE t (name VARCHAR COLLATE NOACCENT);
SELECT 'mühleisen' = 'muhleisen';   -- 在该列上为 true
```

**dot operator 链式调用。** DuckDB 支持用点号把函数链式调用在字面量或列上，例如 `'hello'.upper()`、`name.replace('goose', 'duck')`。这一机制**仅适用于标量函数（scalar function），不适用于表函数（table function）**——表函数即使无参数也必须加括号，如 `SELECT * FROM duckdb_settings();`。

## 6.2 聚合函数

聚合函数（aggregate）把多行"压"成一行，是分析查询的主力。最常用的一组是 `count`、`sum`、`avg`、`min`、`max`：

```sql
SELECT count(*), count(amount), sum(amount), avg(amount),
       min(price), max(price)
FROM orders;
```

`list(x)` 把所有值收集进一个 LIST，`string_agg(x, sep)` 则按分隔符拼接成字符串；`histogram(x)` 返回各取值频次构成的 MAP，是快速画像的好工具：

```sql
SELECT list(name) FROM users;                  -- [a, b, c]
SELECT string_agg(name, ', ') FROM users;      -- 'a, b, c'
SELECT histogram(category) FROM products;      -- {a=2, b=1, c=5}
```

当数据规模很大、可以接受近似结果时，应使用近似聚合：

```sql
SELECT approx_count_distinct(user_id) FROM logs;   -- 基于 HyperLogLog
SELECT approx_quantile(latency, 0.95) FROM reqs;   -- 基于 T-Digest，取 95 分位
```

统计类聚合则在做数据分析时频繁出现：`median` 取中位数，`stddev_samp` 取样本标准差，`corr(x, y)` 取皮尔逊相关系数：

```sql
SELECT median(latency), stddev_samp(latency), corr(requests, errors)
FROM daily_stats;
```

以上聚合都能配合 `FILTER` 子句，实现"一次扫描、多口径统计"，远比写多条查询高效：

```sql
SELECT
  count(*)                       AS total,
  count(*) FILTER (WHERE status = 'paid')      AS paid,
  count(*) FILTER (WHERE status = 'refunded')  AS refunded
FROM orders;
```

## 6.3 字符串与正则函数

文本处理是数据分析的日常。DuckDB 中字符串拼接用 `||` 或 `concat`：二者区别在于 `concat` 会跳过 `NULL`，而 `||` 任一操作数为 `NULL` 则结果为 `NULL`。

```sql
SELECT 'Hello' || ' ' || 'World';
SELECT concat('a', NULL, 'b');     -- 'ab'（自动跳过 NULL）
```

常用基础函数一览：

```sql
SELECT length('Hello🦆');          -- 6（字符数；strlen 返回字节数，此处为 4）
SELECT lower('DuckDB'), upper('DuckDB');
SELECT substring('Hello', 2, 2);   -- 'el'（起始下标为 1）
SELECT replace('hello', 'l', '-'); -- 'he--o'
SELECT contains('duckdb', 'uck'), starts_with('duckdb', 'duck');
SELECT string_split('a-b-c', '-'); -- ['a', 'b', 'c']
SELECT format('{} + {} = {}', 3, 5, 8);  -- '3 + 5 = 8'
```

正则能力由 RE2 引擎提供，`regexp_replace` 与 `regexp_extract` 最为常用：

```sql
SELECT regexp_replace('a1b2c3', '\d', '#', 'g');   -- 'a#b#c#'（'g' 表示全局替换）
SELECT regexp_extract('订单号A123', 'A(\d+)', 1);  -- '123'（取第 1 捕获组）
```

`regexp_replace` 默认替换首个匹配，传入 `'g'` 选项可全局替换；`regexp_extract` 的最后一个参数指定捕获组编号（0 表示整段匹配）。

## 6.4 日期时间函数

DuckDB 内建 `DATE`、`TIME`、`TIMESTAMP`、`TIMESTAMP WITH TIME ZONE`（需 ICU 扩展）与 `INTERVAL` 等时间类型。格式化与解析是一对互补操作：`strftime` 把时间按格式串输出为字符串，`strptime` 把字符串按格式串解析为时间戳，`try_strptime` 在解析失败时返回 `NULL` 而非报错。

```sql
SELECT strftime(now(), '%Y-%m-%d %H:%M:%S');
SELECT strptime('2025-01-15', '%Y-%m-%d');   -- 解析为 DATE / TIMESTAMP
```

分量提取、截断与差值构成时间运算的三板斧：`date_part` 取某一分量，`date_trunc` 截断到指定精度，`date_diff` 求两个时间之差（单位由第一个参数指定）。

```sql
SELECT date_part('year', now());
SELECT date_trunc('month', now());
SELECT date_diff('day', DATE '2025-01-01', DATE '2025-01-15');  -- 14
```

`epoch(x)` 把时间转为 Unix 秒；`make_date(y, m, d)` 等构造器则从分量拼出时间值。值得特别留意 `time_bucket`：它把时间戳按固定间隔规整到桶起点，常用于按小时、按天汇总时序数据，**自 v1.5 起增加了时区参数**，使其在跨时区场景中行为更可控：

```sql
SELECT epoch(now());
SELECT make_date(2025, 1, 15);
SELECT time_bucket(INTERVAL '1 hour', ts) FROM events;   -- v1.5 起支持时区参数
```

## 6.5 数组/LIST、STRUCT、MAP 操作函数

DuckDB 对嵌套类型（nested types）的支持非常深入。LIST（又称数组）可用 `list_value` 构造，下标从 1 开始，切片语法类 Python 且支持负数：

```sql
SELECT list_value(4, 5, 6);          -- [4, 5, 6]
SELECT [10, 20, 30][1];              -- 10（1 基下标）
SELECT [10, 20, 30][1:2];            -- [10, 20]
```

LIST 与 lambda 结合后能力最强：`list_transform` 逐元素变换，`list_filter` 按条件过滤，`list_reduce` 归约求和/求积等。它们正是上一节推荐的 `x : x + 1` 写法的主要用武之地：

```sql
SELECT list_transform([1, 2, 3], x : x * 2);              -- [2, 4, 6]
SELECT list_filter([1, 2, 3, 4], x : x % 2 = 0);         -- [2, 4]
SELECT list_reduce([1, 2, 3, 4], (x, y) : x + y);        -- 10
```

`unnest(list)` 把 LIST 展开成多行，是"一进多出"、改变结果集基数（cardinality）的关键操作：

```sql
SELECT unnest([1, 2, 3]) AS v;
-- 返回三行：1 / 2 / 3
```

STRUCT（结构体）用于把若干命名字段打包在一起，点号即可取字段：

```sql
SELECT struct_pack(a := 1, b := 'x').b;     -- 'x'
SELECT {'name': 'duck', 'age': 5}.name;    -- 'duck'
-- 也可用 struct.* 把各字段展开为独立列
```

MAP（映射）是键值对集合，按下标式的 `[]` 或 `map_extract` 查找值：

```sql
SELECT map {'a': 1, 'b': 2}['a'];           -- 1
SELECT map_extract(map {'a': 1}, 'a');      -- 1
```

对于 UNION 类型，则用 `union_tag(u)` 取当前标签、`union_extract(u, 'tag')` 在安全匹配时取出对应值：

```sql
SELECT union_tag(u), union_extract(u, 'num') FROM mixed;
```

## 6.6 JSON 函数

JSON 已是现代数据交换的事实标准，DuckDB 通过 **json 扩展**（v1.x 中已内置并可自动加载）提供原生 JSON 处理。最基础的取值函数是 `json_extract` 与 `json_extract_string`：前者保留 JSON 片段，后者把结果作为纯文本（VARCHAR）返回：

```sql
SELECT json_extract('{"name":"duck"}', '$.name');        -- {"name":"duck"} 或 "duck"
SELECT json_extract_string('{"name":"duck"}', '$.name'); -- 'duck'
```

DuckDB 还提供两个便捷操作符：`->` 等价于 `json_extract`（返回 JSON），`->>` 等价于 `json_extract_string`（返回文本）：

```sql
SELECT '{"name":"duck"}' -> '$.name';    -- JSON 片段
SELECT '{"name":"duck"}' ->> '$.name';   -- 'duck'（文本）
```

当需要对 JSON 内部的值做变换时，可用 `json_transform`，它沿一个 JSON 路径表达式匹配目标，并以 lambda 改写匹配到的值：

```sql
SELECT json_transform('{"a":1}', '$.a', x : x + 10);   -- {"a": 11}
```

JSON 路径使用 `$.key` 形式访问对象字段、`$[i]` 访问数组元素。由于这些能力来自 json 扩展，若环境中该扩展未启用，需先 `INSTALL json` 并 `LOAD json`（在多数 v1.x 安装中会自动加载，无需手动干预）。

## 6.7 条件、哈希、系统函数与元数据

工具类函数虽小，却是排查与诊断的常客。**条件与判空**：除前文的 `COALESCE`、`NULLIF` 外，`IFNULL(a, b)` 等价于两参数的 `COALESCE`，`IF(cond, a, b)` 等价于单条件 `CASE`：

```sql
SELECT IFNULL(a, b), NULLIF(a, b), IF(score > 60, 'pass', 'fail') FROM exam;
```

**类型与版本探查**：`typeof(x)` 返回表达式的类型名，`version()` 返回当前 DuckDB 版本字符串，二者在调试类型推导或确认运行环境时极有用：

```sql
SELECT typeof(42), typeof('x'), version();
```

**哈希与编码**：`hash(value)` 返回 `UBIGINT`，属于非加密哈希，适合做分桶或去重判等；若需要加密级摘要，可用 `md5(s)`、`sha1(value)`、`sha256(value)`，后两者返回 `VARCHAR`：

```sql
SELECT hash('duckdb'), md5('duckdb'), sha256('duckdb');
```

**元数据探查**则有两条互补途径。`information_schema` 是一组 SQL 标准视图（基于 PostgreSQL 实现），适合用标准 SQL 读取库结构：

```sql
SELECT * FROM information_schema.tables;
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'orders';
```

而 `duckdb_*` 表函数族是 DuckDB 自有的、信息更全的源头，多数 `information_schema` 视图本就建立在它们之上。这些表函数**即使无参数也必须加括号**：

```sql
SELECT * FROM duckdb_settings();    -- 全部运行期设置项
SELECT * FROM duckdb_tables();      -- 全部表
SELECT * FROM duckdb_columns();     -- 全部列
CALL duckdb_functions();            -- 全部函数（含类型、返回类型、稳定性等字段）
```

其中 `duckdb_functions()` 的 `function_type` 字段取值为 `table` / `scalar` / `aggregate` / `pragma` / `macro` / `table_macro`，是厘清"某个名字究竟是标量函数还是表函数"的权威依据——这也回扣了 6.1 节关于"表函数必须加括号、不可 dot 链式"的约束。

## 6.8 本章小结

本章把 DuckDB 的函数与表达式体系串成了一张地图。要点归纳为四条：

其一，**表达式的坑多于语法**。`CASE`/`COALESCE`/`NULLIF` 解决条件与判空，`CAST` 与 `TRY_CAST` 区分"严格转换"与"容错转换"；组合类型转换让 `1 = true` 为真，是 DuckDB 与 PostgreSQL 的显见差异。lambda 一律写 `x : x + 1`。

其二，**聚合是分析之骨**。`count`/`sum`/`avg`/`min`/`max` 之外，`list`、`string_agg`、`histogram` 提供结构化聚合；大数据下用 `approx_count_distinct`、`approx_quantile` 换速度，`median`、`stddev_samp`、`corr` 做统计；`FILTER` 子句让一次扫描产出多口径。

其三，**分类函数各司其职**。字符串用 `||`/`concat`/`replace`/`regexp_*`/`format`；时间用 `strftime`/`strptime`/`date_part`/`date_trunc`/`date_diff`/`time_bucket`（后者 v1.5 起带时区）；嵌套类型靠 `list_transform`/`list_filter`/`list_reduce`/`unnest` 与 STRUCT 点取、MAP 下标；JSON 由 json 扩展支撑，`->`/`->>` 是取值捷径。

其四，**元数据靠两个体系**。`information_schema` 视图走 SQL 标准，`duckdb_*` 表函数族信息更全、且是规范的真正源头——记住它们无参也要加括号，这是区分标量函数与表函数的硬界线。
