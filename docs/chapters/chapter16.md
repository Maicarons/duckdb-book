# 第 16 章 运维手册

DuckDB 以进程内（in-process）嵌入式数据库的形态出现，没有常驻服务进程，也不需要 DBA 团队去维护一套独立的数据库服务器。这种轻量特性让很多人误以为它"无需运维"。事实上，当 DuckDB 进入生产环境——无论是作为本地分析工具、数据管道的一环，还是被嵌入到应用程序内部——安装渠道的选择、版本演进的约束、磁盘与内存足迹（footprint）、日志记录以及安全边界，都会直接影响系统的可靠性与可重复性。本章从工程实践的角度，系统梳理把 DuckDB 跑稳、跑安全所必须掌握的四件事：版本策略、足迹管理、日志体系与安全加固。

## 16.1 安装与版本策略

安装 DuckDB 的渠道随使用场景而异。交互式 CLI 与嵌入到应用程序中所采用的路径并不相同，语言客户端也各有各的包管理器。

**安装脚本（install.duckdb.org）**

Linux 与 macOS 上，官方提供一键安装脚本，把最新稳定版 CLI 安装到 `~/.duckdb/cli/latest/duckdb`：

```bash
curl https://install.duckdb.org | sh
```

安装完成后，需把 `export PATH="~/.duckdb/cli/latest":$PATH` 写入 shell 配置文件，使 `duckdb` 命令在任意目录下可用。

版本化（versioning）是生产部署的核心诉求。安装脚本通过 `DUCKDB_VERSION` 环境变量支持精确锁定某一发布版本——可回溯到 v1.0.0 以来的任意历史发布版（past releases）。例如锁定 1.2.2：

```bash
curl https://install.duckdb.org | DUCKDB_VERSION=1.2.2 sh
```

这一机制的价值在于可重复性：在 CI、容器镜像或交付物中固定 `DUCKDB_VERSION`，能确保每次构建都拉取行为一致的二进制，避免因"最新版"漂移引入不预期的变更。从发布治理的角度看，把版本号显式写死，相当于为生产环境锁定一条长期稳定、可审计的基线，其作用类似于其他生态中的 LTS（Long-Term Support，长期支持）策略——差别只是 DuckDB 并不单独划定一条带名称的 LTS 通道，而是把"选哪个版本"的决定权完全交给使用者。

Windows 用户可借助 beta 阶段的 PowerShell 脚本：

```powershell
powershell -NoExit iex (iwr "https://install.duckdb.org/install.ps1").Content
```

**官方 Docker 镜像**

容器化场景下，官方镜像 `duckdb/duckdb` 同时支持 ARM64 与 x86_64 架构：

```bash
docker run --rm -it -v "$(pwd):/workspace" -w /workspace duckdb/duckdb
```

该镜像把工作目录挂载为 `/workspace`，便于在容器内读写宿主文件。若需使用 DuckDB UI，则要附加 `--net host`；但这会把容器的全部端口转发到宿主网络，存在暴露风险，仅在可信环境中采用。

各语言客户端（Python、R、Java、Node 等）通过各自的包管理器安装，CLI 则专用于交互，官方不推荐将其作为嵌入载体。

**升级与扩展版本匹配**

扩展二进制（extension binaries）与具体的 DuckDB 版本、平台严格绑定。一次 DuckDB 主版本或次版本升级，往往意味着既有扩展需要重新安装与之匹配的版本；直接沿用旧版扩展二进制会导致加载失败或行为异常。因此，升级 DuckDB 时必须同步重装匹配版本的扩展——把扩展版本纳入与 `DUCKDB_VERSION` 相同的锁定与回归测试流程，是避免"升级即故障"的关键。

## 16.2 DuckDB 的足迹

DuckDB 的足迹（footprint）指的是它在磁盘与内存上留下的痕迹，以及运行前需要为它预留多少资源。理解这一点，才能在版本控制、备份与容量规划上做出正确决策。

**嵌入式与单文件存储**

DuckDB 是嵌入式（embedded）分析型数据库，以 in-process 方式运行在调用它的进程内部，没有独立服务进程，也不监听端口。它的存储格式是单文件（single-file）的：库文件可以使用任意扩展名，常见的是 `.duckdb`、`.db`、`.ddb`。这一特性让数据库的"部署"退化为"拷贝一个文件"，也是它适合随应用分发的根本原因。

**运行时创建的辅助文件**

除了库文件本身，DuckDB 在运行时会创建若干辅助文件，分全局与工作目录两类。

全局文件位于用户 home 目录（`~`）：

| 文件 / 目录 | 说明 |
|------|------|
| `~/.duckdbrc` | CLI 启动时自动执行的命令，类似 `.bashrc` |
| `~/.duckdb_history` | 历史命令记录，类似 `.bash_history` |
| `~/.duckdb/extensions` | 已安装扩展的二进制（跨版本不共享） |
| `~/.duckdb/stored_secrets` | 持久化 secret |

