# 第 04 章 SQL 基础：表的定义与数据写入

数据库的价值，始于你亲手建出第一张表、并往里写入第一批数据。前三章铺垫了 DuckDB 的定位与执行模型，本章正式落地到 SQL 的 DDL（数据定义语言，Data Definition Language）与 DML（数据操纵语言，Data Manipulation Language）：如何建表、加约束、定义临时表与生成列，如何插入、更新、删除、合并数据，乃至视图、宏、模式与序列这类复用与组织手段，最后收束于事务与并发模型——这是理解 DuckDB"进程内、单写者"性格不可绕开的一环。

## 4.1 CREATE TABLE 与约束

`CREATE TABLE` 是一切的起点。最朴素的建表只声明列名与类型：

```sql
CREATE TABLE t1 (i INTEGER, j INTEGER);
```

主键（PRIMARY KEY）既可写在列上，也可声明复合主键：

```sql
CREATE TABLE t1 (id INTEGER PRIMARY KEY, j VARCHAR);
CREATE TABLE t1 (id INTEGER, j VARCHAR, PRIMARY KEY (id, j));
```

其余约束——`NOT NULL` 与 `DEFAULT`、`CHECK`、`UNIQUE`、`FOREIGN KEY`——同处建表语句之中：

```sql
CREATE TABLE t1 (
    i INTEGER NOT NULL DEFAULT 0,
    decimalnr DOUBLE CHECK (decimalnr < 10),
    d DATE UNIQUE,
    t TIMESTAMP
);
```

`CHECK` 表达行级条件；给它命名能方便日后排查：

```sql
CREATE TABLE t3 (id INTEGER PRIMARY KEY, x INTEGER, y INTEGER,
    CONSTRAINT x_smaller_than_y CHECK (x < y));
```

`FOREIGN KEY` 引用另一表的主键或唯一列，用于维护引用完整性：

```sql
CREATE TABLE t2 (id INTEGER PRIMARY KEY, t1_id INTEGER,
    FOREIGN KEY (t1_id) REFERENCES t1 (id));
```

两处限制须牢记：外键不支持级联删除 `ON DELETE CASCADE`，也不支持自引用（self-referencing）——向一张引用自身的表插入会触发 "Violates foreign key constraint"。

建表还有两个常用变体：`CREATE OR REPLACE` 等价于先 `DROP` 再 `CREATE`；`IF NOT EXISTS` 在表已存在时安静跳过：

```sql
CREATE OR REPLACE TABLE t1 (i INTEGER, j INTEGER);
CREATE TABLE IF NOT EXISTS t1 (i INTEGER, j INTEGER);
```

`CREATE TABLE` 还可接受 `TEMP` / `TEMPORARY` 修饰符以创建会话级临时表，其生命周期与细节留待 4.2 展开。

CTAS（`CREATE TABLE ... AS SELECT`，由查询建表）是把查询结果直接物化为新表的捷径：

```sql
CREATE TABLE nums AS SELECT i FROM range(0, 3) t(i);
CREATE TABLE flights AS FROM 'https://duckdb.org/data/flights.csv';
```

CTAS 只复制列名与类型，**不**复制约束、默认值与索引；它本身也**不能**携带约束（主键、`CHECK` 等）。仅复制结构可用 `WITH NO DATA` 或 `LIMIT 0`：

```sql
CREATE TABLE t1 AS FROM t2 WITH NO DATA;
```

关于性能，有一条值得记住的经验：DuckDB 在每一行插入时都会逐条校验约束，海量数据写入时这会带来可观开销。官方建议的模式是先创建不带约束的表、批量灌入数据，再用 `ALTER TABLE ... ADD PRIMARY KEY` 补加主键；不过须注意，除主键可用 `ALTER TABLE` 追加外，`CHECK`、`FOREIGN KEY` 等一般约束目前尚不支持事后增删，故应在建表时一并声明到位。

