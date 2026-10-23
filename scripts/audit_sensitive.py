#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""发布前敏感信息体检：个人信息 / 本机绝对路径 / 内网地址 / 组织名。

用法
    python scripts/audit_sensitive.py            # 扫描全库
    python scripts/audit_sensitive.py --strict   # 把 WARN 也当失败

退出码：0 = 无 ERROR；1 = 有 ERROR（或 --strict 下有 WARN）。

设计说明
- 只放**通用规则**，不放任何人名/项目名的字面量 —— 否则体检脚本自己就成了泄露源。
- 需要按本项目额外核查的词（客户名、项目号、内部编号），写进
  `scripts/audit_terms.local.txt`（每行一个词，该文件已在 .gitignore 中，
  不要提交）。命中即报 ERROR。
- 本脚本自身不参与扫描。
"""
from __future__ import print_function

import io
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SELF = os.path.basename(os.path.abspath(__file__))
LOCAL_TERMS = os.path.join(ROOT, "scripts", "audit_terms.local.txt")

EXTS = {".md", ".py", ".jou", ".json", ".yml", ".yaml", ".txt", ".sh", ".wbjn", ".csv"}
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv"}

# ---------------------------------------------------------------- ERROR 规则
ERROR_RULES = [
    ("盘符绝对路径", re.compile(r"(?<![\w])[A-Za-z]:[\\/]")),
    ("非系统盘 msys 路径", re.compile(r"(?<![\w])/[defgh]/")),
    ("用户目录硬编码", re.compile(r"C:[\\/]Users[\\/](?!<)")),
    ("邮箱", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
]

# 允许的例外（文档里必须出现的示例值）
ALLOW = [
    re.compile(r"1055@localhost"),          # ANSYS 本地许可证端口写法
    re.compile(r"<[^>]{1,20}>"),            # 占位符本身
    re.compile(r"[Cc]:[\\/]Windows[\\/]"),  # Windows 系统目录，人人相同，不含个人信息
]

# ---------------------------------------------------------------- WARN 规则
WARN_RULES = [
    ("组织/机构名的中文字样", re.compile(
        "有限公司|股份有限公司|集团|研究院|设计院|研究所|大学|学院|工程公司")),
    ("企业后缀英文", re.compile(r"(?<!\w)(?:Ltd|LLC|GmbH)\.?")),
]

# GitHub 页面会正常出现的商标声明，不算泄露
WARN_ALLOW = [re.compile(r"Ansys, Inc\.")]

IPV4 = re.compile(r"(?<![\d.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?![\d.])")
IP_OK = {"127.0.0.1", "0.0.0.0", "255.255.255.255"}


def load_local_terms():
    if not os.path.isfile(LOCAL_TERMS):
        return []
    out = []
    for line in io.open(LOCAL_TERMS, encoding="utf-8", errors="replace"):
        t = line.strip()
        if t and not t.startswith("#"):
            out.append(t)
    return out


def iter_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn == SELF:
                continue
            if os.path.splitext(fn)[1].lower() in EXTS:
                yield os.path.join(dirpath, fn)


def allowed(snippet, allow_list):
    return any(rx.search(snippet) for rx in allow_list)


def scan():
    local = load_local_terms()
    errors, warns = [], []
    files = 0
    for path in iter_files():
        files += 1
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        try:
            txt = io.open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        lines = txt.splitlines()

        for label, rx in ERROR_RULES:
            for m in rx.finditer(txt):
                no = txt[:m.start()].count("\n") + 1
                snippet = lines[no - 1].strip()
                if allowed(snippet, ALLOW):
                    continue
                errors.append((label, rel, no, snippet))

        for m in IPV4.finditer(txt):
            ip = m.group(0)
            if ip in IP_OK:
                continue
            no = txt[:m.start()].count("\n") + 1
            errors.append(("IPv4 地址", rel, no, "%s  ←  %s" % (ip, lines[no - 1].strip())))

        for term in local:
            for m in re.finditer(re.escape(term), txt):
                no = txt[:m.start()].count("\n") + 1
                errors.append(("自定义词表: " + term, rel, no, lines[no - 1].strip()))

        for label, rx in WARN_RULES:
            for m in rx.finditer(txt):
                no = txt[:m.start()].count("\n") + 1
                snippet = lines[no - 1].strip()
                if allowed(snippet, WARN_ALLOW):
                    continue
                warns.append((label, rel, no, snippet))

    return files, errors, warns


def dedupe(rows):
    seen, out = set(), []
    for row in rows:
        key = (row[1], row[2], row[0])
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def main():
    files, errors, warns = scan()
    errors, warns = dedupe(errors), dedupe(warns)

    print("=" * 74)
    print("发布前敏感信息体检")
    print("=" * 74)
    print("扫描文件 %d 个   ERROR %d   WARN %d" % (files, len(errors), len(warns)))
    print("自定义词表: %s" % (("已加载 %d 条" % len(load_local_terms()))
                              if os.path.isfile(LOCAL_TERMS) else "未提供（可选）"))

    for title, rows in (("ERROR（必须清零）", errors), ("WARN（逐条确认）", warns)):
        print("\n" + "-" * 74)
        print(title)
        print("-" * 74)
        if not rows:
            print("  无")
            continue
        for label, rel, no, snippet in rows:
            print("  [%s] %s:%d" % (label, rel, no))
            print("      %s" % snippet[:110])

    strict = "--strict" in sys.argv
    fail = bool(errors) or (strict and bool(warns))
    print("\n结果：%s" % ("FAIL" if fail else "PASS"))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
