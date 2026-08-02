# DuckDB SQL Statements 精读笔记（基于官方文档 1.5.5）

> 本文件整理自 `duckdb-web-main/docs/current/sql/statements/` 下全部 .md 文档。
> 保留英文术语（如 CTAS、MVCC、ART、Upsert 等），便于读者对照官方文档。
> 版本号标注（如 v1.5、v1.4.0）均为文档中明确出现的版本相关事实。

---

## 0. 速览：语句总清单

| 类别 | 语句 |
|------|------|
| DDL（定义） | `CREATE TABLE` / `CREATE VIEW` / `CREATE MACRO` / `CREATE TYPE` / `CREATE INDEX` / `CREATE SCHEMA` / `CREATE SEQUENCE` / `CREATE SECRET` / `ALTER TABLE` / `ALTER VIEW` / `DROP` / `COMMENT ON` |
| DML（操纵） | `INSERT` / `COPY` / `UPDATE` / `DELETE` / `MERGE INTO` / `TRUNCATE` |
| 查询 | `SELECT` / `PIVOT` / `UNPIVOT` / `SUMMARIZE` / `DESCRIBE`(= `SHOW`) |
| 事务 | `BEGIN TRANSACTION` / `COMMIT` / `ROLLBACK`(= `ABORT`) / `SAVEPOINT`（文档未单独成篇，见事务模型说明） |
| 元数据/运维 | `CALL` / `SHOW DATABASES` / `SHOW SCHEMAS` / `EXPLAIN` / `EXPLAIN ANALYZE` / `ANALYZE` / `ATTACH` / `DETACH` / `USE` / `CHECKPOINT` / `VACUUM` / `EXPORT/IMPORT DATABASE` / `SET` / `RESET` / `SET VARIABLE` / `RESET VARIABLE` / `LOAD` / `INSTALL` / `UPDATE EXTENSIONS` |

> 注意：官方没有单独的 `EXPLAIN.md`、`PRAGMA.md`、`SAVEPOINT.md` 文件。`EXPLAIN`/`EXPLAIN ANALYZE` 内容在 `profiling.md`；`PRAGMA` 以配置项形式存在（见 `SET`/配置文档）；`SAVEPOINT` 文档未在 statements 目录单列。

---

## 1. CREATE TABLE

### 1.1 基本语法与示例
```sql
CREATE TABLE t1 (i INTEGER, j INTEGER);
CREATE TABLE t1 (id INTEGER PRIMARY KEY, j VARCHAR);
CREATE TABLE t1 (id INTEGER, j VARCHAR, PRIMARY KEY (id, j));   -- 复合主键
CREATE TABLE t1 (
    i INTEGER NOT NULL DEFAULT 0,
    decimalnr DOUBLE CHECK (decimalnr < 10),
    date DATE UNIQUE,
    time TIMESTAMP
);
```

### 1.2 临时表（Temporary Tables）
- 语法：`CREATE TEMP TABLE` 或 `CREATE TEMPORARY TABLE`。
- 会话级（session scoped）：仅创建连接的连接可见，连接关闭自动删除（类似 PostgreSQL）。
- 属于 `temp.main` schema；命名可与普通表冲突，此时临时表优先解析，需用全限定名引用普通表（如 `memory.main.t1`）。
- 默认驻留内存，即使连接的是持久 DuckDB；若设置 `temp_directory` 配置，内存紧张时数据可 spill 到磁盘。
```sql
SET temp_directory = '/path/to/directory/';
```

### 1.3 CREATE OR REPLACE / IF NOT EXISTS
```sql
CREATE OR REPLACE TABLE t1 (i INTEGER, j INTEGER);  -- 等价于先 DROP 再 CREATE
CREATE TABLE IF NOT EXISTS t1 (i INTEGER, j INTEGER);
```

### 1.4 CTAS（CREATE TABLE ... AS SELECT）
```sql
CREATE TABLE nums AS SELECT i FROM range(0, 3) t(i);
CREATE TABLE flights AS FROM 'https://duckdb.org/data/flights.csv';  -- FROM-first 语法
CREATE OR REPLACE TABLE flights AS FROM 'https://duckdb.org/data/flights.csv';
```
- 仅复制列名与类型，**不**复制约束、默认值、索引等。
- 复制 schema（仅结构）：
```sql
CREATE TABLE t1 AS FROM t2 WITH NO DATA;
CREATE TABLE t1 AS FROM t2 LIMIT 0;
```
- **限制**：CTAS 不能带约束（主键、CHECK 等）。

