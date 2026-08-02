# 第 18 章 应用场景实践

前十七章沿着"安装配置 → SQL 查询 → 数据工程 → 客户端与生态集成 → 扩展机制 → 性能调优 → 原理剖析"的脉络，逐步拆解了 DuckDB 的能力边界与内部机理。能力终究要落到具体的工作负载上才有意义。DuckDB 的出身决定了它并非用来取代传统服务式数据库，而是以进程内（in-process）、列式存储（columnar storage）、向量化执行（vectorized execution）的特质，在若干类场景中提供低摩擦的分析能力：本地随手探索数据、给事务型数据库补上分析侧、搭建轻量 ETL（Extract-Transform-Load）管线、把引擎嵌入应用做就地分析、以及与 Python 数据科学生态互为表里。本章逐一给出这些场景的落地方式与取舍，所有示例均以 DuckDB v1.5.5 为基线，代码均可直接运行。

## 18.1 本地数据分析与探索式查询

探索式分析（exploratory data analysis）的痛点往往是"想看一眼数据却要先搭一套环境"。DuckDB 的进程内特性恰好消解了这道门槛：不需要启动服务，不需要建表，把 CSV、Parquet 甚至远程文件直接当作查询对象即可。零成本试错，是这一场景最贴切的注脚。

### 18.1.1 CLI 随手查文件

DuckDB 的命令行工具（CLI）开箱即用。给定一个 Parquet 文件，无需任何导入步骤，直接用 `FROM` 把它当表查询：

```bash
duckdb -c "SELECT year, count(*) AS n
           FROM 'sales.parquet'
           GROUP BY year ORDER BY year;"
```

单条 `-c` 参数即可执行整段 SQL 并退出，适合写进 shell 管道或定时任务。文件格式由扩展名自动识别，CSV 同样适用：

```bash
duckdb -c "SELECT region, sum(amount) AS total
           FROM 'orders.csv'
           WHERE order_date >= '2024-01-01'
           GROUP BY region;"
```

面对陌生的数据集，先摸清结构与分布比急着写查询更务实。`DESCRIBE` 看 schema，`SUMMARIZE` 则一次性给出每列的最小值、最大值、近似唯一值数、均值、分位数与 NULL 占比：

```bash
duckdb -c "SUMMARIZE SELECT * FROM 'sales.parquet';"
duckdb -c "DESCRIBE SELECT * FROM 'sales.parquet';"
```

远程文件也无需预先下载，DuckDB 会把列裁剪（projection pushdown）与过滤下推（filter pushdown）直接作用到远程读取上，只传输所需部分：

```bash
duckdb -c "SELECT count(*) FROM 'https://blobs.duckdb.org/data/holdings.parquet';"
```

CLI 默认以 Duckbox 表格呈现结果，配合 `YouPlot` 这类终端绘图工具，更能在无图形界面的环境里快速做可视化：

```bash
duckdb -c "COPY (SELECT region, sum(amount) AS total
                  FROM 'orders.csv' GROUP BY region)
           TO '/dev/stdout' (FORMAT csv, HEADER)"
| uplot bar -d, -H -t "Region Totals"
```

### 18.1.2 Jupyter 中的交互分析

笔记本环境里，DuckDB 既能以原生 Python 连接工作，也能借由 jupysql 把代码单元变成 SQL 单元。原生接入只需加载扩展并指向一条连接：

```python
import duckdb
%load_ext sql
conn = duckdb.connect()
%sql conn --alias duckdb
```

此后 `%sql` 执行单行查询、`%%sql` 把整段单元当作 SQL 来跑，结果默认呈现为 pandas DataFrame。需要把本地 DataFrame 也纳入查询范围时，可执行：

```python
%sql SET python_scan_all_frames = true
```

这会让当前命名空间中所有可见的 pandas DataFrame 都能被 SQL 直接引用，省去手动注册的步骤。`%sqlplot` 则把绘图计算下推到 SQL 引擎内部完成，避免把超大数据集整体搬进 Python：

```sql
%sqlplot histogram --column amount --with orders.csv
```

借助 `httpfs` 扩展，笔记本同样能查询云端 Parquet，把远程数据探查与本地建模整合在同一工作流中：

```python
con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
con.execute("SELECT * FROM read_parquet('s3://bucket/large.parquet') LIMIT 10;")
```

