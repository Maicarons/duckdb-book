# 第 14 章 关键扩展详解

DuckDB 的功能大多以扩展（extension）的形式交付：核心能力如 Parquet、JSON 读写，外部系统集成如 PostgreSQL、Delta Lake 挂载，乃至向量检索、全文搜索，都遵循"按需加载"的模型。这种拆分的益处是把不常用的依赖挡在默认二进制之外，让引擎保持轻量，也让各扩展能独立版本化演进。前文已交代过扩展的 `INSTALL`/`LOAD` 机制与自动加载（autoloading）规则，本章不再复述，而是把镜头对准几类最具代表性的扩展，逐一讲清它们是什么、能做什么、有哪些边界。其中 JSON 与 Spatial 属基础数据类型与函数族，Iceberg 是开放表格式接入的典型，其余常用扩展则覆盖了从本地文件到云存储、从关系数据库到向量检索的广阔场景。另需提醒，除随二进制发布的内置扩展外，所有可安装扩展的二进制都严格绑定具体的 DuckDB 版本与平台，升级引擎后须重新拉取匹配构建——这条铁律贯穿本章每个扩展的使用。

## 14.1 JSON 扩展

JSON 扩展是随 DuckDB 二进制一同发布的内置扩展（built-in extension），与 `parquet` 并列，开箱即用。它不经由扩展仓库下载，也无需执行 `INSTALL`/`LOAD`——尽管显式 `LOAD json;` 不会报错，只是多余。该扩展为 DuckDB 引入了原生的 JSON 类型（JSON type）以及一整套读写与构造函数，是处理接口返回、埋点日志、配置快照等半结构化数据的基石。第 6 章已系统讲解 `json_extract`/`json_extract_string` 与 `->`/`->>` 等取值函数，本节把重心放在类型本身与读入、构造两端。

**JSON 类型。** DuckDB 的 JSON 类型以半结构化方式承载 JSON 文本：它不强制 schema，也不在写入时严格校验内部结构，因此适合形态不固定的数据。当一个列声明为 `JSON` 时，DuckDB 不会尝试把它拆解成关系型列；需要结构化视图时，应经由 `read_json` 的自动推断或取值函数显式投影。换言之，JSON 类型回答的是"不规则数据如何落地"，而取结构是下游的事。与把 JSON 存成 `VARCHAR` 相比，JSON 类型在内部采用专为半结构化数据设计的存储布局，既保留对象层级，也让取值函数能直接在其上导航、省去文本解析开销；`VARCHAR` 只是原样保存字符串，每次访问都要重新解析。

**读取与自动推断。** `read_json` 与 `read_json_auto` 负责把 JSON 文件读入表。二者都支持 schema 自动推断（auto-detection），能依据样本记录揣测列名与类型；遇到嵌套（nested）结构时，可整体保留为 JSON 列，也可按路径下钻成标量列。line-delimited JSON（NDJSON，每行一条记录的 JSON 流）同样受支持，这使它天然契合日志与流式导出。

```sql
-- JSON 为内置扩展，直接使用，无需安装/加载
SELECT * FROM read_json('events.json', auto_detect = true) LIMIT 10;

-- 读取 NDJSON（每行一条 JSON 记录）
SELECT * FROM read_json_auto('logs.ndjson');
```

嵌套结构不会迫使你立即扁平化：可以把一整个子对象保留为 JSON 列，待真正需要某字段时再下钻。至于输入形态，`read_json` 与 `read_json_auto` 的差异在于后者在格式判定上更主动——它会探测输入是单个 JSON 数组还是 NDJSON 流、并据此选择读取策略；`read_json` 则更依赖调用方显式给出的选项。对列中出现的类型不一致，DuckDB 按兼容原则归并类型，必要时以 JSON 容纳异质值，从而让推断出的 schema 不至于因个别脏记录而整体失真。

**构造与序列化函数。** 与读取相对，扩展提供 `json_object`、`json_array` 现结构造对象与数组，并可用 `to_json`/`json_serialize` 把 DuckDB 的结构体（STRUCT）、列表（LIST）等类型序列化为 JSON 文本，便于回写外部系统。

```sql
-- 构造对象与数组
SELECT json_object('city', 'Beijing', 'coords', json_array(116.4, 39.9)) AS doc;

-- 把 STRUCT 序列化为 JSON
SELECT json_serialize(STRUCT('a', 1, 'b', 'x')) AS s;
```

`read_json` 的自动推断、json 类型的容纳能力，正是第 6 章那些取值函数得以灵活运作的底座：前者解决"如何读入"，后者解决"不规则数据如何落下"，取值函数则在其上解构访问。

## 14.2 Spatial

