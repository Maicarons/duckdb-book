# 第 13 章 扩展体系

DuckDB 的一大设计特征是"可扩展（Extensible）"：Parquet、JSON、时区（ICU）、HTTP(S) 与 S3 等基础能力本身都以扩展（extension）形式实现，连引擎核心也借由扩展机制向外延展。这种"内核精简、能力外挂"的格局，让 DuckDB 既能保持二进制轻量，又能按需吸纳地理空间、向量检索、湖仓格式、跨数据库挂载等丰富功能。理解扩展的加载模型、版本绑定规则与签名安全机制，是安全、稳定地使用生态的先决条件。本章系统拆解 DuckDB 的扩展体系——从安装与加载的底层机制，到版本兼容的硬性约束，再到签名安全与社区生态，为后续自定义函数与扩展开发章节铺垫基础。

## 13.1 扩展架构与加载模型

DuckDB 把功能划分为两类：一类是**内置扩展（built-in / 静态链接，statically linked）**，随二进制一同发布、无法在运行时另行安装或卸载；另一类是**可安装扩展（installable / 动态加载，dynamically loaded）**，默认不随二进制发布，需经 `INSTALL` 与 `LOAD` 两步引入。

`INSTALL` 的职责是从仓库下载扩展二进制、校验其签名（signature），并存入本地扩展目录。默认路径因版本与平台而异，组织为 `~/.duckdb/extensions/<duckdb_version>/<platform_name>/`，例如 `~/.duckdb/extensions/v1.5.5/linux_amd64/`。仅执行 `INSTALL` 不会把扩展加载进当前实例——它只是把二进制落到磁盘。

```sql
-- 从默认仓库（core）安装 httpfs 扩展
INSTALL httpfs;
-- 动态加载到当前实例，使其函数与类型生效
LOAD httpfs;
```

`LOAD` 则把已安装的扩展**动态加载（dynamic loading）**到当前 DuckDB 实例，让扩展注册的函数、类型、表函数与索引方法生效。多数 core 扩展支持 **autoload（自动加载）**：首次被使用时，DuckDB 会透明地从官方仓库下载并加载（需联网），用户无需手动 `INSTALL`/`LOAD`。例如访问 `s3://`、`https://` 路径时，`httpfs` 会自行 autoload。

`INSTALL` 不指定来源时默认从 `core` 仓库拉取；也可通过 `FROM <repository>` 指定 `core_nightly`（每夜构建仓库）或 `community`（社区仓库）等来源。一旦用户显式 `INSTALL` 过某扩展，之后即使重启实例，该扩展通常已在本地缓存，autoload 不会再触发网络下载。

少数扩展因依赖外部系统库而无法 autoload，必须显式 `LOAD`。典型是 `spatial`（依赖 GEOS、PROJ、GDAL 等地理空间库）与 `odbc`（依赖 unixODBC / ODBC Driver Manager）。它们的加载语句不可省略：

```sql
-- spatial、odbc 不会自动加载，必须显式 LOAD
LOAD spatial;
LOAD odbc;
```

两个硬性限制需要牢记。其一，已加载的扩展在当前进程生命周期内**无法卸载（unload）或重新加载（reload）**——`LOAD` 之后便一直存在。其二，**不存在 `UNINSTALL` 命令**：若要移除一个扩展，只能手动删除 `~/.duckdb/extensions/...` 下的对应文件。这一约束意味着扩展的取舍须在加载前想清楚，加载后只能重启进程来"重置"。

还有一类扩展以静态链接形式存在，连运行时加载都不支持——例如 `jemalloc`（内存分配器），它被编译进二进制以替换系统分配器，既不能用 `INSTALL` 下载，也不能用 `LOAD` 动态加载。这类扩展的开关取决于构建方式（如 Linux 发行版自带，macOS 需 `BUILD_JEMALLOC=1` 自行构建，Windows 不可用）。

排查扩展状态时，`duckdb_extensions()` 表函数给出当前环境可用扩展的清单，含名称、是否已安装、是否已加载、版本与仓库等字段：

```sql
SELECT extension_name, installed, loaded, version, repository
FROM duckdb_extensions()
WHERE extension_name IN ('httpfs', 'spatial', 'odbc');
```