### 18.1.3 零成本试错的工作流

探索式分析的价值在于"快速失败、快速迭代"。DuckDB 的内存库（`:memory:`）天然契合这种节奏：每条查询独立、互不影响，试错不会产生遗留的表或文件。即便改用持久库做稍长期的草稿，单个 `.duckdb` 文件也方便随项目归档或删除，不构成运维负担。

当探索产出有价值的中间结果，再把它固化下来也不费事——内存库可通过 `COPY FROM DATABASE` 整体落盘为持久库：

```sql
ATTACH 'exploration.db';
COPY FROM DATABASE memory TO exploration;
DETACH exploration;   -- 目标文件需事先不存在
```

这条路径把"随手试"与"正式沉淀"连成一条平滑曲线：分析师不必在探索阶段就为 schema 设计纠结，待模式稳定后再固化即可。

## 18.2 作为 SQLite 的 OLAP 补充

SQLite 是嵌入式事务处理（OLTP）的事实标准，几乎内置在所有手机与桌面软件中；它在小事务、高并发写入的场景表现稳健，却不擅长跨多表、跨多行的聚合分析。DuckDB 恰好在另一侧补足：同一个应用，让 SQLite 守住事务型数据，把分析型查询交给 DuckDB，二者通过文件与 `ATTACH` 桥接，无需引入额外的服务组件。

### 18.2.1 分工：事务与分析各司其职

典型形态是移动端或桌面应用用 SQLite 持续记录交易流水、用户行为等行级写入；运营侧要回答"各区域本月成交额""用户留存趋势"这类问题，则把 SQLite 文件交给 DuckDB 直接扫描。SQLite 的强项在于点查、小批量写入与 ACID 保证，DuckDB 的强项在于列式扫描、向量化聚合与大于内存（larger-than-memory）的处理能力——两者目标不同，互补而非竞争。

需要强调的是，DuckDB 通过 `sqlite` 扩展读取 SQLite 文件是只读桥接，分析查询不会改写源库，这与把事务库与分析库物理隔离的安全诉求一致。

### 18.2.2 通过 sqlite 扩展桥接

桥接的第一步是安装并加载扩展：

```sql
INSTALL sqlite;
LOAD sqlite;
```

随后即可用 `sqlite_scan` 直接扫描某张表，或用 `ATTACH` 把整个 SQLite 库挂为 DuckDB 的一个 schema：

```sql
-- 单表扫描
SELECT * FROM sqlite_scan('app.db', 'transactions');

-- 整库桥接，之后以 schema 形式引用
ATTACH 'app.db' AS app (TYPE sqlite);
SHOW TABLES FROM app;
```

`ATTACH ... (TYPE sqlite)` 之后，`app` 下的所有表都像普通 DuckDB 表一样可查，列类型按 SQLite 的存储类自动映射。桥接是即时且轻量的，挂上即可分析，摘下（`DETACH`）即恢复 SQLite 文件的独立状态，不污染任何一方。

### 18.2.3 一次桥接查询示例

设想 `app.db` 内有一张 `transactions` 表，记录每笔订单的地区、金额与时间。用 DuckDB 承接其分析侧只需一次桥接：

```sql
INSTALL sqlite;
LOAD sqlite;
ATTACH 'app.db' AS app (TYPE sqlite);

SELECT
    region,
    DATE_TRUNC('month', order_ts) AS month,
    sum(amount)                   AS revenue,
    count(*)                      AS orders
FROM app.transactions
WHERE order_ts >= DATE '2024-01-01'
GROUP BY region, month
ORDER BY region, month;
```

这段查询对 SQLite 文件做列式读取与向量化聚合，源库保持只读。若分析结论需要回流到事务系统（例如把汇总结果写回 SQLite 的报表表），可先把结果写成 Parquet 或以 `COPY` 导出，再由应用侧导入——保持桥接单向，避免分析负载反过来拖累事务写入。

## 18.3 轻量级数据管线

ETL 管线的本质是把分散、异构的数据抽取出来，清洗转换后落到统一的存储。重型方案往往需要专门的调度服务与计算集群，而许多中小规模场景里，DuckDB 自身就能充当内存计算层（in-memory compute layer）：读取多源文件或数据库、在进程内完成连接与聚合、再把结果写出为 Parquet 或持久库，整个流程一个二进制文件即可驱动。

### 18.3.1 多源读取与内存计算

