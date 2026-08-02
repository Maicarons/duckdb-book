# DuckDB 查询语法（Query Syntax）详解

> 整理自官方文档 `docs/current/sql/query_syntax/` 全部 18 个 `.md` 文件（DuckDB 1.5.5 版）。
> 已忽略 Jekyll frontmatter（`--- ... ---`）与 Liquid 标签（`{% ... %}`），仅保留正文内容。
> 技术术语（SELECT / JOIN / CTE 等）保留英文，便于与官方文档对应。

---

## 0. SELECT 语句的逻辑执行顺序（重要背景）

理解 DuckDB 的查询子句，首先要记住**书写顺序 ≠ 逻辑执行顺序**：

- `SELECT` 虽然写在最前面，但在逻辑上**最后执行**（对输出做投影/转换）。
- 逻辑执行顺序大致为：`FROM`（含 JOIN）→ `WHERE` → `GROUP BY` → `HAVING` → `WINDOW` → `QUALIFY` → `SELECT` → `UNION/INTERSECT/EXCEPT`（集合运算）→ `ORDER BY` → `LIMIT/OFFSET`。
- `SAMPLE` / `TABLESAMPLE` 在 `FROM` 之后、`WHERE` 之前应用。

---

## 1. SELECT 子句（SELECT Clause）

### 1.1 语法与语义
`SELECT` 指定查询返回的结果列列表。它可以包含任意表达式（算术、函数、标量/聚合/窗口函数）。每个表达式都会被命名（可用 `AS` 显式命名，否则系统自动命名）。**列名大小写不敏感**。

### 1.2 别名（alias）
- 后缀别名：`SELECT col1 + col2 AS res, sqrt(col1) AS root FROM tbl;`
- **前缀别名（DuckDB 特色）**：`SELECT res: col1 + col2, root: sqrt(col1) FROM tbl;`
- 含空格/特殊字符的列用双引号：`SELECT "Some Column Name" FROM tbl;`

### 1.3 Star 表达式（`*`）
- `SELECT * FROM tbl;` 选择所有列。
- 表/子查询整体作为 struct：`SELECT t FROM t;`（返回单列，整行作为 struct）。
- `*` 可配合 `EXCLUDE` / `REPLACE`：
  - `SELECT * EXCLUDE (city) FROM addresses;`（排除某列）
  - `SELECT * REPLACE (lower(city) AS city) FROM addresses;`（替换某列）
- `COLUMNS('...')` 正则选列：`SELECT COLUMNS('number\d+') FROM addresses;`
- 对多列套用聚合：`SELECT min(COLUMNS(*)) FROM addresses;`

### 1.4 DISTINCT / ALL
- `SELECT DISTINCT city FROM addresses;` —— 仅返回去重后的行（**开销大**，非必要时勿用）。
- `SELECT DISTINCT ON (expr)` —— 对每个唯一表达式值只返回一行；若有 `ORDER BY`，返回该排序下的**第一行**；无 `ORDER BY` 时哪行被返回未定义。
  ```sql
  SELECT DISTINCT ON (country) city, population
  FROM cities
  ORDER BY population DESC;
  ```
  > 对大表，用 `DISTINCT ON` 关键列比 `DISTINCT *` 性能更好（关键列可保证唯一性）。
- `ALL` 是默认行为（保留重复行），通常不必显式写出。

### 1.5 聚合与窗口函数（在 SELECT 中的使用）
- 聚合函数（aggregate）：`SELECT count(*) FROM addresses;` 把多行合并为一个值。一旦 SELECT 含聚合，查询即变为聚合查询，所有非聚合表达式必须出现在 `GROUP BY` 中。
- 窗口函数：`SELECT row_number() OVER () FROM sales;`；`SELECT amount - lag(amount) OVER (ORDER BY time) FROM sales;`（详见第 9 节）。

### 1.6 unnest（在 SELECT 中）
`SELECT unnest([1, 2, 3]);` 把数组/list 拆一层；`SELECT unnest({'a':42,'b':84});` 把 struct 拆成多列。详见第 11 节。

---

## 2. FROM 子句与 JOIN（FROM and JOIN Clauses）

