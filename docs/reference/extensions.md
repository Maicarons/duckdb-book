# DuckDB 扩展体系（Extensions）研究摘要

> 目标版本：DuckDB **1.5.5**
> 资料来源：`duckdb-web-main/docs/current/extensions/` 与 `duckdb-web-main/docs/current/core_extensions/` 下全部 65 个 `.md` 文件。
> 说明：忽略所有 Jekyll frontmatter（`--- ... ---`）与 Liquid 标签（`{% ... %}`），仅提取真实内容。技术术语保留英文。

---

## 目录

1. [扩展体系架构](#1-扩展体系架构)
2. [INSTALL / LOAD / DROP 语法与行为](#2-install--load--drop-语法与行为)
3. [Core Extensions 详解](#3-core-extensions-详解)
4. [社区扩展（Community Extensions）概览](#4-社区扩展community-extensions概览)
5. [版本相关事实（Version-Specific Facts）](#5-版本相关事实version-specific-facts)

---

## 1. 扩展体系架构

### 1.1 内置扩展 vs 可安装扩展

- DuckDB 把功能分成**内置扩展（build-in / statically linked）**和**可安装扩展（installable / dynamically loaded）**两类。
- 少数扩展被**静态链接**进二进制，无法在运行时安装/加载/卸载（例如 `jemalloc`，见 §3.23）。
- **内置到核心、开箱即用**的数据格式扩展：`parquet`（Parquet 读写）、`json`（JSON 读写）。它们不是通过仓库下载，而是随二进制一起发布，因此也无需 `INSTALL`/`LOAD`（尽管显式 `LOAD` 也不会报错）。
- 其余扩展默认不随二进制发布，需要 `INSTALL`（下载 + 校验 + 存储）与 `LOAD`（动态加载进当前实例）。

### 1.2 列出已安装/可用扩展

- `duckdb_extensions()` 表函数返回当前环境可用的扩展信息（名称、状态、安装/加载状态、版本、仓库等）。
- `duckdb_extensions()` 可用于排查某个扩展是否已 autoload、是否已加载。

### 1.3 自动加载（Autoloading）

- 多数 **core extension** 支持 **autoloading**：首次使用时，DuckDB 会从官方仓库**透明地下载并加载**（需联网），无需手动 `INSTALL`/`LOAD`。
- 文档中明确标注“会被 autoload”的包括：`fts`、`icu`、`inet`、`tpcds`、`tpch`（部分构建内置）、`motherduck`（autoinstall + autoload）、`quack`（autoinstall + autoload，实验性）、`sqlite`、`excel`、`aws`、`azure`、`delta`、`ducklake` 等。
- **不会**被 autoload 的扩展（必须手动 `LOAD`）包括：`spatial`、`odbc`（因为它们依赖外部系统库，例如 `spatial` 依赖 GEOS/PROJ/GDAL，`odbc` 依赖 unixODBC/ODBC Driver Manager）。
- 一旦用户显式 `INSTALL`，之后即使重启，扩展通常已在本地缓存，autoload 不会再触发网络下载。

### 1.4 扩展仓库（Extension Repositories）

`INSTALL` 时通过 `FROM <repository>` 指定仓库来源，默认是 `core`。可用仓库别名：

| 别名（alias） | 含义 / URL |
|---|---|
| `core` | 官方稳定仓库，URL `http://extensions.duckdb.org`（默认） |
| `core_nightly` | 每夜构建仓库，URL `http://nightly-extensions.duckdb.org` |
| `community` | 社区扩展仓库，URL `http://community-extensions.duckdb.org` |
| `local_build_debug` | 本地调试构建 |
| `local_build_release` | 本地发布构建 |

示例：

```sql
INSTALL tarfs FROM community;
INSTALL iceberg FROM core_nightly;
```

### 1.5 安装位置与配置

- 扩展默认安装到用户目录：`~/.duckdb/extensions/<duckdb_version>/<platform_name>/`。
- 可通过配置项自定义：
  - `extension_directory`：单个自定义目录。
  - `extension_directories`：以平台分隔符分隔的多个目录列表（多个搜索路径）。
- **没有 `UNINSTALL` 命令**：要“移除”一个扩展只能手动删除其文件。

### 1.6 版本管理与兼容性（关键规则）

- 扩展二进制**与特定的 DuckDB 版本以及平台（platform）严格绑定**。版本或平台不匹配会被拒绝加载。
- 仓库中扩展按 `Target DuckDB Version` 组织目录，例如 `v1.5.5/linux_amd64/`。
- 稳定性分级（stability levels）：
  - **unstable**：基于 git hash，随每次提交变化，主要用于 `core_nightly`。
  - **pre-release**：形如 `v0.y.z`（主版本仍为 0），可能不稳定。
  - **stable**：形如 `vx.y.z`（`x > 0`）。官方 `core` 仓库发布的扩展通常带 stable 版本号。
- **in-tree（树内）vs out-of-tree（树外）**：
  - **in-tree** 扩展位于 DuckDB 主仓库（`duckdb/duckdb`）中，随主仓库一起版本化、构建与发布（如 `httpfs`、`parquet`、`json`、`postgres`、`iceberg`、`spatial` 等 core extensions）。
  - **out-of-tree** 扩展位于独立仓库（通常以 `duckdb-<name>` 命名，如 `duckdb/duckdb-avro`、`duckdb/duckdb-mysql`、`duckdb/duckdb-fts`），独立版本化。
- **版本兼容性铁律（version-compatibility rule）**：扩展的二进制是针对**某一个具体 DuckDB 版本**和**某一平台**编译的。用错版本（例如用 1.4.0 的扩展去配 1.5.5 的 DuckDB）或错平台（例如 `linux_amd64` 的扩展运行在 `osx_arm64`）会被拒绝。因此升级 DuckDB 后，一般需要用 `FORCE INSTALL` 重新拉取匹配新版本的扩展。

### 1.7 签名（Signed）与未签名（Unsigned）

- 官方仓库（`core`、`community` 等）发布的扩展是**已签名**的，DuckDB 会校验签名。
- 第三方/本地构建的扩展可能**未签名**。加载未签名扩展需要显式开启：
  - 配置：`SET allow_unsigned_extensions = true;`
  - 或启动参数：`-unsigned`。
- 注意：部分功能（如 `ui` 扩展的 `ui_remote_url` 自定义远程地址）只有在 `allow_unsigned_extensions` 开启时才被尊重，因为远程 UI 资源可访问本地数据。

### 1.8 高级安装方法（Advanced Installation Methods）

- **直接按 URL 安装**：可指向 S3/HTTP 上的 `duckdb_extension` 文件，格式类似：
  ```sql
  INSTALL 'http://example.com/path/to/extension.duckdb_extension';
  LOAD 'http://example.com/path/to/extension.duckdb_extension';
  ```
- **从本地文件安装/加载**：
  ```sql
  INSTALL 'path/to/ext.duckdb_extension';
  LOAD 'path/to/ext.duckdb_extension';
  ```
  这在离线环境、CI、或加载自己编译的扩展时很有用。

### 1.9 FORCE INSTALL（强制重装）

- 默认 `INSTALL` 若发现本地已有所需版本则跳过。
- `FORCE INSTALL` 会**忽略本地缓存、重新下载**（例如升级 DuckDB 后拉取匹配版本，或从 `core` 切回 `community`/夜晚版时）：
  ```sql
  FORCE INSTALL httpfs;
  FORCE INSTALL iceberg FROM core_nightly;
  ```
- 也可用于切换仓库来源（例如先用 `community`，再 `FORCE INSTALL ... FROM core` 切回官方仓库）。

### 1.10 更新与局限

- `UPDATE EXTENSIONS;` 语句可尝试更新所有已安装扩展（按当前 DuckDB 版本和仓库）。
- **重要局限**：
  - 已加载的扩展**无法卸载（unload）或重新加载（reload）**——一旦 `LOAD`，在当前进程生命周期内一直存在。
  - 没有 `UNINSTALL` 命令。
  - 扩展与 DuckDB 版本强绑定，跨大版本升级时务必重新 `INSTALL`（建议 `FORCE INSTALL`）。
- 故障排查（troubleshooting）：
  - 若出现 404，通常是版本/平台不匹配或仓库里没有该平台构建；可手动用浏览器下载对应 `duckdb_version`/`platform` 下的文件再 `LOAD '...'`。
  - 网络受限环境用本地文件或 `extension_directories` 指向预下载目录。

---

## 2. INSTALL / LOAD / DROP 语法与行为

### 2.1 INSTALL

```sql
INSTALL <extension_name>;
INSTALL <extension_name> FROM <repository>;
INSTALL '<url_or_path>';          -- 直接 URL 或本地路径
FORCE INSTALL <extension_name>;   -- 忽略缓存，重新下载
```

- 作用：从仓库下载扩展二进制、校验签名、存入本地扩展目录。**仅安装不会把它加载进当前实例**。
- 不指定 `FROM` 时默认仓库是 `core`。
- `FORCE` 用于重装/换源/升级。

### 2.2 LOAD

```sql
LOAD <extension_name>;
LOAD '<url_or_path>';             -- 直接加载网络或本地文件
```

- 作用：把已安装的扩展**动态加载**到当前 DuckDB 实例，使其函数/类型/表函数/索引方法等生效。
- 对于 autoload 的扩展，首次使用时自动 `LOAD`，不必手动。
- 对于 `spatial`、`odbc` 等非 autoload 扩展，必须显式 `LOAD`。
- `LOAD` 之后无法在当前进程内卸载。

### 2.3 DROP EXTENSION（/ 删除扩展状态）

- 文档未提供“卸载已加载扩展”的语句（扩展不可 unload）。
- `DROP EXTENSION` 在部分文档语境中用于移除扩展创建的对象（如索引、宏），并非卸载扩展本身。
- 真正“移除”扩展 = 删除 `~/.duckdb/extensions/...` 下的文件，且无 `UNINSTALL` 命令。

### 2.4 与 ATTACH 的关系

- 很多扩展（postgres、sqlite、mysql、delta、iceberg、ducklake、unity_catalog、lance、motherduck）通过 `ATTACH ... (TYPE <ext>)` 把外部系统作为“附加数据库（catalog）”暴露给 DuckDB，从而可用标准 SQL 读写外部表。
- 这类扩展通常先 `LOAD`（或 autoload），再 `ATTACH`。`ATTACH` 时可用 `SECRET` 参数引用 Secrets Manager 中存的连接凭据。

---

## 3. Core Extensions 详解

> 共 28 个 core extensions（见 `core_extensions/overview.md`）。维护方（Maintainer）与支持层级（Support tier）：
> - **Primary**：`httpfs`、`icu`、`json`、`parquet`
> - **Secondary**：其余官方维护扩展
> - **Third-party（第三方）**：`lance`、`motherduck`、`ui`、`vortex`
>
> 别名（aliases）：`httpfs`→`http`/`https`/`s3`；`postgres`→`postgres_scanner`；`odbc`→`odbc_scanner`；`sqlite`→`sqlite_scanner`/`sqlite3`；`mysql`→`mysql_scanner`；`unity_catalog`→`uc_catalog`；`motherduck`→`md`。

---

### 3.1 httpfs（HTTP / S3 / R2 / GCS / Hugging Face 文件系统）

**用途**：让 DuckDB 能从 HTTP(S)、S3、Cloudflare R2、Google Cloud Storage、Hugging Face 等远程对象存储读取（以及写入）文件。

- **autoload**：是。首次访问 `s3://`、`https://`、`hf://` 等会触发 autoload。
- 别名包含 `http`/`https`/`s3`，所以 `LOAD httpfs;`、`LOAD s3;` 等价。

#### S3 配置与凭据（s3api）

- 提供 `s3` secret，常见参数：`KEY_ID`、`SECRET`、`REGION`、`ENDPOINT`、`SESSION_TOKEN`、`ENDPOINT_URL`、`URL_STYLE`（`path` 或 `vhost`）、`USE_SSL` 等。
- **credential_chain provider**：支持链式的凭据提供者，包括：
  - `config`（~/.aws/credentials）
  - `env`（环境变量）
  - `sts` / `assume_role`（STS 临时凭据、跨账号 AssumeRole）
  - `sso`（AWS SSO）
  - `instance`（EC2/ECS 实例元数据）
  - `process`（外部进程凭据）
  - `web_identity`（Web Identity / OIDC）
- 例：
  ```sql
  CREATE SECRET (
      TYPE s3,
      PROVIDER credential_chain,
      CHAIN config,sts,
      ASSUME_ROLE_ARN 'arn:aws:iam::123456789012:role/my-role',
      REGION 'us-east-1'
  );
  ```
- R2 / GCS：通过 `ENDPOINT` + `URL_STYLE='path'` 或相应厂商端点配置；例如 R2 用 `endpoint 'https://<acctid>.r2.cloudflarestorage.com'`，GCS 用 `endpoint 'https://storage.googleapis.com'`（注意 GCS 的 region 处理差异）。

#### 写入（multipart upload）

- 通过 S3 的分块上传（multipart upload）写入大文件，相关调优参数：
  - `s3_uploader_max_parts_per_file`：默认 **10000**
  - `s3_uploader_max_filesize`：默认 **800 GB**
  - `s3_uploader_thread_limit`：默认 **50**
- `s3_version_id_pinning`：可固定读取某个 S3 对象版本（version id pinning），便于可重复读取。

#### Legacy 认证

- `s3api_legacy_authentication.md` 记录老的 `s3_region`、`s3_access_key_id` 等旧的会话级配置方式，现已建议改用 Secrets Manager。

#### HTTPS（https.md）

- `http` secret 支持：`BEARER_TOKEN`（Bearer 认证）、`EXTRA_HTTP_HEADERS`（自定义请求头）。
- 支持代理（proxy）与自定义 CA 证书（custom certificate）。

#### Hugging Face（hugging_face.md）

- 通过 `hf://` 协议读取 Hugging Face 数据集/文件，例如：
  ```sql
  SELECT * FROM 'hf://datasets/.../data.parquet' LIMIT 10;
  ```
- 可用 HF token secret 访问私有仓库。

---

### 3.2 parquet（内置）

- **内置**扩展，开箱即用，无需 `INSTALL`/`LOAD`。
- 提供 `read_parquet`、`COPY ... TO 'x.parquet'`、以及 `parquet_metadata`/`parquet_schema`/`parquet_file_metadata` 等函数。
- 支持 filter/project pushdown、并行读取、Hive 分区、多文件 glob、S3/HTTP 直读。

### 3.3 json（内置）

- **内置**扩展，开箱即用。
- 提供 `read_json`、`read_json_auto`、`json`/`json_extract` 系列函数、`to_json`/`json_serialize`、`json_object`/`json_array` 等。
- 支持自动推断 schema、嵌套 JSON、line-delimited JSON（NDJSON）。

---

### 3.4 postgres

**用途**：把运行中的 PostgreSQL 数据库作为外部 catalog 附加到 DuckDB，直接读取/写入 PostgreSQL 表。

- autoload：首次使用相关函数/`ATTACH` 时触发。
- 别名：`postgres_scanner`。

#### 连接与 ATTACH

```sql
ATTACH '' AS postgres_db (TYPE postgres);
-- 早期写法 postgres_attach(...) 已废弃，推荐用 ATTACH
```

- 凭据可用 `TYPE postgres` secret 存储（支持 AWS RDS IAM 认证；secret 可存入 PostgreSQL 的 `duckdb_secrets` 表实现跨会话持久化）。
- 相关设置（settings）表：控制 pushdown、事务、类型映射等。

#### 关键函数

- `postgres_query(attached_db, query)`：在 PostgreSQL 侧执行只读查询，结果返回 DuckDB。
- `postgres_execute(attached_db, query)`：在 PostgreSQL 侧执行任意语句（含 DDL/DML）。
- `postgres_clear_cache()`：清除 schema 缓存（当外部 schema 变化后）。

#### 连接池（connection_pool）

- 通过连接池复用 PostgreSQL 连接；可配置池大小、空闲超时、最大存活时间、获取模式（`force`/`wait`/`try`）、reaper 线程、线程本地缓存等。

#### **版本相关事实（v1.5.5）**

- v1.5.5 新增**自动检测 schema 变化**：设置 `pg_staleness_query_enabled`（BOOLEAN，默认 `FALSE`）。启用后，DuckDB 可通过周期性查询判断缓存的 PostgreSQL schema 是否过期，从而自动失效（来自 `duckdb/duckdb-postgres#514`）。默认关闭以保持向后兼容。

---

### 3.5 iceberg

**用途**：读取（及部分写入）Apache Iceberg 表。两种访问模式：
1. **Path-based（只读）**：`iceberg_scan('path/to/metadata.json')` 直接读本地/S3 上的 Iceberg 元数据文件。
2. **Catalog-based（读写）**：`ATTACH ... (TYPE iceberg, ENDPOINT_TYPE ...)` 连接 Iceberg REST Catalog 后进行读写。

- autoload：是（首次访问 Iceberg 相关函数时）。

#### 关键函数

- `iceberg_scan(metadata_file)`：按 metadata 文件读取快照。
- `iceberg_metadata('table_or_metadata')`：读取表元数据。
- `iceberg_snapshots('table_or_metadata')`：列出快照。
- `iceberg_table_properties` / `set_iceberg_table_properties` / `remove_iceberg_table_properties`：表属性查看/设置/删除。
- `iceberg_to_ducklake(...)`：把 Iceberg catalog 迁移/复制到 DuckLake（互操作）。

#### 选项（iceberg_options）

- `format-version`：可指定 2 或 3。
- 分区变换（partition transforms）：`identity`、`year/month/day/hour`、`bucket(n, col)`、`truncate(n, col)`。
- `PARTITIONED BY (...)` 建表，`ALTER TABLE ... SET PARTITIONED BY (...)` 改分区。

#### REST Catalogs（iceberg_rest_catalogs）

- 通过 `ATTACH` 选项接入 Iceberg REST Catalog，支持兼容性标志（compatibility flags）。
- 支持的 catalog 后端（`catalogs.md`）：
  - **S3 Tables**（Amazon S3 Tables，实验性）：`ENDPOINT_TYPE s3_tables`
  - **AWS Glue / SageMaker Lakehouse**（实验性）：`ENDPOINT_TYPE glue`
  - **Cloudflare R2**
  - **Polaris**（Apache Polaris）
  - **Lakekeeper**
  - **BigLake**（Google Biglake）
- 写入必须通过已附加的 REST catalog；path-based `iceberg_scan` 只读。

#### 写入（writing / writing_to_iceberg）

- 创建 schema/table、INSERT、UPDATE、DELETE、MERGE INTO、ALTER TABLE（加/删/改名/改类型列）均支持。
- `COPY FROM DATABASE duckdb_db TO my_catalog` 与反向复制可做深度拷贝。
- **V3 spec 支持**（v1.5.5）：支持 `VARIANT`、`TIMESTAMP_NS`、默认值（default values）、binary deletion vectors。
- **UPDATE/DELETE 限制**：
  - 只支持 **positional delete** 文件，**不支持 copy-on-write**。
  - 只支持 **merge-on-read** 语义；若表把 `write.update.mode` / `write.delete.mode` 设为非 `merge-on-read` 则失败。
  - 只能作用于**非排序（non-sorted）**表。
- 分区表的 `write.target-file-size-bytes` 与 `write.parquet.row-group-size-bytes` 不被遵守（会报错，除非设置 `ignore_target_file_size_for_partitioned_tables` / `ignore_row_group_size_for_partitioned_tables`）。
- `GEOGRAPHY` / `UNKNOWN` 类型计划于 **v2.0.0** 支持。

---

### 3.6 spatial

**用途**：地理空间（GIS）函数与类型，基于 GEOS、PROJ、GDAL。

- **autoload：否**——必须显式 `LOAD spatial;`（因为依赖外部系统库，无法 autoload）。
- `functions.md` 提供大量 `ST_*` 标量函数（如 `ST_Area`、`ST_AsText`、`ST_Buffer`、`ST_Distance`、`ST_Within`、`ST_Transform` 等）与若干聚合函数。
  - 注：该文件输出很大（函数清单完整），实际使用时按 `ST_` 前缀查找即可。
- **GDAL 集成（gdal.md）**：`ST_Read(...)` 读取数十种矢量/栅格格式；`COPY ... FORMAT gdal` 导出到 GDAL 支持的格式。

#### R-Tree 空间索引（r-tree_indexes）

- 可建 R-Tree 索引加速空间查询：
  ```sql
  CREATE INDEX idx ON tbl USING RTREE (geom);
  ```
- 参数 `max_node_capacity`：默认 **128**。
- 诊断：`rtree_index_dump(...)` 查看索引结构。

---

### 3.7 odbc

**用途**：通过 ODBC 驱动访问任意支持 ODBC 的 DBMS（SQL Server、Oracle、MySQL、Access 等）。

- **autoload：否**——必须显式 `LOAD odbc;`。
- Linux/macOS 需系统安装 **unixODBC**（ODBC Driver Manager）；Windows 用系统 ODBC。
- **版本无关 C API（nightly 版）**：nightly 构建使用与版本无关的 ODBC C API，**同一二进制可用于 1.2.0 及以后所有版本**（这是 odbc 扩展相对早期仅匹配单版本的改进，降低重装负担）。
- DBMS 类型分层（tiers）：不同数据库的能力/类型映射分三档支持度。

#### 关键函数（functions.md）

- `odbc_connect(connection_string)`：建立连接返回连接句柄。
- `odbc_query(handle, query)`：执行查询返回表。
- `odbc_copy(handle, query, table)`：把查询结果写入 DuckDB 表。
- `odbc_close(handle)`：关闭连接。
- `odbc_begin_transaction(handle)` / `odbc_commit(handle)` / `odbc_rollback(handle)`：事务控制。
- `odbc_create_params(...)` / `odbc_bind_params(...)`：参数化查询。
- `odbc_list_drivers()` / `odbc_list_data_sources()`：列出系统已配置驱动与数据源。

---

### 3.8 sqlite

**用途**：把 SQLite 数据库文件作为外部 catalog 附加，直接读写。

- autoload：是。别名 `sqlite_scanner` / `sqlite3`。
- 用法：
  ```sql
  ATTACH 'file.db' AS my_sqlite (TYPE sqlite);
  ```
- **类型亲和（type affinity）规则**：SQLite 的存储类（INTEGER/REAL/TEXT/BLOB/NULL）映射到 DuckDB 类型；提供 `sqlite_all_varchar` 选项把所有列读成 `VARCHAR`（应对脏数据）。
- **Turso 兼容**：可与 Turso（libSQL）数据库文件配合。

---

### 3.9 excel

**用途**：读写 Excel（`.xlsx`）文件。

- autoload：是。
- 读取：`excel_text` / `text`（把单元格文本读出）、`read_xlsx(...)`。
- 写入：`COPY ... TO 'out.xlsx' (FORMAT xlsx)`。
- **限制**：`.xls`（旧版二进制格式）**不支持**，仅支持 `.xlsx`（Office Open XML）。

---

### 3.10 aws

**用途**：AWS 凭据与服务的 Secrets Manager 集成（S3、Glue、S3 Tables、RDS 等）。

- autoload：是。
- `credential_chain` 提供多种 provider：`config`、`env`、`sts`、`sso`、`instance`、`process`、`web_identity`（详见 §3.1）。
- 新增 **rds secret type**：支持 **AWS RDS IAM 认证**（用 IAM 令牌连接 RDS/PostgreSQL/MySQL）。
- 凭据**自动刷新**（auto-refresh）：临时凭据过期前自动续期。

---

### 3.11 azure

**用途**：Azure Blob Storage / Data Lake Storage（ADLS）访问。

- autoload：是。
- 支持协议 scheme：`az` / `azure` / `abfss`。
- 凭据 provider：`CONFIG`、`credential_chain`、`managed_identity`、`service_principal`。
- **Blob vs ADLS globbing**：ADLS Gen2 支持递归通配（`/**`），Blob 的 glob 语义略有差异，文档给出注意点。

---

### 3.12 delta

**用途**：读取 Delta Lake 表（基于 delta-kernel-rs）。

- autoload：是。
- 读取：`delta_scan('path')`；`ATTACH ... (TYPE delta)`。
- **Time travel**：`SELECT * FROM tbl AT (VERSION => n)` 或按时间戳。
- 平台：仅 **Linux/macOS/Windows 的 AMD64**（`linux_amd64`、`linux_arm64` 也支持）。
- 辅助函数：`delta_list_files`、`delta_set_transaction_version`。
- 注：`unity_catalog`（见 §3.27）构建在 `delta` 之上。

---

### 3.13 ducklake

**用途**：DuckLake——DuckDB 原生的湖仓（lakehouse）格式，元数据与数据分离存储。

- autoload：是。
- 用法：
  ```sql
  ATTACH 'ducklake:metadata.ducklake' AS my_ducklake (DATA_PATH 's3://bucket/data');
  ```
- 提供 `ducklake_*` 系列函数（管理快照、表、schema 等）。
- **版本相关事实**：**DuckLake 1.0 于 2026 年 4 月发布**。
- 与 Iceberg 互操作：`iceberg_to_ducklake(...)`。

---

### 3.14 vss（Vector Similarity Search，实验性）

**用途**：向量相似度搜索，基于 HNSW 索引。

- 实验性（experimental）。
- 建索引：
  ```sql
  CREATE INDEX idx ON vec_tbl USING HNSW (vec);
  ```
- 距离度量（metrics）：`l2sq`（欧氏平方）、`cosine`（余弦）、`ip`（内积）。
- 相关函数：`vss_join`、`vss_match`。
- 仅支持 **FLOAT** 向量（不支持其他数值类型）。
- 持久化实验开关：`hnsw_enable_experimental_persistence`（索引持久化仍为实验特性）。

---

### 3.15 autocomplete

- 为 CLI 客户端提供自动补全；CLI 默认随附该扩展。
- 函数：`sql_auto_complete(query_string)` 返回补全建议（列 `suggestion`、`suggestion_start`）。

### 3.16 avro

- 读取 Apache Avro 文件：`read_avro('x.avro')`，支持 HTTP/S3 直读、glob、文件名列（`filename=true`）。
- 2024 年底作为社区扩展发布，**2025 年初成为 core extension**。
- **限制**：
  - 单文件/多文件读取**不并行**；
  - 无 projection/filter pushdown（计划中）；
  - 不支持 Wasm 与 Windows-MinGW 构建；
  - DuckDB 无法表达 Avro 的**递归类型定义**；
  - 不支持 `union_by_name` 标志。

### 3.17 encodings

- 让 CSV 读取支持 **1000+ 字符编码**（基于 ICU 字符集数据）。
- 用法：`FROM read_csv('x.csv', encoding = 'shift_jis');`
- 完整编码清单含 `utf-8`、`utf-16`、`big5`、`gb18030`、`EUC_CN`、`CP1252`、`windows-1251-2000`、`shift_jis` 等上千项（见原文件长表）。

### 3.18 fts（Full-Text Search）

- 类 SQLite FTS5 的全文检索。
- autoload：是（`fts` 扩展）。
- 用法：
  ```sql
  PRAGMA create_fts_index('documents', 'document_identifier', 'text_content', 'author');
  -- 检索
  SELECT *, fts_main_documents.match_bm25(document_identifier, 'small cats') AS score
  FROM documents WHERE score IS NOT NULL ORDER BY score DESC;
  ```
- 参数：stemmer（porter/english/.../none）、stopwords、ignore 正则、`strip_accents`、`lower`、`overwrite`。
- `PRAGMA drop_fts_index('table')` 删除索引；`stem(str, stemmer)` 内部宏。
- **限制**：索引不会随基表变更自动更新，需重建。

### 3.19 icu

- 提供 ICU 库的**排序规则（collations）**与**时区（time zones）**支持。
- autoload：是（首次使用区域相关排序或时区时）。

### 3.20 inet

- 定义 `INET` 数据类型，存储 IPv4/IPv6 及 CIDR 子网。
- autoload：是。
- 函数/操作符：`HOST()`、`netmask()`、`network()`、`broadcast()`；谓词 `<<=`（被包含）、`>>=`（包含）；支持整数加减 IP。
- 另提供 `html_escape` / `html_unescape`。

### 3.21 jemalloc

- **静态链接**扩展，替代系统内存分配器；**不能运行时安装/加载**。
- Linux：随发行版自带；`GEN=ninja SKIP_EXTENSIONS="jemalloc" make` 可禁用。
- macOS：默认不带，需 `BUILD_JEMALLOC=1 make` 自行构建。
- Windows：不可用。
- 配置：`DUCKDB_JE_MALLOC_CONF` 环境变量；`SET allocator_background_threads = true;` 开启后台线程异步回收。

### 3.22 lance

- 读取/写入 [Lance](https://github.com/lance-format/lance) 数据集（面向 ML/AI 的 lakehouse 格式，原生云存储）。
- 第三方维护（lance-format/lance-duckdb）。
- 读写：`SELECT * FROM 'x.lance'`；`COPY (...) TO 'x.lance' (FORMAT lance, MODE 'overwrite'|'append')`。
- `ATTACH 'dir' AS ns (TYPE lance)` 后可用 `CREATE TABLE` / CTAS。
- 向量搜索：`lance_vector_search(...)`；全文：`lance_fts(...)`；混合：`lance_hybrid_search(...)`。
- 平台：`linux_amd64`、`linux_arm64`、`osx_arm64`、`windows_amd64`。

### 3.23 motherduck

- 连接 [MotherDuck](https://motherduck.com/)（云端 DuckDB 数仓）。
- autoload：是（autoinstall + autoload）；别名 `md`。
- 用法：`ATTACH 'md';`
- 平台：`linux_amd64`、`linux_arm64`、`osx_amd64`、`osx_arm64`、`windows_amd64`（`windows_arm64` 暂不支持）。

### 3.24 mysql

- 直接读写运行中的 MySQL 实例（类比 postgres 扩展）。
- autoload：首次使用时。
- 连接：`ATTACH 'host=localhost user=root port=0 database=mysql' AS mysqldb (TYPE mysql);`（别名 `mysql_scanner`）。
- 凭据可用 `TYPE mysql` secret（支持命名 secret、持久 secret、SSL 参数 `ssl_mode` 等）。
- 支持操作：`CREATE TABLE`、`INSERT`、`SELECT`、`COPY`（含 `COPY FROM DATABASE`）、`UPDATE`、`DELETE`、`ALTER TABLE`、`DROP`、`CREATE VIEW`、`CREATE/DROP SCHEMA`、事务。
- 函数：`mysql_query(attached_db, query)`、`mysql_execute(attached_db, query)`、`mysql_clear_cache()`。
- 设置项丰富：`mysql_bit1_as_boolean`、`mysql_tinyint1_as_boolean`、`mysql_enable_filter_pushdown`、`mysql_pool_*`、`mysql_session_time_zone`、`mysql_time_as_time` 等。
- 注意 MySQL 的 DDL 非事务性。

### 3.25 quack

- 支持 [Quack remote protocol](https://.../quack/overview)（远程查询协议）。
- autoload：是（实验性，beta）。
- **版本相关事实**：自 **v1.5.3** 起处于实验状态，协议/函数名/实现都可能变；**预计 v2.0.0（计划 2026 年 9 月）达到稳定**。

### 3.26 sqlsmith

- 测试用途：注册 `sqlsmith`、`fuzzyduck`、`reduce_sql_statement`、`fuzz_all_functions` 等函数，用于模糊测试 SQL 路径。

### 3.27 tpch

- TPC-H 基准的数据生成器与查询。
- 部分构建默认内置，否则 autoload。
- `CALL dbgen(sf = 1);` 生成数据；`PRAGMA tpch(4);` 跑固定查询；`tpch_queries()` / `tpch_answers()` 列出查询与预期答案。
- 预生成数据集可从 blobs.duckdb.org 下载（sf1 ~ sf3000）。

### 3.28 tpcds

- TPC-DS 基准的数据生成器与查询。
- autoload：是。
- `CALL dsdgen(sf = 1);`；`PRAGMA tpcds(8);`；`tpcds_queries()` / `tpcds_answers()`。
- **版本相关事实**：**v2.0 起 tpcds 扩展将变更**以兼容 TPC-DS version 4（见 `duckdb/duckdb#21746`）。当前 v1.x 生成的预生成数据集与 v2.x 略有差异。

### 3.29 ui

- 由 MotherDuck 维护的本地 DuckDB 图形界面（嵌入 HTTP 服务器，默认 `http://localhost:4213`）。
- 启动：`duckdb -ui` 或 `CALL start_ui();`；`CALL start_ui_server();` 仅起服务不弹浏览器；`CALL stop_ui_server();` 停止。
- 默认**完全本地执行**，数据不出本机；接入 MotherDuck 需显式登录。
- 配置：`ui_local_port`（默认 4213）、`ui_remote_url`（默认 `https://ui.duckdb.org`，仅 `allow_unsigned_extensions` 时尊重自定义值）、`ui_polling_interval`（默认 284 ms）。
- 不支持 `windows_arm64`；只读数据库上运行 UI 不支持（需用另一个 db 文件 + `ATTACH ... READ_ONLY`）。

### 3.30 unity_catalog

- 在 Delta Lake 格式与 DuckDB `delta` 扩展之上，支持 [Unity Catalog](https://www.unitycatalog.io/)（Databricks / OSS）。
- `TYPE unity_catalog` secret：`TOKEN`、`ENDPOINT`、`AWS_REGION`。
- 支持：`SHOW ALL TABLES`、`SELECT`、time travel `AT (VERSION => ...)`、`INSERT`、`CALL unity_catalog_checkpoint_table(...)`、Catalog-Managed Commits（CCv2，透明使用）。
- **不支持**：`DELETE`/`UPDATE`、`CREATE TABLE` DDL（CMC 表须由 Spark/UC CLI 先建）。
- 平台：`linux_amd64`、`linux_arm64`、`osx_amd64`、`osx_arm64`、`windows_amd64`（与 `delta` 相同，仅 AMD64/ARM64，无 `windows_arm64`）。

### 3.31 vortex

- 读写 [Vortex](https://vortex.dev/) 文件格式。
- 第三方维护（vortex-data/duckdb-vortex）。
- 读：`SELECT * FROM read_vortex('x.vortex');`；写：`COPY (...) TO 'x.vortex' (FORMAT vortex);`（务必带 `FORMAT vortex`，否则退化为 CSV）。
- 平台：仅 Linux（`linux_amd64`、`linux_arm64`）与 macOS（`osx_amd64`、`osx_arm64`）。

---

## 4. 社区扩展（Community Extensions）概览

- **社区扩展仓库**（`community`，URL `http://community-extensions.duckdb.org`）自 **2024 年夏** 起可用。
- 由社区（非 DuckDB 核心团队）维护、独立版本化、独立仓库（out-of-tree），例如 `tarfs`、`avro`（先社区后转正为 core）、`quack`、`lance`、`vortex`、`unity_catalog` 等。
- 使用：
  ```sql
  INSTALL tarfs FROM community;
  LOAD tarfs;
  ```
- 社区扩展同样受签名校验；从 `community` 仓库安装需联网且版本匹配当前 DuckDB（见 §1.6 版本兼容性铁律）。
- 注意：从 `community` 安装后若想切回 `core`，使用 `FORCE INSTALL ... FROM core`（§1.9）。

---

## 5. 版本相关事实（Version-Specific Facts）

以下为面向 **DuckDB 1.5.5** 写作本书时必须标注的版本相关要点：

1. **扩展加载模型（loading model）**
   - 两阶段：`INSTALL`（下载+校验+存本地）与 `LOAD`（动态加载进实例）。多数 core 扩展**首次使用自动加载**；`spatial`、`odbc` 因依赖外部库**必须手动 `LOAD`**。
   - 已加载扩展**无法 unload/reload**，无 `UNINSTALL` 命令。
   - 无网络/离线场景：可用 `INSTALL/LOAD '<url_or_path>'` 或 `extension_directories` 指向预下载文件。

2. **版本兼容性铁律（version-compatibility rule）**
   - 扩展二进制**绑定具体 DuckDB 版本 + 平台**（`~/.duckdb/extensions/<duckdb_version>/<platform>/`）。
   - 跨版本（尤其跨主版本）须重新 `INSTALL`，推荐 `FORCE INSTALL`。
   - 升级 DuckDB 后旧版扩展会被拒绝加载。

3. **v1.5.5 具体新增/变更**
   - **postgres**：新增 `pg_staleness_query_enabled`（BOOLEAN，默认 `FALSE`），实现自动检测 PostgreSQL schema 变化、自动失效缓存（duckdb-postgres#514）。
   - **iceberg**：支持 **V3 spec**（VARIANT、TIMESTAMP_NS、默认值、binary deletion vectors）；写入仅支持 positional delete + merge-on-read，且受限于非排序表；`GEOGRAPHY`/`UNKNOWN` 计划于 v2.0.0。
   - **ducklake**：**DuckLake 1.0 于 2026 年 4 月发布**。
   - **quack**：自 v1.5.3 起实验性，协议不稳定，预计 v2.0.0（2026-09）稳定。
   - **odbc**：nightly 使用**版本无关 C API**，同一二进制兼容 1.2.0+。
   - **tpcds**：将在 **v2.0** 变更为兼容 TPC-DS v4（生成数据会与 v1.x 略有差异）。

4. **平台注意事项**
   - `windows_arm64` 不被 `motherduck`、`ui`、`unity_catalog`/`delta` 支持；`vortex` 仅 Linux/macOS；`avro` 不支持 Wasm/MinGW；`encodings` 依赖 ICU。
   - 签名：官方仓库扩展已签名；加载未签名扩展需 `allow_unsigned_extensions` 或 `-unsigned`。

---

> 备注：本摘要已覆盖 `extensions/` 与 `core_extensions/` 下全部 65 个 `.md` 文件（含 httpfs/postgres/iceberg/spatial/odbc 子目录）。`json` 与 `parquet` 为内置扩展，其文档位于 `docs/data/` 而非本目录树，本书相关章节应另行引用 `docs/data/json.md` 与 `docs/data/parquet.md`。
