# 第 09 章 Python 客户端深入

DuckDB 作为进程内（in-process）分析型数据库，与 Python 的契合不只是"能连上"那么简单。Python 是 DuckDB 的一级（Primary）客户端，拥有与 SQL 语法一致、与磁盘格式互通的完整能力，且天然衔接 pandas、PyArrow、Polars、NumPy 这一整套数据科学生态。理解 Python 客户端的内部机制——惰性求值的关系 API（relational API）、参数化的 DB-API、零拷贝的 Arrow 互操作、以及最快的批量写入路径 Appender——是把 DuckDB 用对、用快的分水岭。本章所有示例均以 DuckDB v1.5.5 为基线，代码均可在独立进程中直接运行。

## 9.1 安装与连接

### 9.1.1 安装

DuckDB 的 Python 包名为 `duckdb`，使用 pip 或 conda 安装：

```bash
pip install duckdb
```

```bash
conda install python-duckdb -c conda-forge
```

该包对 Python 版本的要求是 **≥ 3.9**。DuckDB 与 pandas、PyArrow、Polars 的互操作是可选依赖——若只需基础功能，安装核心包即可；若要享受与 DataFrame 的无缝转换，则按需安装对应库：

```bash
pip install "duckdb[pandas]"      # 启用 pandas 互操作
pip install "duckdb[pyarrow]"     # 启用 PyArrow 互操作
pip install "duckdb[polars]"      # 启用 Polars 互操作
```

### 9.1.2 建立连接

导入包后，最朴素的用法是模块级快捷调用 `duckdb.sql()`，它复用一条隐式的全局内存连接：

```python
import duckdb

duckdb.sql("SELECT 42 AS the_answer").show()
```

生产代码中更推荐显式创建连接对象，因为模块级全局连接并非线程安全，多任务并行时容易相互干扰。`connect()` 是创建连接的入口，它既可以打开内存库，也可以打开持久化的单文件数据库：

```python
import duckdb

con = duckdb.connect()             # 内存库（in-memory database）
con = duckdb.connect("file.db")   # 持久库（on-disk，文件扩展名任意）
```

持久库的扩展名并不强制为 `.duckdb`，`.db`、`.ddb` 或任意后缀均可，因为 DuckDB 的磁盘格式与文件后缀无关。需要调优运行参数时，可通过 `config` 字典在连接建立时传入，例如限制单连接线程数：

```python
con = duckdb.connect(config={'threads': 1})
con = duckdb.connect(config={'storage_compatibility_version': 'latest'})
```

连接对象支持 Python 上下文管理器（context manager），退出 `with` 块时会自动关闭并刷写，避免句柄泄漏：

```python
with duckdb.connect("file.db") as con:
    con.execute("CREATE TABLE t(i INTEGER)")
    con.execute("INSERT INTO t VALUES (1), (2), (3)")
# 此处连接已自动关闭
```

多进程并发读取同一持久库时，应显式以只读方式打开，避免写操作相互干扰：

```python
con = duckdb.connect("file.db", read_only=True)
```

### 9.1.3 线程与并发

`duckdb.connect()`、`duckdb.connect(':default:')` 与 `duckdb.sql()` 建立的都是同一全局内存连接，**非线程安全**。并行场景应让每个线程各自建立独立连接。`cursor()` 方法返回的只是同一连接上的一个新句柄，**不能**实现并发查询——单连接上的查询会被加锁并串行化执行。这一约束与 DuckDB 的进程内本质一致：把连接视为"一个数据库会话"，而非"一个查询槽位"。

## 9.2 关系 API

### 9.2.1 什么是 Relation

关系 API（relational API）围绕核心类型 `DuckDBPyRelation` 展开，其返回的不是数据本身，而是查询的**符号化表示（symbolic representation）**。它的关键特征是**惰性求值（lazy evaluation）**：构造 Relation 时并不真正执行计算，只有显式取数或打印时才触发物化（materialization）。调用 `show()` 或 `print()` 时，DuckDB 默认仅取前 10K 行用于展示。

惰性带来的直接收益是**下推优化（pushdown optimization）**。下面的链式调用中，`filter` 与 `project` 不会逐步产生中间结果，而是被合并、重写后一次性推送到执行引擎：

```python
import duckdb

rel = duckdb.sql("SELECT * FROM range(1000000) t(i)")
rel = rel.filter("i % 2 = 0")          # 惰性：未执行
rel = rel.project("i, i * i AS square")  # 惰性：未执行
result = rel.limit(5).df()             # 此刻才物化，且 LIMIT 已下推
print(result)
```