### 1.5 约束（Constraints）
- `CHECK`：行级表达式约束。
```sql
CREATE TABLE t1 (id INTEGER PRIMARY KEY, percentage INTEGER CHECK (0 <= percentage AND percentage <= 100));
CREATE TABLE t3 (id INTEGER PRIMARY KEY, x INTEGER, y INTEGER,
    CONSTRAINT x_smaller_than_y CHECK (x < y));
```
- `FOREIGN KEY`：引用另一表主键/唯一列，检查引用完整性。
```sql
CREATE TABLE t2 (id INTEGER PRIMARY KEY, t1_id INTEGER,
    FOREIGN KEY (t1_id) REFERENCES t1 (id));
```
  - **限制**：
    - 不支持级联删除 `ON DELETE CASCADE`。
    - 不支持自引用外键（self-referencing FK），插入会报 "Violates foreign key constraint"。

### 1.6 生成列（Generated Columns）
```sql
CREATE TABLE t1 (x FLOAT, two_x AS (2 * x));                                  -- 类型自动推断，默认 VIRTUAL
CREATE TABLE t1 (x FLOAT, two_x FLOAT GENERATED ALWAYS AS (2 * x) VIRTUAL);   -- 完整写法
```
- 两种：`VIRTUAL`（不落盘，每次引用时计算）与 `STORED`（落盘，依赖变化时重算）。
- **当前仅支持 `VIRTUAL`**，且为缺省选项。类型可省略（由表达式推断）。
- 生成列不能直接 INSERT。

### 1.7 版本相关
- 无专门版本标注，但 `DEFAULT nextval('seq')` 常与 `CREATE SEQUENCE` 配合（见 7）。

---

## 2. CREATE VIEW
```sql
CREATE VIEW view1 AS SELECT * FROM tbl;
CREATE OR REPLACE VIEW view1 AS SELECT 42;
CREATE VIEW view1(a) AS SELECT 42;   -- 重命名列
```
- 视图**不物化**（not physically materialized），每次引用时执行底层查询。
- `CREATE OR REPLACE VIEW`：同名则替换。
- 读取视图定义 SQL：`SELECT sql FROM duckdb_views() WHERE view_name = 'view1';`
- 临时视图存于特殊 schema，不能指定 schema 名。

---

## 3. CREATE MACRO（函数宏 & 表宏）

### 3.1 标量宏（Scalar Macro）
```sql
CREATE MACRO add(a, b) AS a + b;
CREATE OR REPLACE MACRO add(a, b) AS a + b;
CREATE MACRO IF NOT EXISTS add(a, b) AS a + b;
CREATE MACRO ifelse(a, b, c) AS CASE WHEN a THEN b ELSE c END;
CREATE FUNCTION main.my_avg(x) AS sum(x) / count(x);   -- FUNCTION 是别名
CREATE MACRO add_default(a, b := 5) AS a + b;           -- 默认参数
CREATE MACRO is_maximal(a INTEGER) AS a = 2^31 - 1;     -- 类型化参数
```
- 宏在调用时**展开**为原始表达式并替换参数。
- 默认参数顺序无关：`triple_add(40, c := 1, b := 1)`。

### 3.2 表宏（Table Macro）
```sql
CREATE MACRO static_table() AS TABLE
    SELECT 'Hello' AS column1, 'World' AS column2;
CREATE MACRO dynamic_table(col1_value, col2_value) AS TABLE
    SELECT col1_value AS column1, col2_value AS column2;
CREATE OR REPLACE TEMP MACRO dynamic_table(...) AS TABLE ...;   -- 临时
```

### 3.3 重载（Overloading）
- 可按参数数量/类型重载，标量宏与表宏均可：
```sql
CREATE MACRO add_x (a, b) AS a + b, (a, b, c) AS a + b + c;
```
- 重载必须在创建时一次性设定，不能分两次定义。

### 3.4 限制
- 含子查询的表宏/标量宏不能用于 table function 参数（报 "Table function cannot contain subqueries"）。
- 不支持递归函数（报 "Max expression depth limit of 1000 exceeded"，可用 `SET max_expression_depth TO x` 调整）。
- 不支持函数链式点操作符（如 `s.lower()` 不行，需 `lower(s)`）。
- 查看宏列表：`SELECT schema_name, function_name, function_type, parameters FROM duckdb_functions();`

---

## 4. CREATE TYPE
```sql
CREATE TYPE mood AS ENUM ('happy', 'sad', 'curious');
CREATE TYPE many_things AS STRUCT(k INTEGER, l VARCHAR);
CREATE TYPE one_thing AS UNION(number INTEGER, string VARCHAR);
CREATE TYPE x_index AS INTEGER;   -- 类型别名
```
- 可在 `duckdb_types` 表查看。
- **限制**：不能通过纯 SQL 扩展自定义操作符；不支持 `OR REPLACE`。

---

## 5. CREATE INDEX（注意：DuckDB 使用 ART 索引）

DuckDB 的索引基于 **ART（Adaptive Radix Tree，自适应基数树）**。索引相关说法出现在文档多处（如 `VACUUM` 提到 "tables that have ART indexes"）。`CREATE INDEX` 本身文档未展开索引类型细节，但关键事实如下：

