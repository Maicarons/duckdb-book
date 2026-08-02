# 第 02 章 安装、编译与连接

DuckDB 能在笔记本上秒开、在服务器里随取随用，根子在于它回避了传统数据库的"服务进程"范式。本章从获取这个引擎开始，依次讲清三件事：怎么把它装上、怎么从源码自己编译、以及装好之后怎样建立起第一条连接并用第一行查询验证一切正常。贯穿其中的主线是 DuckDB 的"进程内（in-process）"本性——理解这一点，安装与连接的诸多选择便不再显得随意。

## 2.1 安装方式总览

对绝大多数读者而言，预编译的二进制文件已经足够，无需触碰编译器。DuckDB 为常见平台都准备好了开箱即用的发行物。

最轻量的入口是官方安装脚本。在 Linux 与 macOS 上，一条命令即可把最新稳定版的 CLI 装到 `~/.duckdb/cli/latest/duckdb`：

```bash
curl https://install.duckdb.org | sh
```

装完后记得把可执行文件所在的目录加入 PATH，否则每次都得敲全路径：

```bash
export PATH="$HOME/.duckdb/cli/latest:$PATH"
```

这个脚本支持版本回退——通过环境变量 `DUCKDB_VERSION` 可以指定任意历史发布版（最早可回溯到 v1.0.0）：

```bash
curl https://install.duckdb.org | DUCKDB_VERSION=1.2.2 sh
```

Windows 用户有一条尚处 beta 阶段的 PowerShell 安装命令：

```powershell
powershell -NoExit iex (iwr "https://install.duckdb.org/install.ps1").Content
```

习惯包管理器的读者还有另一条路。macOS 上可用 Homebrew，Linux 上则可走 apt 或 yum 系发行渠道；Docker 用户直接拉取官方镜像 `duckdb/duckdb`，它同时支持 ARM64 与 x86_64：

```bash
docker run --rm -it -v "$(pwd):/workspace" -w /workspace duckdb/duckdb
```

若想在容器里使用 DuckDB UI，需额外加上 `--net host` 参数——它会转发容器的所有端口，故仅在受信任的环境这样配置。

语言客户端走的是另一条分发通道：Python 用 `pip install duckdb`（要求 Python ≥ 3.9），R、Java、Node 等各自经由本语言的包管理器。需要强调的是，CLI 主要面向交互式探索，官方并不推荐把它嵌入到应用里；真正嵌入业务系统时应当调用客户端库。

无论哪种途径，DuckDB 落地的形态是一致的：一个无独立服务进程的嵌入式（embedded）分析引擎，数据库就是单个文件，扩展名任取（`.duckdb`、`.db`、`.ddb` 皆可）。这种"单文件存储格式（single-file storage format）"决定了后续所有连接方式的基调。

## 2.2 从源码构建

当预编译产物无法满足需求时——比如要在树莓派这类实验性平台上运行、要构建某个尚未合并的 Pull Request、或需要启用特定扩展——就得自己动手编译。

构建系统建立在 CMake 之上，要求一台装有 C++11 兼容编译器的机器（GCC、Apple-Clang 或 MSVC 均可），并强烈建议搭配 Ninja 作为构建后端以获得自动并行化带来的加速。一个值得留意的版本信号：当前主线只需 C++11，但即将到来的 v2.0 会把门槛抬到 C++17，届时老编译器将被拒之门外。

DuckDB 的顶层 Makefile 封装了常用目标：

```bash
make                 # 等价于 make release
make release         # 发布版：去断言与调试符号，性能最优
make relassert       # 保留 D_ASSERT 与调试符号，比 debug 快很多
make debug           # 全调试信息，二进制偏慢，需预留 ≥25 GB 磁盘
GEN=ninja make       # 改用 Ninja 后端
BUILD_BENCHMARK=1 make   # 一并编译基准测试套件
```

`GEN=ninja make` 这个前缀在后面几乎随处可见，它告诉构建系统放弃默认的串行 make、改用 Ninja。

三个主流平台在命令上略有分歧。Linux 发行版差异明显：Ubuntu/Debian 用 apt 装 `git g++ cmake ninja-build libssl-dev libcurl4-openssl-dev`；Fedora/CentOS/RHEL 换用 yum，把 `g++` 写成 `gcc-c++`；Arch 则是 `pacman -S git gcc cmake ninja openssl`。拿到依赖后统一执行 `git clone` 加 `GEN=ninja make`。macOS 最省心，一条 `brew install git cmake ninja` 之后同样 `GEN=ninja make` 即可。Windows 的处境特殊——它没有 UNIX 那层 Makefile 包装，需要直接调用 CMake，且构建期和运行期都依赖 Microsoft Visual C++ Redistributable；追求开源工具链的也可走 MSYS2 的 MinGW64 路线。