由于过滤与投影都被下推，`range(1000000)` 中绝大多数行从未真正生成——这正是延迟计算（deferred computation）优于"先全量物化再处理"的地方。下推并非黑箱，可用 `explain()` 直接观察执行计划：

```python
print(rel.limit(5).explain())
```

计划中会显示过滤条件与 `LIMIT` 已被合并进底层扫描算子，而非在物化后才做取舍——这正是关系 API 把"描述计算"与"执行计算"分离带来的可优化空间。

### 9.2.2 从数据源创建 Relation

关系 API 提供多种创建入口，覆盖文件、DataFrame、Arrow、原生表与值构造：

```python
import duckdb

con = duckdb.connect()

rel_csv  = con.read_csv("example.csv")          # 读取 CSV 文件
rel_parq = con.read_parquet("data.parquet")      # 读取 Parquet 文件
rel_json = con.read_json("data.json")            # 读取 JSON 文件
rel_tbl  = con.table("my_table")                 # 引用已存在表
rel_vals = con.values([1, 2, 3], "x")           # 由值构造
```

拿到一个 Relation 后，在不触发物化的前提下即可检视其结构：`columns` 列出列名，`dtypes`/`types` 给出各列逻辑类型，`shape` 返回（行数, 列数），`describe` 给出摘要。这些方法返回的仍是元信息，不意味着执行了查询——这正是惰性 API 的便利：先看清数据长相，再决定如何计算。

```python
print(rel.columns)   # 列名列表
print(rel.dtypes)    # 各列类型
print(rel.shape)     # (估计行数, 列数)
```

### 9.2.3 链式转换与物化

Relation 的转换方法（transformation）支持链式调用且全程惰性，包括 `filter`、`project`/`select`、`aggregate`、`order`/`sort`、`limit`、`join`（inner/left/right/outer/semi/anti）、`union`/`except_`/`intersect`、`cross`、`apply`。转换结束后再以物化方法取回结果。

```python
import duckdb

con = duckdb.connect()
con.execute("CREATE TABLE sales(region VARCHAR, amount DOUBLE)")
con.execute("INSERT INTO sales VALUES ('East', 100), ('West', 250), ('East', 150)")

rel = con.table("sales")
agg = (rel
       .aggregate("region, sum(amount) AS total", groups="region")
       .order("total DESC"))

print(agg.df())          # Pandas DataFrame
print(agg.pl())          # Polars DataFrame
print(agg.arrow())       # Apache Arrow 表（推荐 to_arrow_reader）
print(agg.fetchnumpy())  # NumPy 字典（各列为数组）
```

四种物化出口各有用途：`.df()` 取 pandas，`.pl()` 取 Polars，`.arrow()` 取 PyArrow（对外推荐 `to_arrow_reader(chunk_size)`，可按 `chunk_size` 分块流式读取），`.fetchnumpy()` 取 NumPy 字典，其中带 NULL 的列会以掩码数组（masked array）表达缺失。若结果集过大，可用 `fetch_df_chunk(vector_multiple)` 分块取回 DataFrame，块大小等于 `2048 × vector_multiple`——这里的 2048 正是 DuckDB 向量化执行的基本单位 `STANDARD_VECTOR_SIZE`，与底层列式执行引擎的 `DataChunk`/`Vector` 一一对应。

### 9.2.4 一个性能警示

关系 API 的 `sql()`/`query()`/`from_query()` 方法在传参时存在显著开销（约 5 倍处理、近 2 倍内存）。需要参数化查询时，应改用 `execute()` 做参数绑定，再借助 replacement scan（见 9.4 节）把结果接入关系 API，而非在 Relation 内部反复嵌入参数化 SQL。

## 9.3 DB-API 与参数化查询

### 9.3.1 标准 DB-API 用法

DuckDB 的 `con.execute()` 实现了 Python DB-API 约定：执行语句、用 `fetchall()`/`fetchone()` 取数。取回的是原生 Python 对象（而非 DataFrame），列名可通过 `description` 属性查看。

```python
import duckdb

con = duckdb.connect()
con.execute("CREATE TABLE items(name VARCHAR, price INTEGER, qty INTEGER)")
con.execute("INSERT INTO items VALUES ('laptop', 2000, 1), ('mouse', 50, 3)")

rows = con.fetchall()
print(rows)            # [('laptop', 2000, 1), ('mouse', 50, 3)]
print(con.description) # 列名与类型描述
```