### 2.1 数据源种类
`FROM` 逻辑上最先执行，可包含：
- 单表：`SELECT * FROM tbl;`
- 带 schema：`SELECT * FROM schema_name.tbl;`
- 表函数（table function）：`range`、`generate_series`、`read_csv`、`read_parquet`、`repeat`、`unnest`、`glob` 等。
  - `FROM 'test.csv';` 会被隐式翻译为 `FROM read_csv('test.csv');`
  - 列重命名：`FROM range(100) AS t(i);` 把 range 函数首列命名为 `i`。
- 子查询：`FROM (SELECT * FROM tbl);`
- 文件引用直接用字符串：`SELECT * FROM 'test.csv';`
- 整行取 struct：`SELECT t FROM t;`（或子查询 `SELECT t FROM (SELECT unnest(generate_series(41,43)) AS x, 'hello' AS y) t;`）

### 2.2 表函数的 `WITH ORDINALITY`
所有表函数支持 `WITH ORDINALITY` 后缀，附加一个从 1 开始的 `ordinality` 整数列：
```sql
SELECT * FROM read_csv('test.csv') WITH ORDINALITY;
```
> 在存在 JOIN 时，`WITH ORDINALITY` 可枚举 JOIN 单侧而不是最终结果集，免去子查询。

### 2.3 FROM-first 语法（DuckDB 特色）
DuckDB 允许把 `FROM` 放在 `SELECT` 之前，甚至省略 `SELECT`：
```sql
FROM tbl SELECT *;      -- 等价 SELECT * FROM tbl;
FROM tbl;               -- 等价 SELECT * FROM tbl;
FROM range(100) AS t(i) SELECT sum(t.i) WHERE i % 2 = 0;  -- 带 WHERE/聚合
```

### 2.4 JOIN 总览
JOIN 是水平连接两个关系（左/右）的关系运算。各结果行含两关系所有列。无匹配时，外连接用 `NULL` 填充另一侧属性。

| JOIN 类型 | 说明 |
|---|---|
| `INNER`（默认） | 仅返回能配对的行 |
| `LEFT` | 左关系每行至少出现一次，右无匹配补 NULL |
| `RIGHT` | 右关系每行至少出现一次，左无匹配补 NULL |
| `FULL` | 两侧每行至少出现一次，缺失侧补 NULL |
| `CROSS` | 笛卡尔积，无连接条件 |
| `NATURAL` | 按同名列自动连接 |
| `USING (col)` | 仅对同名列等值连接（更简洁） |
| `SEMI` | 左表有匹配的行（逻辑同 `IN`） |
| `ANTI` | 左表无匹配的行（逻辑同 `NOT IN`，但忽略右表 NULL） |
| `LATERAL` | 子查询可引用前面子查询的列 |
| `POSITIONAL` | 按物理行位置连接 |
| `ASOF` | 时序/有序数据的最近事件连接 |

### 2.5 各种 JOIN 详解与示例

**CROSS JOIN（笛卡尔积）**
```sql
SELECT a.*, b.* FROM a CROSS JOIN b;
-- 等价：SELECT a.*, b.* FROM a, b;
```

**条件连接（Conditional Joins）**
```sql
SELECT n.*, r.* FROM l_nations n JOIN l_regions r ON (n_regionkey = r_regionkey);
SELECT n.*, r.* FROM l_nations n JOIN l_regions r USING (regionkey);
-- 条件不必是等值，任意谓词均可（也可写在 WHERE 中，但 ON 更清晰）
```

**NATURAL JOIN**
```sql
SELECT * FROM city_airport NATURAL JOIN airport_names;
-- 等价 JOIN ... USING (iata);
```

**SEMI / ANTI JOIN**
```sql
SELECT * FROM city_airport SEMI JOIN airport_names USING (iata);  -- 等价 WHERE iata IN (...)
SELECT * FROM city_airport ANTI JOIN airport_names USING (iata);  -- 等价 WHERE iata NOT IN (... WHERE iata IS NOT NULL)
```
> SEMI/ANTI 结果行数不会超过左表。

