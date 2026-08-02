# 第 11 章 与外部数据库集成

DuckDB 以进程内（in-process）分析引擎立足，但真实数据工程里，业务系统往往运行在独立的数据库之上：PostgreSQL 承载交易与业务元数据，MySQL 支撑高并发在线服务，SQLite 嵌在应用与移动端本地存储。把这类外部系统直接纳入 DuckDB 的分析视野、免去向中间文件搬运，正是数据库集成（database integration）一节的价值所在。DuckDB 借助一组 scanner 扩展——postgres_scanner、sqlite_scanner、mysql_scanner——把外部数据库映射为本地的 catalog（目录），从而用统一的标准 SQL 读写远端表。本章先拆解 ATTACH 机制与集成模式，再分别落到 PostgreSQL、SQLite、MySQL 三条集成路径，并说明各自的关键函数、凭据管理与注意事项。

## 11.1 ATTACH 机制与数据库集成模式

ATTACH 是 DuckDB 纳入外部数据源的统一入口。其语义是把一个外部存储"挂载"为当前实例中的一个 catalog（目录）——catalog 是 DuckDB 命名空间的最高层级，默认的本地库名为 `main`，每挂载一个外部源便获得一个别名 catalog。挂载完成后，外部表以三段式 `catalog.schema.table` 寻址，与本地表在写法上无任何区别。

DuckDB 把外部数据库集成归类为"附加数据库（attached database）"能力。对原生 DuckDB 文件，直接 `ATTACH 'file.db' AS db;` 即可；对外部关系型数据库，则需对应扩展在 ATTACH 时声明 `TYPE`：

```sql
-- 把 PostgreSQL 库挂载为 catalog pg
ATTACH 'host=localhost port=5432 dbname=mydb' AS pg (TYPE postgres);
-- 把 SQLite 文件挂载为 catalog sq
ATTACH 'test.db' AS sq (TYPE sqlite);
-- 把 MySQL 实例挂载为 catalog my（只读）
ATTACH 'host=localhost user=root port=0 database=mysqlscanner' AS my (TYPE mysql, READ_ONLY);
```

`TYPE postgres` / `TYPE sqlite` / `TYPE mysql` 分别由 postgres、sqlite、mysql 三个扫描扩展（scanner extension）提供实现。这组扩展多数支持首次使用时自动加载（autoload），亦可显式 `INSTALL` 后 `LOAD`。由于扩展二进制与具体 DuckDB 版本、平台严格绑定，跨版本升级须重新安装匹配构建，必要时用 `FORCE INSTALL` 拉取对应版本。

只读挂载通过 ATTACH 的 `READ_ONLY` 选项实现，如上方 MySQL 示例。只读挂载既保护源库不被意外写入，也省去 scanner 在远端建立写会话的开销，是做分析取数时的推荐默认。

集成模式上，官方给出明确优先序：首选 scanner 扩展直接 ATTACH 远端库；若源系统不支持或不便暴露连接，则导出为 Parquet/CSV 再由 DuckDB 加载；再不行才用各语言客户端的 appender 逐批写入。应避免循环逐行插入——即便借助预处理语句，只要数据量不小（例如超过十万行）就不应采用。

一个与事务模型相关的约束值得强调：DuckDB 采用 MVCC 快照隔离，单笔事务只允许写入一个 attached 数据库；当两个事务同时写入同一远端库而发生写写冲突时，乐观并发控制（optimistic concurrency control）会使一方失败，调用方需重试。这点在把分析结果回写 PostgreSQL/MySQL 时须纳入错误处理。

scanner 在挂载时会缓存远端 schema（模式）以提升重复查询效率。当远端表结构在外部被修改后，可用各扩展提供的 `clear_cache` 函数（如 `postgres_clear_cache()`）强制失效本地缓存。

## 11.2 PostgreSQL 集成

PostgreSQL 集成由 postgres 扩展提供，其别名即 postgres_scanner。该扩展支持自动加载，但显式加载更利于在脚本中控制初始化：