通过该表函数可确认某扩展开是否已被 autoload、是否已实际加载，是诊断加载问题的第一步。

## 13.2 版本兼容性铁律与离线安装

扩展二进制与特定的 DuckDB 版本及平台（platform）**严格绑定**，这是整个扩展体系最不可动摇的规则。仓库按 `Target DuckDB Version` 组织目录，形如 `v1.5.5/linux_amd64/`；每一次编译都针对某一个具体版本与某一平台。用错版本（例如拿 1.4.0 的扩展去配 1.5.5 的 DuckDB）或错平台（例如 `linux_amd64` 的扩展跑在 `osx_arm64`），加载会被直接拒绝。这条**版本兼容性铁律（version-compatibility rule）**意味着：升级 DuckDB 之后，旧版本对应的扩展二进制一律失效，必须重新拉取匹配新版本的扩展。

常规做法是重装匹配版本。由于默认 `INSTALL` 发现本地已有同版本文件便会跳过，`FORCE INSTALL` 用于忽略本地缓存、强制重新下载——升级后或切换仓库来源时都应使用它：

```sql
-- 升级 DuckDB 后，强制重新拉取匹配新版本的扩展
FORCE INSTALL httpfs;
-- 也可切换仓库来源（例如从 nightly 切回官方 core）
FORCE INSTALL iceberg FROM core_nightly;
```

网络受限或完全离线的场景，可用"直接按 URL 或本地路径安装/加载"的方式绕过仓库联网：

```sql
-- 离线环境：加载预先下载到本地的扩展文件
INSTALL 'path/to/httpfs.duckdb_extension';
LOAD    'path/to/httpfs.duckdb_extension';

-- 也可直接指向 HTTP/S3 上的扩展文件
INSTALL 'http://example.com/path/to/extension.duckdb_extension';
LOAD    'http://example.com/path/to/extension.duckdb_extension';
```

更系统化的离线方案是指定扩展搜索目录：通过配置项 `extension_directory`（单个目录）或 `extension_directories`（多个目录、以平台分隔符分隔）指向预先下载好的扩展文件所在位置，DuckDB 会在这些目录中查找而不再尝试联网：

```sql
-- 指向预下载扩展所在的多个目录（unix 以冒号分隔）
SET extension_directories = '/data/duckdb_exts:/opt/duckdb_exts';
```

与 `extension_directories` 对应的还有单数形式的 `extension_directory`，用于指定单个自定义目录；`extension_directories` 则是以平台分隔符分隔的多个目录列表，适合把预下载文件分散在多台机器或多种存储介质的场景。两者都让 DuckDB 优先在本地目录查找扩展，从而在完全离线的 CI 流水线或内网环境中稳定复现依赖。

`UPDATE EXTENSIONS;` 语句可尝试按当前 DuckDB 版本与仓库批量更新已安装扩展，但同样受版本绑定约束——跨大版本升级本质上仍需 `FORCE INSTALL` 重新获取匹配二进制。故障排查时若出现 404，多半是版本/平台不匹配或该平台没有对应构建，此时可手动用浏览器下载对应 `duckdb_version`/`platform` 下的文件再 `LOAD '...'`。

## 13.3 扩展签名与安全

DuckDB 对来自官方仓库的扩展实施**签名（signature）校验**。官方仓库 `core` 与 `community` 发布的扩展均经数字签名，DuckDB 在 `INSTALL` 下载后会校验签名，签名不符则拒绝加载。这套机制保证扩展二进制确实出自可信来源、未被篡改。

第三方或本地自行构建的扩展可能**未签名（unsigned）**。加载此类扩展需显式开启未签名支持——但该开关**只能在启动期确定**：要么在启动前通过配置项设定，要么以 `-unsigned` 命令行参数启动；一旦实例已经运行，便无法在会话中途将其开启。

```sql
-- 启动期开启未签名扩展支持（仅可在启动时生效）
SET allow_unsigned_extensions = true;
-- 等价地通过命令行参数启动
--   duckdb -unsigned my.db
```

