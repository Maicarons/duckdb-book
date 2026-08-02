#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Normalize the 19 chapter markdown files for VitePress.

Fixes:
  * Ensure every chapter has a single top-level H1 title of the form
    "# 第 NN 章 <title>" (consistent spacing, no stray "第2章"/"第 2章").
  * Chapter 16 originally started with an H2 ("## 16. 运维手册"); promote
    all of its real (non-code) headings by one level so the title becomes H1.
"""
import os
import re

CHAPTERS_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "chapters")


def normalize(text, num):
    lines = text.split("\n")
    # find min heading level among real (non-code) headings
    in_code = False
    levels = []
    for ln in lines:
        s = ln.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = re.match(r"^(#{1,6})\s", ln)
        if m:
            levels.append(len(m.group(1)))
    minlvl = min(levels) if levels else 2
    promo = minlvl - 1  # shift everything up so the top heading becomes H1

    out = []
    in_code = False
    title_rewritten = False
    for ln in lines:
        s = ln.strip()
        if s.startswith("```"):
            in_code = not in_code
            out.append(ln)
            continue
        if in_code:
            out.append(ln)
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", ln)
        if m and not title_rewritten:
            lvl = len(m.group(1)) - promo
            if lvl < 1:
                lvl = 1
            content = m.group(2).strip()
            # strip any existing "第 N 章 / 第N章 / N." prefix
            cleaned = re.sub(r"^第\s*\d+\s*[.章]?\s*", "", content).strip()
            cleaned = re.sub(r"^\d+\.\s*", "", cleaned).strip()
            new_title = "第 %02d 章 %s" % (num, cleaned) if num < 10 else "第 %d 章 %s" % (num, cleaned)
            out.append("# %s" % new_title)
            title_rewritten = True
        elif m:
            lvl = len(m.group(1)) - promo
            if lvl < 1:
                lvl = 1
            out.append("%s %s" % ("#" * lvl, m.group(2).strip()))
        else:
            out.append(ln)
    return "\n".join(out)


def main():
    for i in range(1, 20):
        path = os.path.join(CHAPTERS_DIR, "chapter%02d.md" % i)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        new = normalize(text, i)
        with open(path, "w", encoding="utf-8") as f:
            f.write(new)
        # report first line
        first = new.split("\n", 1)[0]
        print("chapter%02d -> %s" % (i, first))


if __name__ == "__main__":
    main()