```sql
CREATE UNIQUE INDEX films_id_idx ON films (id);
CREATE INDEX s_idx ON films (revenue);
CREATE INDEX IF NOT EXISTS s_idx ON films (revenue);
CREATE INDEX gy_idx ON films (genre, year);              -- 复合索引
CREATE INDEX i_index ON integers ((j + k));              -- 表达式索引
```

参数：

| 名称 | 说明 |
|------|------|
| `UNIQUE` | 创建/插入时检查重复值 |
| `name` / `table` / `column` | 索引名 / 表名 / 列名 |
| `expression` | 基于列的表达式，通常需括号包裹（函数调用形式可省略） |
| `index type` | 可选索引类型（见 Indexes 文档） |
| `option` | 布尔值或键值对形式的索引选项 |

- `DROP INDEX title_idx;` / `DROP INDEX IF EXISTS title_idx;`
- **限制**：
  - 不支持 `OR REPLACE`。
  - `CREATE INDEX IF NOT EXISTS` **没有提前退出**：仍会尝试创建，仅在提交前检查是否存在，可能比其他 `IF NOT EXISTS` 更慢。
  - `VACUUM` 默认跳过带 ART 索引的表（见 §17）。

---

## 6. CREATE SCHEMA
```sql
CREATE SCHEMA s1;
CREATE SCHEMA IF NOT EXISTS s2;
CREATE OR REPLACE SCHEMA s2;
CREATE TABLE s1.t (id INTEGER PRIMARY KEY, other_id INTEGER);
```
- 默认 schema 为 `main`。

---

## 7. CREATE SEQUENCE
```sql
CREATE SEQUENCE serial;
CREATE SEQUENCE serial START 101;
CREATE SEQUENCE serial START WITH 1 INCREMENT BY 2;
CREATE SEQUENCE serial START WITH 99 INCREMENT BY -1 MAXVALUE 99;
CREATE SEQUENCE serial START WITH 1 MAXVALUE 10 CYCLE;
```
- 默认不循环（到达极值报 "Sequence Error: nextval: reached maximum value"）。`CYCLE` 可循环。
- 管理与使用：
```sql
CREATE OR REPLACE SEQUENCE serial;
CREATE SEQUENCE IF NOT EXISTS serial;
DROP SEQUENCE serial;
DROP SEQUENCE IF EXISTS serial;
```
- 作为主键默认值：
```sql
CREATE SEQUENCE id_sequence START 1;
CREATE TABLE tbl (id INTEGER PRIMARY KEY DEFAULT nextval('id_sequence'), s VARCHAR);
```
- `ALTER TABLE tbl ADD COLUMN id INTEGER DEFAULT nextval('id_sequence');`（见 §9.6）
- 取值函数：`nextval('serial')`（下一个值）、`currval('serial')`（当前值，必须先调用过 `nextval`，否则报 Serialization Error）。
- 参数：`CYCLE/NO CYCLE`、`INCREMENT BY`、`MAXVALUE`/`MINVALUE`、`START WITH`、`TEMPORARY/TEMP`。基于 `BIGINT` 算术（范围 -2^63..2^63-1）。
- **限制**：因依赖管理器限制，某些情况下 `DROP SEQUENCE` 失败；`DROP SEQUENCE ... CASCADE` 会连表一起删除（依赖在表级跟踪）。

---

## 8. CREATE SECRET
```sql
CREATE SECRET ...   -- 在 Secrets Manager 中创建密钥
DROP SECRET ...
```
- 用于管理连接外部存储（S3 等）的凭证。
- **警告**：CLI 下 `CREATE SECRET` 以明文存入 DuckDB 历史。

---

## 9. ALTER TABLE
```sql
ALTER TABLE integers ADD COLUMN k INTEGER;
ALTER TABLE integers ADD COLUMN l INTEGER DEFAULT 10;
ALTER TABLE integers DROP k;
ALTER TABLE integers ALTER i TYPE VARCHAR;
ALTER TABLE integers ALTER i SET DATA TYPE VARCHAR USING concat(i, '_', j);
ALTER TABLE integers ALTER COLUMN i SET DEFAULT 10;
ALTER TABLE integers ALTER COLUMN i DROP DEFAULT;
ALTER TABLE integers ALTER COLUMN i SET NOT NULL;
ALTER TABLE integers ALTER COLUMN i DROP NOT NULL;
ALTER TABLE integers RENAME TO integers_old;
ALTER TABLE integers RENAME i TO ii;          -- 或 RENAME COLUMN i TO ii
ALTER TABLE integers ADD PRIMARY KEY (i);
ALTER TABLE integers ADD PRIMARY KEY (i, j);
```
- 全部遵守事务语义（提交前对其他事务不可见，可回滚）。
- `RENAME` 不会自动更新依赖该表的视图；`RENAME COLUMN` 会更新依赖该列名的约束（如 CHECK），但不会更新视图。
- `DROP COLUMN`：列上若有索引（含主键/唯一约束索引）或多列 CHECK 依赖则不可删。
- 类型变更：`USING` 子句逐行转换；有索引或属于 CHECK 约束的列不能改类型。
- STRUCT 子 schema 变更：
```sql
ALTER TABLE tbl ALTER col TYPE USING struct_insert(col, a := 42, b := NULL::VARCHAR);
```
  - **v1.3.0 起**支持对 STRUCT 列用 `ADD COLUMN`/`DROP COLUMN`/`RENAME COLUMN` 更新子 schema。