`fetchone()` 逐行取数，取完返回 `None` 后才真正关闭底层事务；`fetchdf()`（别名 `fetch_df`）则直接返回 pandas DataFrame，省去手动转换。

```python
df = con.execute("SELECT * FROM items").fetchdf()
print(df)
```

### 9.3.2 参数化查询与防注入

把用户输入直接拼进 SQL 字符串是 SQL 注入（SQL injection）的根源。DuckDB 支持两种占位符：**`?`（顺序占位）**与 **`$1`（可复用、按序号）**，二者均可配合参数列表执行：

```python
con.execute("INSERT INTO items VALUES (?, ?, ?)", ["keyboard", 300, 2])
con.execute("SELECT * FROM items WHERE price > ? AND qty >= ?", [100, 2])
```

命名参数以字典传入，键名对应 `$参数名`：

```python
con.execute("SELECT $p AS val", {"p": 5})
```

参数化查询的底层是 prepared statement（预处理语句），值在绑定时按类型安全转换，从根本上杜绝了字符串拼接带来的注入风险。DuckDB 还提供 `executemany()` 批量执行同一语句多组数据：

```python
con.executemany("INSERT INTO items VALUES (?, ?, ?)",
                [["monitor", 800, 1], ["cable", 20, 10]])
```

`executemany()` 适合小批量数据。**灌入海量数据时切勿使用它**——每条记录都会触发一次语句执行的开销，速度远不及 9.5 节介绍的 Appender 或 `COPY`/readers。

## 9.4 与 pandas / PyArrow / Polars / NumPy 互操作

### 9.4.1 replacement scan：把 DataFrame 当表查

DuckDB 能直接查询当前作用域中可见的 Python DataFrame，机制是 **replacement scan（替换扫描）**：当 SQL 的 `FROM` 子句引用了一个 DataFrame 变量名时，DuckDB 自动把它替换为一个可扫描的数据源，无需任何显式注册。

```python
import duckdb
import pandas as pd

df = pd.DataFrame({"i": [1, 2, 3], "j": ["one", "two", "three"]})

# 直接把 DataFrame 当作表查询
result = duckdb.sql("SELECT sum(i) AS total_i FROM df").df()
print(result)
```

Polars 与 PyArrow 对象同样适用，只是把变量换成对应类型：

```python
import polars as pl
import pyarrow as pa

polars_df   = pl.DataFrame({"x": [1, 2, 3]})
arrow_table = pa.table({"y": [10, 20, 30]})

duckdb.sql("SELECT * FROM polars_df").show()
duckdb.sql("SELECT * FROM arrow_table").show()
```

replacement scan 仅对 `sql()`/`execute()` 调用处**可见**的变量有效。若想关闭这一行为，可执行 `SET python_enable_replacements=false`。当同名冲突时，优先级为：`register()` 显式注册的视图 > 原生表/视图 > replacement scan。pandas 的 `object` 列在转换前会做采样分析（默认采样 `pandas_analyze_sample=1000` 行），若类型推断不准，可用 `SET GLOBAL pandas_analyze_sample=100000` 调大采样量。

### 9.4.2 从查询结果回到 DataFrame

把 SQL 查询结果取回为 DataFrame 是常见的"出"方向，依赖 9.2 节已经介绍过的物化方法：

```python
import duckdb
import pandas as pd

con = duckdb.connect()
con.execute("CREATE TABLE t AS SELECT range AS i FROM range(5)")
df = con.execute("SELECT i, i * i AS square FROM t").fetchdf()
print(type(df))   # <class 'pandas.core.frame.DataFrame'>
```

### 9.4.3 把 DataFrame 写回 DuckDB

"DataFrame → DuckDB"有两条常用落地路径。其一，先 `register` 注册为视图，再用 `CREATE TABLE ... AS SELECT` 持久化：

```python
import duckdb
import pandas as pd

con = duckdb.connect()
df = pd.DataFrame({"k": [1, 2], "v": ["a", "b"]})

con.register("my_view", df)                       # 注册为虚拟表（只读视图）
con.execute("CREATE TABLE persisted AS SELECT * FROM my_view")
```

其二，用关系 API 的 `from_df()` 拿到 Relation 后，直接 `create` 建表或 `insert_into` 写入已存在的表——这条路径语义清晰，且与查询闭环：