spatial 扩展提供地理空间（GIS）函数与类型，底层依赖 GEOS、PROJ、GDAL 三套外部系统库。由于这些库独立于 DuckDB 二进制、无法由 DuckDB 自行打包，spatial 不会被自动加载（autoload），每次会话都必须显式 `LOAD spatial;`。这是它与绝大多数 core 扩展最显眼的区别。这三套库各司其职：GEOS 提供几何算法与空间谓词（相交、包含、缓冲、距离等），PROJ 负责坐标参考系之间的投影变换，GDAL 则负责读写数十种矢量与栅格文件格式。也正因为它们是平台相关的原生库，spatial 不能像纯 SQL 扩展那样在首次使用时透明地从仓库拉取，只能由使用者显式加载。

**地理类型与版本演进。** 自 DuckDB v1.5 起，`GEOMETRY` 类型已成为内置类型——意味着即便不加载 spatial 扩展，表中也能创建并存储 `GEOMETRY` 列；但真正的几何运算（面积、距离、投影变换等）仍由 spatial 扩展提供。这种"类型内建、运算外置"的安排，让存储与计算的职责清晰分离：持久化一份几何数据不再强制要求 GIS 函数库在场。

**空间函数概览。** spatial 提供大量以 `ST_` 为前缀的标量函数，例如 `ST_Area`（面积）、`ST_AsText`（转 WKT 文本）、`ST_Buffer`（缓冲）、`ST_Distance`（距离）、`ST_Within`（包含关系）、`ST_Transform`（坐标参考系变换）等，另有若干聚合函数。实践上按 `ST_` 前缀检索即可定位所需函数。下列示例在创建几何列后做距离计算与面积测算：

```sql
LOAD spatial;

CREATE TABLE pois (name VARCHAR, geom GEOMETRY);
INSERT INTO pois VALUES
  ('Beijing', ST_Point(116.40, 39.90)),
  ('Shanghai', ST_Point(121.47, 31.23));

-- 以 WKT 形式输出，并计算到原点的距离
SELECT name,
       ST_AsText(geom) AS wkt,
       ST_Distance(geom, ST_Point(116.40, 39.90)) AS dist
FROM pois;

-- 缓冲区的面积（单位取决于坐标参考系）
SELECT ST_Area(ST_Buffer(ST_Point(0, 0), 1)) AS circle_area;

-- 判定某点是否落在另一个几何体内
SELECT ST_Within(ST_Point(116.40, 39.90), ST_Buffer(ST_Point(116.40, 39.90), 10)) AS inside;
```

坐标参考系（CRS）的换算由 PROJ 承担，`ST_Transform` 可在不同 CRS 间投影；涉及经纬度与投影平面距离的语义差异，务必在调用前确认数据所用参考系。`ST_` 前缀源自 OGC Simple Features 规范，与 PostGIS 等成熟 GIS 系统的命名一致，便于直接迁移既有查询知识；需要提醒的是，`ST_Distance` 在经纬度坐标下返回的数值并非真实地表距离，若需物理距离应先经 `ST_Transform` 投影到合适的平面参考系再计算。

**R-Tree 空间索引。** 为加速空间范围查询，可建 R-Tree 索引：

```sql
CREATE INDEX idx_pois ON pois USING RTREE (geom);
```

R-Tree 节点的默认容量为 `max_node_capacity = 128`；`rtree_index_dump` 可用于诊断索引结构。

**GDAL 集成。** 借助 GDAL，`ST_Read` 能读取数十种矢量与栅格格式，`COPY ... FORMAT gdal` 可将结果导出到 GDAL 支持的格式，从而把 DuckDB 接入既有的 GIS 工具链。

## 14.3 Iceberg 扩展

iceberg 扩展用于读取乃至写入 Apache Iceberg 表——一种面向大规模分析的开放表格式（open table format）。Iceberg 表以元数据文件（`metadata.json`）描述快照、schema 与分区，数据本身则是 Parquet 等列式文件。该扩展会在首次使用时自动加载（autoload）。

**两种访问模式。** 路径模式（path-based，只读）直接以 `iceberg_scan('path/to/metadata.json')` 读取本地或 S3 上的元数据文件，适合一次性探查；目录模式（catalog-based，读写）则通过 `ATTACH ... (TYPE iceberg, ENDPOINT_TYPE ...)` 接入 Iceberg REST Catalog 后读写。可接入的目录后端包括 Amazon S3 Tables、AWS Glue / SageMaker Lakehouse、Cloudflare R2、Polaris、Lakekeeper、BigLake 等。需要牢记：路径模式只读，写入必须经已附加的 REST Catalog。