**LATERAL JOIN**
```sql
SELECT * FROM range(3) t(i), LATERAL (SELECT i + 1) t2(j);
SELECT * FROM generate_series(0,1) t(i),
         LATERAL (SELECT i + 10 UNION ALL SELECT i + 100) t2(j);
```
> LATERAL 是相关子查询（correlated subquery）的泛化，每个输入值可返回多行。DuckDB 会自动检测何时需要 LATERAL，关键字可省略。

**POSITIONAL JOIN**
```sql
SELECT * FROM t1 POSITIONAL JOIN t2;
```
> 始终为 FULL OUTER 语义：结果长度等于较长表，缺失侧补 NULL。适合数据框/CSV/Parquet 等本身有自然顺序的数据。

**ASOF JOIN**（时序"最接近"连接）
```sql
SELECT t.*, p.price FROM trades t
ASOF JOIN prices p ON t.symbol = p.symbol AND t.when >= p.when;
```
- 至少需要一个关于排序字段的**不等式条件**（`>=`/`>`/`<=`/`>` 皆可，最常用 `>=`），其他条件必须是等值（`=` 或 `NOT DISTINCT`）。左右表顺序敏感。
- 可加 `OUTER`（如 `ASOF LEFT JOIN`）找无配对行。
- 可用 `USING`，但**列表中最后一个属性必须是不等式**（`>=`）。

**SELF-JOIN**：所有 JOIN 类型均支持自连接，但必须起别名，否则报 "Duplicate alias" 错误：
```sql
SELECT * FROM t AS t1 JOIN t AS t2 USING (x);
```

**JOIN 子句内的简写**
```sql
SELECT * FROM t1 NATURAL JOIN t2 t2(x);          -- 列名简写
SELECT * FROM t1 NATURAL JOIN (VALUES (2),(4)) _(x);  -- JOIN 内用 VALUES
```

### 2.6 采样（TABLESAMPLE / SAMPLE）
```sql
SELECT * FROM tbl TABLESAMPLE 10%;     -- 按百分比抽样
SELECT * FROM tbl TABLESAMPLE 10 ROWS; -- 按行数抽样
SELECT * FROM addresses USING SAMPLE 1%;                 -- 系统默认抽样
SELECT * FROM addresses USING SAMPLE 1% (bernoulli);     -- bernoulli 抽样
SELECT * FROM (SELECT * FROM addresses) USING SAMPLE 10 ROWS;
```
> `SAMPLE` 在 FROM 之后（含 JOIN 后）、WHERE 之前应用，用于加速或快速预览。

---

## 3. WHERE 子句

`WHERE` 在 `FROM` 之后立即逻辑执行，用于过滤数据行（不是分组后过滤，那是 `HAVING`）。
```sql
SELECT * FROM tbl WHERE id = 3;
SELECT * FROM tbl WHERE name LIKE '%mark%';     -- 大小写敏感
SELECT * FROM tbl WHERE name ILIKE '%mark%';    -- 大小写不敏感
SELECT * FROM tbl WHERE id = 3 OR id = 7;
```

---

## 4. GROUP BY 子句

`GROUP BY` 指定按哪些列分组以执行聚合。即使 SELECT 中没有聚合函数，只要写了 `GROUP BY`，查询即为聚合查询。同一组的元组被合并，分组列值不变，其余列用聚合函数（count/sum/avg 等）合并。

### 4.1 GROUP BY ALL（DuckDB 特色）
```sql
SELECT city, street_name FROM addresses GROUP BY ALL;
SELECT city, street_name, avg(income) FROM addresses GROUP BY ALL;
```
> 自动按 SELECT 中所有"未被聚合包裹"的列分组，减少出错、保持粒度一致。

### 4.2 多维分组（GROUPING SETS / ROLLUP / CUBE）
详见第 5 节。注意 `GROUP BY ALL` **不兼容** `GROUPING SETS/CUBE/ROLLUP`。

示例：
```sql
SELECT city, count(*) FROM addresses GROUP BY city;
SELECT city, street_name, avg(income) FROM addresses GROUP BY city, street_name;
```

---

## 5. GROUPING SETS / ROLLUP / CUBE

用于在**单次查询**内沿多个维度分组。

