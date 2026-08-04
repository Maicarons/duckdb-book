# 第 05 章 SQL 基础：查询语言

SQL 是 DuckDB 与使用者对话的唯一正式语言。DuckDB 复用了 PostgreSQL 的解析器（libpg_query），因此标准 SQL 的骨架在这里都能直接使用；与此同时，它在投影（projection）、分组、连接、集合运算与公共表表达式（CTE）等若干处都做了务实的扩展，这些扩展正是 DuckDB "为分析减负" 设计取向的集中体现。本章不重复 SQL 的通用教程，而是围绕 DuckDB 的方言特性展开：哪些写法比标准 SQL 更省事，哪些语义与 PostgreSQL、SQLite 存在微妙差异，以及哪些看似花哨的语法其实是数据分析的利器。理解本章的关键，是先接受一个事实——**书写顺序不等于逻辑执行顺序**：`SELECT` 写在最前，却在逻辑上最后落地。

## 5.1 SELECT 与投影

`SELECT` 子句决定结果包含哪些列，它可以承载任意表达式：算术运算、标量函数、聚合或窗口函数。每个输出表达式都会被赋予一个名字，显式命名用 `AS`，缺省时由系统自动推导。DuckDB 的列名大小写不敏感，`city` 与 `CITY` 指向同一列。

最朴素的投影是星号表达式（star expression）：`SELECT * FROM tbl;` 取回所有列。在列众多的宽表上，逐个点名既啰嗦又易错，DuckDB 因此提供了两个配套修饰——`EXCLUDE` 与 `REPLACE`：

```sql
-- 排除某一列
SELECT * EXCLUDE (zip) FROM (VALUES (1, 'X', '123'), (2, 'Y', '456')) a(id, city, zip);

-- 替换某一列（保留列名，改写其值）
SELECT * REPLACE (lower(city) AS city) FROM (VALUES (1, 'AMSTERDAM')) a(id, city);
```

`EXCLUDE` 在"我几乎要全部列、只丢掉少数几列"时格外顺手；`REPLACE` 则在不改变输出列结构的前提下就地改写某列，省去重写整个投影列表。

当列名遵循某种命名规律（例如 `number1`、`number2`……）时，逐列罗列同样低效。DuckDB 的 `COLUMNS()` 接受正则表达式，按列名批量选中：

```sql
-- 选出所有以 number 开头、后接数字的列
SELECT COLUMNS('number\d+') FROM (VALUES (10, 20, 'ignore')) t(number1, number2, other);

-- 对每一列分别套用同一个聚合
SELECT min(COLUMNS(*)) FROM (VALUES (3, 9), (1, 5)) t(a, b);
```

`COLUMNS(*)` 把"所有列"作为参数传给聚合函数，等价于对每列各写一次 `min`。

别名（alias）有两种写法。后缀别名是 SQL 通用形式：`SELECT i * i AS square FROM ...`。DuckDB 额外支持**前缀别名**，把名字写在表达式之前、以冒号分隔：

```sql
SELECT res: i * i, root: sqrt(i) FROM range(5) t(i);
```

前缀别名在投影列表很长、且表达式本身已较复杂时，能让"输出叫什么"一眼可读，不必滚到行尾去找 `AS`。列名若含空格或特殊字符，用双引号包裹：`SELECT "Some Column Name" FROM tbl;`。

DuckDB 还有一个背离传统 SQL 习惯、却深得数据分析者喜欢的特性——**FROM-first 语法**。它允许把 `FROM` 前置，甚至可以省略 `SELECT`：

```sql
FROM range(5) t(i) SELECT i, i * i AS square WHERE i % 2 = 0;
FROM range(5) t(i);                 -- 等价于 SELECT * FROM range(5) t(i);
```

在交互式探索数据时，FROM-first 让思路顺着"先定位数据、再决定看什么"展开。`SELECT` 在此被推到最后，恰好印证了它逻辑上最后执行的本质。

