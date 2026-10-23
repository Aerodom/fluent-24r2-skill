#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""案例库一致性校验（Fluent 24R2 case library linter）。

检查项
  1. 卡片文件名 / ID / front matter 七个键
  2. `class` 与 `status` 是否为受控词
  3. `reuse_of` 指向是否存在、是否自指
  4. 前缀是否已在 cases/README.md 的前缀登记表里注册
  5. 索引表（中文、英文两份）与卡片文件是否**双向一致**
  6. **索引表状态列与 front matter `status` 是否一致**（两处漂移是历史事故）
  7. **登记闭环**：references/*.md 与 scripts/*.py 是否都在 SKILL.md 里登记；
     SKILL.md 引用的 references/ 文件是否存在
  8. 全库相对链接是否可达
  9. 卡片里 `assets/<ID>/...` 引用是否存在
 10. 提醒：文档里写死"N 张卡"这类数量（会随库增长而失真）

用法
    python scripts/check_cases.py            # 在 skill 根目录运行
    python scripts/check_cases.py --quiet    # 只报错误

退出码：0 = 零 error（有 warning 仍算通过）；1 = 有 error。
"""

import argparse
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASES = os.path.join(ROOT, "cases")
INDEX_ZH = os.path.join(CASES, "README.md")
INDEX_EN = os.path.join(CASES, "README.en.md")

CLASSES = ("compressible-shock", "vof-free-surface", "species-dispersion", "single-phase")
STATUSES = ("verified", "partial", "untested")
KEYS = ("id", "name", "class", "status", "last_run", "keywords", "reuse_of")
CARD_RE = re.compile(r"^([A-Z][A-Za-z]?\d+)-[a-z0-9\-]+\.md$")
FM_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):[ \t]*(.*)$")
INDEX_LINK = re.compile(r"\[([A-Z][A-Za-z]?\d+)\]\(([^)]+\.md)\)")
ASSET = re.compile(r"assets/[A-Za-z0-9_\-]+(?:/[A-Za-z0-9_\-.]+)*")

errors = []
warnings = []


def err(msg):
    errors.append(msg)


def warn(msg):
    warnings.append(msg)


def read(path):
    return io.open(path, encoding="utf-8", errors="replace").read()


def strip_comment(value):
    """去掉 YAML 行尾注释（要求 # 前至少一个空白，避免误伤 URL 里的 #）。"""
    m = re.search(r"[ \t]+#", value)
    return value[:m.start()].rstrip() if m else value.strip()


def front_matter(path):
    lines = read(path).split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    out = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return out
        m = FM_LINE.match(line)
        if m:
            out[m.group(1)] = strip_comment(m.group(2))
    return None


def cards():
    found = {}
    for name in sorted(os.listdir(CASES)):
        if not CARD_RE.match(name):
            continue
        path = os.path.join(CASES, name)
        fm = front_matter(path)
        if fm is None:
            err("%s：缺少 front matter（首行必须是 ---）" % name)
            continue
        found[name] = fm
    return found


def check_front_matter(name, fm):
    missing = [k for k in KEYS if k not in fm]
    if missing:
        err("%s：front matter 缺键 %s" % (name, ", ".join(missing)))
    extra = [k for k in fm if k not in KEYS]
    if extra:
        warn("%s：front matter 有未约定键 %s" % (name, ", ".join(extra)))

    cid = fm.get("id", "")
    m = CARD_RE.match(name)
    if cid != m.group(1):
        err("%s：id=%r 与文件名前缀 %r 不一致" % (name, cid, m.group(1)))

    cls = fm.get("class", "")
    if cls not in CLASSES:
        err("%s：class=%r 不在受控取值 %s" % (name, cls, "/".join(CLASSES)))

    st = fm.get("status", "")
    if st not in STATUSES:
        err("%s：status=%r 不在受控词 %s（中文原文请移到正文的状态行）" % (name, st, "/".join(STATUSES)))

    lr = fm.get("last_run", "")
    if lr not in ("", "—", "-") and not re.match(r"^\d{4}(-\d{2}){0,2}$", lr):
        warn("%s：last_run=%r 建议写成 YYYY-MM" % (name, lr))

    kw = fm.get("keywords", "")
    if not kw.startswith("[") or not kw.endswith("]"):
        err("%s：keywords 必须是方括号列表，当前 %r" % (name, kw))
    elif len([x for x in kw.strip("[]").split(",") if x.strip()]) < 2:
        warn("%s：keywords 少于 2 个，检索时容易漏" % name)

    for key in ("name",):
        if not fm.get(key, "").strip():
            err("%s：%s 为空" % (name, key))


def check_reuse(found):
    for name, fm in found.items():
        ref = fm.get("reuse_of", "").strip().strip('"').strip("'")
        if not ref:
            continue
        if ref == fm.get("id"):
            err("%s：reuse_of 指向自己" % name)
            continue
        if not any(f.get("id") == ref for f in found.values()):
            err("%s：reuse_of=%s 没有对应卡片" % (name, ref))


def registered_prefixes():
    text = read(INDEX_ZH) if os.path.exists(INDEX_ZH) else ""
    return set(re.findall(r"^\|\s*`([A-Z][A-Za-z]?)`\s*\|", text, re.M))


def check_prefix(found):
    reg = registered_prefixes()
    if not reg:
        warn("cases/README.md 里没找到前缀登记表（| `L` | … |）")
        return
    for name, fm in found.items():
        p = re.match(r"^([A-Z][A-Za-z]?)", fm.get("id", ""))
        if p and p.group(1) not in reg:
            err("%s：前缀 %r 未在 cases/README.md 的前缀登记表注册" % (name, p.group(1)))


def index_entries(path):
    if not os.path.exists(path):
        err("%s 不存在" % os.path.basename(path))
        return {}
    out = {}
    for line in read(path).split("\n"):
        if not line.startswith("|"):
            continue
        for cid, target in INDEX_LINK.findall(line):
            out[cid] = target
    return out


def check_index(found):
    by_id = {fm.get("id"): name for name, fm in found.items()}
    zh = index_entries(INDEX_ZH)
    en = index_entries(INDEX_EN)

    for label, idx in (("README.md", zh), ("README.en.md", en)):
        for cid, target in idx.items():
            if cid not in by_id:
                err("%s：索引里有 %s，但 cases/ 下没有这张卡" % (label, cid))
                continue
            if os.path.normpath(target) != by_id[cid]:
                err("%s：%s 的链接指向 %s，实际文件是 %s" % (label, cid, target, by_id[cid]))
        for cid in sorted(by_id):
            if cid not in idx:
                err("%s：卡片 %s 没进索引表（新增卡片必须补两行）" % (label, cid))
    if zh and en and set(zh) != set(en):
        warn("两份索引的条目不一致：仅中文 %s，仅英文 %s"
             % (sorted(set(zh) - set(en)) or "无", sorted(set(en) - set(zh)) or "无"))


def check_links():
    md = []
    for base, _dirs, files in os.walk(ROOT):
        if os.sep + "." in base:
            continue
        for f in files:
            if f.endswith(".md"):
                md.append(os.path.join(base, f))
    for path in md:
        text = read(path)
        for target in re.findall(r"\]\(([^)\s]+)\)", text):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target = target.split("#")[0]
            if not target:
                continue
            resolved = os.path.normpath(os.path.join(os.path.dirname(path), target))
            if not os.path.exists(resolved):
                err("%s：相对链接失效 -> %s" % (os.path.relpath(path, ROOT), target))


def check_assets(found):
    for name in found:
        text = read(os.path.join(CASES, name))
        for ref in set(ASSET.findall(text)):
            if not os.path.exists(os.path.join(CASES, ref)):
                err("%s：引用素材不存在 -> cases/%s" % (name, ref))


# 索引状态列必须以受控词开头，后面括号里可以写人话。
STATUS_TOK = re.compile(r"^[*★\s]*(verified|partial|untested)[\s（(]", re.I)
COUNT_CLAIM = re.compile(r"\d+\s*(?:张卡|个案例|张卡片)")


def index_status(path):
    """取每行索引的最后一列（状态列）。"""
    out = {}
    if not os.path.exists(path):
        return out
    for line in read(path).split("\n"):
        if not line.startswith("|"):
            continue
        m = INDEX_LINK.search(line)
        if not m:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3:
            out[m.group(1)] = cells[-1]
    return out


def check_index_status(found):
    """索引状态列 vs front matter status —— 这两处最容易各写各的。"""
    by_id = {fm.get("id"): fm for fm in found.values()}
    for label, path in (("cases/README.md", INDEX_ZH), ("cases/README.en.md", INDEX_EN)):
        for cid, cell in index_status(path).items():
            fm = by_id.get(cid)
            if fm is None:
                continue
            m = STATUS_TOK.match(cell)
            if not m:
                err("%s：%s 的状态列必须以 verified / partial / untested 开头"
                    "（后面可跟括号说明），当前 %r" % (label, cid, cell))
                continue
            if m.group(1).lower() != str(fm.get("status", "")).lower():
                err("%s：%s 索引状态是 %r，但卡片 front matter 写的是 %r"
                    % (label, cid, m.group(1).lower(), fm.get("status")))


def check_registration():
    """登记闭环：没被登记的文件，下一个人等于它不存在。"""
    skill_path = os.path.join(ROOT, "SKILL.md")
    if not os.path.exists(skill_path):
        err("缺少 SKILL.md")
        return
    skill = read(skill_path)

    ref_dir = os.path.join(ROOT, "references")
    if os.path.isdir(ref_dir):
        for name in sorted(os.listdir(ref_dir)):
            if name.endswith(".md") and name not in skill:
                err("references/%s 未在 SKILL.md §12 资源地图登记" % name)

    scr_dir = os.path.join(ROOT, "scripts")
    if os.path.isdir(scr_dir):
        for name in sorted(os.listdir(scr_dir)):
            if name.endswith(".py") and name not in skill:
                err("scripts/%s 未在 SKILL.md §4.4 脚本清单登记" % name)

    for ref in sorted(set(re.findall(r"`(references/[A-Za-z0-9_\-]+\.md)`", skill))):
        if not os.path.exists(os.path.join(ROOT, ref)):
            err("SKILL.md 引用了不存在的 %s" % ref)
    for ref in sorted(set(re.findall(r"`(scripts/[A-Za-z0-9_\-]+\.py)`", skill))):
        if not os.path.exists(os.path.join(ROOT, ref)):
            err("SKILL.md 引用了不存在的 %s" % ref)


def check_counts():
    """写死"N 张卡"会在库长大之后变成假话。"""
    for base, _dirs, files in os.walk(ROOT):
        if os.sep + "." in base:
            continue
        for f in sorted(files):
            if not f.endswith(".md"):
                continue
            path = os.path.join(base, f)
            for i, line in enumerate(read(path).split("\n"), 1):
                m = COUNT_CLAIM.search(line)
                if m:
                    warn("%s:%d 写死了数量「%s」，库一扩充就会失真"
                         % (os.path.relpath(path, ROOT), i, m.group(0)))


def check_templates():
    for tmpl in ("_TEMPLATE.md", "_TEMPLATE.en.md"):
        path = os.path.join(CASES, tmpl)
        if not os.path.exists(path):
            err("缺少模板 %s" % tmpl)
            continue
        fm = front_matter(path)
        if fm is None:
            err("%s：缺少 front matter" % tmpl)
            continue
        missing = [k for k in KEYS if k not in fm]
        if missing:
            err("%s：front matter 缺键 %s" % (tmpl, ", ".join(missing)))
        if fm.get("status") not in STATUSES:
            err("%s：模板的 status 应为受控词之一，当前 %r" % (tmpl, fm.get("status")))


def main():
    ap = argparse.ArgumentParser(description="案例库一致性校验")
    ap.add_argument("--quiet", action="store_true", help="只输出错误与总结")
    args = ap.parse_args()

    found = cards()
    for name in sorted(found):
        check_front_matter(name, found[name])
    check_reuse(found)
    check_prefix(found)
    check_index(found)
    check_index_status(found)
    check_registration()
    check_counts()
    check_links()
    check_assets(found)
    check_templates()

    if not args.quiet:
        print("卡片总数：%d" % len(found))
        for cls in CLASSES:
            ids = sorted(fm.get("id") for fm in found.values() if fm.get("class") == cls)
            if ids:
                print("  %-20s %2d  %s" % (cls, len(ids), " ".join(ids)))
        for st in STATUSES:
            print("  status=%-9s %2d" % (st, sum(1 for fm in found.values() if fm.get("status") == st)))
        print("")

    for w in warnings:
        print("[warn ] " + w)
    for e in errors:
        print("[ERROR] " + e)
    if warnings and not args.quiet:
        print("")
    print("%s  错误 %d 项，警告 %d 项" % ("通过" if not errors else "未通过", len(errors), len(warnings)))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