```sql
-- 显式分组集（() 表示空分组 = 不分组的总聚合）
SELECT city, street_name, avg(income)
FROM addresses
GROUP BY GROUPING SETS ((city, street_name), (city), (street_name), ());

SELECT city, street_name, avg(income) FROM addresses GROUP BY CUBE (city, street_name);
SELECT city, street_name, avg(income) FROM addresses GROUP BY ROLLUP (city, street_name);
```

- `ROLLUP(a,b,c)` → 产生 `(a,b,c),(a,b),(a),()`，共 n+1 个分组集，用于层级下钻。
- `CUBE(a,b,c)` → 产生全部 `2^n` 个组合。
- 等价于多个 `UNION ALL` 分组查询（超聚合行用 NULL 填充缺失维度列）。

### 5.1 用 GROUPING_ID() / GROUPING() 识别超聚合行
当分组列本身含真实 NULL 时，无法用 NULL 区分"真实 NULL"还是"分组产生的 NULL"。`GROUPING_ID()` 返回 BIGINT：非超聚合行返回 0；超聚合行返回一个位标志整数（对应被 rollup 的表达式位）。例如 `GROUPING_ID(y,q,m)`：`(y,q,m)`→0，`(y,q)`→1，`(y)`→3，`()`→7。可 cast 成 BIT 观察位：`GROUPING_ID(y,q,m)::BIT::VARCHAR`。

---

## 6. HAVING 子句

`HAVING` 在 `GROUP BY` 之后应用，对**分组后的结果**过滤（语法同 WHERE，但作用于聚合之后）。
```sql
SELECT city, count(*) FROM addresses GROUP BY city HAVING count(*) >= 50;
SELECT city, street_name, avg(income) FROM addresses
GROUP BY city, street_name
HAVING avg(income) > 2 * median(income);
```

---

## 7. FILTER 子句

`FILTER` 跟在聚合函数后面，仅把满足条件的行喂给该聚合（类似局部 WHERE）。常用于多个聚合带不同过滤、以及静态 pivot。相比 `CASE WHEN`，`FILTER` 对 `first`/`last`/`list`/`array_agg` 等"不忽略 NULL"的函数处理更准确。
```sql
SELECT
    count() AS total_rows,
    count() FILTER (i <= 5) AS lte_five,
    count() FILTER (i % 2 = 1) AS odds
FROM generate_series(1, 10) tbl(i);

-- 静态 pivot
SELECT
    count(i) FILTER (year = 2022) AS "2022",
    count(i) FILTER (year = 2023) AS "2023",
    count(i) FILTER (year IS NULL) AS "NULLs"
FROM stacked_data;
```
> 仅做"满足条件计数"也可用 `sum(i <= 5)` 代替 FILTER。

---

## 8. 集合运算（Set Operations）：UNION / INTERSECT / EXCEPT

传统集合运算**按列位置**合并，要求列数相同（类型不同会隐式 cast，结果列名取第一个查询）。

| 运算 | 语义 | 去重 |
|---|---|---|
| `UNION` | 合并两查询行 | 集合语义（去重） |
| `UNION ALL` | 合并两查询行 | 包语义（不去重） |
| `INTERSECT` | 两查询结果都出现的行 | 去重 |
| `INTERSECT ALL` | 同上 | 不去重（按重数） |
| `EXCEPT` | 仅出现在左查询的行 | 去重 |
| `EXCEPT ALL` | 同上 | 不去重（按重数） |

```sql
SELECT * FROM range(2) t1(x) UNION SELECT * FROM range(3) t2(x);
SELECT * FROM range(2) t1(x) UNION ALL SELECT * FROM range(3) t2(x);
SELECT * FROM range(2) t1(x) INTERSECT SELECT * FROM range(6) t2(x);
SELECT unnest([5,5,6,6]) AS x INTERSECT ALL SELECT unnest([5,6,6]);
SELECT * FROM range(5) t1(x) EXCEPT SELECT * FROM range(2) t2(x);
```

### 8.1 UNION [ALL] BY NAME（DuckDB 特色）
按**列名**（而非位置）合并，不要求列数相同，缺失列补 NULL。
```sql
SELECT * FROM capitals
UNION BY NAME
SELECT * FROM weather;   -- UNION BY NAME 去重；UNION ALL BY NAME 不去重
```