投影相关的另一个值得记下的语法是 `DISTINCT ON (expr)`：它为每个唯一表达式值只保留一行，若有 `ORDER BY`，则保留该排序下的第一行。对大表做关键列去重时，它比 `DISTINCT *` 更省——只要排序列能唯一标识，优化器就无需对整行哈希。

## 5.2 WHERE、过滤与排序

`WHERE` 在逻辑顺序中紧随 `FROM`（含 `JOIN`）之后执行，对**行**做过滤——注意它发生在分组之前，因此作用于聚合之前的原始数据。过滤谓词写法与通用 SQL 一致，字符串匹配需留意 `LIKE` 大小写敏感、而 `ILIKE` 不敏感：

```sql
SELECT i FROM range(10) t(i) WHERE i > 3 AND i < 8;
```

排序由 `ORDER BY` 承担，它在接近查询末尾、`LIMIT`/`OFFSET` 之前执行。`ORDER BY` 可含多个表达式（逗号分隔），每个可单独指定 `ASC`/`DESC` 与 `NULLS FIRST`/`NULLS LAST`。这里藏着一个与 PostgreSQL 的分歧：**DuckDB 默认的 NULL 排序是 `NULLS LAST`**，并且无论升序还是降序都保持 `NULLS LAST`——而 PostgreSQL 在 `DESC` 时会把 NULL 翻到最前。这一差异在跨数据库迁移排序逻辑时极易踩坑：

```sql
SELECT v FROM (VALUES (1), (NULL), (3)) t(v) ORDER BY v;          -- NULL 在末尾
SELECT v FROM (VALUES (1), (NULL), (3)) t(v) ORDER BY v DESC;     -- DuckDB 中 NULL 仍在末尾
```

若希望行为与 PostgreSQL 完全对齐，可设置 `SET default_null_order = 'NULLS_LAST_ON_ASC_FIRST_ON_DESC';`。

当需要对所有列按从左到右依次排序时，逐个列出列名是浪费。`ORDER BY ALL` 一次性按全部输出列排序，且不可再混入其他表达式：

```sql
SELECT * FROM (VALUES (2, 'b'), (1, 'a'), (3, 'c')) t(x, y) ORDER BY ALL;
SELECT * FROM (VALUES (2, 'b'), (1, 'a'), (3, 'c')) t(x, y) ORDER BY ALL DESC;
```

`LIMIT` 与 `OFFSET` 是逻辑上最后落地的输出修饰符：`LIMIT` 限定返回行数，`OFFSET` 跳过前 N 行，二者常用于分页或取 Top-N。DuckDB 还允许 `LIMIT` 接受一个百分比，按总行数比例截取——没有 `ORDER BY` 时结果顺序不确定，仅适合快速预览：

```sql
SELECT i FROM range(10) t(i) ORDER BY i LIMIT 3 OFFSET 2;   -- 取第 3、4、5 行
SELECT i FROM range(100) t(i) ORDER BY i LIMIT 10%;         -- 取约前 10 行
```

## 5.3 聚合与分组

`GROUP BY` 指定按哪些列分组后再聚合。只要 `SELECT` 中出现了聚合函数，查询便成为聚合查询，所有未被聚合包裹的表达式都必须出现在 `GROUP BY` 里。DuckDB 的 `GROUP BY ALL` 把这件事自动化：它按 `SELECT` 中所有"未被聚合包裹"的列自动分组，既减少笔误，也保证投影粒度与分组粒度一致：

```sql
SELECT city, avg(income)
FROM (VALUES ('A', 100), ('A', 200), ('B', 300)) t(city, income)
GROUP BY ALL;
```

需要提醒的是，`GROUP BY ALL` 与多维分组（`GROUPING SETS`/`CUBE`/`ROLLUP`）互不兼容，后文的多维分组须显式列出维度。

多维分组用于在**单次查询**内沿多个维度汇总，等价于把多个分组查询 `UNION ALL` 拼起来，超聚合（super-aggregate）行以 NULL 填充缺失维度：