```python
rel = con.from_df(df)        # 得到 DuckDBPyRelation
rel.create("from_rel")       # 新建表
# 或写入已存在的表：
# rel.insert_into("existing_table")
```

### 9.4.4 与 Arrow 的零拷贝

DuckDB 与 Apache Arrow 的深度集成是其与大数据生态互通的基石。从 DuckDB 取出 Arrow 表、或把 Arrow 表交给 DuckDB 扫描，都尽量走**零拷贝（zero-copy）**路径——内存中的列式缓冲被直接共享，省去序列化与逐行复制。对外推荐 `to_arrow_reader(chunk_size)` 以流式分块方式读取，避免一次性把超大结果集物化进内存。

```python
import duckdb
import pyarrow as pa

con = duckdb.connect()
reader = con.execute("SELECT range AS i FROM range(1000)").to_arrow_reader(2048)
for batch in reader:
    print(type(batch))   # pyarrow.RecordBatch
```

## 9.5 Appender 批量写入与性能

### 9.5.1 为什么不用逐行 INSERT

写入大量数据时，最慢的做法是用预处理语句逐行 `INSERT`，或等价地用 `executemany` 灌入上百万条记录。每一条记录的写入都要经历语句解析、绑定、事务提交的完整链路，开销被重复放大。DuckDB 文档多次强调：**大量数据务必走 Appender 或 COPY（readers）**。

### 9.5.2 使用 Appender

Appender 是 DuckDB 批量写入的**最快路径**。其核心思路是：建立 Appender 后，逐行追加（append）各列的值，行满后结束该行（end row），最后刷新（flush）或关闭（close）以落盘。在 Python 中，这一机制被封装为连接对象的 `append` 方法——把一个完整 DataFrame 追加进已存在的表：

```python
import duckdb
import pandas as pd

con = duckdb.connect()
con.execute("CREATE TABLE logs(id INTEGER, msg VARCHAR)")

# 待写入的数据
new_rows = pd.DataFrame({"id": [1, 2, 3], "msg": ["a", "b", "c"]})

# Appender 批量写入（最快路径），by_name=True 按列名对齐
con.append("logs", new_rows, by_name=True)

print(con.execute("SELECT count(*) FROM logs").fetchone())
```

`append(table_name, df, by_name=False)` 的 `by_name` 参数控制按位置还是按列名对齐列——列顺序与表不一致时，务必设 `by_name=True`，否则数据会错位落列。从关系 API 一侧，亦可用 `DuckDBPyRelation` 的 `insert` / `insert_into` 完成同样语义的追加，其底层同样借助 Appender 避免逐语句开销。无论走哪条封装，关键认知一致：**Appender 把"逐行 INSERT"的解析开销摊薄，仅在缓冲满或显式关闭时才触发一次落盘**。

当数据已经以文件形式存在（Parquet、CSV），与其先读进 DataFrame 再 `append`，不如直接用 `COPY ... FROM` 或 `read_parquet`/`read_csv` 这类 readers 让 DuckDB 自身完成摄入，路径更短、内存占用更平滑。例如把一批 Parquet 直接追加进表：

```python
con.execute("COPY logs FROM 'logs_*.parquet' (FORMAT parquet)")
```

`COPY` 让 DuckDB 以内置的向量化读取器直接解析文件、分批落库，绕开了 DataFrame 中转与逐语句开销，是文件来源数据摄入的推荐做法。

## 9.6 Jupyter 与 SQLAlchemy

### 9.6.1 在 Jupyter 中使用 DuckDB

DuckDB 的 Python 客户端无需额外配置即可在 Jupyter 中直接使用。若要获得更顺手的笔记本体验，可借助社区生态：

- **jupysql**：把 Jupyter 代码单元变为 SQL 单元；
- **pandas / matplotlib**：结果可视化与下游分析；
- **duckdb-engine**：DuckDB 的 SQLAlchemy 驱动（见下）。

原生连接方式下，先加载 jupysql 扩展并指向一条 DuckDB 连接：

```python
import duckdb
import pandas as pd
%load_ext sql
conn = duckdb.connect()
%sql conn --alias duckdb
```

此后 `%sql` 用于单行查询、`%%sql` 用于整个单元做 SQL 单元，结果默认以 pandas DataFrame 呈现；`<<` 可把结果赋值给 Python 变量：

```sql
%sql res << SELECT 'Off and flying!' AS a_duckdb_column;
```