### 9.1 SET / RESET 表选项（**v1.5 新特性**）
```sql
ALTER TABLE my_table SET ('option_name' = 'value');
ALTER TABLE my_table RESET ('option_name');
ALTER TABLE my_table SET ('option1' = 'value1', 'option2' = 'value2');
ALTER TABLE my_table RESET ('option1', 'option2');
```

### 9.2 ADD / DROP CONSTRAINT
- **尚未支持**（文档明确说明）。

### 9.3 限制
- `ALTER COLUMN` 即便冲突类型的值已被删除仍可能失败（"Could not convert string ... to INT32"）。变通：重建表 `CREATE OR REPLACE TABLE tbl AS FROM tbl;`
- 有依赖（如列上有索引）时需先 DROP 索引，再 ALTER，再重建索引。

---

## 10. ALTER VIEW
```sql
ALTER VIEW view1 RENAME TO view2;
```
- 遵守事务语义；依赖该视图的其他视图不会自动更新。

---

## 11. DROP
```sql
DROP TABLE tbl;
DROP VIEW IF EXISTS view1;
DROP FUNCTION fn;
DROP INDEX idx;
DROP SCHEMA sch;
DROP SEQUENCE seq;
DROP MACRO mcr;
DROP MACRO TABLE mt;   -- TABLE 可选（**v1.4.0 起**）
DROP TYPE typ;
```
- 依赖：`RESTRICT`（默认）下若有依赖对象则报错；`CASCADE` 连同依赖对象一起删除。
- 被跟踪的依赖关系（SCHEMA → 各类对象）。
- **限制**：视图依赖**不**跟踪（删表后视图处于无效状态）。
- 磁盘空间：DROP TABLE 释放内存但未必释放磁盘空间，空闲块标记为 `free`；用 `PRAGMA database_size` 查看 `free_blocks`。

---

## 12. INSERT

### 12.1 基本
```sql
INSERT INTO tbl VALUES (1), (2), (3);
INSERT INTO tbl SELECT * FROM other_tbl;
INSERT INTO tbl (i) VALUES (1), (2), (3);
INSERT INTO tbl (i) VALUES (1), (DEFAULT), (3);
```

### 12.2 列顺序：BY POSITION（默认）与 BY NAME
```sql
INSERT INTO tbl BY POSITION VALUES (5, 42);          -- 默认行为
INSERT INTO tbl (b, a) VALUES (5, 42);               -- 指定目标列
INSERT INTO tbl BY NAME (SELECT 42 AS b, 32 AS a);   -- 按列名匹配
```
- `BY NAME`：SELECT 列名与表列名匹配，缺失列填默认值，列名拼错会报错。

### 12.3 ON CONFLICT（Upsert / 冲突处理）
```sql
INSERT INTO tbl VALUES (1, 84) ON CONFLICT DO NOTHING;
INSERT OR IGNORE INTO tbl VALUES (1, 84);            -- 等价简写

INSERT INTO tbl VALUES (1, 84) ON CONFLICT DO UPDATE SET j = EXCLUDED.j;   -- Upsert
INSERT OR REPLACE INTO tbl VALUES (1, 84);           -- 简写：所有列更新为新值
```
- 冲突目标：`ON CONFLICT (conflict_target)`，省略时针对主键；多唯一约束且用 DO UPDATE 时必须指定。
- `EXCLUDED` 虚拟表指代待插入元组；可加 `WHERE` 过滤。
- 复合主键：`PRIMARY KEY (id1, id2)` + `INSERT OR REPLACE`。
- **限制**：`ON CONFLICT ... DO UPDATE` 时 DuckDB 内部先将未受影响列置 NULL 再赋值，若这些列有 `NOT NULL` 约束会触发 "NOT NULL constraint failed"。

### 12.4 RETURNING
```sql
INSERT INTO t1 SELECT 42 RETURNING *;
INSERT INTO t2 SELECT 2 AS i, 3 AS j RETURNING *, i * j AS i_times_j;
```
- 返回插入行内容，适合自增主键/生成列场景。

---

## 13. COPY（重点：文件导入导出）