```sql
-- 显式分组集；() 表示"不分组的总聚合"
SELECT city, street, avg(income)
FROM (VALUES ('A', 's1', 100), ('A', 's2', 200), ('B', 's1', 300)) t(city, street, income)
GROUP BY GROUPING SETS ((city, street), (city), (street), ());

SELECT city, street, avg(income) FROM t GROUP BY ROLLUP (city, street);   -- 层级下钻：(city,street),(city),()
SELECT city, street, avg(income) FROM t GROUP BY CUBE  (city, street);   -- 全组合：2^2 = 4 个分组集
```

`ROLLUP(a,b,c)` 产出 n+1 个层级分组集，适合从细到粗的下钻；`CUBE(a,b,c)` 产出全部 2^n 个维度组合。当分组列本身含真实 NULL 时，"真实 NULL" 与"超聚合产生的 NULL" 无法区分，此时用 `GROUPING_ID()`（返回 BIGINT 位标志）来识别哪些列参与了当前分组。

`FILTER` 子句跟在聚合函数之后，只把满足谓词的行喂给该聚合，相当于聚合内部的局部 `WHERE`。它在"同一查询内对多个子集分别计数"时极为自然，最典型的应用是**静态 pivot（static pivot）**——把行里的类别转成并排的列：

```sql
SELECT
    count(i) FILTER (y = 2022) AS "2022",
    count(i) FILTER (y = 2023) AS "2023",
    count(i) FILTER (y IS NULL) AS "missing"
FROM (VALUES (1, 2022), (2, 2022), (3, 2023), (4, NULL)) t(i, y);
-- 结果：2022 = 2，2023 = 1，missing = 1
```

相比用 `CASE WHEN` 实现同样效果，`FILTER` 对 `first`/`last`/`list`/`array_agg` 这类"不忽略 NULL"的函数处理得更准确，因为它在聚合求值前就先筛掉了无关行。

`HAVING` 则在 `GROUP BY` 之后、对**分组后的结果**做过滤——语法与 `WHERE` 相仿，但作用对象已是聚合输出而非原始行：

```sql
SELECT city, count(*) AS n
FROM (VALUES ('A'), ('A'), ('B')) t(city)
GROUP BY city
HAVING count(*) >= 2;   -- 只保留出现不少于两次的城市
```

## 5.4 多表连接

连接（join）是把两个关系（左、右）水平拼接的关系运算，结果行包含两侧的全部列；外连接在无匹配时用 NULL 填充缺失一侧。DuckDB 支持的连接类型如下表：

| 连接类型 | 语义 |
|---|---|
| `INNER`（默认） | 仅返回两侧都能配对的行 |
| `LEFT` | 左表每行至少出现一次，右无匹配补 NULL |
| `RIGHT` | 右表每行至少出现一次，左无匹配补 NULL |
| `FULL` | 两侧每行至少出现一次，缺失侧补 NULL |
| `CROSS` | 笛卡尔积，无连接条件 |
| `NATURAL` | 按所有同名列自动等值连接 |
| `USING (col)` | 仅对指定同名列做等值连接（更简洁） |
| `SEMI` | 左表中存在匹配的行（逻辑同 `IN`） |
| `ANTI` | 左表中不存在匹配的行（逻辑同 `NOT IN`，但忽略右表 NULL） |
| `LATERAL` | 右侧子查询可引用左侧列（相关子查询的泛化） |
| `POSITIONAL` | 按物理行位置连接 |
| `ASOF` | 时序/有序数据的最近事件连接 |

`SEMI` 与 `ANTI` 是 DuckDB 对 SQL 标准的有益补充，它们的结果行数绝不会超过左表。`SEMI` 等价于 `WHERE 列 IN (...)`；`ANTI` 等价于 `WHERE 列 NOT IN (...)`，但规避了 `NOT IN` 的著名陷阱——一旦右侧列含有 NULL，`NOT IN` 的语义会让整个结果变空，而 `ANTI` 直接忽略右表 NULL：