## 4.2 临时表、生成列与默认值

临时表（temporary table）用 `CREATE TEMP` / `CREATE TEMPORARY` 创建，生命周期与会话绑定——仅创建它的连接可见，连接关闭即自动删除，语义与 PostgreSQL 相近：

```sql
CREATE TEMP TABLE session_cache (k VARCHAR, v DOUBLE);
```

临时表位于 `temp.main` schema，其命名可与普通表冲突；冲突时临时表优先被解析，若要引用同名普通表需用全限定名，如 `memory.main.t1`。它默认驻留内存，即便底层连接的是持久化 DuckDB 文件；当内存吃紧，可通过 `temp_directory` 配置把溢出数据落到磁盘：

```sql
SET temp_directory = '/path/to/directory/';
```

生成列（generated column）由表达式在引用时计算，省去手动维护派生值的麻烦：

```sql
CREATE TABLE t1 (x FLOAT, two_x AS (2 * x));
CREATE TABLE t1 (x FLOAT, two_x FLOAT GENERATED ALWAYS AS (2 * x) VIRTUAL);
```

生成列有两种语义：`VIRTUAL`（不落盘，每次引用时计算）与 `STORED`（落盘，依赖列变化时重算）。DuckDB 当前**仅支持 `VIRTUAL`**，且为缺省选项，类型也可省略、由表达式推断。需提醒的是，生成列不能直接 `INSERT` 数据，其值总是从源列派生而来。

默认值（DEFAULT）配合 `NOT NULL` 给出稳妥的初始值：

```sql
CREATE TABLE counters (id INTEGER NOT NULL DEFAULT 0, label VARCHAR);
```

插入时若省略该列，便取 `DEFAULT`；也可显式写 `DEFAULT` 关键字：

```sql
INSERT INTO counters (id) VALUES (1), (DEFAULT), (3);
```

## 4.3 INSERT / INSERT INTO SELECT / 批量写入

最基础的插入以 `VALUES` 列出元组，支持一次多行：

```sql
INSERT INTO tbl VALUES (1), (2), (3);
INSERT INTO tbl (i) VALUES (1), (2), (3);
```

把一张表（或查询结果）整批写入另一张表，靠 `INSERT INTO ... SELECT`——这是批量写入的主路径：

```sql
INSERT INTO tbl SELECT * FROM other_tbl;
```

列匹配默认按位置（BY POSITION），也可显式指定目标列。DuckDB 还提供 `BY NAME`，按列名而非位置匹配，缺失列填默认值，列名拼错则直接报错：

```sql
INSERT INTO tbl BY POSITION VALUES (5, 42);
INSERT INTO tbl (b, a) VALUES (5, 42);
INSERT INTO tbl BY NAME (SELECT 42 AS b, 32 AS a);
```

冲突处理（`ON CONFLICT`）让插入在遇到主键或唯一约束冲突时有确定行为。`DO NOTHING` 静默跳过，`INSERT OR IGNORE` 是其简写：

```sql
INSERT INTO tbl VALUES (1, 84) ON CONFLICT DO NOTHING;
INSERT OR IGNORE INTO tbl VALUES (1, 84);
```

`DO UPDATE` 实现 upsert（冲突时更新既有行），`EXCLUDED` 虚拟表指代待插入的元组：

```sql
INSERT INTO tbl VALUES (1, 84) ON CONFLICT DO UPDATE SET j = EXCLUDED.j;
INSERT OR REPLACE INTO tbl VALUES (1, 84);
```

省略冲突目标时针对主键；当存在多个唯一约束且用 `DO UPDATE` 时，必须显式写出冲突目标。一个隐蔽陷阱：走 `DO UPDATE` 时，DuckDB 内部先把未受影响列置 `NULL` 再赋值，若这些列含 `NOT NULL` 约束，会触发 "NOT NULL constraint failed"——设计插入逻辑时需为此留好退路。

