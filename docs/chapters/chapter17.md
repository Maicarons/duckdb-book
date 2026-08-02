# 第 17 章 DuckDB 内部原理

DuckDB 之所以能在进程内（in-process）环境中提供接近专门分析引擎的查询性能，根源不在某一处魔法，而是一组相互咬合的设计选择：列式存储（columnar storage）、向量化执行（vectorized execution）、磁盘上的轻量压缩（lightweight compression）以及基于 MVCC 的并发模型。前三者决定了单条查询如何被高效执行，最后一项决定了多个查询与写入如何互不干扰地共存。本章沿"一条 SQL 如何被执行"这条主线，逐层拆解 DuckDB 的内部机制：从词法解析到物理计划，从 DataChunk 在算子间的流动到 Row Group 在磁盘上的压缩布局，再到优化器的改写规则与事务的乐观并发。读完本章，读者应能把书中学过的 SQL 语句与引擎内部的实际行为对应起来。

## 17.1 查询处理流水线

SQL 字符串从输入到产出结果，在 DuckDB 内部经历一条分层、单向的流水线。这条流水线把"文本"逐级翻译成"可在内存中批量执行的物理算子"，每一层只关心自己职责范围内的转换，且下游阶段依赖上游阶段已经完成的解析与绑定。理解这条流水线，是理解后续向量化执行、优化器与存储所有机制的前提。

### 17.1.1 Parser：只做词法拆解，不感知语义

Parser 的职责是把原始 SQL 字符串切成若干 token，并组装成四种中间结构：`SQLStatement`、`QueryNode`、`TableRef` 与 `ParsedExpression`。其中 `SQLStatement` 表示一条完整语句——一条 SQL 字符串可以拆成多条语句；`QueryNode` 表示 `SELECT` 或集合操作（`UNION` / `INTERSECT` / `DIFFERENCE`）；`TableRef` 表示一切表来源，无论是基表、join、表生成函数还是子查询；`ParsedExpression` 表示表达式。

关键在于，Parser 阶段完全不感知 catalog，也不解析列类型。即使被查询的表在数据库中根本不存在，Parser 也不会报错——它只在语法层面完成 token 化。除显式 `CAST` 外，`ParsedExpression` 在此时没有类型信息，真正的类型要到 Binder 阶段才被解析。这种"无语义"的设计让 Parser 足够轻量，也为后续阶段保留了全部判断空间。

### 17.1.2 Binder：借助 catalog 完成语义绑定

Binder 把 Parser 产出的节点转换为"绑定（bound）"等价物，对应关系为：`SQLStatement` → `BoundStatement`、`QueryNode` → `BoundQueryNode`、`TableRef` → `BoundTableRef`、`ParsedExpression` → `Expression`。Binding 过程通过 catalog 解析表与列、解析每个表达式的类型，并抽取聚合函数与窗口函数。只有经过 Binder，一个表达式才真正拥有了类型，一个表引用才真正指向 catalog 中存在的对象。

### 17.1.3 Logical Planner 与 Optimizer

Logical Planner 由 bound statement 构造 `LogicalOperator` 节点树，形成逻辑查询树——这一步描述"要算什么"，还不涉及"怎么算"。Optimizer 随后对逻辑查询树运行一系列改写优化（详见 17.4），目标是产出语义等价但执行代价更低的计划。

### 17.1.4 Column Binding Resolver：从"列名"到"下标"

逻辑层的表达式引用的是"某表某列"，形式为 `BoundColumnRefExpression`。Column Binding Resolver 把这种语义化引用改写为执行引擎中的 `BoundReferenceExpression`，即直接引用某个 DataChunk 内具体下标的列。这一步抹去了所有表/列的符号信息，让下游算子只需按位置取数，是向量化执行得以高效运转的关键衔接。

### 17.1.5 Physical Plan Generator 与 Execution

Physical Plan Generator 把逻辑算子树转换为 `PhysicalOperator` 树，描述"具体如何执行"。Execution 阶段运行这些物理算子，产出结果。物理算子的执行采用向量化方式，DataChunk 在算子之间流动——这正是 17.2 的主题。

整条流水线用文字描述如下：

```
SQL 字符串 → Parser(token) → Binder(bound)
  → Logical Planner(LogicalOperator 树) → Optimizer(优化后的逻辑树)
  → Column Binding Resolver → Physical Plan Generator(PhysicalOperator 树)
  → 向量化执行(DataChunk 在算子间流动) → 结果
```

借助 `EXPLAIN` 可以直接观察优化后的物理计划，验证上述阶段的最终产物：