```sql
-- SEMI：左表中能在右表找到匹配者
SELECT * FROM (VALUES (1), (2), (3)) a(x)
SEMI JOIN (VALUES (2), (4)) b(x) USING (x);          -- 返回 x = 2

-- ANTI：左表中在右表找不到匹配者；右侧的 NULL 被忽略
SELECT * FROM (VALUES (1), (2), (3)) a(x)
ANTI JOIN (VALUES (2), (NULL)) b(x) USING (x);       -- 返回 x = 1, 3
```

`LATERAL` 让右侧子查询能引用左侧已计算的列，是相关子查询（correlated subquery）的泛化——左侧每个输入值都可让右侧返回多行。DuckDB 还能自动判断何时需要 `LATERAL`，关键字常常可以省略：

```sql
SELECT * FROM range(3) t(i), LATERAL (SELECT i + 1) t2(j);
```

`POSITIONAL` 连接按物理行号把两表对齐，它始终表现为 FULL OUTER 语义：结果长度等于较长的一侧，短侧不足处补 NULL。它专为本身带有自然顺序的数据（dataframe、CSV、Parquet 读入的批）而设，避免使用脆弱的偏移量去假装有序：

```sql
SELECT * FROM (VALUES (1), (2), (3)) a(x)
POSITIONAL JOIN (VALUES ('p'), ('q')) b(y);
-- 结果：(1,'p'), (2,'q'), (3, NULL)
```

`ASOF` 连接服务于时序场景：把左表的每条记录，与右表中"时间上最近且不超过它"的事件配对。它至少需要一个关于排序字段的**不等式条件**（最常用 `>=`），其余条件必须是等值（`=` 或 `NOT DISTINCT`），且左右表顺序敏感，可加 `OUTER` 寻找无配对行：

```sql
SELECT t.symbol, t.when, p.price
FROM (VALUES ('A', TIMESTAMP '2024-01-01 10:00:00'),
             ('A', TIMESTAMP '2024-01-01 10:05:00')) t(symbol, when)
ASOF JOIN (VALUES ('A', TIMESTAMP '2024-01-01 09:59:00', 10.5),
                  ('A', TIMESTAMP '2024-01-01 10:03:00', 11.0)) p(symbol, when, price)
ON t.symbol = p.symbol AND t.when >= p.when;   -- 右表价格按时间就近匹配
```

所有连接类型都支持**自连接**（self-join），但必须把同一张表起不同的别名，否则会报 "Duplicate alias" 错误。下面这条查询用自连接从员工表中找出每位员工的直接上级：

```sql
WITH emp(id, mgr) AS (
    VALUES (1, NULL), (2, 1), (3, 1), (4, 2)
)
SELECT e.id AS employee, m.id AS boss
FROM emp e JOIN emp m ON e.mgr = m.id;
```

## 5.5 集合运算

集合运算把两个查询的结果纵向叠加。`UNION`/`UNION ALL`/`INTERSECT`/`EXCEPT` 传统上**按列位置**合并，要求两侧列数相同（类型不同会隐式转换，结果列名取自第一个查询）：

```sql
SELECT * FROM range(2) t(x) UNION     SELECT * FROM range(3) t(x);   -- 去重合并
SELECT * FROM range(2) t(x) UNION ALL SELECT * FROM range(3) t(x);   -- 保留重复
SELECT * FROM range(2) t(x) INTERSECT SELECT * FROM range(6) t(x);   -- 交集
SELECT * FROM range(5) t(x) EXCEPT    SELECT * FROM range(2) t(x);   -- 差集
```

`UNION` 与 `INTERSECT`、`EXCEPT` 默认带集合语义（去重），加上 `ALL` 则转为包语义（不去重、按重数计），在已知无重复或本就希望保留重复时，`ALL` 能省去去重开销。

位置对齐在列顺序不一致时是个麻烦。DuckDB 的 `UNION [ALL] BY NAME` 改为**按列名**合并，不要求列数或列序相同，缺失列自动补 NULL：

```sql
SELECT * FROM (VALUES (1, 'x'), (2, 'y')) a(id, label)
UNION BY NAME
SELECT * FROM (VALUES ('p', 3), ('q', 4)) b(label, id);
-- 两查询按 id、label 两列名对齐合并，顺序不同也无妨；UNION BY NAME 默认去重
```