### 13.1 COPY ... FROM（导入）
```sql
COPY lineitem FROM 'lineitem.csv';
COPY lineitem FROM 'lineitem.csv' (DELIMITER '|');
COPY lineitem FROM 'lineitem.pq' (FORMAT parquet);
COPY lineitem FROM 'lineitem.json' (FORMAT json, AUTO_DETECT true);
COPY category FROM 'categories.csv' (HEADER);
COPY category(name) FROM 'names.csv';                -- 仅导入指定列，其余列填默认
COPY lineitem FROM (getvariable('source_file'));     -- 表达式作源（括号包裹）
PREPARE v1 AS COPY lineitem FROM ($1); EXECUTE v1('lineitem.json');
```
- 追加到现有表；列数须匹配，类型须可转换。
- 为兼容 PostgreSQL，接受 `COPY tbl FROM 'tbl.csv' WITH DELIMITER '|' CSV HEADER;` 形式。

### 13.2 COPY ... TO（导出）
```sql
COPY lineitem TO 'lineitem.csv';
COPY lineitem TO 'lineitem.tbl' (DELIMITER '|');
COPY lineitem TO 'lineitem.tsv' (DELIMITER '\t', HEADER false);
COPY lineitem(l_orderkey) TO 'orderkey.tbl' (DELIMITER '|');
COPY (SELECT 42 AS a, 'hello' AS b) TO 'query.csv' (DELIMITER ',');
COPY (SELECT 42 AS a, 'hello' AS b) TO 'query.parquet' (FORMAT parquet);
COPY (SELECT l_orderkey, l_comment FROM lineitem) TO 'lineitem_part.parquet' (RETURN_STATS);
COPY (SELECT 42 AS i) TO 'file' (FORMAT getvariable('my_format'));
```
- 支持表名或查询作为源。
- 通用选项（部分，详情见下表）：`FORMAT`、`USE_TMP_FILE`、`PARTITION_BY`、`PER_THREAD_OUTPUT`、`FILE_SIZE_BYTES`、`RETURN_FILES`、`RETURN_STATS`、`PRESERVE_ORDER` 等。
- 兼容 PostgreSQL 的旧式 `WITH DELIMITER '|' CSV HEADER;`。

**COPY ... TO 通用选项：**

| 名称 | 说明 | 类型 | 默认 |
|------|------|------|------|
| `FORMAT` | csv/parquet/json/blob（默认按扩展名推断） | VARCHAR | auto |
| `USE_TMP_FILE` | 先写临时文件防中断损坏 | BOOL | auto |
| `OVERWRITE_OR_IGNORE` / `OVERWRITE` / `APPEND` | 配合 `PARTITION_BY` 的文件处理策略 | BOOL | false |
| `PARTITION_BY` | Hive 分区列 | VARCHAR[] | - |
| `PER_THREAD_OUTPUT` | 每线程一个文件，并行更快 | BOOL | false |
| `FILE_SIZE_BYTES` | 超过则分新文件（配合 PER_THREAD_OUTPUT） | VARCHAR/BIGINT | - |
| `FILENAME_PATTERN` | 文件名模式，可含 {uuid}/{i} | VARCHAR | auto |
| `PRESERVE_ORDER` | 是否保持顺序 | BOOL | * |
| `RETURN_FILES` / `RETURN_STATS` | 返回文件路径/列统计 | BOOL | false |

**CSV 选项**：`COMPRESSION`(none/gzip/zstd)、`DATEFORMAT`、`DELIM`/`SEP`、`NEW_LINE`、`ESCAPE`、`FORCE_QUOTE`、`HEADER`、`NULLSTR`、`PREFIX`/`SUFFIX`、`QUOTE`、`TIMESTAMPFORMAT`。
**Parquet 选项**：`COMPRESSION`(uncompressed/snappy/gzip/zstd/brotli/lz4/lz4_raw)、`COMPRESSION_LEVEL`(zstd 1-22)、`FIELD_IDS`、`ROW_GROUP_SIZE`(默认 122880)、`ROW_GROUPS_PER_FILE`、`PARQUET_VERSION`(V1/V2)、`KV_METADATA`、`SHREDDING`(VARIANT 类型)、`DICTIONARY_SIZE_LIMIT`、`WRITE_BLOOM_FILTER`、`BLOOM_FILTER_FALSE_POSITIVE_RATIO`、`GEOPARQUET_VERSION` 等。
**JSON 选项**：`ARRAY`(true=JSON 数组, false=NDJSON)、`COMPRESSION`、`DATEFORMAT`、`TIMESTAMPFORMAT`。
**BLOB 选项**：`COMPRESSION`。

### 13.3 COPY FROM DATABASE ... TO（库间复制）
```sql
ATTACH 'db1.db' AS db1; ATTACH 'db2.db' AS db2;
COPY FROM DATABASE db1 TO db2;          -- 含 schema/约束/索引/序列/宏/数据
COPY FROM DATABASE db1 TO db2 (SCHEMA); -- 仅 schema
```
- **限制**：`COPY` 不支持表到表复制，应改用 `INSERT INTO tbl2 FROM tbl1;`

---

