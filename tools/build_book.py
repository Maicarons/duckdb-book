#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Assemble the 19 DuckDB chapters into one continuous Markdown manuscript.

Fixes applied during assembly:
  * Chapter 16 starts with an H2 title (bug) -> promote all its real headings by one level.
  * Normalize every chapter H1 title to the form "第 X 章 <rest>".
  * Insert 7 part dividers and page breaks (raw openxml) for a proper book layout.
  * Code fences are tracked so in-code "# comments" are never treated as headings.
"""
import re
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CHAPTERS_DIR = os.path.join(REPO, "docs", "chapters")
OUT_DIR = os.path.join(REPO, "manuscript")
PREFACE = os.path.join(REPO, "docs", "preface.md")
os.makedirs(OUT_DIR, exist_ok=True)

# chapter number -> part title (inserted right before that chapter)
PARTS = {
    1: "第一部分 基础入门",
    7: "第二部分 数据工程",
    9: "第三部分 客户端与生态集成",
    13: "第四部分 扩展机制",
    15: "第五部分 性能与运维",
    17: "第六部分 原理剖析",
    18: "第七部分 实战与总结",
}

PAGE_BREAK = "\n```{=openxml}\n<w:p><w:r><w:br w:type=\"page\"/></w:r></w:p>\n```\n"


def normalize_chapter(text):
    lines = text.split("\n")
    # Pass 1: find min heading level among REAL (non-code) headings
    in_code = False
    levels = []
    for ln in lines:
        if ln.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = re.match(r"^(#{1,6})\s", ln)
        if m:
            levels.append(len(m.group(1)))
    minlvl = min(levels) if levels else 1
    promo = minlvl - 1  # shift everything up so the top heading becomes H1

    # Pass 2: transform
    out = []
    in_code = False
    for ln in lines:
        if ln.strip().startswith("```"):
            in_code = not in_code
            out.append(ln)
            continue
        if in_code:
            out.append(ln)
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", ln)
        if m:
            lvl = len(m.group(1)) - promo
            if lvl < 1:
                lvl = 1
            content = m.group(2).strip()
            if lvl == 1:  # normalize chapter title
                tm = re.match(r"^第?\s*(\d+)\s*[.章]?\s*(.*)$", content)
                if tm:
                    content = "第 %s 章 %s" % (tm.group(1), tm.group(2).strip())
            out.append("%s %s" % ("#" * lvl, content))
        else:
            out.append(ln)
    return "\n".join(out).strip()


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


parts = []
# Preface (starts on its own page after the auto-generated TOC)
preface = read(PREFACE).strip()
parts.append(PAGE_BREAK + preface)

for i in range(1, 20):
    if i in PARTS:
        parts.append(PAGE_BREAK + "# %s" % PARTS[i])
    ch = read(os.path.join(CHAPTERS_DIR, "chapter%02d.md" % i))
    ch = normalize_chapter(ch)
    parts.append(PAGE_BREAK + ch)

disclaimer = """
# 版权与免责声明

本书《DuckDB 数据库从入门到进阶》由 AI 辅助文档生成流程编撰，内容以 DuckDB v1.5.5 官方文档为基线整理而成，仅供学习与技术参考之用。

DuckDB 及其文档由 DuckDB 社区与相关权利人在相应开源许可（主要为 MIT）下发布；本书不主张对 DuckDB 本身的任何知识产权，相关商标与版权归原权利人所有。

免责声明：尽管本书已尽量对照官方文档核验事实与语法，但软件版本演进迅速，文中个别参数、默认值或行为可能随版本更新而变化。在涉及生产环境的关键决策（安全加固、并发方案、版本升级、容量规划等）时，请务必以官方文档与社区的最新结论为准。因使用本书内容所导致的任何直接或间接后果，编撰方不承担责任。

—— 编撰团队，2026 年 8 月
"""
parts.append(PAGE_BREAK + disclaimer.strip())

body = "\n\n".join(parts)

metadata = """---
title: DuckDB 数据库从入门到进阶
subtitle: 基于 DuckDB v1.5.5 官方文档的系统性实战指南
author: WorkBuddy 文档生成团队
date: 2026 年 8 月
lang: zh
---
"""

out_path = os.path.join(OUT_DIR, "book.md")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(metadata + "\n" + body + "\n")

print("Built", out_path, os.path.getsize(out_path), "bytes")