```sql
EXPLAIN SELECT l_orderkey, sum(l_quantity)
FROM lineitem
WHERE l_shipdate >= DATE '1995-01-01'
GROUP BY l_orderkey
ORDER BY l_orderkey;
```

`EXPLAIN` 的输出自上而下展示物理算子（如 `SEQ_SCAN`、`HASH_GROUP_BY`、`ORDER_BY`），其结构正对应 Physical Plan Generator 产出的 `PhysicalOperator` 树。

## 17.2 向量化执行引擎

### 17.2.1 Volcano 模型的问题

传统数据库普遍采用 Volcano（又称 Iterator）执行模型。该模型中每个算子实现 `next()` 方法，每次调用返回一行（tuple-at-a-time）数据。算子之间形成嵌套调用，一次查询要在整棵算子树上来回穿梭、逐行推进。这种逐行模型带来三个性能短板：频繁的虚函数调用（virtual function call）产生可观的解释开销；分支走向难以预测，破坏 CPU 流水线；单次只搬运一行，CPU 缓存利用率低，难以发挥 SIMD 指令的批处理能力。

### 17.2.2 DuckDB 的推送式向量化模型

DuckDB 采用基于推送（push-based）的向量化执行模型。算子的批处理单位不是单行，而是固定大小的向量（Vector）。整批数据在算子树间流动，DataChunk 被"推送"穿过各层算子，而非由上层逐个拉取。所有算子都针对一个固定的向量大小优化，这个大小由常量 `STANDARD_VECTOR_SIZE` 决定，默认 2048 行（元组）。

向量化模型相对 Volcano 模型的优势体现在三点：其一，批处理把解释与虚调用的开销摊薄到 2048 行上，单位数据的调度成本大幅下降；其二，对整批数据做紧凑循环，既贴合 CPU 流水线，也便于编译器生成 SIMD 指令；其三，某些向量格式可以在不解压的情况下直接参与计算，即"压缩执行（compressed execution）"。

### 17.2.3 DataChunk 与 Vector

DataChunk 是一组 Vector 的集合，是执行期间在算子间传递的基本单位。例如 `PhysicalProjection` 算子就用一个 DataChunk 表示一个列列表。Vector 则是执行期内存中保存单类型数据的容器。DuckDB 允许同一逻辑数据以不同物理格式（vector formats）表示，从而更紧凑，并可能实现压缩执行。

### 17.2.4 向量格式

DuckDB 支持多种向量格式：

- **Flat Vector（扁平向量）**：物理上就是一段连续数组，是标准的未压缩格式，逻辑表示与物理表示完全一致。
- **Constant Vector（常量向量）**：物理上只存一个常量值，适合重复值（如 `SELECT lst || 'duckdb'` 中的字面量），也由存储层从"常量压缩（Constant Encoding）"解压时产生。
- **Dictionary Vector（字典向量）**：由一个 child vector 加一个指向 child 的下标数组（selection vector）组成，存储层从"字典压缩（Dictionary Encoding）"解压时产生，使数据在执行期保持压缩。
- **Sequence Vector（序列向量）**：由一个 offset 与一个 increment 值表示，适合存储递增序列，通常用于行标识符（rowid）。
- **Unified Vector Format（统一向量格式）**：为简化编程而生——任何 Vector 都可转换为这种"通用视图"，避免为每种向量格式的组合编写特化代码（否则会产生组合爆炸）。

### 17.2.5 复杂类型的内存布局

字符串用 `string_t` 结构表示。长度不超过 12 字节的短字符串被内联（inlined）进结构体本身；更长的字符串则用指针指向 auxiliary string buffer。该结构同时携带 `length` 字段与 4 字节 `prefix` 字段——prefix 用于在比较时做 early-out 优化，前缀不符即可免追指针，从而规避 `strlen` 与空指针检查。List、Struct、Map、Union 等复杂类型则分别由 child vector 与元信息（如 `list_entry_t` 的 offset 与 length）组合而成。

压缩执行正建立在这些格式之上：字典向量与常量向量在解压后仍以压缩形态驻留内存，算子可直接在其上计算，省去完整解压的代价。

## 17.3 列式存储与压缩

### 17.3.1 Row Group 与列式布局

DuckDB 的数据文件采用列式存储，并按 Row Group（行组）做水平分区——这一概念等价于 Parquet 的 row group。同一列的数据在物理上连续存放，使分析查询只读取涉及的列，天然契合 OLAP 负载。

