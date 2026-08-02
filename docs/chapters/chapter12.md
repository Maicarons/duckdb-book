# 第 12 章 云存储与远程数据

DuckDB 作为进程内（in-process）分析型数据库，数据默认落在本地文件。真实的数据工程与科学计算场景中，待分析的数据往往并不在本地磁盘：它们可能存放在 Amazon S3、Google Cloud Storage 这类对象存储（object storage）之中，也可能分布在多台机器上的 DuckDB 实例里。DuckDB 不内置独立的网络服务进程，却提供了一套完整且统一的机制来跨越"本地"与"远程"的边界——`httpfs` 扩展负责把远程文件当作本地文件一样读写，`CREATE SECRET` 体系集中管理跨服务的访问凭证（secret），而 Quack 远程协议则把任意 DuckDB 实例变成可被其他实例连接的 HTTP 服务端。本章依次展开这三块能力，并给出远程读取的性能调优要点。

## 12.1 httpfs 扩展与对象存储

### 12.1.1 统一接入模型

`httpfs` 是 DuckDB 的 core extension，维护层级为 Primary，开箱可用且支持 autoload：当查询首次触及 `s3://`、`https://` 等远程 scheme 时，DuckDB 会自动从官方仓库下载并加载它，无需手动 `INSTALL`/`LOAD`。该扩展的别名涵盖 `http`、`https`、`s3`，因此 `LOAD httpfs;` 与 `LOAD s3;` 等价。所有远程文件访问——无论是读取 Parquet、导出数据，还是挂载远程 DuckDB 库——都经由 `httpfs` 这一条路径，不存在第二套网络栈。

```sql
-- 多数情况下 autoload 已足够；显式加载仅用于明确意图或离线预装
INSTALL httpfs;
LOAD httpfs;
```

### 12.1.2 支持的对象存储后端

`httpfs` 把对象存储统一抽象为文件系统接口，覆盖 S3、Google Cloud Storage（GCS）、Azure Blob/Data Lake、HTTP(S)、Cloudflare R2、Fastly、Tigris 以及 S3 Express One，Iceberg 表也能直接落在 S3 上访问。各后端在 DuckDB 中以不同 URL scheme 与 secret 类型区分，但读写 API 完全一致。

**S3 与 S3 互操作后端。** S3 及其兼容实现（R2、Fastly、Tigris、S3 Express）都通过 `TYPE s3` 的 secret 配置，差异主要体现在 `ENDPOINT`、`URL_STYLE`、`REGION` 等参数。

```sql
CREATE SECRET (TYPE s3, KEY_ID 'AKIA...', SECRET '...', REGION 'us-east-1');
-- 读取：DuckDB 只下载查询真正需要的列与行组
SELECT * FROM read_parquet('s3://bucket/path/file.parquet');
-- 写入：经 S3 multipart upload，分块大小与线程数可调
COPY my_table TO 's3://bucket/path/out.parquet';
```

**Google Cloud Storage。** GCS 经 S3 互操作 API 接入，需使用 HMAC key 构建 `TYPE gcs` 的 secret。

```sql
CREATE SECRET (TYPE gcs, KEY_ID 'GOOG...', SECRET '...');
SELECT * FROM read_parquet('gs://bucket/path/file.parquet');
COPY my_table TO 'gs://bucket/path/out.parquet';
```

**Cloudflare R2。** R2 需要 `ACCOUNT_ID` 以拼出端点 `https://<acctid>.r2.cloudflarestorage.com`，由 `TYPE r2` 的 secret 承载。

```sql
CREATE SECRET (TYPE r2, KEY_ID '...', SECRET '...', ACCOUNT_ID '...');
SELECT * FROM read_parquet('r2://bucket/path/file.parquet');
```

**Azure。** Azure Blob Storage 与 Data Lake Storage（ADLS）使用 `az`/`azure`/`abfss` scheme，凭据支持 `CONFIG`、`credential_chain`、`managed_identity`、`service_principal` 等 provider。

**Fastly 与 Tigris。** 二者均为 S3 兼容存储，借助 `TYPE s3` 配合特定 `ENDPOINT` 与 `URL_STYLE` 接入。Fastly 需 `URL_STYLE 'path'` 与端点 `us-east.object.fastlystorage.app`；Tigris 单端点 `fly.storage.tigris.dev` 服务所有区域，`REGION` 仅用于签名，可设为 `auto`。

**S3 Express One。** 需显式指定端点 `s3express-<az>.<region>.amazonaws.com`（如 `s3express-use1-az5.us-east-1.amazonaws.com`）。性能上建议让 EC2 实例与 bucket 处于同一可用区，LDBC SF300 实测仅加载 4.1 GB Parquet 约 3.5 秒。

### 12.1.3 远程 DuckDB 库的只读挂载

除了文件，`httpfs` 还能直接挂载（ATTACH）位于对象存储或 HTTPS 上的 DuckDB 数据库文件，将其中的表当作本地表查询：