## 14. UPDATE
```sql
UPDATE tbl SET i = 0 WHERE i IS NULL;
UPDATE tbl SET i = 1, j = 2;
```
- 基于其他表更新（FROM 子句或子查询，批量性能更好）：
```sql
UPDATE original SET value = new.value FROM new WHERE original.key = new.key;
UPDATE original SET value = (SELECT new.value FROM new WHERE original.key = new.key);
```
- 同一表自更新需不同别名：`UPDATE original AS true_original SET value = (...) FROM original AS new WHERE ...`
- JOIN 更新：`UPDATE city SET revenue = revenue + 100 FROM country WHERE city.country_code = country.code AND country.name = 'France';`
- Upsert 见 INSERT 文档。

---

## 15. DELETE 与 TRUNCATE
```sql
DELETE FROM tbl WHERE i = 2;
DELETE FROM tbl;                  -- 删全部
TRUNCATE tbl;                     -- DELETE FROM 无 WHERE 的别名
```
- `USING` 子句：基于其他表/子查询删除。
- `RETURNING` 子句（不支持 DISTINCT）：
```sql
DELETE FROM employees RETURNING name, 2025 - age AS approx_birthyear;
```
- **空间回收限制**：DELETE 仅标记删除（marked as deleted），不立即回收空间；需 `CHECKPOINT` 才部分回收；`VACUUM` **不**回收空间。

---

## 16. MERGE INTO（Upsert，无需主键）
```sql
MERGE INTO people
    USING (SELECT unnest([3,1]) AS id, unnest(['Sarah','John']) AS name,
           unnest([95000.0,105000.0]) AS salary) AS upserts
    ON (upserts.id = people.id)
    WHEN MATCHED THEN UPDATE
    WHEN NOT MATCHED THEN INSERT;
```
- 支持 `WHEN MATCHED THEN UPDATE SET salary = salary_updates.salary;`
- 支持 `WHEN MATCHED THEN DELETE;`
- 多条件 + `RETURNING merge_action, *;`
- `WHEN NOT MATCHED BY SOURCE THEN DELETE;`（删除目标存在但源不存在的行）
- `WHEN NOT MATCHED BY TARGET` 与 `WHEN NOT MATCHED` 等价。
- 适合目标表无主键约束的 upsert 场景。

---

## 17. VACUUM
```sql
VACUUM;                       -- No-op
VACUUM ANALYZE;              -- No-op
VACUUM my_table(my_column);  -- 重建列 distinct 统计
VACUUM ANALYZE my_table(my_column);
VACUUM FULL;                 -- 不支持（"Not implemented Error: Full vacuum option"）
```
- 主要为 PostgreSQL 兼容性，行为**不一致且未来可能变化**。
- 默认跳过带 **ART 索引**的表；`vacuum_rebuild_indexes`（实验性）可设行数阈值以压缩并重建索引。
- **不回收空间**（回收见 CHECKPOINT / Reclaiming space 文档）。

---

## 18. 事务模型（Transaction Management）

DuckDB 支持 **ACID** 事务，采用 **MVCC（多版本并发控制）** 风格的快照隔离：

```sql
BEGIN TRANSACTION;
INSERT INTO person VALUES ('Ada', 52);
COMMIT;

BEGIN TRANSACTION;
DELETE FROM person WHERE name = 'Ada';
INSERT INTO person VALUES ('Bruce', 39);
ROLLBACK;                    -- 或 ABORT（等价）
```

- 语句：
  - `BEGIN TRANSACTION;` 开始
  - `COMMIT;` 提交（未处于事务中则失败）
  - `ROLLBACK;` / `ABORT;` 回滚（未处于事务中则失败）
- **隔离级别**：保证 **snapshot isolation**（快照隔离）；按 PostgreSQL 隔离级别定义，DuckDB 保证 **repeatable reads（可重复读）**。违反隔离级别的事务会被中止。
- **多语句事务**：以分号分隔的批量语句在单一隐式事务内执行；任一失败，整批前序语句回滚（含 `COPY FROM DATABASE` 等分解为多内部操作的 PRAGMA）。
- **跨库写入限制（重要）**：多数据库附加时，每个库各自开事务（默认懒启动；`SET immediate_transaction_mode = true` 可改为急启动）。单一事务**只能写入一个**附加数据库，否则报 "a single transaction can only write to a single attached database"。原因：DuckDB 不维护跨库原子性，事务原子性仅限单个库文件内。
- 文档未单列 `SAVEPOINT` 专篇，但支持 savepoint 概念（需参考其他章节/客户端）。

---

## 19. 元数据与运维语句

### 19.1 DESCRIBE / SHOW
```sql
DESCRIBE tbl;                       -- 表/视图 schema
DESCRIBE SELECT * FROM tbl;         -- 查询 schema
SHOW tbl;                           -- DESCRIBE 的别名
SHOW DATABASES;                     -- 列出附加数据库
SHOW SCHEMAS;                       -- 列出所有 schema（**v1.5 新特性**）
```

### 19.2 EXPLAIN / EXPLAIN ANALYZE（在 profiling.md）
```sql
EXPLAIN <query>;                    -- 查询计划，含估算基数，不执行
EXPLAIN ANALYZE <query>;           -- 执行并显示实际基数与耗时
```