若希望 `%sql` 的结果默认以 pandas DataFrame 呈现（而非 `ResultSet`），可在笔记本开头配置 jupysql 的魔法选项：

```python
%config SqlMagic.autopandas = True
```

### 9.6.2 通过 SQLAlchemy 连接（duckdb-engine）

`duckdb-engine`（由社区维护的 SQLAlchemy driver）让 SQLAlchemy 应用能用统一接口连接 DuckDB。无需显式 `import duckdb_engine`，jupysql 会依据连接字符串自动探测驱动。支持三种目标：

```sql
%sql duckdb:///:memory:        -- 内存库
%sql duckdb:///:default:      -- 默认全局连接（与 duckdb.sql 共享）
%sql duckdb:///path/to/file.db -- 文件路径持久库
```

借助 duckdb-engine，既有的 SQLAlchemy 代码（ORM、连接池、metadata 反射等）几乎无需改动即可迁移到 DuckDB 之上。

### 9.6.3 marimo：响应式笔记本

[marimo](https://github.com/marimo-team/marimo) 是与 DuckDB Python 客户端深度集成的开源**响应式笔记本（reactive notebook）**。与传统笔记本不同，当某个单元被运行或与界面元素交互时，marimo 会自动（或惰性）重算受影响的下游单元，始终保持代码与输出一致。它的另一特点是把笔记本存为纯 Python 文件，便于 git 版本管理与作为脚本运行。

安装与启动教程：

```bash
pip install "marimo[sql]"      # 或 uv add "marimo[sql]"
marimo tutorial sql            # 运行交互式 SQL 教程
```

marimo 的 SQL 单元在底层被序列化为标准的 Python 代码 `mo.sql()`，因此不需要特殊语法或魔法命令：

```python
import marimo as mo
df = mo.sql(f"SELECT 'Off and flying!' AS a_duckdb_column")
```

SQL 语句以 f-string 书写，可用 `{}` 把 Python 变量（包括滑块等 UI 元素的值）插值进查询，构成数据依赖图的一部分。若 SQL 中出现用户输入，须自行做好净化以防范注入。要接入自定义连接，只需把 `duckdb.connect()` 创建的连接赋给一个 Python 变量，marimo 会自动在 SQL 单元的连接下拉框中发现它：

```python
import duckdb
conn = duckdb.connect("path/to/my.duckdb.db")   # marimo 自动识别
```

配合 UI 元素，可写出随参数联动的响应式查询——拖动滑块时，依赖该参数的 SQL 单元会被标记为"待刷新"，在 lazy 运行模式下由用户决定何时重算，从而从容处理昂贵查询与大型数据集。

## 9.7 本章小结

本章沿着"连接 → 计算 → 交换 → 写入 → 集成"的链路，梳理了 DuckDB Python 客户端的核心机制：

- **连接的两种形态**：`connect()` 既能开内存库也能开持久单文件库；显式连接优于模块级全局连接，多线程务必各建连接，`cursor()` 不能带来并发。
- **关系 API 的惰性价值**：`DuckDBPyRelation` 是查询的符号化表示，惰性求值让 `filter`/`project`/`limit` 等被合并下推，物化时才真正计算；取数出口 `df()`/`pl()`/`arrow()`/`fetchnumpy()` 分别对应 pandas、Polars、Arrow 与 NumPy。
- **参数化查询防注入**：`execute()` 配合 `?`/`$1` 占位符与字典命名参数，是安全传参的唯一正解；`executemany` 只适合小批量。
- **replacement scan 与零拷贝**：DataFrame/Arrow 可直接当表查询，免去注册；与 Arrow 的互操作尽量走零拷贝，并推荐 `to_arrow_reader` 流式读取。DataFrame 写回可用 `register`+`CREATE TABLE` 或关系 API 的 `from_df().create()/.insert_into()`。
- **Appender 是写入最快路径**：`con.append(table, df, by_name=True)` 底层借助 Appender 摊薄逐行写入开销，海量数据应弃用逐行 INSERT 与 `executemany`，改走 Appender 或 `COPY`/readers。
- **生态集成**：Jupyter 中可用 jupysql 魔法命令，duckdb-engine 提供 SQLAlchemy 连接串（`duckdb:///:memory:` 等）；marimo 则以响应式、纯 Python 文件的形式，把 SQL 与 Python 无缝编织进可复现的分析流。

下一章将走出 Python 单进程，进入 DuckDB 在更大工程场景中的扩展与集成。
