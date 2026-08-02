# 第 01 章 DuckDB 概述与核心思想

数据库管理系统（DBMS）种类繁多，却不存在一种能包打天下的方案——Stonebraker 等人早已指出"one-size-fits-all"在数据库领域并不成立，每一款系统都在特定取舍中找寻自己的生态位。DuckDB 同样如此：它无意取代事务型主库，而是把分析型（analytical）负载在进程内（in-process）高效地完成。本章先为 DuckDB 给出清晰定位，再拆解支撑它的设计哲学与技术直觉，最后给出全书的阅读地图。

## 1.1 什么是 DuckDB：进程内（in-process）分析型数据库

DuckDB 是一个关系型（table-oriented）、以表为中心（table-oriented）的数据库，使用 SQL 作为查询语言。它的两条核心标签，一是进程内（in-process），二是面向分析型负载（OLAP，Online Analytical Processing）。

"进程内"意味着 DuckDB 没有独立的服务器进程（server process）。引擎被直接编译进宿主程序，与调用方运行在同一地址空间内。这与 PostgreSQL、MySQL 这类"客户端—服务器"（client-server）数据库形成根本分野：后者需要部署、运维一个常驻服务，应用经由网络与之通信；而 DuckDB 只是一个被链接进来的库（library），你引入（import）它、调用它，数据就安放在本进程的内存中。官方甚至把整个源码树合并（amalgamation）成头文件与实现文件两个产物，零外部依赖（no external dependencies），使部署与集成极其轻量。

"分析型"意味着它的优化目标不是高频短小的事务（OLTP，如每秒数万次单行读写），而是相对长时、复杂、扫描大块数据的查询——整表聚合、多张大表 join、窗口函数分析等。文档将其负载特征概括为：查询处理数据集的显著部分，而数据变更也往往是大规模批量（一次追加或改写大段数据）。

把两条标签合起来，DuckDB 的本质便清晰了：**一个跑在你程序里、为分析而生的列存数据库**。它最常见的形态是单文件数据库（扩展名 `.duckdb` / `.db` / `.ddb`），亦支持纯内存模式。

下面用命令行（CLI）启动并完成第一条查询：

```bash
# 安装 DuckDB（Python 包附带 CLI，或下载官方二进制）
python -m pip install duckdb

# 进入交互式 CLI，打开或创建单文件数据库
duckdb my_first.duckdb
```

进入 CLI 后执行：

```sql
SELECT 42 AS answer, 'hello duckdb' AS greeting;
```

这条查询不经过任何网络往返，引擎就在当前进程内解析、向量化执行并返回结果。

## 1.2 设计哲学与适用场景

DuckDB 官网用一组关键词归纳其设计取向：Simple（简单）、Portable（可移植）、Feature-Rich（功能完备）、Fast（快）、Extensible（可扩展）、Free（自由）、Thoroughly Tested（经严格测试）。其中与定位最相关的三条是 Simple、Portable、Fast。

**简单与嵌入式体验。** DuckDB 借用了 SQLite 最成功的两点——安装简单、进程内运行——但后来通过 Quack 协议把能力延伸到进程外。它无需安装、更新或维护任何 DBMS 服务端软件。对于其面向的分析场景，进程内还带来额外红利：宿主与数据库之间的数据搬运极快，某些情况下甚至零拷贝。例如 Python 包可以在不导入、不复制任何数据的前提下，直接对 Pandas DataFrame 运行 SQL 查询（replacement scan 机制）。

**可移植与"无服务器"。** 由于零依赖，DuckDB 可编译到 Linux、macOS、Windows 以及 x86、ARM 架构，从资源受限的边缘设备一路部署到数百核、数 TB 内存的服务器；借助 DuckDB-Wasm，它还能跑在浏览器乃至手机里。它提供 C、C++、Go、Python、R、Rust、Java、Node.js 等语言的 API。此处的"无服务器体验"并非云函数那种 serverless，而是"无需管理服务端"——你拿到一个库、一份数据文件，分析即刻开始。