---

## 9. 窗口函数（Window Functions）

> 窗口函数的完整函数列表在独立文档 `sql/functions/window_functions.md`（不在本 query_syntax 目录内）。本目录仅含 `WINDOW` 子句（命名窗口）与 QUALIFY 子句。

### 9.1 OVER / PARTITION BY / ORDER BY
窗口函数通过 `OVER` 子句计算"相对其他行"的值，不折叠行数。
```sql
SELECT row_number() OVER () FROM sales;
SELECT amount - lag(amount) OVER (ORDER BY time) FROM sales;
SELECT
    schema_name, function_name,
    row_number() OVER (PARTITION BY schema_name ORDER BY function_name) AS function_rank
FROM duckdb_functions();
```
- `PARTITION BY`：分区（类似 GROUP BY 但不合并行）。
- `ORDER BY`：分区内排序。
- 帧规范（frame spec）：`ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING`（见 with.md 递归 CTE 中的 endReached 示例）、`RANGE` 等，详见 window_functions 文档。

### 9.2 WINDOW 子句（命名窗口）
当多个窗口函数使用相同窗口时，可用 `WINDOW` 命名复用，避免重复：
```sql
SELECT
    row_number() OVER my_window AS function_rank
FROM duckdb_functions()
WINDOW my_window AS (PARTITION BY schema_name ORDER BY function_name)
QUALIFY row_number() OVER my_window < 3;
```

### 9.3 QUALIFY 子句（DuckDB 特色）
`QUALIFY` 用于**过滤窗口函数的结果**（类比 `HAVING` 过滤聚合）。位置在 `WINDOW` 子句之后、`ORDER BY` 之前。避免用子查询/CTE 来过滤窗口函数。
```sql
SELECT
    schema_name, function_name,
    row_number() OVER (PARTITION BY schema_name ORDER BY function_name) AS function_rank
FROM duckdb_functions()
QUALIFY function_rank < 3;
```
> 等价写法（不用 QUALIFY）是外包一层 `WITH ranked_functions AS (...) SELECT * WHERE function_rank < 3`。

---

## 10. WITH 子句 / 公共表表达式（CTE）

CTE 是作用域限定在单条查询内的"视图"。可相互引用、可嵌套；递归 CTE 可自我引用。

### 10.1 基础 CTE
```sql
WITH cte AS (SELECT 42 AS x) SELECT * FROM cte;

WITH
    cte1 AS (SELECT 42 AS i),
    cte2 AS (SELECT i * 100 AS x FROM cte1)
SELECT * FROM cte2;

WITH cte(j) AS (SELECT 42 AS i) FROM cte;   -- 指定列名
```

### 10.2 CTE 物化（Materialization，DuckDB 特色）
DuckDB 默认**物化** CTE（算一次存临时表）。满足条件时**内联**（inline，复制定义到引用处）：
- CTE 被引用不超过一次；
- 不含 `VOLATILE` 函数；
- 使用 `AS NOT MATERIALIZED` 且未用 `AS MATERIALIZED`；
- 不做分组聚合。
显式控制：`WITH t(x) AS MATERIALIZED (...)` / `WITH t(x) AS NOT MATERIALIZED (...)`。
> 一般不建议显式物化提示，优化器会自动决定；但昂贵 CTE 被多次引用时用 `MATERIALIZED` 可提升性能。

### 10.3 递归 CTE（WITH RECURSIVE）
可自我引用，必须确保终止（否则死循环）。基本结构：`anchor 部分 UNION ALL 递归部分`。

**斐波那契：**
```sql
WITH RECURSIVE FibonacciNumbers (RecursionDepth, FibonacciNumber, NextNumber) AS (
    SELECT 0, 0, 1                       -- base case
    UNION ALL
    SELECT fib.RecursionDepth + 1, fib.NextNumber, fib.FibonacciNumber + fib.NextNumber
    FROM FibonacciNumbers fib
    WHERE fib.RecursionDepth + 1 < 10
)
SELECT fn.RecursionDepth, fn.FibonacciNumber FROM FibonacciNumbers fn;
```