编译产物统一落在 `build/release/duckdb`（Windows 下为 `duckdb.exe`）。

自带扩展是源码构建最自然的理由。用 `BUILD_EXTENSIONS` 列出需要的扩展，分号分隔：

```bash
BUILD_EXTENSIONS='tpch;httpfs;fts;json;parquet' GEN=ninja make
```

若想连 Python 绑定一起编出来，加上 `BUILD_PYTHON=1` 即可（`make debug` 也适用）。httpfs 扩展在 Linux 上常因缺 OpenSSL 而失败，补装 `libssl-dev` 通常能解决。

反复编译时，ccache 能显著缩短周转。在 macOS 上：

```bash
brew install ccache
ccache -M 50G
```

构建完成后若要验证改动正确，应当跑测试。DuckDB 沿用源自 SQLite 的 sqllogictest 框架，纯 SQL 测试文件放在 `test/sql` 目录，由 `unittest` 运行器驱动。调试构建下可只挑失败的用例：

```bash
build/debug/test/unittest test/sql/projection/test_simple_projection.test
```

不少测试开头会带 `PRAGMA enable_verification`，它把同一条查询在"未优化"与"优化"两条路径上各跑一遍并比对结果，借以捕获优化器引入的偏差——当数据集超过百行时这条校验会变慢，故大数据集测试中一般不开。

## 2.3 CLI 客户端详解

CLI 是初学者与 DuckDB 打交道最直接的界面，它本质上是一个单一、无依赖的可执行文件，交互方式脱胎于 SQLite 的命令行 shell，但 SQL 语法遵循 PostgreSQL 约定。

最基本的启动方式是不带任何参数：

```bash
duckdb
```

此时打开的是一块临时内存数据库（transient in-memory database），进程退出数据即失。与之相对，把文件路径一并给出便得到持久库文件（persistent database file）：

```bash
duckdb my_database.duckdb
```

文件路径不存在则新建，存在则打开——这正是单文件存储格式带来的便利。两类数据库都支持溢出到磁盘（spilling to disk）以承载超内存的工作负载，区别只在数据是否随进程结束而消失。SQL 以分号结束，省略分号可续行；退出可用 `Ctrl+D`、`Ctrl+C` 或 `.exit`，退出持久库时会自动做 checkpoint、合并 `.wal` 文件。

CLI 的灵魂在点命令（dot commands）上——它们以小数点开头，单行输入、结尾无需分号。下表列出本章最常用的一组：

| 点命令 | 作用 |
|--------|------|
| `.help` | 列出全部点命令与简要说明 |
| `.mode ⟨MODE⟩` | 切换输出格式（csv、json、markdown、box 等） |
| `.tables [PATTERN]` | 列出表，含列名、类型与行数，支持 `LIKE` 模式 |
| `.schema [PATTERN]` | 打印匹配表的 `CREATE` 语句 |
| `.import ⟨FILE⟩ ⟨TABLE⟩` | 从文件导入数据，自动推断 schema |
| `.read ⟨FILE⟩` | 读取并执行文件中的 SQL 与点命令 |
| `.timer on/off` | 显示每条 SQL 的计时 |

`.mode` 支持十余种格式，默认 `duckbox` 功能最丰富；脚本里若想要机器友好输出，常用 `csv` 或 `json`。点命令支持前缀简写（如 `.mo ma` 等价于 `.mode markdown`），但正经脚本里不建议依赖这种缩写。

把 DuckDB 当作流水线的一环时，非交互用法更顺手。把 SQL 文件喂给标准输入：

```bash
duckdb file.db < script.sql
```

也可一行内直接执行查询：

```bash
duckdb :memory: "SELECT 42 AS the_answer"
```

需要隔离不可信脚本的场景，安全模式（Safe Mode）派得上用场。启动时加 `-safe` 参数，或在会话里敲 `.safe_mode`，都会禁用 `.cd`、`.import`、`.read`、`.open`、`.sh` 等触及外部文件系统的点命令，并把 `enable_external_access` 关掉——此后 `ATTACH` 文件、`COPY` 读写、`read_csv/read_parquet` 全部失效。要紧的是，安全模式一旦开启，同一会话内无法再关闭，这是刻意为之的纵深防御设计。

1.5.x 系列给 CLI 加了一项贴心改进：Query Completion ETA。基于 Kalman 滤波（Kalman filter），CLI 能在进度条上估算查询的剩余时间。需留意它的局限——在内存压力大、I/O 瓶颈或网络延迟明显的场景下，估算会变得不准，甚至可能不再单调递减。相关开关藏在 `enable_progress_bar` 与 `progress_bar_time`（触发进度条的最小毫秒数，默认 2000）里，用 `duckdb_settings()` 即可查到。