`UNION ALL BY NAME` 则不去重。它让"结构相似但列不完全一致"的多张表合并变得轻而易举，不必先用 `SELECT` 把列补齐对齐。

## 5.6 窗口函数

窗口函数（window function）通过 `OVER` 子句计算"相对其他行"的值，关键在于它**不折叠行数**——每一行都保留，并附上计算结果。`PARTITION BY` 划定分区（类似 `GROUP BY` 但不合并行），`ORDER BY` 决定分区内的顺序：

```sql
SELECT
    schema_name, function_name,
    row_number() OVER (PARTITION BY schema_name ORDER BY function_name) AS function_rank
FROM duckdb_functions();
```

窗口的核心是**帧（frame）**规范，它划定每个当前行所"看到"的邻域。`ROWS BETWEEN ... AND ...` 以物理行数为界，下面的例子对每个点取前后各一行做滑动求和：

```sql
SELECT i,
       sum(i) OVER (ORDER BY i ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING) AS moving_sum
FROM range(1, 6) t(i);   -- 第 1 行看到 [1,2]，中间行看到三行，末行看到 [4,5]
```

当多个窗口函数共用同一窗口定义时，重复书写既冗长又易错。`WINDOW` 子句允许把窗口命名并复用：

```sql
SELECT
    row_number() OVER w AS r,
    rank()       OVER w AS rnk
FROM duckdb_functions()
WINDOW w AS (PARTITION BY schema_name ORDER BY function_name);
```

窗口函数的结果若想再过滤，标准做法是外包一层子查询或 CTE。DuckDB 提供 `QUALIFY` 子句，直接对窗口函数输出做筛选，位置在 `WINDOW` 之后、`ORDER BY` 之前——如同 `HAVING` 之于聚合：

```sql
SELECT
    schema_name, function_name,
    row_number() OVER (PARTITION BY schema_name ORDER BY function_name) AS function_rank
FROM duckdb_functions()
QUALIFY function_rank < 3;   -- 每个 schema 内只保留排名前两的函数
```

时间序列分析中常遇到零星缺失的采样点。DuckDB 的 `fill()` 可对 NULL 做**线性插值**（linear interpolation），把断点之间的空缺按线性趋势补上，配合窗口即可沿时间轴逐段填补：

```sql
SELECT ts, val, fill(val) OVER (ORDER BY ts) AS filled
FROM (VALUES (1, 10.0), (2, NULL), (3, NULL), (4, 40.0)) t(ts, val);
-- filled 列：10, 20, 30, 40 —— 两端已知点之间等距线性补值
```

fill() 对列内缺失值做线性插值；对序列**两端的缺失值默认采用线性外推**。其签名为 `fill(expr [ORDER BY ordering])`，没有可切换该行为的额外参数。它把"清理带洞的时序"从几十行 CASE 表达式压缩成一行调用。

## 5.7 CTE 与递归查询

公共表表达式（CTE，Common Table Expression）是用 `WITH` 定义的、作用域限定在单条查询内的临时视图，可相互引用、可嵌套。它让复杂查询的逻辑分层清晰，而不必落地成真实表：

```sql
WITH cte1 AS (SELECT 42 AS i),
     cte2 AS (SELECT i * 100 AS x FROM cte1)
SELECT * FROM cte2;
```

DuckDB 默认会**物化**（materialize）CTE——计算一次、存入临时表；在满足条件（被引用不超过一次、不含 VOLATILE 函数、不做分组聚合等）时则**内联**（inline，把定义复制到引用处）。你也可以用 `MATERIALIZED` / `NOT MATERIALIZED` 显式干预——一个昂贵的 CTE 若被多次引用，强制 `MATERIALIZED` 可避免重复计算：

```sql
WITH expensive AS MATERIALIZED (SELECT count(*) FROM (VALUES (1),(2),(3)) t(x))
SELECT * FROM expensive, expensive;   -- 仅计算一次
```