`allow_unsigned_extensions` 的"仅启动期可开"特性，把安全开关固化在进程生命周期起点，避免运行期被动态放宽从而引入风险。部分涉及本地数据的功能（如 `ui` 扩展的 `ui_remote_url` 自定义远程地址）也只有在开启该开关时才会被尊重，理由正是远程 UI 资源可能访问本地数据。

另一个相关开关 `allow_community_extensions` 默认值为 `true`，控制是否允许从社区仓库安装扩展。它的关键行为是**自我锁定（self-lock）**：一旦在启动期将其设为 `false`，运行期便无法再改回 `true`。也就是说，关闭社区扩展支持是不可逆的会话级决定，必须在启动阶段就规划清楚。

```sql
-- 默认开启；一旦启动期关闭，运行期不可再开（自我锁定）
SET allow_community_extensions = false;   -- 仅可在启动期设置
```

综上，扩展安全由三层保障：签名校验确保来源可信、`allow_unsigned_extensions` 把未签名支持锁在启动期、`allow_community_extensions` 的不可逆关闭防止运行期误开社区源。三者在启动期一次性定调，运行期不再可放宽。

## 13.4 核心扩展一览

DuckDB 共有 **28 个核心扩展（core extensions）**，按维护方分为 Primary、Secondary 与 Third-party 三档支持层级。其中 `parquet` 与 `json` 作为**内置扩展（built-in）**随二进制发布、开箱即用——它们不是从仓库下载，而是直接静态链接进二进制，因此既无需 `INSTALL`/`LOAD`（显式 `LOAD` 也不会报错）。其余核心扩展默认不随二进制发布，需经 `INSTALL`/`LOAD` 或 autoload 引入。

autoload 是区分扩展"要不要手动管"的核心机制。下表列出若干代表性核心扩展及其加载特征：

| 扩展 | 主要用途 | autoload | 备注 |
|---|---|---|---|
| `parquet` | Parquet 读写 | 内置 | 无需 INSTALL/LOAD |
| `json` | JSON 读写 | 内置 | 无需 INSTALL/LOAD |
| `httpfs` | HTTP/S/S3/R2/GCS/Hugging Face | 是 | 别名 http/https/s3 |
| `postgres` | 挂载 PostgreSQL | 是 | 别名 postgres_scanner |
| `iceberg` | Apache Iceberg 表 | 是 | 支持 V3 spec（v1.5.5） |
| `icu` | 排序规则与时区 | 是 | 首次区域/时区操作时触发 |
| `fts` | 全文检索 | 是 | 类 SQLite FTS5 |
| `inet` | INET（IPv4/IPv6/CIDR）类型 | 是 | — |
| `sqlite` | 挂载 SQLite | 是 | 别名 sqlite_scanner/sqlite3 |
| `excel` | 读写 .xlsx | 是 | 不支持旧版 .xls |
| `aws` | AWS 凭据集成 | 是 | 支持 RDS IAM 认证 |
| `azure` | Azure Blob/ADLS | 是 | 协议 az/azure/abfss |
| `delta` | Delta Lake 读取 | 是 | 基于 delta-kernel-rs |
| `ducklake` | DuckLake 湖仓 | 是 | DuckLake 1.0 于 2026-04 发布 |
| `spatial` | 地理空间（GIS） | 否 | 依赖 GEOS/PROJ/GDAL，须显式 LOAD |
| `odbc` | ODBC 访问任意 DBMS | 否 | 依赖 unixODBC，须显式 LOAD |

从组织方式看，核心扩展又分 **in-tree（树内）** 与 **out-of-tree（树外）** 两类：in-tree 扩展位于 DuckDB 主仓库（如 `httpfs`、`parquet`、`json`、`postgres`、`iceberg`、`spatial`），随主仓库一起版本化与发布；out-of-tree 扩展位于独立仓库（如 `duckdb-avro`、`duckdb-mysql`、`duckdb-fts`），独立版本化。