DuckDB 的 `read_csv` 与 `read_parquet` 是查询级别的函数式读取器，可在一条 SQL 内同时打开不同来源并 join：

```sql
CREATE TABLE enriched AS
SELECT
    c.customer_id,
    c.name,
    o.order_date,
    o.amount,
    o.amount * COALESCE(e.rate, 1.0) AS amount_local
FROM read_csv('orders.csv', auto_detect = true)       AS o
JOIN read_parquet('customers.parquet')                 AS c
  ON o.customer_id = c.customer_id
LEFT JOIN read_parquet('fx_rates.parquet')             AS e
  ON c.country = e.country
 AND o.order_date = e.rate_date
WHERE o.order_date >= DATE '2024-01-01';
```

`CREATE TABLE ... AS`（CTAS）把结果物化为当前连接中的一张表，后续步骤直接引用，不必重复扫描源文件。当源 schema 偶发不一致（例如某批文件多出或少了几列），可用 `UNION ALL BY NAME` 技巧在转换时动态对齐列，而非手工修补每一份文件。

### 18.3.2 写出 Parquet 或持久库

中间结果既可以持久化为 DuckDB 单文件库，也可以导出为 Parquet 供下游继续消费。写出 Parquet 时，可显式指定压缩与 row group 大小以贴合下游读取习惯——row group 在 100K~1M 行区间对并行扫描最为友好：

```sql
COPY enriched
TO 'enriched.parquet'
(FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 200000);
```

若下游是另一个 DuckDB 库（或同一管线不同阶段的产物需要集中管理），则直接 `COPY ... TO` 进已 `ATTACH` 的目标库：

```sql
ATTACH 'warehouse.db' AS wh;
COPY enriched TO wh.fact_orders;
```

数据需要增量更新而非全量重写时，`MERGE` 语句（自 v1.4.0 引入）可用单条语句完成按主键的插入、更新与软删除，契合缓慢变化维（SCD Type 2）等常见 ETL 语义：

```sql
MERGE INTO wh.fact_orders AS target
USING enriched AS source
  ON target.customer_id = source.customer_id
     AND target.order_date = source.order_date
WHEN MATCHED THEN UPDATE SET amount = source.amount
WHEN NOT MATCHED THEN INSERT *;
```

### 18.3.3 调度中的批处理脚本

把上面的 SQL 收进一个脚本，再交给 cron 或 Airflow 定时触发，便是一条完整的轻量管线。DuckDB 进程内、无服务的特性意味着脚本启动即算运行、结束即算退出，没有常驻进程需要看护：

```python
import duckdb

con = duckdb.connect("pipeline.db")
con.execute("INSTALL httpfs; LOAD httpfs;")
con.execute("""
    CREATE OR REPLACE TABLE staging AS
    SELECT * FROM read_parquet('s3://bucket/incoming/*.parquet');
""")
con.execute("""
    INSERT INTO fact_daily
    SELECT day, sum(amount) FROM staging GROUP BY day;
""")
```

批量加载阶段应尽量避开主键、唯一等约束——它们会触发索引维护与完整性检查，显著拖慢摄入；确有完整性需要时，遵循"先加载、后加约束"的原则，加载完成再补主键，比边加载边校验快数倍。

## 18.4 嵌入式分析中台与应用

中台（middle platform）概念常被等同于一套独立的分析服务，但很多产品的分析需求其实轻到不必起服务：报表看板、运营埋点查询、本地 BI（business intelligence）工具，都可以把 DuckDB 引擎直接嵌入应用进程，就地分析应用自身产生的数据。

### 18.4.1 进程内就地分析

DuckDB 不依赖任何后台进程，引擎与宿主应用共享同一地址空间。应用启动时顺带打开一个持久库，后续查询就是一次函数调用，没有网络往返、没有连接池耗尽之忧：

```python
import duckdb

con = duckdb.connect("analytics.duckdb")
con.execute("INSERT INTO events SELECT * FROM read_csv('events.csv')")
rows = con.execute(
    "SELECT device, count(*) AS n FROM events GROUP BY device"
).fetchall()
print(rows)
```

持久库的默认线程数等于 CPU 核数，默认 `memory_limit` 为物理内存的 80%——分析即服务（analytics-as-a-service）被压缩到"嵌入一个库"的体量，部署复杂度趋近于零。需要限制资源占用时，通过连接参数或 pragma 显式设小即可，例如受限容器里把 `threads` 调低以匹配分配的 vCPU。