```sql
INSTALL iceberg;
LOAD iceberg;

-- 路径模式只读探查
SELECT * FROM iceberg_scan('s3://bucket/warehouse/table/metadata/v3.metadata.json') LIMIT 5;

-- 目录模式读写（以 Polaris 为例）
ATTACH 'catalog' AS iceberg_cat (TYPE iceberg, ENDPOINT_TYPE polaris, ...);

-- 常用元数据探查函数
SELECT * FROM iceberg_snapshots('s3://bucket/warehouse/table/metadata/v3.metadata.json');
SELECT * FROM iceberg_metadata('s3://bucket/warehouse/table/metadata/v3.metadata.json');
```

**V3 spec 支持。** v1.5.5 的 iceberg 扩展支持 Iceberg V3 spec，涵盖 `VARIANT` 类型、`TIMESTAMP_NS`（纳秒级时间戳）、列默认值（default values）以及 binary deletion vectors（二进制删除向量）。这让 DuckDB 能无损读写采用最新规范的 Iceberg 表。分区变换（partition transforms）支持 `identity`、`year/month/day/hour`、`bucket(n, col)`、`truncate(n, col)`，可通过 `PARTITIONED BY (...)` 建表、`ALTER TABLE ... SET PARTITIONED BY (...)` 改分区。

从使用者视角，Iceberg 的价值在于快照（snapshot）隔离：每张表在任意时刻都对应一个快照，历史快照被保留，`iceberg_snapshots` 能列出它们，从而支持时间旅行（time travel）——回到过去某个一致性视图读取数据。这也是开放表格式相比直接堆 Parquet 文件的关键优势：元数据层统一管理 schema、分区与快照演进，读端无需关心文件层面的物理布局。

**写入限制。** 写入能力虽已具备，但约束明确：

- 仅支持 positional delete（位置删除）文件，不支持 copy-on-write（写时复制）删除；
- 仅采用 merge-on-read（读时合并）语义；若目标表将 `write.update.mode` / `write.delete.mode` 设为非 merge-on-read，写入会失败；
- 只能作用于非排序（non-sorted）表。

此外，分区表的 `write.target-file-size-bytes` 与 `write.parquet.row-group-size-bytes` 不被遵守（会报错），除非显式设置 `ignore_target_file_size_for_partitioned_tables` / `ignore_row_group_size_for_partitioned_tables`。`GEOGRAPHY` 与 `UNKNOWN` 类型计划于扩展 v2.0.0 支持。表属性可用 `iceberg_table_properties` / `set_iceberg_table_properties` / `remove_iceberg_table_properties` 查看与改写；跨格式迁移则可经 `iceberg_to_ducklake(...)` 把 Iceberg catalog 复制进 DuckLake。

在允许的约束内，扩展支持较完整的 DML：建 schema/表、`INSERT`、`UPDATE`、`DELETE`、`MERGE INTO`、以及 `ALTER TABLE`（加列、删列、改名、改类型）均可执行；`COPY FROM DATABASE duckdb_db TO my_catalog` 与反向复制可做整库深拷贝。需要认清的是，这些能力都建立在前面列出的 positional delete + merge-on-read + 非排序表这三项限制之上，超出范围的写入会直接报错而非静默降级。

## 14.4 其他常用扩展

**sqlite。** 把 SQLite 数据库文件作为外部 catalog 附加后直接读写，autoload 为是，别名 `sqlite_scanner` / `sqlite3`。

```sql
INSTALL sqlite;
LOAD sqlite;
ATTACH 'file.db' AS my_sqlite (TYPE sqlite);
SELECT * FROM my_sqlite.main.table1;
```

类型亲和（type affinity）规则将 SQLite 的存储类 `INTEGER`/`REAL`/`TEXT`/`BLOB`/`NULL` 映射到 DuckDB 类型；选项 `sqlite_all_varchar` 可把所有列读成 `VARCHAR` 以对抗脏数据。该扩展与 Turso（libSQL）文件兼容。附加后可像普通 catalog 一样读写，改动回写到原文件；也可只读挂载以作探查，使其成为 DuckDB 与既有 SQLite 应用之间的双向桥接。

**excel。** 读写 Excel `.xlsx` 文件，autoload 为是。`read_xlsx` 负责读取，`COPY ... TO 'out.xlsx' (FORMAT xlsx)` 负责写出。

```sql
INSTALL excel;
LOAD excel;
SELECT * FROM read_xlsx('report.xlsx');
COPY (SELECT * FROM t) TO 'out.xlsx' (FORMAT xlsx);
```

限制：仅支持 `.xlsx`（Office Open XML），旧的二进制 `.xls` 格式不被支持。常见用途是把业务导出的报表直接入库，或把查询结果回写供非技术同事用 Excel 打开；多工作表场景下需逐表指定后再合并。