工作目录或库文件相对路径下的本地文件：

| 名称 | 说明 |
|------|------|
| `<database_filename>` | 数据库文件（仅磁盘模式） |
| `.tmp/` | 临时目录（仅内存模式） |
| `<database_filename>.tmp/` | 临时目录（仅磁盘模式） |
| `<database_filename>.wal` | 预写日志（WAL），正常退出时删除，崩溃时用于恢复 |

预写日志 `.wal` 是崩溃恢复的关键：正常关闭数据库后它会被清理；若进程异常终止，下次打开时 DuckDB 会依据 `.wal` 回放未落盘的写入。临时目录 `.tmp/` 则用于查询溢出（spill）与中间结果，其大小受 `max_temp_directory_size` 约束（默认可用磁盘的 90%）。

**二进制体积与内存占用**

DuckDB 以极小的嵌入式库著称：CLI 是单个可执行文件，客户端库也保持轻量。内存方面，默认上限为物理内存的 80%（`memory_limit`），由 `threads`（默认等于 CPU 核数）控制并行度。需要提醒的是，`memory_limit` 仅约束 buffer manager，向量、查询结果以及复杂状态聚合函数（如 `list`、`mode`、`quantile`）所用的内存在其之外，实际占用可能高于设定值，不能把它当作硬性内存天花板。

**用 .gitignore 管理版本控制**

把 DuckDB 库纳入 Git 仓库时，应按"保留库文件、忽略临时产物"或"连库文件一并忽略"两种策略配置。仅忽略临时文件、保留库文件：

```
*.wal
*.tmp/
```

若连库文件本身也要排除（以 `.duckdb` 为例）：

```
*.duckdb*
*.wal
*.tmp/
```

删除数据行后，DuckDB 不会通过 `VACUUM` 回收空间——这一点与 PostgreSQL 等行为不同。`VACUUM` 在 DuckDB 中不发生收缩；要回收删除产生的空闲空间，应执行 `CHECKPOINT;`。若要彻底压缩库文件、得到一个紧凑副本，可用 `COPY FROM DATABASE` 生成全新数据库：

```sql
ATTACH 'db1.db' AS db1;
ATTACH 'db2.db' AS db2;
COPY FROM DATABASE db1 TO db2;
```

单库文件本身没有实际大小上限（已有 15 TB 以上的库文件正常运行），但连接超大库可能耗费数秒，checkpoint 也更慢，容量规划时应对此有预期。

## 16.3 日志

DuckDB 内置一套可查询的日志体系，由 `enable_logging`（默认开启，值为 1）控制。所有日志进入名为 `duckdb_logs` 的特殊视图，可像普通表一样 `SELECT`：

```sql
CALL enable_logging();
SELECT * FROM duckdb_logs;
CALL truncate_duckdb_logs();   -- 清空当前日志
CALL disable_logging();
```

**日志级别**

日志级别按严重程度由低到高排列为 `ERROR` < `WARN` < `INFO` < `DEBUG` < `TRACE`。配置参考中 `logging_level` 的默认值为 `WARNING`，即默认只记录警告及以上。需要排查问题时，可临时调高：

```sql
CALL enable_logging(level = 'debug');
```

**日志存储位置**

日志可写入三种存储（storage）：`memory`（默认）、`stdout`（以 CSV 形式输出到标准输出）、`file`（CSV 文件）。切换到标准输出：

```sql
CALL enable_logging(storage = 'stdout');
```

写入文件时指定路径，简写形式为 `storage_path`：

```sql
CALL enable_logging(storage = 'file', storage_config = {'path':'path/to/logs'});
CALL enable_logging(storage_path = 'path/to/logs');
```

`duckdb_logs` 视图会自动指向当前活动存储。需要注意日志有缓冲，`stdout` 默认禁用缓冲、而 `memory`/`file` 默认缓冲 2048 条；调试崩溃场景可设 `buffer_size=0` 以尽量不丢日志：

```sql
CALL enable_logging(storage_config = {'buffer_size': 0});
```

**结构化日志类型**

DuckDB 对特定子系统提供结构化（structured）日志，便于机器解析与可观测性接入。任务关键的类型包括 `HTTP`、`FileSystem` 与 `Metrics`：

- `HTTP`：记录每次 HTTP 请求的 `request` 与 `response` 结构，含类型、URL、起止时间、耗时与头信息；
- `FileSystem`：记录文件系统层的操作；
- `Metrics`：暴露内部度量指标。

此外还有 `QueryLog`、`PhysicalOperator` 等类型。按类型启用日志：

```sql
CALL enable_logging('HTTP');
CALL enable_logging(['HTTP','FileSystem']);
```

结构化日志可用 `duckdb_logs_parsed('HTTP')` 宏解析，并用 `DESCRIBE FROM duckdb_logs_parsed('HTTP')` 查看其 schema，从而直接落地到监控系统或数据管道。

## 16.4 安全加固