**树遍历（tag 层级）：**
```sql
WITH RECURSIVE tag_hierarchy(id, source, path) AS (
    SELECT id, name, [name] FROM tag WHERE subclassof IS NULL
    UNION ALL
    SELECT tag.id, tag.name, list_prepend(tag.name, tag_hierarchy.path)
    FROM tag, tag_hierarchy
    WHERE tag.subclassof = tag_hierarchy.id
)
SELECT path FROM tag_hierarchy WHERE source = 'Oasis';
```

**图遍历与环检测（cycle detection）：**
- 枚举所有路径：在递归步中用 `WHERE list_position(paths.path, node2id) IS NULL` 防止重复节点（避免环）。
- 枚举最短路径：用 `WHERE NOT EXISTS (FROM paths previous_paths WHERE list_contains(previous_paths.path, node2id))` 确保节点未被任何先前路径访问。
- 两点间最短路径：递归步中加 `max(CASE WHEN node2id = 8 THEN 1 ELSE 0 END) OVER (ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS endReached`，并在 `WHERE paths.endReached = 0` 处停止递归。

### 10.4 recurring 前缀访问并集表（union table）
在递归项的 `FROM` 中，CTE 名只指"上一次迭代产生的行"；用 `recurring.<cte>` 可访问**所有迭代累积至今的全部行**：
```sql
WITH RECURSIVE counter(i) AS (
    SELECT 1
    UNION ALL
    SELECT i + 1 FROM counter
    WHERE (SELECT max(i) FROM recurring.counter) < 5
)
SELECT * FROM counter;
```

### 10.5 USING KEY 递归 CTE（键式更新，DuckDB 特色）
`USING KEY (key_col)` 使 CTE 在每轮迭代可**更新**并集中已有键的行（类似字典），而非只追加。无此键则追加。能显著缩小并集表、降低内存与耗时。
```sql
WITH RECURSIVE tbl(a, b) USING KEY (a) AS (
    SELECT a, b FROM (VALUES (1,3),(2,4)) t(a,b)
    UNION ALL
    SELECT a + 1, b FROM tbl WHERE a < 3
)
SELECT * FROM tbl;
```
anchor 也可用 `VALUES`：`WITH RECURSIVE tbl(a,b) USING KEY (a) AS (VALUES (1,3),(2,4) UNION ALL ...)`。
> 应用示例：连通分量（connected components）算法，用 `recurring.<cte>` 引用并集表做字典更新。

### 10.6 版本特定事实（重要）
> **DuckDB 1.5.0 起弃用**：`USING KEY` 递归 CTE 中的递归 `UNION` 改为要求递归 `UNION ALL`（因为所有行都会传入下一轮，而非去重传递）。
> - `SET deprecated_using_key_syntax = 'DEFAULT';`（1.5.0 默认，两者均允许）
> - `SET deprecated_using_key_syntax = 'UNION_AS_UNION_ALL';`
> - DuckDB 2.0.0 默认禁用 `UNION` 语法；2.1.0 移除该 flag 并彻底弃用 `UNION` 写法。

### 10.7 限制
DuckDB **不支持相互递归（mutually recursive）CTE**。

---

## 11. VALUES 子句

`VALUES` 生成固定行数，可作独立语句、FROM 子句一部分或 INSERT 输入。
```sql
VALUES ('Amsterdam', 1), ('London', 2);
SELECT * FROM (VALUES ('Amsterdam', 1), ('London', 2)) cities(name, id);
INSERT INTO cities VALUES ('Amsterdam', 1), ('London', 2);
CREATE TABLE cities AS SELECT * FROM (VALUES ('Amsterdam',1),('London',2)) cities(name, id);
```

---

## 12. unnest（Unnesting）

`unnest` 把 list/struct 拆一层（仅用于 SELECT 子句，作为标量函数）。

### 12.1 拆 list
```sql
SELECT unnest([1, 2, 3]);                       -- 3 行
SELECT unnest([1, 2, 3]), 10;                   -- 标量表达式每行重复
SELECT unnest([1,2,3]), unnest([10,11]);        -- 多个 list 并排拆，短者补 NULL
SELECT unnest(l) + 10 FROM (VALUES ([1,2,3]),([4,5])) tbl(l);
SELECT unnest([]);                              -- 空结果
SELECT unnest(NULL);                            -- 空结果
```
> 空 list 与 NULL list 都拆成零行。