`WITH RECURSIVE` 让 CTE 自我引用，从而表达层级、序列与图遍历。递归 CTE 的基本结构是"锚点（anchor）部分 `UNION ALL` 递归部分"。下面用斐波那契数列作最小示例：

```sql
WITH RECURSIVE FibonacciNumbers (RecursionDepth, FibonacciNumber, NextNumber) AS (
    SELECT 0, 0, 1                                            -- 锚点
    UNION ALL
    SELECT fib.RecursionDepth + 1,
           fib.NextNumber,
           fib.FibonacciNumber + fib.NextNumber
    FROM FibonacciNumbers fib
    WHERE fib.RecursionDepth + 1 < 10                          -- 终止条件
)
SELECT RecursionDepth, FibonacciNumber FROM FibonacciNumbers;
```

需要特别注意版本事实：自 **DuckDB 1.5.0 起**，`USING KEY` 递归 CTE 中弃用了递归部分的 `UNION`，改用 `UNION ALL`——因为所有行都会流入下一轮而非去重传递；**2.0.0 默认禁用**递归 `UNION`，到 2.1.0 将彻底移除该写法。为兼容未来版本，递归 CTE 一律使用 `UNION ALL` 是最稳妥的选择。

递归最自然的用武之地是图遍历，而图必有环，需要**环检测（cycle detection）**。借助列表函数 `list_position` 与 `list_contains` 记录已访问节点，可阻止递归无限延伸：

```sql
WITH edges(from_node, to_node) AS (
    VALUES (1, 2), (2, 3), (3, 1)          -- 含环：1 → 2 → 3 → 1
),
paths(start_node, current, path) AS (
    SELECT from_node, to_node, [from_node, to_node]
    FROM edges
    UNION ALL
    SELECT p.start_node, e.to_node, list_append(p.path, e.to_node)
    FROM paths p JOIN edges e ON p.current = e.from_node
    WHERE list_position(p.path, e.to_node) IS NULL   -- 节点已访问过则不再延伸，破除环
)
SELECT * FROM paths;
```

`list_position(p.path, e.to_node) IS NULL` 保证某节点在一条路径上只出现一次；若想枚举的是两点间最短路径，可改用 `WHERE NOT EXISTS (FROM paths prev WHERE list_contains(prev.path, e.to_node))`，确保节点不被任何已有路径访问过。

`USING KEY (key_col)` 是另一种递归增强，它让 CTE 在每轮迭代中对"已存在该键的行"做**更新**而非单纯追加，相当于一张按字典键更新的并集表（union table）。无该键时则照常追加，能显著压缩并集表体积、降低内存与耗时，常用于连通分量等图算法：

```sql
WITH RECURSIVE tbl(a, b) USING KEY (a) AS (
    SELECT a, b FROM (VALUES (1, 3), (2, 4)) t(a, b)
    UNION ALL
    SELECT a + 1, b FROM tbl WHERE a < 3
)
SELECT * FROM tbl;
```

此外，递归项中 CTE 名默认只指"上一轮迭代产生的行"；前缀 `recurring.` 则可访问**截至当前的全部累积行**，用于需要回顾历史并集的算法。最后提醒：DuckDB **不支持相互递归（mutually recursive）CTE**，递归只能指向自身。

## 5.8 采样、VALUES、PIVOT/UNPIVOT

大数据集上，先抽样看轮廓往往比全量扫描更高效。DuckDB 提供两种几乎等效的写法：`TABLESAMPLE` 紧贴表名之后，`USING SAMPLE` 则置于表引用（或子查询）之后，二者都在 `FROM` 之后、`WHERE` 之前生效，支持按百分比或按行数抽样，并可指定方法（如 `bernoulli`）：

```sql
SELECT * FROM (VALUES (1),(2),(3),(4),(5)) t(x) TABLESAMPLE 50%;     -- 约半数行
SELECT * FROM (VALUES (1),(2),(3),(4),(5)) t(x) USING SAMPLE 2 ROWS;  -- 约两行
```

抽样结果是随机的，小数据上返回的行数并不精确，仅用于快速预览或近似统计。