默认情况下，DuckDB 仅对持久化数据库做压缩，内存数据库不压缩；可用 `ATTACH ... (COMPRESS)` 为内存库开启压缩。Row Group 的大小可通过 `ATTACH` 选项指定：

```sql
ATTACH '/tmp/analytics.db' AS analytics (ROW_GROUP_SIZE 16384);
```

### 17.3.2 轻量压缩算法族

DuckDB 采用"轻量压缩（lightweight compression）"策略，追求压缩与解压/执行之间的低开销平衡，而非追求极限压缩率。可用的磁盘压缩算法包括：

- Constant Encoding（常量编码）
- RLE（游程编码）
- Bit Packing（位打包）
- Frame of Reference（FOR，偏移基准编码）
- Dictionary Encoding（字典编码）
- FSST（VLDB 2020 提出的字符串压缩）
- ALP（SIGMOD 2024 提出的自适应无损浮点压缩）
- Chimp（VLDB 2022 提出的浮点压缩）
- Patas（浮点压缩）
- Zstd（v1.2.0 引入的通用压缩）

具体选用哪种算法取决于存储版本（storage version），部分算法需显式设定存储版本才能启用。

### 17.3.3 存储文件头与版本兼容

数据文件以 `uint64_t` 校验和开头，随后是 4 个魔数字节 `DUCK`，再是 `uint64_t` 存储版本号。可用 `hexdump -n 20 -C file.db` 或 Python 的 `struct` 模块读取魔数与版本。

存储格式自 v0.10 起保证向后兼容（新版本能读旧版本写出的文件）；向前兼容（旧版本读新版本文件）仅"尽力而为（best effort）"。本书基线为 DuckDB v1.5.5，对应的存储版本号是 68；v1.0–v1.5 默认创建的是 storage version 64（即 v1.0.0 格式）。

### 17.3.4 磁盘占用经验值

压缩效果与数据类型、数据分布及所选压缩方法密切相关。经验上：约 100 GB 未压缩的 CSV 载入 DuckDB 后约需 25 GB 磁盘；约 100 GB 的 Parquet 载入后约需 120 GB（Parquet 本身已压缩，DuckDB 的列式布局在某些分布下反而需要更多空间）。这提醒我们：DuckDB 并不总比源文件小，压缩收益取决于数据特征。

## 17.4 查询优化器

DuckDB 的优化器对逻辑查询树运行下列优化：

### 17.4.1 Expression Rewriter

Expression Rewriter 简化表达式并做常量折叠（constant folding）——把能在编译期求值的部分直接算出结果，例如把 `1 + 2` 替换为 `3`，把 `WHERE year = 2020 + 1` 中的常量表达式提前求值，减少运行期重复计算。

### 17.4.2 Filter Pushdown（谓词下推）

Filter Pushdown 把过滤条件下推进计划树，并在等价集（equivalency sets）上复制过滤条件，使过滤尽早发生、减少上游算子处理的数据量。它还会剪掉那些"静态求值为 false"而必然为空的子树，直接从计划中删除无意义的扫描。

### 17.4.3 Join Order Optimizer

Join Order Optimizer 使用动态规划（dynamic programming）重排 join 顺序，具体采用论文《Dynamic Programming Strikes Back》中的 DPhyp 算法。多表 join 的排列组合随表数指数增长，DPhyp 通过动态规划在合理代价内寻找较优的连接顺序，对分析查询的多表关联尤为关键。

### 17.4.4 Common Sub Expressions

Common Sub Expressions（公共子表达式提取）从 projection 与 filter 节点中抽取公共子表达式，避免同一段计算在多处重复执行。这对含有重复复杂表达式的查询能显著降低开销。

### 17.4.5 In Clause Rewriter

In Clause Rewriter 把大的静态 `IN` 子句重写为 MARK join 或 INNER join。当 `IN` 列表很长时，这种改写让查询能走更高效的连接路径，而非逐元素比对。

## 17.5 事务与 MVCC、乐观并发

### 17.5.1 进程内模式下的两种并发选项

DuckDB 在进程内（in-process）模式下提供两类并发选项：读写模式（read-write）下一个进程可读可写；只读模式（read-only）下多个进程可同时读，但无人能写（通过 `access_mode='READ_ONLY'` 设定）。读写模式的核心由 MVCC（多版本并发控制）加乐观并发控制（optimistic concurrency control）支撑，支持多线程写入，但全部发生在单一写进程之内。

采用这种模型的动机是把数据缓存在 RAM 以加速分析查询，并缓存函数指针、catalog 等，使同一连接的后续查询更快。catalog 在进程内被缓存正是这一动机的直接体现。