**aws。** AWS 凭据与服务的 Secrets Manager 集成（覆盖 S3、Glue、S3 Tables、RDS 等），autoload 为是。`credential_chain` 支持 `config`、`env`、`sts`、`sso`、`instance`、`process`、`web_identity` 多种 provider；新增的 `rds` secret type 支持 AWS RDS IAM 认证，临时凭据还能在过期前自动刷新（auto-refresh）。对临时凭据而言，自动刷新意味着长任务无需手动续期 IAM 令牌；配合 `credential_chain` 的 `sts` / `assume_role` 还能实现跨账号访问，是生产环境访问 S3 数据湖的常见路径。

```sql
INSTALL aws;
LOAD aws;
CREATE SECRET (TYPE s3, PROVIDER credential_chain, CHAIN config,sts, REGION 'us-east-1');
```

**azure。** 访问 Azure Blob Storage 与 Data Lake Storage（ADLS），autoload 为是；协议 scheme 含 `az` / `azure` / `abfss`。凭据 provider 有 `CONFIG`、`credential_chain`、`managed_identity`、`service_principal`。当数据落在 ADLS Gen2 时，递归通配（`/**`）能一次扫描整个目录树；而 Blob 存储的 glob 更偏向单层级匹配，混用时需留意语义差异，避免漏读或多读。

```sql
INSTALL azure;
LOAD azure;
SELECT * FROM 'az://container/path/file.parquet';
```

**delta。** 读取 Delta Lake 表（基于 delta-kernel-rs），autoload 为是。可通过 `delta_scan('path')` 或 `ATTACH ... (TYPE delta)` 接入，并支持 time travel：`SELECT * FROM tbl AT (VERSION => n)` 或按时间戳回溯。

```sql
INSTALL delta;
LOAD delta;
SELECT * FROM delta_scan('s3://bucket/delta-table') AT (VERSION => 3);
```

限制：平台仅含 Linux / macOS / Windows 的 AMD64（`linux_amd64` 与 `linux_arm64` 也支持），无 `windows_arm64`。time travel 让数据回滚与审计变得直接；由于 Unity Catalog 扩展构建于 delta 之上，二者共享底层读取能力，理解 delta 即理解了 Unity Catalog 的读取底座。

**ducklake。** DuckLake 是 DuckDB 原生的湖仓（lakehouse）格式，元数据与数据分离存储，autoload 为是。

```sql
INSTALL ducklake;
LOAD ducklake;
ATTACH 'ducklake:metadata.ducklake' AS my_ducklake (DATA_PATH 's3://bucket/data');
```

版本事实：DuckLake 1.0 于 2026 年 4 月发布。其与 Iceberg 互通，可经 `iceberg_to_ducklake(...)` 把 Iceberg catalog 迁移或复制到 DuckLake。元数据与数据分离意味着 catalog 信息（schema、表、快照）与真实数据文件可置于不同存储后端（例如元数据留在本地、数据落在 S3），便于权限与生命周期分别治理。

**vss（向量相似度搜索）。** vss 基于 HNSW 索引提供向量相似度搜索，目前为实验性（experimental）。

```sql
INSTALL vss;
LOAD vss;
CREATE INDEX idx_vec ON vec_tbl USING HNSW (vec);
SELECT * FROM vss_match('vec_tbl', 'vec', [0.1, 0.2, 0.3]);
```

距离度量（metrics）有 `l2sq`（欧氏平方）、`cosine`（余弦）、`ip`（内积）；配套函数 `vss_join`、`vss_match`。限制：仅支持 `FLOAT` 向量，不支持其他数值类型；索引持久化仍属实验特性（开关 `hnsw_enable_experimental_persistence`）。HNSW（Hierarchical Navigable Small World）是一种近似最近邻（ANN）索引，查询时不保证全局最优但速度远快于暴力扫描；开启持久化后索引可落盘复用，但该能力目前仍标记为实验。

## 14.5 本章小结

- JSON 与 parquet 为内置扩展，随二进制发布、开箱即用；JSON 类型承载不规则数据，`read_json` 负责读入与 schema 自动推断，构造函数则把 DuckDB 结构回写为 JSON。
- spatial 因依赖 GEOS / PROJ / GDAL 外部系统库而必须显式 `LOAD`；`GEOMETRY` 类型自 v1.5 内建、运算由扩展提供，R-Tree 索引与 GDAL 集成进一步扩展了空间能力。
- iceberg 支持路径与目录两种模式，v1.5.5 兼容 V3 spec（VARIANT、TIMESTAMP_NS、默认值、binary deletion vectors），但写入仅限 positional delete + merge-on-read 且作用于非排序表，`GEOGRAPHY`/`UNKNOWN` 待 v2.0.0。
- sqlite、excel、aws、azure、delta、ducklake、vss 等扩展覆盖了从本地文件到云存储、从关系数据库到向量检索的常见场景，各自有 autoload 行为与平台/格式限制；使用前应核对扩展与 DuckDB 版本的强绑定关系，跨版本升级时以 `FORCE INSTALL` 重新拉取匹配构建。