### 12.2 拆 struct
```sql
SELECT unnest({'a': 42, 'b': 84});              -- 生成两列 a,b
SELECT unnest({'a': 42, 'b': {'x': 84}});       -- 嵌套 struct 逐层展开成多列
```

### 12.3 递归 unnest（recursive / max_depth）
```sql
SELECT unnest([{'a':42,'b':84},{'a':100,'b':NULL}], recursive := true);
SELECT unnest([[[1,2],[3,4]], [[5,6],[7,8,9],[]], [[10,11]]], max_depth := 2);
```
- `recursive := true` 先完全拆 list 再完全拆 struct（struct 内的 list 不会被拆）。
- `max_depth` 限制递归深度（默认即递归）。
- `keep_parent_names := true` 递归时保留父列名路径（如 `b.bb.bbb`）。

### 12.4 保留位置（下标）
```sql
SELECT unnest(l) AS x, generate_subscripts(l, 1) AS index
FROM (VALUES ([1,2,3]),([4,5])) tbl(l);
```

---

## 13. ORDER BY 子句

`ORDER BY` 是输出修饰符，逻辑上在接近查询末尾（LIMIT/OFFSET 之前）执行，对行排序。可含多表达式（逗号分隔），每个可带方向（`ASC`/`DESC`，默认 ASC）与 NULL 排序（`NULLS FIRST`/`NULLS LAST`，默认 `NULLS LAST`）。

```sql
SELECT * FROM addresses ORDER BY city;
SELECT * FROM addresses ORDER BY city DESC NULLS LAST;
SELECT * FROM addresses ORDER BY city, zip;
SELECT * FROM addresses ORDER BY city COLLATE DE;   -- 德语排序规则
```

### 13.1 ORDER BY ALL（DuckDB 特色）
按从左到右所有列排序，不可与其他表达式混用：
```sql
SELECT * FROM addresses ORDER BY ALL;        -- 升序
SELECT * FROM addresses ORDER BY ALL DESC;   -- 降序
```

### 13.2 NULL 排序默认值与配置
- 默认 `ASC` 且 `NULLS LAST`（与 PostgreSQL 的 ASC 一致）。但 DuckDB 即便 `DESC` 也保持 `NULLS LAST`，而 PostgreSQL 的 DESC 把 NULL 放最前。
- 两边匹配 PostgreSQL：`SET default_null_order = 'NULLS_LAST_ON_ASC_FIRST_ON_DESC';`
- 可用配置：`default_null_order`（取值 `NULLS_FIRST`/`NULLS_LAST`/`NULLS_FIRST_ON_ASC_LAST_ON_DESC`/`NULLS_LAST_ON_ASC_FIRST_ON_DESC`）、`default_order`（`ASC`/`DESC`）。

### 13.3 文本排序（Collation）
默认按二进制（UTF-8 字节）比较；非 ASCII 语言可用 collation（如 `COLLATE DE`）。

---

## 14. LIMIT / OFFSET / TOP

`LIMIT`/`OFFSET` 是输出修饰符，逻辑上最后执行。`LIMIT` 限制返回行数，`OFFSET` 跳过前 N 行。
```sql
SELECT * FROM addresses LIMIT 5;
SELECT * FROM addresses LIMIT 5 OFFSET 5;
SELECT city, count(*) AS population FROM addresses GROUP BY city ORDER BY population DESC LIMIT 5;
SELECT * FROM addresses LIMIT 10%;   -- 按百分比
```
> 无 `ORDER BY` 时 `LIMIT` 结果可能不确定（适合快速预览快照）。文档未单列 TOP 语法，但 `LIMIT n` 即等价功能。

---

## 15. SAMPLE 子句（补充说明）

见第 2.6 节。语法为 `USING SAMPLE <size> [(method)]`，size 可为百分比或 `ROWS`。与 `TABLESAMPLE` 类似，区别在于写法位置。