### 17.5.2 单进程内的写并发规则

只要没有写冲突，多个并发写都会成功；append（追加插入）永不冲突，即便写入同一张表。多个线程可同时更新不同的表，或更新同一张表的不同子集。当两个线程试图同时编辑（update / delete）同一行时，乐观并发控制生效——第二个线程以冲突错误失败。常见冲突信息为 `Transaction conflict: cannot update a table that has been altered!`，标准应对是重跑（rerun）该事务。

这种乐观并发控制适合读密集的分析系统：大多数查询互不修改数据，冲突概率低；一旦发生写写冲突，以乐观失败告终并要求重试，比悲观锁的常驻开销更轻。

### 17.5.3 多进程写与文件锁

DuckDB 原生格式不支持多进程并发写。需要多进程写入时，须经 Quack 远程协议（把 DuckDB 变成客户端-服务器数据库，目前为 beta）或 DuckLake + PostgreSQL catalog（生产级稳定方案）。DuckDB 用文件锁处理并发访问请求，在网络存储或共享目录访问时需格外小心。

### 17.5.4 隔离级别

DuckDB 提供快照隔离（snapshot isolation），表现为 repeatable reads：一个事务在其生命周期内看到的是启动时刻的一致性快照，不受其他已提交事务干扰。

只读挂载的示例如下：

```sql
ATTACH 'shared.db' (ACCESS_MODE READ_ONLY);
```

## 17.6 ART 索引

DuckDB 使用 Adaptive Radix Tree（自适应基数树，ART）作为索引的原语数据结构，主要用于主键与等值查找等场景。其设计目标是在分析负载下保持低内存占用与高查找效率。

### 17.6.1 适用场景与单列限制

ART 索引有一个重要限制：只有单列查询才能走 index scan——复合条件或涉及多列的范围扫描无法利用 ART 索引。这与 B-Tree 的多列前缀命中不同，是 ART 在 DuckDB 中的适用边界。创建 ART 索引的语法与普通索引一致：

```sql
CREATE INDEX idx_orders_cust ON orders (o_custkey);
```

### 17.6.2 VACUUM 行为差异与实现参考

另一处与 PostgreSQL 的行为差异在于：在 DuckDB 中，VACUUM 会跳过带有 ART 索引的表，且不回收其空间。对建有 ART 索引的表执行 `VACUUM` 并不能像预期那样释放已删除数据占用的空间，这一点与 PostgreSQL 中 VACUUM 回收空间的行为不同，运维时须特别留意。

```sql
VACUUM;
```

关于 ART 的逐节点实现细节，本书所依据的官方 internals 文档未设独立章节，权威内容可参考《Design and Implementation of DuckDB Internals》（DiDi）库条目及对应源码（`src/storage` 等）。

## 17.7 本章小结

本章沿"一条 SQL 如何被执行"的主线拆解了 DuckDB 的内部机制，可归纳为四个相互支撑的支柱：

- **分层流水线**：Parser 仅做词法拆解、不感知 catalog 与类型；Binder 借 catalog 完成表/列/类型的语义绑定；Logical Planner 产出逻辑树，Optimizer 改写，Column Binding Resolver 把列名引用降级为 DataChunk 下标，Physical Plan Generator 产出物理算子树，最终由向量化执行引擎运行。
- **向量化执行**：推送式模型以 `STANDARD_VECTOR_SIZE = 2048` 行的 DataChunk 为批处理单位在算子间流动，相较 Volcano 的逐行 `next()` 显著降低虚调用开销、利于 SIMD；Flat / Constant / Dictionary / Sequence 等向量格式与 Unified Vector Format 共同支撑了"压缩执行"。
- **列式存储与轻量压缩**：数据按 Row Group 水平分区；磁盘上采用 Constant / RLE / Bit Packing / FOR / Dictionary / FSST / ALP / Chimp / Patas / Zstd 等低开销压缩；100 GB CSV 约落 25 GB，100 GB Parquet 约需 120 GB。
- **MVCC 与乐观并发**：进程内以 MVCC + 乐观并发支持多写线程，写写冲突以失败告终需重跑；多进程写须经 Quack 或 DuckLake；加上仅单列可走 index scan 的 ART 索引，共同构成 DuckDB 在进程内分析场景下的并发与索引图景。

掌握这些内部原理，有助于在实际调优时判断一条查询为何走某个计划、为何占用某等磁盘空间，以及并发写入应如何组织。