**快与面向分析。** DuckDB 针对 OLAP 负载设计：这类负载要在每个被处理的值上尽量少花 CPU 周期，手段是向量化（vectorized）或即时编译（JIT）执行引擎。DuckDB 选择了 columnar-vectorized（列式向量化）执行：查询仍是解释执行，但一次操作处理一大"批"值（一个 vector），大幅削减了 PostgreSQL、MySQL、SQLite 那种逐行（tuple-at-a-time）处理的开销。

**功能完备与可扩展。** 进程内的便利并未以能力缩水为代价。DuckDB 支持复杂的 SQL 查询——庞大的函数库、窗口函数、CTE、各类 join 一应俱全；通过自研、面向批处理的 MVCC 提供 ACID 事务保证；数据既可用原生单文件格式存储，也能落到 DuckLake 等湖仓（lakehouse）格式，后者可扩展到 PB 级。它还提供灵活的扩展机制：Parquet、JSON、时区（ICU）、HTTP(S) 与 S3 等核心能力本身就是以扩展形式实现的，社区扩展则进一步打开了自定义类型、函数与文件格式的空间。

适用场景由此自然浮现：本地数据分析与探索、作为 Pandas / Arrow / Polars 等数据科学生态的查询引擎、把 Parquet / CSV 直接当库来查、笔记本（notebook）中的交互式分析，以及嵌入式分析（在应用进程内就地分析，无需起服务）。它不适合充当高并发、多客户端、需要严格写并发的"主数据库"——那是 PostgreSQL 或 ClickHouse 集群的领地；单进程内的写冲突会以乐观并发失败告终，需要重跑事务。

## 1.3 与 SQLite、ClickHouse、PostgreSQL 等系统的定位对比

理解 DuckDB 最直观的办法，是把它放进软件谱系里看。下面四个系统常被并列提及，各自的取舍却截然不同。

| 系统 | 部署形态 | 存储模型 | 主攻负载 | 多进程写 |
|---|---|---|---|---|
| SQLite | 进程内（in-process） | 行式（row-oriented） | OLTP（事务） | 单写者，多进程可读 |
| DuckDB | 进程内（in-process） | 列式（columnar） | OLAP（分析） | 单进程内多写线程；多进程写经 Quack / DuckLake |
| PostgreSQL | 客户端—服务器 | 行式（row-oriented） | OLTP 为主 | 多客户端并发写 |
| ClickHouse | 客户端—服务器 | 列式（columnar） | OLAP（分析） | 服务端分布式写 |

SQLite 是地球上部署最广的 DBMS，DuckDB 直接继承了它"简单、进程内"的基因，但 SQLite 是行存、为事务（OLTP）优化；DuckDB 把同样的嵌入范式搬到了分析（OLAP）阵地，换成列存与向量化。二者互补而非替代：需要轻量事务用 SQLite，需要就地分析用 DuckDB。

PostgreSQL 是经典客户端—服务器数据库，DuckDB 甚至直接复用了 PostgreSQL 的 SQL 解析器（libpg_query）。但两者定位不同：PostgreSQL 把数据放在独立服务里，靠行级处理服务高频事务；DuckDB 把引擎放进你的进程，靠批处理服务分析查询。顺带一提，DuckDB 也能通过 postgres 扩展直接扫描或挂载 PostgreSQL 库，二者是协作关系。

ClickHouse 与 DuckDB 在"列式 + OLAP"上交汇，却分属两条路线：ClickHouse 是服务端、可分布式部署的面向分析的数据库，擅长远程多节点的大规模分析；DuckDB 是进程内、单文件的嵌入式分析库，强调"零运维、随取随用"。前者是"分析服务"，后者是"分析库"。

一句话定位：DuckDB 处在"嵌入式（SQLite 的便利）× 分析型（ClickHouse / OLAP 的能力）"的交叉点。

## 1.4 列式存储与向量化执行的直观理解

DuckDB 有四项技术支柱：列式存储（columnar storage）、向量化执行（vectorized execution）、轻量压缩（lightweight compression）、多版本并发控制（MVCC）。本节先用直觉讲清前两柱，后两柱在后续章节展开。

