#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
运行一个 Fluent journal 并回显关键日志。

用途：把"启动 fluent.exe + 落盘日志 + 抓取 journal 执行段落 + 返回退出码"
固定成一条命令，避免每次手敲一长串命令行。

用法：
    python run_fluent_journal.py --journal solve.jou
    python run_fluent_journal.py --journal solve.jou --t 4 --tail 80
    python run_fluent_journal.py --journal r.jou --fluent "%AWP_ROOT242%/fluent/ntbin/win64/fluent.exe"

重要：
  1. 本脚本以子进程方式启动 fluent。若运行它的进程（例如 agent 会话）结束时
     子进程会被一并终止。需要数小时独立运行求解时，请改用 Windows 任务计划。
  2. 默认并行进程数 4。不要调到 8：会报 MPIDU_Init_shm_alloc 失败。
"""
import argparse
import os
import re
import subprocess
import sys

DEFAULT_FLUENT = r"%AWP_ROOT242%/fluent/ntbin/win64/fluent.exe"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--journal", required=True, help="要执行的 .jou 文件")
    ap.add_argument("--fluent", default=DEFAULT_FLUENT, help="fluent.exe 路径")
    ap.add_argument("--dim", default="3ddp", help="维度与精度，默认 3ddp（3D 双精度）")
    ap.add_argument("--t", type=int, default=4, help="并行进程数，默认 4（不要用 8）")
    ap.add_argument("--log", default=None, help="日志路径，默认与 journal 同名 .log")
    ap.add_argument("--tail", type=int, default=60, help="回显日志尾部行数")
    ap.add_argument("--timeout", type=int, default=0, help="超时秒数，0 表示不设")
    args = ap.parse_args()

    journal = os.path.abspath(args.journal)
    if not os.path.isfile(journal):
        sys.exit("journal 不存在: %s" % journal)
    if not os.path.isfile(args.fluent):
        sys.exit("fluent 不存在: %s" % args.fluent)

    log = args.log or os.path.splitext(journal)[0] + ".log"
    cmd = [args.fluent, args.dim, "-gu", "-t%d" % args.t, "-i", journal]

    print("EXEC: %s" % " ".join('"%s"' % c if " " in c else c for c in cmd))
    print("LOG : %s" % log)
    with open(log, "w", encoding="utf-8", errors="replace") as fh:
        try:
            proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT,
                                  timeout=(args.timeout or None))
            code = proc.returncode
        except subprocess.TimeoutExpired:
            fh.write("\n[run_fluent_journal] TIMEOUT after %ds\n" % args.timeout)
            code = -999

    print("EXIT: %s" % code)

    text = open(log, encoding="utf-8", errors="replace").read()
    parts = re.split(r"Reading journal", text)
    body = parts[-1] if len(parts) > 1 else text

    # 抓取有助于快速定位问题的行
    keys = ("Error", "error", "invalid", "Invalid", "Warning", "warning",
            "Flow time", "Iteration", "SIGSEGV", "stopped", "Segmentation",
            "not available", "Could not", "Unable", "failed")
    hits = [ln for ln in body.splitlines() if any(k in ln for k in keys)]
    if hits:
        print("\n--- 关键行 (%d) ---" % len(hits))
        for ln in hits[-40:]:
            print("  " + ln.strip())

    print("\n--- 日志尾部 %d 行 ---" % args.tail)
    for ln in text.splitlines()[-args.tail:]:
        print("  " + ln.rstrip())

    sys.exit(0 if code == 0 else 1)


if __name__ == "__main__":
    main()