```sql
INSTALL postgres;
LOAD postgres;
```

挂载整库后用三段式寻址读取：

```sql
ATTACH 'host=localhost port=5432 dbname=mydb' AS pg (TYPE postgres);
SELECT * FROM pg.public.orders LIMIT 10;
```

若只需临时探查某一张表，无需挂载整库，可用 `postgres_scan` 直接扫描单表：

```sql
SELECT * FROM postgres_scan('host=localhost port=5432 dbname=mydb', 'public', 'orders');
```

ATTACH 使用的连接串为 PostgreSQL 风格 `{key}={value}` 键值对，可携带 host、port、user、password、dbname、passfile 等字段。

除标准 SQL 读写外，扩展暴露一组在 PostgreSQL 侧执行的辅助函数：`postgres_query(attached_db, query)` 在远端执行只读查询并返回结果集；`postgres_execute(attached_db, query)` 在远端执行任意语句，含 DDL/DML；`postgres_clear_cache()` 清除 schema 缓存。例如需要在 PostgreSQL 侧建索引而不希望经过 DuckDB 计划器时：

```sql
CALL postgres_execute('pg', 'CREATE INDEX idx_orders_cust ON orders(customer_id)');
```

连接复用由连接池（connection pool）管理，可配置池大小、空闲超时、最大存活时间与获取模式（`force`/`wait`/`try`），降低高频查询下的握手成本。

### RDS 与 Aurora 的 IAM 认证

访问托管在 Amazon RDS / Aurora 的 PostgreSQL 时，用户名密码可用短期 IAM 令牌替代。做法是由 aws 扩展配合 postgres 扩展：aws 扩展借助 AWS credential chain 生成 IAM 令牌作为密码，并在过期前自动刷新，无需在连接串中硬编码凭据。

```sql
INSTALL aws; LOAD aws;
CREATE SECRET aws_rds_secret (
    TYPE rds, PROVIDER credential_chain, CHAIN 'env;sso',
    REGION 'eu-west-1', RDS_USER 'postgres',
    RDS_HOST 'database-1.xxxx.eu-west-1.rds.amazonaws.com', RDS_PORT '5432'
);
CREATE SECRET pg_rds_secret (
    TYPE postgres, HOST 'database-1.xxxx.eu-west-1.rds.amazonaws.com',
    PORT '5432', USER 'postgres', DATABASE 'postgres',
    SSLMODE require, AWS_RDS_SECRET aws_rds_secret
);
ATTACH '' AS rds_db (TYPE postgres, SECRET pg_rds_secret);
SELECT * FROM rds_db.public.tbl_name;
```

此处 `TYPE rds` 的 secret 持有 RDS 实例标识与 IAM 主体，`TYPE postgres` 的 secret 通过 `AWS_RDS_SECRET` 引用前者，挂载时由 `SECRET` 子句关联。令牌刷新对调用方透明，连接串留空（`ATTACH ''`）即可。

### v1.5.5 schema 变化自动检测

v1.5.5 引入 `pg_staleness_query_enabled` 配置项（BOOLEAN，默认 `FALSE`）。启用后，DuckDB 可周期性探查缓存的 PostgreSQL schema 是否过期，过期则自动失效本地缓存，省去手动调用 `postgres_clear_cache()`。默认关闭以保持向后兼容：

```sql
SET pg_staleness_query_enabled = true;
```

## 11.3 SQLite 集成

SQLite 集成由 sqlite 扩展提供，别名 sqlite_scanner / sqlite3，支持自动加载。挂载一个 SQLite 数据库文件即把它作为 catalog 暴露：

```sql
INSTALL sqlite;
LOAD sqlite;
ATTACH 'test.db' AS sq (TYPE sqlite);
SELECT * FROM sq.main.users;
```

SQLite 默认 schema（模式）名为 `main`，故三段式寻址写作 `sq.main.users`。单表快速探查可用 `sqlite_scan`：