**列存 vs 行存。** 想象一张 100 万行、含 `id / name / age / city` 四列的表。行存（如 SQLite、PostgreSQL）把每一行的四个字段紧挨着放在磁盘上；当你只关心"各城市的平均年龄"时，仍得把 name、city 一并读出来，浪费 IO 与缓存。列存则把同一列的 100 万个 age 连续存放、100 万个 city 连续存放——分析查询往往只读少数几列，于是只需加载相关列，IO 量成数量级下降。同时，同列数据类型一致，压缩效率远高于行存。

**向量化执行。** 传统 Volcano / Iterator 模型里，每个算子实现 `next()`，一次吐一行，逐行穿过整棵算子树；这带来频繁的虚函数调用、糟糕的分支预测与可怜的缓存命中率。DuckDB 改为**推送式（push-based）向量化模型**：算子以固定大小的向量（Vector）为批处理单位，整批数据在算子间流动。这个固定大小由常量 `STANDARD_VECTOR_SIZE` 决定，默认 **2048 行**——所有算子都针对这个批量优化。

批处理带来三重收益：① 解释与虚调用的开销被摊薄到 2048 行上；② 对整批数据做紧凑循环，利于 CPU 流水线与 SIMD 指令；③ 支持"压缩执行"——部分向量格式（如 Dictionary Vector）可在不解压的情况下直接参与计算。执行期间在算子间流动的基本单位是 DataChunk，即一组 Vector 的集合。

用一个形象的比喻：Volcano 模型像流水线工人一次只递给你一颗螺丝；向量化模型则把 2048 颗螺丝装进一个料盒一次性递过来，你用机械臂批量拧紧——单位成本被剧烈摊薄。

## 1.5 本书路线图与阅读建议

本书以 DuckDB v1.5.5 为版本基线，共 19 章，分为七大部分：

1. **基础入门**：安装与 CLI、SQL 基础、数据类型、单文件与内存数据库。
2. **数据工程**：CSV / Parquet / JSON 等文件格式的读写，外部数据源与云存储，与其他数据库的集成。
3. **客户端与生态集成**：Python、R、Arrow、Pandas、JDBC / ODBC 等。
4. **扩展机制**：核心扩展与社区扩展、自定义函数与扩展开发。
5. **性能与运维**：并行与超内存、索引与压缩、性能剖析（`EXPLAIN` / `EXPLAIN ANALYZE`）、故障排查。
6. **原理剖析**：查询流水线、向量化引擎、存储格式、MVCC 与并发。
7. **实战与总结**：综合案例与最佳实践。

阅读建议随背景而异：初次接触分析型数据库的读者，请按顺序通读前两部分，把"列存 + 向量化"的直觉打牢；已有 SQL 经验、只想用 DuckDB 做数据处理的，可直接跳到数据工程与客户端集成部分；打算深入内核或做二次开发的，重点研读原理剖析与扩展机制章节。无论哪条路径，都建议边读边在 CLI 或 Python 里敲一遍示例——DuckDB 的进程内特性让"随手试一条查询"几乎没有成本。

## 1.6 本章小结

本章给出了 DuckDB 的清晰轮廓：它是一个**进程内、面向分析（OLAP）的列式数据库**，无独立服务进程，常见形态为单文件或纯内存。它的便利性继承自 SQLite 的"嵌入式"基因，分析能力则来自列存与向量化执行。与 SQLite（行存 OLTP）、PostgreSQL（客户端—服务器 OLTP）、ClickHouse（客户端—服务器列式 OLAP）相比，DuckDB 占据"嵌入式便利 × 分析能力"的交叉生态位，定位为分析库而非主数据库。

四条技术支柱中，本章用直觉讲清了**列式存储**（按列连续存放，分析查询只读所需列、压缩率更高）与**向量化执行**（以 2048 行为一批的推送式批处理，摊薄调用开销、利好 SIMD 与压缩执行）；剩余两柱——轻量压缩与 MVCC——将在后续性能与原理章节展开。带着"它跑在我的进程里、为分析而优化"这一核心认知，即可进入下一章的动手实践。