```sql
ATTACH 'https://blobs.duckdb.org/databases/stations.duckdb' AS stations_db;
SELECT count(*) FROM stations_db.stations;
```

这种远程挂载**仅支持只读**，不支持写回；S3/GCS 兼容 API 同样适用，GCS 上的 DuckDB 库也只能通过 `ATTACH ... (READ_ONLY)` 附加。需要写回时，仍须在本地文件上完成变更，再导出到远端。

## 12.2 CREATE SECRET 与凭证管理

### 12.2.1 Secret 类型与典型参数

跨后端的访问凭证统一由 Secrets Manager 管理，通过 `CREATE SECRET` 声明，并在 `ATTACH` 或查询时按类型自动匹配。常用类型包括 `s3`、`gcs`、`r2`、`azure`、`quack` 等，核心参数有 `KEY_ID`、`SECRET`、`REGION`、`ENDPOINT`。S3 还支持 `credential_chain` provider，可串联 `config`（~/.aws/credentials）、`env`、`sts`、`sso`、`instance`、`process`、`web_identity` 等来源，免去硬编码长期密钥。

```sql
-- 显式长期密钥
CREATE SECRET (TYPE s3, KEY_ID 'AKIA...', SECRET '...', REGION 'us-east-1');
-- 链式凭据：从配置与 STS 临时凭据获取，并跨账号 AssumeRole
CREATE SECRET (
    TYPE s3,
    PROVIDER credential_chain,
    CHAIN config,sts,
    ASSUME_ROLE_ARN 'arn:aws:iam::123456789012:role/my-role',
    REGION 'us-east-1'
);
```

### 12.2.2 持久化存储与权限

Secret 默认仅存在于当前会话，重启后失效。可声明为持久（persistent）secret，使其跨会话保留——持久 secret 以**未加密的二进制形式**存放在用户目录 `~/.duckdb/stored_secrets` 下，文件权限为 `600`（仅属主可读写）。这一机制便于单机复用凭据，却也意味着明文密钥落盘，须确保该目录的属主与文件系统权限受控，避免在共享或多用户主机上泄露。对安全敏感的环境，更宜依赖 `credential_chain` 的临时凭据或外部密钥管理，而非长期持久化静态密钥。

## 12.3 远程文件读取性能建议

### 12.3.1 网络延迟与并行度

`httpfs` 采用同步 IO：每个线程在同一时刻最多发起一个 HTTP 请求。当查询需要向远端索取大量小对象（例如海量小 Parquet 文件、深层级 Hive 分区）时，单线程会串行等待网络往返，CPU 反而空闲。此时应将 `threads` 提升到 CPU 核数的约 2–5 倍，用更多并发请求填满网络带宽：

```sql
SET threads = 16;  -- 假设机器为 4 核，提升到 2–5 倍
```

### 12.3.2 大查询的落盘（spill to disk）

超出内存的数据集仍可处理，DuckDB 通过 spill to disk 把中间状态溢出到临时目录（默认持久化模式下的 `<db>.tmp` 或内存模式下的 `.tmp`，可用 `temp_directory` 修改）。GROUP BY、JOIN、ORDER BY、窗口函数这类阻塞算子（blocking operator）都支持超内存执行，但多个阻塞算子叠加或特定聚合（`list()`、`string_agg()`）仍可能 OOM。面对远程大查询，配合 `SET memory_limit` 与 `preserve_insertion_order = false` 能降低内存峰值。

### 12.3.3 下推减少传输

远程读取的最大开销是网络传输量，而 DuckDB 的向量化执行器会把多种操作下推到扫描层，从源头削减取回的数据：

- **列裁剪（projection pushdown）**：`SELECT` 只列出所需列，DuckDB 只下载这些列的数据块，而非整行。
- **过滤下推（filter pushdown）**：`WHERE` 谓词被下推到 parquet 扫描，结合 row group 的 zonemap 跳过不匹配的行组，并减少回传行数。
- **范围与限制下推**：`LIMIT` 与范围过滤能把取数规模压到最小，远程只回传命中的少量行组。
- **Hive 分区**：按常用过滤列分区，使整目录的无关分区被直接排除。

自 v1.3.0 起 DuckDB 支持远程数据缓存（`duckdb_external_file_cache()`），重复访问同一远端对象可免二次下载。用 `EXPLAIN ANALYZE` 可直观查看一次查询发起的 HTTP 请求数与实际传输字节数，据此判断下推是否生效、并行度是否需要调整。

## 12.4 Quack 远程协议

### 12.4.1 协议模型

Quack 是一项把 DuckDB 实例转变为服务器的扩展，让其他 DuckDB 实例作为客户端通过 HTTP 连接——它补上了进程内架构天生缺失的多进程并发写与远程访问能力。Quack 于 2026-05-12 发布，beta 版随 DuckDB v1.5.3 经 `core` 仓库提供，处于实验状态，协议与函数名仍可能变化，预期在 v2.0 达到稳定。

