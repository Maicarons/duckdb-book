---
layout: home

hero:
  name: "DuckDB 数据库从入门到进阶"
  text: "基于官方文档 v1.5.5 的系统性实战指南"
  tagline: 进程内 · 列式 · 向量化 —— 一本既能入门、又能进阶的 DuckDB 中文专著
  actions:
    - theme: brand
      text: 开始阅读
      link: /chapters/chapter01
    - theme: alt
      text: 下载 PDF / 讲义
      link: /downloads
  image:
    alt: DuckDB 书封
    light: /downloads/cover-light.svg
    dark: /downloads/cover-dark.svg

features:
  - icon: 📚
    title: 由浅入深，七大板块
    details: 基础入门 → 数据工程 → 客户端集成 → 扩展机制 → 性能运维 → 原理剖析 → 实战总结，共 19 章、7 大部分。
  - icon: 🎯
    title: 事实可溯，版本精确
    details: 内容以 DuckDB v1.5.5 官方文档为基线整理，关键能力均标注所属版本（如 DuckLake 1.0、Quack 协议等）。
  - icon: 🧪
    title: 代码可运行，风格统一
    details: 所有示例 SQL / Shell / Python 均可复现，默认基于 v1.5.5，并显式标注版本差异。
  - icon: 📎
    title: 配套讲义与整书 PDF
    details: 提供教学 PPTX 讲义与整书 PDF，支持在线阅览与一键下载。
---

## 这本书讲什么

DuckDB 正在重新定义“分析型数据库”的部署形态：它不走“起一个服务、连一个集群”的老路，而是把自己做成了一个**进程内的嵌入式引擎**——一条 `pip install duckdb`，就能在笔记本、数据管道、边缘设备上直接跑起列式存储与向量化执行的分析查询。

当数据规模还没到需要分布式系统的程度、却又远超电子表格所能承受的体量时，DuckDB 恰好卡在那个最舒服的区间：轻量、零运维、对文件与 Arrow 生态天生友好。

本书完全建立在 DuckDB 官方文档的基础之上，按“由浅入深、面面俱到”的原则重新编排，力求给中文世界的数据库学习者与从业者一本“既能入门、又能进阶”的 DuckDB 专著。

## 如何阅读

- **完全的初学者**：建议从第 1 章顺序读到第 6 章，把基础打牢。
- **有 SQL / 数据库经验**：可跳过入门铺垫，直接从数据工程或客户端集成部分切入。
- **想理解“为什么快”**：第六部分（原理剖析）值得精读。

每章末尾都配有“本章小结”，便于复习与速查。建议读者在自己的环境中动手敲一遍代码——DuckDB 的“免服务、单文件”特性，让即时实验的成本几乎为零。