DuckDB 的执行模型决定了它必须与 bash、Python 一样被看待：它用运行它的那个用户的权限执行 SQL。把 SQL 当作代码，而不是数据——不要在未经沙箱化的情况下执行来源不可信的 SQL。本章列出的配置项属于纵深防御（defense-in-depth），它们能收窄攻击面，但无法替代操作系统或容器级别的隔离。

**最小权限的文件访问**

`enable_external_access` 默认 `true`，允许加载扩展、`COPY`、读取 CSV/Parquet 等外部状态访问。不可信环境下应先将其关闭，再以白名单精确放行必要的目录或文件——即便外部访问被整体禁止，白名单项仍可使用：

```sql
SET allowed_directories = ['/tmp'];
SET enable_external_access = false;
```

也可通过 `allowed_paths` 以单文件粒度放行，或用 `SET disabled_filesystems='LocalFileSystem';` 彻底禁掉本地文件系统。

**扩展签名与供应链风险**

扩展与 DuckDB 进程同权，每一次加载都做二进制签名校验，分为 core key 签名、community key 签名与无签名三类。安全级别由配置项决定：默认允许 core 与 community 扩展；设 `SET allow_community_extensions = false` 则只允许 core 扩展（运行不可信 SQL 的 Web 服务建议如此）。`allow_community_extensions` 具备自我锁定特性——关闭后运行期内无法再改回 `true`，报 `Cannot upgrade ... while database is running`。

`allow_unsigned_extensions` 默认 `false`，且只能在启动时开启，属于明确的提权风险，仅扩展开发时才考虑。社区扩展仓库本质类似 pip/npm，是"远程代码执行设计"，务必只从可信源安装。

与之相关的还有自动加载/安装开关 `autoload_known_extensions` 与 `autoinstall_known_extensions`，二者默认值均为 `true`：查询依赖某扩展时，DuckDB 会自动联网安装并加载。为抵御供应链（supply-chain）风险——避免不可信环境下静默拉取并执行远程代码——应显式关闭：

```sql
SET autoload_known_extensions = false;
SET autoinstall_known_extensions = false;
```

**锁定配置防篡改**

自定义配置完成之后，可用 `lock_configuration` 把实例配置整体锁定，此后任何配置项都不可再改；`allowed_configs` 则指定锁定时仍可调的例外项：

```sql
SET allowed_configs = ['memory_limit','threads'];
SET lock_configuration = true;
```

这与关闭自动加载/安装组合使用，能固化一个受控、可重复的安全基线。

**CLI 安全模式**

交互式 CLI 提供 Safe Mode（安全模式），通过启动参数 `-safe` 或点命令 `.safe_mode` 进入，禁止访问数据库文件以外的外部文件，等于把读写的边界限制在库自身：

```bash
duckdb -safe mydata.duckdb
```

**预编译语句与权限**

防止 SQL 注入的正确做法是使用预编译语句（prepared statements）：你控制查询结构，只接收不可信数据作为值参数，从而杜绝拼接字符串带来的注入。

```python
# 危险：字符串拼接
duckdb.execute("... WHERE x = " + str(42))
# 安全：预编译，值以参数传入
duckdb.execute("... WHERE x = ?", [42])
```

若允许用户提交整条 SQL，等价于允许执行任意代码，必须配合沙箱处理。

权限方面，应避免以 root（`sudo`）运行 DuckDB。嵌入场景中，CLI 客户端面向交互，带有 `.sh` 等可直接执行 shell 命令的特性（仅 CLI 具备，其他客户端无）；嵌入应用时应当调用客户端库（Python/R/Java/Node 等），而不要通过 shell 去调用 CLI，以免引入命令执行面。

## 16.5 本章小结

把 DuckDB 投入生产，运维重心从"养服务器"转变为"管版本、控足迹、开日志、守边界"。本章的四条主线可归纳如下：

- 安装与版本：通过 `DUCKDB_VERSION` 锁定发布版本，保证构建可重复；官方 Docker 镜像覆盖主流架构；升级须同步重装与版本、平台严格绑定的扩展。
- 足迹管理：单文件库无服务进程，但会产生 `.wal` 与 `.tmp/` 等辅助文件；用 `.gitignore` 区分库文件与临时产物，删除空间回收靠 `CHECKPOINT` 而非 `VACUUM`。
- 日志体系：`logging_level` 默认 `WARNING`，日志可存 `memory`/`stdout`/`file`，`HTTP`/`FileSystem`/`Metrics` 等结构化类型便于接入可观测性。
- 安全加固：把 SQL 当作代码，`enable_external_access` 配白名单做最小权限，关闭自动加载/安装以抵御供应链风险，`lock_configuration` 固化基线，CLI 用 `-safe` 进入 Safe Mode，嵌入走客户端库而不调用 CLI。

这些配置并非银弹，它们与操作系统沙箱、容器隔离共同构成纵深防御。在不可信输入面前，限制文件访问、禁用 root、使用预编译语句，才是最贴近本质的防线。