插入亦可 `RETURNING` 回传写入的行，特别适合自增主键或生成列的取值确认：

```sql
INSERT INTO t1 SELECT 42 RETURNING *;
INSERT INTO t2 SELECT 2 AS i, 3 AS j RETURNING *, i * j AS i_times_j;
```

## 4.4 UPDATE / DELETE / MERGE

`UPDATE` 更新既有行，条件经 `WHERE` 圈定：

```sql
UPDATE tbl SET i = 0 WHERE i IS NULL;
UPDATE tbl SET i = 1, j = 2;
```

批量更新可借助 `FROM` 子句或子查询连表，通常比逐行子查询更快：

```sql
UPDATE original SET value = new.value FROM new WHERE original.key = new.key;
```

同一张表自我更新时要用不同别名区分：

```sql
UPDATE original AS true_original SET value = (...)
  FROM original AS new WHERE true_original.key = new.key;
```

`DELETE` 删除行，可带 `WHERE` 亦可清空整表（`TRUNCATE` 即 `DELETE FROM` 无 `WHERE` 的别名）：

```sql
DELETE FROM tbl WHERE i = 2;
DELETE FROM tbl;
TRUNCATE tbl;
```

这里有一个与 PostgreSQL 不同的关键事实：`DELETE` **只标记删除（marked as deleted）**，并不立即回收物理空间；空间要等 `CHECKPOINT` 才部分回收，而 `VACUUM` 在 DuckDB 里并不回收空间。配套地，`RETURNING` 还能回传被删内容：

```sql
DELETE FROM employees RETURNING name, 2025 - age AS approx_birthyear;
```

`MERGE INTO` 把"匹配则更新、不匹配则插入"合并进单条语句，特别适合目标表没有主键约束时的 upsert：

```sql
MERGE INTO people
    USING (SELECT unnest([3,1]) AS id, unnest(['Sarah','John']) AS name,
           unnest([95000.0,105000.0]) AS salary) AS upserts
    ON (upserts.id = people.id)
    WHEN MATCHED THEN UPDATE
    WHEN NOT MATCHED THEN INSERT;
```

`WHEN MATCHED` 可细化到 `UPDATE SET salary = upserts.salary` 或 `DELETE`；`WHEN NOT MATCHED BY SOURCE THEN DELETE` 还能清理"目标有、源没有"的残留行。MERGE 的这套组合使其自然胜任缓慢变化维度（SCD, Slowly Changing Dimension）Type 2 的建模，自 v1.4.0 起该用法被纳入官方支持范围；对无主键表的合并更新而言，它比 `ON CONFLICT` 更灵活。

## 4.5 视图、宏、模式与序列

视图（VIEW）封装一条查询、按需复用，且**不物化（not physically materialized）**——每次引用都重新执行底层查询：

```sql
CREATE VIEW view1 AS SELECT * FROM tbl;
CREATE OR REPLACE VIEW view1 AS SELECT 42;
CREATE VIEW view1(a) AS SELECT 42;   -- 重命名输出列
```

查看视图定义：`SELECT sql FROM duckdb_views() WHERE view_name = 'view1';`

宏（MACRO）把一段逻辑参数化封装。函数宏在调用处展开为原始表达式：

```sql
CREATE MACRO add(a, b) AS a + b;
CREATE MACRO add_default(a, b := 5) AS a + b;        -- 默认参数
CREATE MACRO is_maximal(a INTEGER) AS a = 2^31 - 1;  -- 类型化参数
CREATE FUNCTION main.my_avg(x) AS sum(x) / count(x); -- FUNCTION 是 MACRO 别名
```

表宏（table macro）返回一张表，关键字 `AS TABLE`：

```sql
CREATE MACRO static_table() AS TABLE
    SELECT 'Hello' AS column1, 'World' AS column2;
```

按参数数量或类型重载须一次性设定：

```sql
CREATE MACRO add_x (a, b) AS a + b, (a, b, c) AS a + b + c;
```