`VALUES` 是表值构造器（table value constructor），生成固定行数的关系，可作独立语句、嵌入 `FROM`，或作为 `INSERT` 的输入：

```sql
SELECT * FROM (VALUES ('Amsterdam', 1), ('London', 2)) cities(name, id);
INSERT INTO cities VALUES ('Amsterdam', 1), ('London', 2);
```

`PIVOT` 把"类别在行中"的表旋转为"类别在列中"，即行转列，对列联表（crosstab）式报表极为实用。`ON` 指定要展开成列的列，`USING` 指定聚合方式：

```sql
PIVOT (SELECT country, sales
       FROM (VALUES ('NL', 100), ('NL', 200), ('UK', 150)) t(country, sales))
ON country USING sum(sales);
-- 结果：单列聚合被展开为 NL = 300、UK = 150 的一行
```

与之相对，`UNPIVOT` 执行列转行，把若干列重新堆回"键—值"两列。用 `INTO NAME ... VALUE ...` 显式声明新列名，可读性最佳：

```sql
UNPIVOT (SELECT * FROM (VALUES ('x', 10, 20, 30)) t(name, "2021", "2022", "2023"))
ON "2021", "2022", "2023"
INTO NAME year VALUE amount;
-- 结果：name 保持不变，原三列年份被折叠为 year / amount 两列的多行
```

`PIVOT`/`UNPIVOT` 与 5.3 节用 `FILTER` 手写的静态 pivot 殊途同归：前者是专为旋转设计的语句级语法，后者是通用 SQL 的表达式级写法，可按场景与可读性取舍。

## 5.9 本章小结

本章铺开了 DuckDB 查询语言的主干，而真正需要记住的，是它在标准 SQL 之上为分析场景做的那些"减法"与"加法"。

投影一侧，`*` 配合 `EXCLUDE`/`REPLACE`、`COLUMNS()` 正则选列，把宽表上的列操作从体力活变成一行声明；前缀别名 `res:` 与 FROM-first 语法则是 DuckDB 在可读性上的小执念。`SELECT` 逻辑上最后执行，这一点贯穿全章。

过滤与排序里，最易忽视的细节是 **NULL 排序默认 `NULLS LAST` 且升降序皆然**，与 PostgreSQL 的 `DESC` 行为不同；`ORDER BY ALL` 与百分比 `LIMIT` 则是探索数据时的顺手工具。

分组聚合的核心扩展是 `GROUP BY ALL` 与多维分组 `GROUPING SETS`/`CUBE`/`ROLLUP`；`FILTER` 子句把"同一查询内按不同条件分别聚合"表达得干净，并天然胜任静态 pivot；`HAVING` 守在分组之后做二次过滤。

连接类型中，`SEMI`/`ANTI` 补上了 `IN`/`NOT IN` 的表达缺口，其中 `ANTI` 自动规避 `NOT IN` 遇 NULL 失效的陷阱；`LATERAL`、`POSITIONAL`、`ASOF` 三种特色连接分别解决了相关子查询、按物理位置对齐、时序就近匹配三类真实问题。自连接务必起别名。

集合运算的 `UNION [ALL] BY NAME` 用列名而非位置对齐，让结构相近的表合并不再需要先手工对齐列序。窗口函数以 `OVER`、帧规范、`WINDOW` 命名复用与 `QUALIFY` 过滤构成完整工具链，`fill()` 则把时序线性插值压成一行。CTE 与 `WITH RECURSIVE` 是表达层级与图的利器，物化可控、环检测靠 `list_position`/`list_contains`、键式更新靠 `USING KEY`；版本上务必用 `UNION ALL` 以保证对 2.0+ 的兼容。最后，`TABLESAMPLE`/`USING SAMPLE` 抽样、`VALUES` 构造与 `PIVOT`/`UNPIVOT` 旋转，补足了数据整形（reshaping）的最后一公里。带着这些特性回看日常 SQL，多数"绕弯路"的写法都能在 DuckDB 里找到更短的直路。