## 2.4 连接模型概述

"连接"在 DuckDB 语境下远比传统数据库轻。它的内核是进程内（in-process / 嵌入式）架构：数据库引擎直接运行在调用方进程之内，没有独立常驻的服务进程，也没有连接池的概念。这与 PostgreSQL、MySQL 那种客户端—服务器（client-server）模型形成根本对比。

这种差异带来一组可量化的取舍：

| 维度 | 进程内（in-process） | 客户端—服务器（client-server） |
|------|----------------------|--------------------------------|
| 网络开销 | 零，数据就在本地内存 | 每次往返走网络协议 |
| 写入模型 | 单进程读写 + 多写线程（MVCC + 乐观并发） | 独立服务端协调多客户端 |
| 多进程并发写 | 原生不支持 | 服务端天然支持 |
| 部署形态 | 库文件随应用分发 | 需单独运维服务进程 |

在进程内模型下，DuckDB 用 MVCC（多版本并发控制，Multi-Version Concurrency Control）配合乐观并发控制（optimistic concurrency control）支撑单进程内的多线程写入：只要没有写冲突，多个并发写都能成功；当两个线程试图改动同一行时，后到者以冲突错误失败，常规做法是重跑事务。原生格式不支持多进程并发写——这条需求要靠外部方案补足。

把 DuckDB 推向客户端—服务器模型的，是名为 Quack 的远程协议。它在 2026-05-12 发布，以 beta 形态随 v1.5.3 提供，把一个 DuckDB 实例变成可通过 HTTP 访问的服务器，URI 使用 `quack:` 协议头，默认端口 9494。协议栈相当务实：消息走明文或经反向代理的 HTTPS，请求/响应用 `application/duckdb` 序列化（与 WAL 同源的代码路径），复杂类型无损跨线；握手之后一条查询只需一次往返，大结果经后续 `FETCH` 分块流式返回。由于它暴露底层 DuckDB 的完整 SQL 面，默认仅绑定 localhost 并生成随机认证 token——任何面向公网的部署都应前置 TLS 终止的反向代理。Quack 目前仍是 beta，预期在 v2.0 趋于成熟。

## 2.5 第一条查询与安装验证

装好之后，最该做的就是用一行查询确认一切就绪。两条路径都只需几秒钟。

CLI 路径下，直接在交互界面里执行：

```sql
SELECT 'Hello, DuckDB!' AS greeting;
```

或者非交互地一次性验证版本：

```bash
duckdb -c "SELECT version() AS v;"
```

`version()` 会如实回显当前引擎版本，借此可确认装的是不是预期的 v1.5.5。

Python 路径同样直白。确认 `pip install duckdb` 成功之后：

```python
import duckdb

# 内存库上的单行查询；sql() 返回惰性求值的 Relation
result = duckdb.sql("SELECT 42 AS the_answer")
print(result.fetchall())
```

`duckdb.sql()` 返回的是名为 Relation 的"符号化表示"，惰性求值——直到调用 `fetchall()` 取数时才真正执行。若想指向磁盘库而非内存，把连接显式建出来即可：

```python
con = duckdb.connect("file.db")   # 持久库
con.execute("CREATE TABLE IF NOT EXISTS t(i INTEGER);")
con.execute("INSERT INTO t VALUES (1), (2), (3);")
print(con.execute("SELECT sum(i) FROM t").fetchall())
con.close()
```

能稳定打印出结果，便说明二进制、客户端库与运行环境三者已对齐，可以进入后续的正式学习。

## 2.6 本章小结

本章把 DuckDB 的安装、编译与连接三条线索收拢起来，几个真正值得带走的要点是：

- 预编译二进制覆盖绝大多数场景，官方脚本、包管理器与 Docker 镜像三者择一即可；语言客户端走各自的包管理器，CLI 只适合交互、不宜嵌入。
- 源码构建建立在 CMake + C++11 之上，Ninja 是推荐的并行后端；`BUILD_EXTENSIONS` 与 `BUILD_PYTHON=1` 是启用扩展和 Python 绑定的关键开关；验证改动用 sqllogictest 框架的 `unittest` 运行器。
- CLI 的能力集中在点命令上，`.help`、`.mode`、`.tables`、`.schema`、`.import`、`.read`、`.timer` 最常用；安全模式与 1.5.x 新增的 Query Completion ETA 分别服务于隔离与体验两个不同诉求。
- 连接的本质是进程内（in-process）嵌入式架构——零网络、单文件、无服务进程；多进程并发写需借助 Quack（beta）或 DuckLake。
- 验证安装不必复杂：CLI 的 `version()` 与 Python 的 `duckdb.sql(...).fetchall()` 各一行足矣。