### 19.3 ANALYZE
```sql
ANALYZE;                            -- 重算统计，仅用于 join order 优化
```
- 建议大批量增删后执行以改善 join 顺序。

### 19.4 CALL
```sql
CALL duckdb_functions();
CALL pragma_table_info('pg_am');
```
- 调用 table function；可用 `FROM` 代替（因 DuckDB 过程以 table function 实现 + FROM-first 语法）。

### 19.5 ATTACH / DETACH
```sql
ATTACH 'file.db';
ATTACH 'file.db' AS file_db;
ATTACH 'file.db' (READ_ONLY);
ATTACH 'file.db' (BLOCK_SIZE 16_384);
ATTACH 'file.db' (READ_ONLY);                    -- HTTP/S3 默认只读
ATTACH 'sqlite_file.db' AS sqlite_db (TYPE sqlite);
ATTACH IF NOT EXISTS 'file.db' AS file_db;
ATTACH OR REPLACE 'file2.db' AS file_db;
DETACH file;
```
- 附加定义**不持久化**于会话间，需重连重附加。
- 选项：`READ_ONLY`/`READ_WRITE`、`COMPRESS`(仅内存库)、`TYPE`(DUCKDB/SQLITE/MySQL/PostgreSQL)、`DEFAULT_TABLE`、`BLOCK_SIZE`(2 的幂，16384–262144)、`ROW_GROUP_SIZE`、`STORAGE_VERSION`(v1.2.0 起可显式指定，如 'v1.2.0' 或 'latest')、`ENCRYPTION_KEY`、`ENCRYPTION_CIPHER`(CBC/CTR/GCM，默认 GCM AES-256)、`RECOVERY_MODE`(no_wal_writes)。
- 数据库加密：默认 AES-256 GCM，覆盖主库/WAL/临时文件；加载 `httpfs` 可加速（OpenSSL 硬件加速）。加密隐含 storage version ≥ 1.4.0。
- 命名限定：catalog.schema.name；可用 `USE` 改默认库/schema；`SET search_path = 'db1,db2'` 改搜索路径。

### 19.6 USE
```sql
USE memory;         -- 默认库
USE duck.main;      -- 库+schema
USE main;           -- 当前库的 schema
```

### 19.7 CHECKPOINT
```sql
CHECKPOINT;
CHECKPOINT file_db;
FORCE CHECKPOINT;                    -- v1.4 起：等待获取 checkpoint 锁再执行（旧版会中止进行中事务）
```
- 将 WAL 同步到数据文件；默认有运行中事务则失败。
- **v1.4.0 起**内存表也支持 checkpoint（可压缩；触发 vacuum 已删行回收空间）。
- 回收空间：checkpoint 会部分回收已删行（合并删除率约 25% 的相邻 row group）。**VACUUM 不回收空间**。

### 19.8 EXPORT / IMPORT DATABASE
```sql
EXPORT DATABASE 'target_directory';                       -- 默认 CSV
EXPORT DATABASE 'target_directory' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 100_000);
IMPORT DATABASE 'source_directory';
PRAGMA import_database('source_directory');
```
- 导出生成 `schema.sql`(CREATE 语句) + `load.sql`(COPY 语句) + 数据文件。
- `IMPORT DATABASE` 期望导入**全新**库（schema.sql 用纯 CREATE，无 OR REPLACE/IF NOT EXISTS）。

### 19.9 SET / RESET
```sql
SET memory_limit = '10GB';
SET threads = 1;                 -- 或 SET threads TO 1;
RESET threads;
SELECT current_setting('threads');
SET SESSION default_collation = 'nocase';
SET GLOBAL sort_order = 'desc';
```
- 作用域：`GLOBAL`（整个实例）、`SESSION`（当前会话）、`LOCAL`（未实现）。默认多数为 GLOBAL。GLOBAL 不写入库文件、不跨实例持久化。

### 19.10 SET VARIABLE / RESET VARIABLE
```sql
SET VARIABLE my_var = 30;
SELECT 20 + getvariable('my_var') AS total;
SET VARIABLE list_of_files = (SELECT list(file) FROM csv_files);
RESET VARIABLE my_var;
```
- 作用域：`SESSION`（默认）、`GLOBAL`。
- 未定义变量 `getvariable` 返回 NULL。可用于 COPY/COLUMNS 表达式中。

### 19.11 PIVOT / UNPIVOT
- `PIVOT`（= `PIVOT_WIDER`）：列转行→列。简化语法 `PIVOT ds ON cols USING agg GROUP BY rows ORDER BY ... LIMIT ...;`；SQL 标准语法 `SELECT * FROM ds PIVOT (values FOR col IN (list) GROUP BY rows);`
- `UNPIVOT`（= `PIVOT_LONGER`）：列堆叠为 name/value 两列。简化语法 `UNPIVOT ds ON cols INTO NAME n VALUE v;`；支持 `COLUMNS(...)` 动态、多值列、表达式（单列表达式）。
- 二者均可作为 CTE/子查询嵌入 SELECT。
- **限制**：PIVOT 的 USING 只接受聚合函数，不接受表达式（如 `sum(x)*1000` 报错），需用 COLUMNS 变通。