```sql
SELECT * FROM sqlite_scan('test.db', 'users');
```

SQLite 采用存储类（storage class）而非严格列类型，其 INTEGER/REAL/TEXT/BLOB/NULL 按类型亲和（type affinity）规则映射到 DuckDB 类型。当文件存在脏数据、列内混有非预期类型时，可开启 `sqlite_all_varchar` 选项把所有列读成 `VARCHAR`，先把数据原样取回再做清洗，避免加载因类型冲突中断：

```sql
ATTACH 'test.db' AS sq (TYPE sqlite, sqlite_all_varchar true);
```

该扩展亦兼容 Turso（libSQL）数据库文件，可用于读取边缘与移动端落地的 SQLite 变体。

## 11.4 MySQL 集成

MySQL 集成由 mysql 扩展提供，别名 mysql_scanner，支持自动加载。挂载语法与 PostgreSQL 对称：

```sql
INSTALL mysql;
LOAD mysql;
ATTACH 'host=localhost user=root port=0 database=mysqlscanner' AS my (TYPE mysql, READ_ONLY);
USE my;
SHOW TABLES;
```

此处必须点明一个易错点：MySQL 集成的连接串同样是 PostgreSQL 风格 `{key}={value}`（database/host/password/port/socket/user），而非原生 MySQL 客户端所用的 `user:password@host:port/database` 形式；其中的 `port=0` 表示沿用客户端默认端口（3306）。混用 MySQL 风格串会导致解析失败。

辅助函数与 PostgreSQL 对称：`mysql_query(attached_db, query)` 在远端执行只读查询；`mysql_execute(attached_db, query)` 执行任意语句；`mysql_clear_cache()` 失效 schema 缓存。

类型映射方面，扩展提供若干开关以贴合 MySQL 的布尔惯例：`mysql_tinyint1_as_boolean` 把长度为 1 的 TINYINT 视作布尔，`mysql_bit1_as_boolean` 把 BIT(1) 视作布尔；连接安全由 `ssl_mode` 参数控制。更多行为可通过 `mysql_enable_filter_pushdown`（下推过滤）、`mysql_session_time_zone`、`mysql_time_as_time` 等设置项微调。

支持的操作涵盖 CREATE TABLE、INSERT、SELECT、COPY（含 `COPY FROM DATABASE`）、UPDATE、DELETE、ALTER TABLE、DROP、CREATE VIEW、CREATE/DROP SCHEMA 与事务。需留意 MySQL 的 DDL 是非事务性的：一条 `ALTER TABLE` 中途失败不会回滚，调用方需自行校验结构状态。

## 11.5 本章小结

本章梳理了 DuckDB 通过 scanner 扩展与 PostgreSQL、SQLite、MySQL 三类外部数据库集成的方法，要点归纳如下：

- ATTACH 是把外部源挂载为 catalog 的统一入口，三段式 `catalog.schema.table` 寻址让远端表与本地表无差别；只读场景应优先 `READ_ONLY` 挂载；单事务只能写入一个 attached 库，回写远端须处理乐观并发冲突的重试。
- PostgreSQL 路径用 postgres（postgres_scanner）扩展，支持整库挂载、单表 `postgres_scan` 与 `postgres_query`/`postgres_execute` 辅助函数；RDS/Aurora 借助 aws 扩展的 `TYPE rds` secret 实现 IAM 令牌自动刷新；v1.5.5 的 `pg_staleness_query_enabled` 可在 schema 变化时自动失效缓存。
- SQLite 路径用 sqlite 扩展挂载文件，注意类型亲和（type affinity）与 `sqlite_all_varchar` 脏数据兜底，并兼容 Turso/libSQL。
- MySQL 路径用 mysql 扩展，连接串务必采用 PostgreSQL 风格；`mysql_tinyint1_as_boolean` / `mysql_bit1_as_boolean` 贴合布尔惯例，且须记住 MySQL DDL 非事务性这一约束。
