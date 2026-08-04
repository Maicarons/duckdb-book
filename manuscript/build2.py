#!/usr/bin/env python3
# Rebuild book.md from the (clean, fixed) chapter sources at docs/chapters/,
# reusing the correct preface + disclaimer from the existing book.md.
# Only normalizes the zero-padded chapter title line; body passed through as-is.
import re, os

ROOT = r"G:\workspace\duckdb-1.5.5\mybook"
CHAPTERS = os.path.join(ROOT, "docs", "chapters")
BOOK = os.path.join(ROOT, "manuscript", "book.md")

PARTS = [
    ("第一部分 基础入门", [1, 2, 3, 4, 5, 6]),
    ("第二部分 数据工程", [7, 8]),
    ("第三部分 客户端与生态集成", [9, 10, 11, 12]),
    ("第四部分 扩展机制", [13, 14]),
    ("第五部分 性能与运维", [15, 16]),
    ("第六部分 原理剖析", [17]),
    ("第七部分 实战与总结", [18, 19]),
]

PB = ["```{=openxml}", '<w:p><w:r><w:br w:type="page"/></w:r></w:p>', "```"]


def normalize_title(num, text):
    s = text.lstrip("#").strip()
    # clean form: "第 01 章 xxx" or "第 1 章 xxx"
    m = re.match(r"^第\s*0*(\d+)\s*章\s*(.*)$", s)
    if m:
        return "# 第 %d 章 %s" % (int(m.group(1)), m.group(2).strip())
    # legacy form: "16. 运维手册"
    m = re.match(r"^0*(\d+)\.\s*(.*)$", s)
    if m:
        return "# 第 %d 章 %s" % (int(m.group(1)), m.group(2).strip())
    return "# 第 %d 章 %s" % (num, s)


def normalize_chapter(num, path):
    lines = open(path, encoding="utf-8").read().splitlines()
    out = []
    for i, l in enumerate(lines):
        if i == 0 and l.lstrip().startswith("#"):
            out.append(normalize_title(num, l))
        else:
            out.append(l)
    return out


def main():
    raw = open(BOOK, encoding="utf-8").read().splitlines()
    i_first_part = next(k for k, l in enumerate(raw) if l.startswith("# 第一部分"))
    i_disc = next(k for k, l in enumerate(raw) if l.startswith("# 版权"))
    preface = raw[:i_first_part]
    disclaimer = raw[i_disc:]

    out_lines = list(preface)
    for pname, chs in PARTS:
        out_lines += ["", "# " + pname, ""] + PB
        for j, c in enumerate(chs):
            if j > 0:
                out_lines += PB
            out_lines += normalize_chapter(c, os.path.join(CHAPTERS, "chapter%02d.md" % c))

    out_lines += PB
    out_lines += list(disclaimer)

    with open(BOOK, "w", encoding="utf-8") as f:
        f.write("\n".join(out_lines) + "\n")

    h1 = [l for l in out_lines if re.match(r"^# ", l)]
    real = [l for l in h1 if re.match(r"^# (前言|第.+部分|第 \d+ 章|版权)", l)]
    print("real structural H1:", len(real), "(expect 28)")
    c9 = next(k for k, l in enumerate(out_lines) if l == "# 第 9 章 Python 客户端深入")
    c10 = next(k for k, l in enumerate(out_lines) if l == "# 第 10 章 其他客户端")
    depth = 0
    for l in out_lines[c9:c10]:
        if l.strip().startswith("```"):
            depth = 1 - depth
    print("chapter9 region fence depth:", depth, "(expect 0)")


if __name__ == "__main__":
    main()