### 19.12 SUMMARIZE
```sql
SUMMARIZE tbl;
SUMMARIZE SELECT * FROM tbl;
```
- 返回表/视图/查询的摘要统计。

### 19.13 SELECT（要点）
- 顺序：`SELECT ... FROM ... [USING SAMPLE] WHERE ... GROUP BY ... HAVING ... [WINDOW] [QUALIFY] ORDER BY ... LIMIT ...;`，可前缀 `WITH`。
- 特性：列名大小写不敏感；`#1, #3` 按列序选择；`SELECT d FROM (SELECT 1 AS a, 2 AS b) d;` 返回 STRUCT；`rowid` 伪列（物理行标识，删除会产生空洞，事务内稳定，**不建议用作标识符**）；CTE 支持。
- JOIN 支持 `USING (a, b)`。

### 19.14 LOAD / INSTALL / UPDATE EXTENSIONS
```sql
INSTALL httpfs;
INSTALL h3 FROM community;
LOAD httpfs;
LOAD spatial;
UPDATE EXTENSIONS;                 -- 更新所有
UPDATE EXTENSIONS (name_a, name_b);-- 更新指定
```
- 扩展运行时不可 reload；更新后需重启进程。
- `UPDATE EXTENSIONS` 用 ETag 条件请求，仅变更的执行 `FORCE INSTALL`。

### 19.15 COMMENT ON
```sql
COMMENT ON TABLE test_table IS 'very nice table';
COMMENT ON COLUMN test_table.test_table_column IS '...';
COMMENT ON VIEW/INDEX/SEQUENCE/TYPE/MACRO/MACRO TABLE ... IS '...';
COMMENT ON TABLE test_table IS NULL;   -- 清除
```
- 读取：查相应元数据函数的 `comment` 列（如 `duckdb_tables()`、`duckdb_columns()`）。
- **限制**：不能 comment schema/database；不能 comment 有依赖的对象（如表带索引）。

---

## 20. 版本相关事实汇总（写书时务必标注）

| 版本 | 相关事实 |
|------|----------|
| **v1.5** | `ALTER TABLE ... SET/RESET ('option'='value')` 表选项；`SHOW SCHEMAS` 语句 |
| **v1.4.0** | `DROP MACRO TABLE` 的 `TABLE` 关键字可选；`FORCE CHECKPOINT` 改为等待锁（旧版中止事务）；内存表支持 checkpoint（可压缩 + 回收已删行空间） |
| **v1.3.0** | `ALTER TABLE` 支持用 `ADD/DROP/RENAME COLUMN` 更新 STRUCT 子 schema |
| **v1.2.0** | `ATTACH` 引入 `STORAGE_VERSION` 选项（可显式指定如 'v1.2.0' 或 'latest'） |

---

## 21. 学习者最该掌握的 DDL / DML 清单（核心优先级）

1. **CREATE TABLE**（含约束、DEFAULT、生成列、CTAS、临时表）—— 一切基础。
2. **INSERT**（含 `ON CONFLICT` Upsert、`BY NAME`、`RETURNING`）—— 数据写入主路径。
3. **COPY ... TO / FROM** —— 与 CSV/Parquet/JSON 文件互导，是 DuckDB 最具代表性的能力。
4. **SELECT**（含 `FROM`-first、`rowid`、CTE、`PIVOT`/`UNPIVOT`）—— 查询核心。
5. **UPDATE / DELETE / MERGE INTO** —— 数据操纵与 upsert/合并。
6. **ALTER TABLE / DROP** —— schema 演进与对象管理（注意依赖 `CASCADE` 与索引限制）。
7. **事务控制 BEGIN/COMMIT/ROLLBACK + 快照隔离 + 单事务单库写入限制** —— 并发与一致性认知。
8. **CREATE VIEW / CREATE MACRO** —— 复用查询与逻辑封装。
9. **CREATE INDEX（ART）/ CREATE SEQUENCE / CREATE SCHEMA / CREATE TYPE** —— 进阶定义。
10. **EXPLAIN / DESCRIBE / SHOW / ANALYZE / CHECKPOINT / VACUUM** —— 诊断与运维。

**关键认知（易错点）**：
- DuckDB 索引基于 **ART**，仅一种；不支持 `CREATE INDEX ... OR REPLACE`。
- 外键不支持 `ON DELETE CASCADE` 与自引用；视图依赖不跟踪。
- DELETE 不回收空间，靠 CHECKPOINT；VACUUM 不回收空间（与 PostgreSQL 语义不同）。
- 跨库事务单事务只能写一个库。
- GENERATE COLUMN 目前只支持 VIRTUAL。
