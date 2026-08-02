# DuckDB 数据库从入门到进阶

> 基于 **DuckDB v1.5.5** 官方文档的系统性实战指南 —— 进程内 · 列式 · 向量化的分析型数据库，从入门到进阶。

[![Deploy to GitHub Pages](https://github.com/Maicarons/duckdb-book/actions/workflows/deploy.yml/badge.svg)](https://github.com/Maicarons/duckdb-book/actions/workflows/deploy.yml)

- 📖 在线文档站（GitHub Pages）：<https://maicarons.github.io/duckdb-book/>
- 📘 整书 PDF / DOCX、教学 PPTX 讲义：见站点内「下载与资源」页

## 本书结构

全书分为 **7 大部分、共 19 章**：

| 部分 | 章节 | 主题 |
| --- | --- | --- |
| 第一部分 基础入门 | 第 1–6 章 | DuckDB 是什么、安装、数据类型与 SQL 方言、建表写数、查询语言、函数与表达式 |
| 第二部分 数据工程 | 第 7–8 章 | 文件直读、数据导出与持久化 |
| 第三部分 客户端与生态集成 | 第 9–12 章 | Python 客户端、其他客户端、外部数据库集成、云存储与远程数据 |
| 第四部分 扩展机制 | 第 13–14 章 | 扩展体系、关键扩展（JSON / Spatial / httpfs / postgres / iceberg / ducklake 等） |
| 第五部分 性能与运维 | 第 15–16 章 | 配置与性能调优、运维手册 |
| 第六部分 原理剖析 | 第 17 章 | 解析、优化、向量化执行与存储格式 |
| 第七部分 实战与总结 | 第 18–19 章 | 应用场景实践、总结与展望 |

另含「参考资料」板块，收录对官方文档（Clients / Configuration / Data I/O / Extensions / Guides / Internals / SQL 函数·语法·语句·类型 等）的研读摘要。

## 仓库结构（GitHub 结构）

```text
duckdb-book/
├── .github/workflows/deploy.yml   # GitHub Pages 自动构建与部署
├── docs/                          # VitePress 内容根目录
│   ├── .vitepress/                # 站点配置与主题
│   ├── public/downloads/          # PDF / DOCX / PPTX / 封面 SVG（发布资源）
│   ├── chapters/                  # 19 章正文（规范性标题）
│   ├── reference/                 # 官方文档研读摘要（10 篇）
│   ├── index.md                   # 首页
│   ├── preface.md                 # 前言
│   └── downloads.md               # 下载与在线阅览
├── tools/                         # 内容生产流水线
│   ├── build_book.py              # 19 章 -> 整书 Markdown
│   ├── build_pptx.py              # 19 章 -> 教学 PPTX
│   ├── normalize_chapters.py      # 章节标题规范化
│   └── parameter_card.md          # 项目参数卡（跨章一致性基础）
├── manuscript/book.md             # 由 19 章汇编而成的整书 Markdown
├── package.json                   # VitePress 依赖与脚本
└── README.md
```

## 本地开发

```bash
npm install
npm run docs:dev      # 本地预览 http://localhost:5173
npm run docs:build    # 构建到 docs/.vitepress/dist
```

> 注意：仓库 `base` 为 `/duckdb-book/`，对应项目页路径；本地 `docs:dev` 预览时资源以根路径解析，属正常现象，构建产物部署到 GitHub Pages 后路径正确。

## 内容生产流水线

```bash
python tools/normalize_chapters.py   # 统一章节标题（第 NN 章 …）
python tools/build_book.py            # 生成 manuscript/book.md（整书）
python tools/build_pptx.py            # 生成教学 PPTX 至 public/downloads
```

整书 PDF 由 `DuckDB从入门到进阶.docx` 经 Pandoc + XeLaTeX（CJK 字体：Microsoft YaHei）转换生成，存放于 `docs/public/downloads/duckdb-book.pdf`。

## 版权与免责声明

本书由 AI 辅助文档生成流程编撰，内容以 DuckDB v1.5.5 官方文档为基线整理，仅供学习与技术参考。DuckDB 及其文档由 DuckDB 社区在相应开源许可（主要为 MIT）下发布，相关商标与版权归原权利人所有。涉及生产环境的关键决策，请以官方文档与社区最新结论为准。详见站点内免责声明与 `DISCLAIMER.md`。