协议本身基于明文 HTTP 或经反向代理的 HTTPS，复用标准的负载均衡、防火墙与反向代理设施，没有自定义传输层。请求与响应以 `application/duckdb` 媒体类型序列化，采用 DuckDB 内部的序列化原语编码——**这条序列化路径与预写日志（WAL, Write-Ahead Log）共用同一套代码**，使得嵌套结构、decimal、interval 等复杂类型都能无损跨线传输。握手之后，单条查询只需一次请求-响应往返；大结果通过后续 `FETCH` 分块流式返回，客户端可多线程并行拉取。URI 使用 `quack:` scheme，默认端口 **9494**。

### 12.4.2 服务端与客户端的启动

服务端从已有 DuckDB 会话启动，返回监听 URI、HTTP URL 以及客户端所需的 `auth_token`：

```sql
-- 默认仅绑定 localhost
CALL quack_serve('quack:localhost');
-- 监听外部地址需显式开启，并建议前置 TLS 终止的反向代理
CALL quack_serve('quack:0.0.0.0:9494', allow_other_hostname => true);
-- 停止服务
CALL quack_stop('quack:localhost');
```

客户端有两种接入方式。其一是无状态的 `quack_query`，无需挂载即可执行远程查询：

```sql
FROM quack_query('quack:localhost', 'SELECT 42', token='⟨TOKEN⟩');
```

其二是 `ATTACH` 把远程实例作为完整 catalog 挂载，远程表、DDL、写入与事务如同本地一样使用：

```sql
ATTACH 'quack:localhost' AS remote_db (TOKEN '⟨TOKEN⟩');
CREATE TABLE remote_db.t AS FROM range(10) r(i);
INSERT INTO remote_db.t VALUES (42);
FROM remote_db.t WHERE i = 42;
```

### 12.4.3 认证、授权与安全部署

Quack 服务端暴露底层 DuckDB 的**完整 SQL 面**（含读写），故默认采取保守策略：启动时生成随机认证 token（auth token），客户端每次连接都必须提供；服务端仅绑定 localhost，非本地主机名需显式 `allow_other_hostname => true`；服务端自身不启用 TLS（localhost 通信加 TLS 无收益），但非本地 URI 时客户端默认假设 HTTPS。

认证（authentication）与授权（authorization）是两道可插拔的钩子，均为全局作用域设置：认证函数 `quack_authentication_function`（默认 `quack_check_token`）在连接请求时校验 token；授权函数 `quack_authorization_function`（默认 `quack_nop_authorization`，放行一切）在准备请求时按查询放行与否。二者可用 SQL `MACRO` 或 C++/Rust/Go 等扩展注册的标量函数替换——Python UDF 因连接作用域问题不可用作回调。推荐把 token 放入 secret 而非硬编码：

```sql
CREATE SECRET (TYPE quack, TOKEN '⟨TOKEN⟩', SCOPE 'quack:localhost');
ATTACH 'quack:localhost' AS remote_db (TYPE quack);
```

任何非本地部署都应前置成熟的 HTTP 反向代理来终止 TLS，常见方案为 nginx 或 Caddy 配合 Let's Encrypt。nginx 侧需关注 `client_max_body_size 256M`（PREPARE/APPEND 体较大）、`proxy_read_timeout`/`proxy_send_timeout` 设为 `600s`（长查询）、`proxy_http_version 1.1` 并保持长连以维持 `quack_connection_id` 状态，以及 `proxy_buffering off`（不缓冲流式 FETCH）。

### 12.4.4 版本状态

Quack 当前为 beta，在生产环境使用尚不成熟，可能包含破坏性变更，预期在 DuckDB **v2.0** 稳定。若遇扩展行为异常，可用 `FORCE INSTALL quack;` 拉取匹配当前版本的扩展。

## 12.5 本章小结

本章覆盖了 DuckDB 跨越本地边界的三组能力。**其一，`httpfs` 扩展**统一了所有远程文件访问：S3、GCS、Azure、HTTP(S)、Cloudflare R2、Fastly、Tigris、S3 Express 与 Iceberg 经同一网络栈读写，远程 DuckDB 库则只能以只读方式 `ATTACH`。**其二，`CREATE SECRET`** 集中管理跨后端凭证，支持显式密钥与 `credential_chain` 链式临时凭据；持久 secret 以未加密二进制存于 `~/.duckdb/stored_secrets`（权限 600），明文落盘须谨慎对待。远程读取的性能关键在于用并行度抵消网络延迟、用 spill to disk 容纳超内存负载、并用列裁剪/过滤/范围/LIMIT 下推与远程缓存尽量压缩传输量。**其三，Quack 远程协议**借助 `application/duckdb` 序列化（与 WAL 共享代码路径）与 token 认证，把 DuckDB 变成可被 `quack_query` 或 `ATTACH` 连接的 HTTP 服务，默认端口 9494；它仍处 beta，生产部署须前置 TLS 反向代理，并预期在 v2.0 稳定。