---

## 16. 预处理语句（Prepared Statements，补充）

`PREPARE ... AS SELECT ...` + `EXECUTE` 可参数化查询（提升可读性、防 SQL 注入）。三种参数语法：
```sql
PREPARE q AS SELECT * FROM person WHERE starts_with(name, ?) AND age >= ?;          -- 自动编号 ?
EXECUTE q('B', 40);

PREPARE q AS SELECT * FROM person WHERE starts_with(name, $2) AND age >= $1;
EXECUTE q(40, 'B');                                                                  -- $1 对应 40

PREPARE q AS SELECT * FROM person WHERE starts_with(name, $name_start) AND age >= $min_age;
EXECUTE q(name_start := 'B', min_age := 40);                                          -- 命名参数
```
`DEALLOCATE query_person;`（或 `DEALLOCATE PREPARE query_person;`）丢弃预处理语句。
> JDBC 客户端仅支持自动编号 `?`。

---

## 17. Lambda 表达式与列引用

本目录范围内涉及：
- 正则选列（lambda 式）：

  ```sql
  SELECT COLUMNS('number\d+') FROM addresses;   -- 列名匹配正则
  SELECT min(COLUMNS(*)) FROM addresses;        -- 对所有列应用聚合
  ```
- `*` / `EXCLUDE` / `REPLACE` 列变换（见 1.3 节）。
- 文档中提到的 `COLUMN['name']` 列引用形式未在本 query_syntax 目录文件出现（属 expressions 文档范畴，本整理未覆盖）。

---

## 18. 速查总结（Cheat Sheet）

| 子句 | 关键特性 / DuckDB 特色 |
|---|---|
| `SELECT` | `*` / `EXCLUDE` / `REPLACE` / `COLUMNS()`；前缀别名 `res:`；`DISTINCT ON` |
| `FROM` | 表函数、`'file.csv'` 自动 read_csv、`WITH ORDINALITY`、FROM-first 语法、`TABLESAMPLE` |
| `JOIN` | INNER/LEFT/RIGHT/FULL/CROSS/NATURAL/USING/SEMI/ANTI/**LATERAL**/**POSITIONAL**/**ASOF** |
| `WHERE` | 行过滤（`LIKE`/`ILIKE`等），在 GROUP BY 前 |
| `GROUP BY` | `GROUP BY ALL` |
| 多维分组 | `GROUPING SETS` / `ROLLUP` / `CUBE`；`GROUPING_ID()` |
| `HAVING` | 分组后过滤 |
| `FILTER` | 聚合内局部过滤 / 静态 pivot |
| 集合运算 | `UNION/INTERSECT/EXCEPT [ALL]`、`UNION [ALL] BY NAME` |
| 窗口 | `OVER`/`PARTITION BY`/`ORDER BY`/帧规范；`WINDOW` 命名；`QUALIFY` 过滤 |
| CTE | `WITH`、物化/内联、`WITH RECURSIVE`、`recurring.` 并集表、`USING KEY`（1.5.0 弃用递归 UNION） |
| `VALUES` | 生成行 |
| `unnest` | 拆 list/struct，`recursive`/`max_depth`/`keep_parent_names` |
| `ORDER BY` | `ORDER BY ALL`、NULLS FIRST/LAST、collation |
| `LIMIT/OFFSET` | 限制/偏移、百分比 |
| `SAMPLE` | `USING SAMPLE` 抽样 |
| 预处理 | `?` / `$1` / `$name` 参数、`PREPARE`/`EXECUTE`/`DEALLOCATE` |

---

> **版本提示（1.5.5）**：本批文档中最显著的版本相关变更是 `USING KEY` 递归 CTE 在 1.5.0 起要求递归 `UNION ALL`（见 10.6）。编写时若需兼容未来版本（2.0+/2.1+），应统一使用 `UNION ALL` 而非 `UNION` 于 `USING KEY` CTE。其余语法（FROM-first、GROUP BY ALL、ORDER BY ALL、UNION BY NAME、QUALIFY、LATERAL/POSITIONAL/ASOF JOIN、FILTER、unnest recursive 等）均为 DuckDB 稳定的特色能力。