在支持层级上，核心扩展分为三档：Primary 档由官方主力维护，含 `httpfs`、`icu`、`json`、`parquet`；Secondary 档为其余官方维护扩展；Third-party 档由第三方维护，含 `lance`、`motherduck`、`ui`、`vortex`。不少扩展还带别名（alias），用别名 `LOAD` 与用原名等价——`httpfs` 的别名包含 `http`/`https`/`s3`，`postgres` 别名 `postgres_scanner`，`sqlite` 别名 `sqlite_scanner`/`sqlite3`，`mysql` 别名 `mysql_scanner`，`motherduck` 别名 `md`。例如 `LOAD s3;` 与 `LOAD httpfs;` 指向同一扩展。

扩展的稳定性分为三级，理解其差异有助于判断能否用于生产：

| 稳定性级别 | 版本号形态 | 说明 |
|---|---|---|
| unstable | 基于 git hash | 随每次提交变化，主要用于 `core_nightly` 仓库 |
| pre-release | `v0.y.z` | 主版本仍为 0，可能不稳定 |
| stable | `vx.y.z`（`x > 0`） | 官方 `core` 仓库发布的扩展通常带 stable 版本号 |

官方 `core` 仓库发布的扩展通常带 stable 版本号，可放心用于生产；`core_nightly` 等仓库则充斥 unstable 构建，仅适合尝鲜与测试。

## 13.5 社区扩展生态

除官方核心扩展外，DuckDB 还设有**社区扩展仓库（community repository，别名 `community`）**，URL 为 `http://community-extensions.duckdb.org`。该仓库自 **2024 年夏**起上线，由社区（而非 DuckDB 核心团队）维护、独立版本化、以 out-of-tree 形式存在于独立仓库。

社区扩展的使用方式与核心扩展一致，只是需显式指定 `FROM community`：

```sql
INSTALL tarfs FROM community;
LOAD tarfs;
```

社区生态中有不少广为人知的成员：`tarfs`、`avro`（先作为社区扩展发布，2025 年初转正为 core extension）、`quack`（Quack 远程协议）、`lance`、`vortex`、`unity_catalog` 等。它们由不同维护方贡献，能力覆盖归档文件系统、向量格式、远程协议、AI 湖仓格式等多元场景。

需要强调的是，社区扩展**同样受版本兼容性铁律约束**——其二进制依然绑定具体 DuckDB 版本与平台，版本错配会被拒绝加载，升级后同样要用 `FORCE INSTALL` 重拉匹配版本。从 `community` 安装后若想切回官方 `core`，用 `FORCE INSTALL ... FROM core` 即可。社区扩展也需通过签名校验，因此默认纳入 DuckDB 的安全体系，除非显式开启 `allow_unsigned_extensions` 加载自编译的未签名版本。

## 13.6 本章小结

本章系统拆解了 DuckDB 的扩展体系，核心要点如下：

- **加载模型分两步**：`INSTALL` 从仓库下载二进制、校验签名并存入 `~/.duckdb/extensions/<版本>/<平台>/`；`LOAD` 将其动态加载进当前实例。多数 core 扩展支持 autoload（首次使用透明下载并加载），但 `spatial`、`odbc` 因依赖外部系统库必须显式 `LOAD`。已加载扩展无法 unload/reload，无 `UNINSTALL`；`jemalloc` 等静态链接扩展连运行时加载都不支持。
- **版本绑定是铁律**：扩展二进制严格绑定具体 DuckDB 版本与平台，错配即被拒加载；升级后须 `FORCE INSTALL` 重拉匹配版本。离线场景用 `INSTALL/LOAD '<url_or_path>'` 或 `extension_directories` 指向预下载文件。
- **安全靠三层锁定**：官方扩展经签名校验；`allow_unsigned_extensions` 仅启动期可开、运行期不可放宽；`allow_community_extensions` 默认开启但一旦关闭即自我锁定、不可逆。
- **核心扩展共 28 个**，`parquet`/`json` 为内置、开箱即用；稳定性分 unstable / pre-release / stable 三级，官方 `core` 仓库多为 stable。
- **社区仓库 2024 年夏上线**，由社区维护、独立版本化，使用方式一致且同样受版本约束，丰富了 DuckDB 的能力边界。

掌握扩展的安装、加载、版本与安全机制后，下一章将进入自定义函数（UDF）与扩展开发，把这套体系延伸到你自己的代码之中。