### 18.4.2 轻量分析中台的实现

一个内嵌的分析中台，对外暴露的往往不是 SQL 字符串，而是若干预定义的查询接口。DuckDB 的 prepared statement（预处理语句）适合这类"同结构、不同参数"的反复查询，缓存解析与计划，降低小查询开销：

```python
import duckdb

con = duckdb.connect("analytics.duckdb")
con.execute("PREPARE get_region AS "
            "SELECT sum(amount) FROM orders WHERE region = $1;")
for region in ("East", "West", "North"):
    print(con.execute("EXECUTE get_region('" + region + "')").fetchone())
```

查询逻辑沉淀在应用内部，数据驻留在本地单文件库，既绕开了独立数仓的运维，又保留了 SQL 的表达力。结合 `httpfs` 与云存储 secret，这类中台还能透明地把远程 Parquet 纳入计算，把"本地分析"自然扩展为"本地 + 云端混合分析"而不改变代码骨架。

### 18.4.3 并发与连接管理

进程内并不意味着不能并发。同一进程内的多 reader/writer 线程，各自用 `cursor()` 拿到线程本地的连接句柄，即可并发读写同一 DuckDB 文件——DuckDB 已在单条查询内部尽力并行，多数场景下单连接已足够，多连接适合需要并行执行多个独立操作的场合：

```python
import duckdb
import threading

con = duckdb.connect("analytics.duckdb")

def worker():
    cur = con.cursor()                       # 线程本地句柄
    cur.execute("INSERT INTO events VALUES (1, 'click')")
    print(cur.execute("SELECT count(*) FROM events").fetchone())

threads = [threading.Thread(target=worker) for _ in range(4)]
for t in threads: t.start()
for t in threads: t.join()
```

连接本身是宝贵资源，复用同一连接优于频繁断开重连；若应用是多线程服务，用连接池或在各线程内复用句柄都比每请求新建连接更经济。单事务只能写入一个 attached 数据库，且写写冲突会乐观失败（optimistic failure），并发写入方需对重试做好处理。

## 18.5 与数据科学生态协同

Python 是 DuckDB 的一级客户端，二者在数据科学生态里的协作方式是本章其余场景的技术底座。pandas、Polars、PyArrow 与 DuckDB 之间并非"谁替代谁"，而是通过 replacement scan（替换扫描）与零拷贝（zero-copy）互为查询引擎与存储后端。

### 18.5.1 replacement scan 无缝互操作

replacement scan 让当前作用域中可见的 DataFrame 变量无需任何注册，就能直接出现在 SQL 的 `FROM` 子句里。DuckDB 遇到一个 DataFrame 变量名时，自动把它替换为一个可扫描数据源：

```python
import duckdb
import pandas as pd

df = pd.DataFrame({"i": [1, 2, 3], "j": ["one", "two", "three"]})

# DataFrame 直接当表查，无需 register
result = duckdb.sql("SELECT sum(i) AS total_i, max(j) AS last FROM df").df()
print(result)
```

把 DataFrame 反向写回 DuckDB 同样简洁，`CREATE TABLE ... AS SELECT` 或 `INSERT INTO` 都能直接消费 DataFrame 变量名；按列名对齐可加 `BY NAME`，或用连接的 `append` 方法做批量追加：

```python
duckdb.sql("CREATE TABLE my_table AS SELECT * FROM df")
con = duckdb.connect()
con.append("my_table", df, by_name=True)        # 按列名对齐追加
```

replacement scan 只对调用处可见的变量生效，同名冲突时优先级为：显式 `register` 的视图 > 原生表/视图 > replacement scan。它把"SQL 与 DataFrame 之间反复搬运"的心智负担降到最低——数据停留在 Python 里，查询却拥有完整的 SQL 能力。

### 18.5.2 把 DuckDB 当查询引擎驱动 DataFrame

数据科学工作流里，清洗与聚合往往用 SQL 表达更清晰，而上下游建模又依赖 DataFrame 接口。DuckDB 恰好充当那个"查询引擎"：DataFrame 进、DataFrame 出，中间的计算由 DuckDB 的向量化执行完成，而非逐行 Python 循环：