模式（SCHEMA）用于逻辑分组，默认 schema 为 `main`：

```sql
CREATE SCHEMA s1;
CREATE SCHEMA IF NOT EXISTS s2;
CREATE OR REPLACE SCHEMA s2;
CREATE TABLE s1.t (id INTEGER PRIMARY KEY, other_id INTEGER);
```

序列（SEQUENCE）生成单调整数，常作主键默认值：

```sql
CREATE SEQUENCE id_sequence START 1;
CREATE TABLE tbl (id INTEGER PRIMARY KEY DEFAULT nextval('id_sequence'), s VARCHAR);
```

取值用 `nextval('serial')`（下一个值）与 `currval('serial')`（当前值，须先调用过 `nextval`）；到达极值默认报错，加 `CYCLE` 可循环。

自定义类型（TYPE）支持枚举、结构、联合与别名：

```sql
CREATE TYPE mood AS ENUM ('happy', 'sad', 'curious');
CREATE TYPE many_things AS STRUCT(k INTEGER, l VARCHAR);
CREATE TYPE one_thing AS UNION(number INTEGER, string VARCHAR);
```

## 4.6 事务与并发模型

DuckDB 提供完整 ACID 事务，采用 MVCC（多版本并发控制，Multi-Version Concurrency Control）风格的快照隔离（snapshot isolation）：

```sql
BEGIN TRANSACTION;
INSERT INTO person VALUES ('Ada', 52);
COMMIT;

BEGIN TRANSACTION;
DELETE FROM person WHERE name = 'Ada';
INSERT INTO person VALUES ('Bruce', 39);
ROLLBACK;   -- 或 ABORT，二者等价
```

隔离级别上，DuckDB 保证 snapshot isolation——按 PostgreSQL 的隔离级别定义，即 **repeatable reads（可重复读）**：一个事务内多次读取同一数据应得到一致快照，违反隔离级别的事务会被中止。多语句以分号分隔批量执行时，它们身处同一条隐式事务，任一语句失败，整批前序语句一并回滚。

理解 DuckDB 的并发性格，须记住三条限制。其一，**单事务只能写入一个 attached 数据库**：多库附加时各库各自开启事务，单一事务跨库写入会报 "a single transaction can only write to a single attached database"——这源于 DuckDB 不维护跨库原子性，事务原子性仅限单个库文件内。其二，写写冲突以乐观并发方式处理：两个事务同时修改同一数据时，后提交者会失败，需要重跑事务（retry）。其三，外键的两处硬限制前文已述——无 `ON DELETE CASCADE`、不支持自引用。

`SAVEPOINT` 可用于事务内设置回退点（尽管官方文档未单列专篇），它让你在不放弃整笔事务的前提下回滚到中间状态。

## 4.7 本章小结

本章把 DuckDB 的"定义与写入"骨架铺开：`CREATE TABLE` 与各类约束、CTAS 由查询建表；临时表与会话同生灭、位于 `temp.main`；生成列当前仅 `VIRTUAL` 一种；`DEFAULT` 给出稳妥初值。写入侧，`INSERT` 配 `ON CONFLICT` 实现 upsert、`BY NAME` 按名匹配、`RETURNING` 回传结果；`UPDATE`/`DELETE` 借 `FROM` 连表高效批量，`DELETE` 仅标记删除、靠 `CHECKPOINT` 回收空间；`MERGE INTO` 则以单语句完成无主键表的合并更新，并自 v1.4.0 起支撑 SCD Type 2。

视图、宏、模式、序列与自定义类型，是把逻辑与结构组织、复用起来的工具箱。最后的事务与并发模型点出 DuckDB 的进程内本性：MVCC 快照隔离保证 repeatable reads，但单事务只写一个库、写写冲突需重跑、外键不支持级联删除与自引用。带着这些约束意识，下一章即可安心展开数据类型与单文件 / 内存数据库的细致用法。