```python
import duckdb
import pandas as pd

orders = pd.DataFrame({
    "region": ["East", "West", "East", "West"],
    "amount": [100.0, 250.0, 150.0, 80.0],
})

agg = duckdb.sql("""
    SELECT region, sum(amount) AS total, count(*) AS n
    FROM orders
    GROUP BY region
    ORDER BY total DESC
""").df()

print(agg)
```

这种"以 SQL 驱动 DataFrame"的模式把声明式查询的简洁性带给 pandas 用户，又规避了 pandas 在大表上逐行操作的内存与速度瓶颈。当结果超大，可改用 `fetch_df_chunk` 分块取回，块大小等于 `2048 × vector_multiple`——这里的 2048 正是 DuckDB 向量化的基本单位 `STANDARD_VECTOR_SIZE`。

关系 API（relational API）则提供另一条延迟求值的路径：`from_df()` 拿到 Relation 后链式 `filter`/`aggregate`/`order`/`limit`，只有真正物化时才计算，且过滤与投影会被合并下推，避免中间结果全量物化：

```python
import duckdb
con = duckdb.connect()
rel = con.from_df(orders)
out = rel.aggregate("region, sum(amount) AS total", groups="region").order("total DESC").df()
print(out)
```

### 18.5.3 与 Polars / Arrow / Ibis 衔接

DuckDB 的互操作不限于 pandas。Polars DataFrame 同样可被 SQL 直接引用，从 DuckDB 取数则用 `.pl()`（传 `lazy=True` 可得 LazyFrame，延续 Polars 的延迟求值）：

```python
import duckdb
import polars as pl

p_df = pl.DataFrame({"x": [1, 2, 3], "y": [10, 20, 30]})
duckdb.sql("SELECT x, sum(y) AS s FROM p_df GROUP BY x").pl()
```

与 Apache Arrow 的互操作走零拷贝路径，列式缓冲在内存中直接共享。对外推荐 `to_arrow_reader(chunk_size)` 以流式分块读取，避免一次性物化超大结果：

```python
import duckdb
con = duckdb.connect()
reader = con.execute("SELECT range AS i FROM range(1000000)").to_arrow_reader(2048)
for batch in reader:
    pass   # 逐 RecordBatch 处理
```

Ibis 这类 DataFrame 库则以 DuckDB 为默认后端，提供链式、延迟求值的表达式 API，真正取数（`to_pandas()`）时才由 DuckDB 执行计算。从 pandas、Polars 到 Arrow、Ibis，DuckDB 在其中扮演的是"统一查询平面"：无论数据以哪种形态进入，都能用同一套 SQL 与向量化引擎完成分析，再按下游需要导回对应形态。

## 18.6 本章小结

本章把 DuckDB 的能力映射到五类真实工作负载，提炼出几个贯穿始终的取舍：

- **本地探索零门槛**：CLI 用 `FROM 'file.parquet'` 直接查文件，`SUMMARIZE`/`DESCRIBE` 快速摸底，内存库让试错无遗留负担，有价值的结果再 `COPY FROM DATABASE` 落盘沉淀。
- **SQLite 的分析侧补位**：通过 `sqlite` 扩展以只读方式 `ATTACH` 桥接，让事务库守住 OLTP、DuckDB 承接聚合分析，桥接单向、互不污染。
- **轻量 ETL 自洽**：`read_csv`/`read_parquet` 在一条 SQL 内多源 join，`CREATE TABLE ... AS` 物化中间结果，`COPY` 写出 Parquet 或持久库，`MERGE`（v1.4.0 起）承担增量更新；批量加载避开约束、先加载后加主键。
- **嵌入式分析中台**：引擎进程内就地分析，无服务、无连接池之忧；prepared statement 服务参数化查询，多线程借 `cursor()` 并发，连接复用优于频繁重连。
- **数据科学生态底座**：replacement scan 让 DataFrame 无需注册即可当表查，零拷贝贯通 Arrow；以 SQL 驱动 DataFrame 规避逐行 Python 瓶颈，Polars、Arrow、Ibis 各取所需，DuckDB 充当统一查询平面。

上述场景共享同一个内核事实：DuckDB 是进程内、列式、向量化的分析引擎。正因无服务、单文件、与生态互操作成本低，它才能在同一份代码里既做随手查询、也做管线计算、还做嵌入式中台——场景切换的边际成本，往往只是一个文件的路径。
