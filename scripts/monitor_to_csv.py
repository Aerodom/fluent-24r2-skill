#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
把 Fluent 的 report-files 监控文本转成下游/后处理可用的 CSV。

输出的 report-files 文本形如（引号可省）：

    "mon_file"
    "Time Step" "mon_p5 etc.."
    ("Time Step" "mon_p5" "mon_p10" "mon_p20" "flow-time")
    0 101325.015625 101324.9375 101325.015625 0
    1 101325.015625 101324.9375 101325.015625 0.0005
    ...

注意两点（都是实测踩过的）：
  * 列序是 ["Time Step", <各测点...>, "flow-time"] —— **flow-time 在最后一列**，
    不能想当然地认为第二列是时间。
  * 值一般是绝对压力（Pa）。超压 = 值 − 操作压力（默认 101325）。

本脚本优先读取第三行的带引号表头来确定列含义，因此对列序变化免疫。

同时打印每个测点的三个关键量：
  * 全程峰值          —— 可能含边界反射伪峰
  * 前 N% 窗口内首峰  —— 通常才是干净的入射首峰
  * 到达时间          —— 超压首次越过阈值的时刻（默认 1000 Pa）

为什么默认只看前 60% 窗口：
  若计算域外边界是 wall（未改 pressure-far-field），激波打到边界会反射回来，
  在远场测点叠加出一个幅值可能更高的假峰。若把它当作衰减样本，远场超压被显著抬高，
  据此拟合的破坏半径会明显偏大。用时间窗截取可以规避。

用法：
    python monitor_to_csv.py --input monitor_p_1_1.txt --out overpressure.csv
    python monitor_to_csv.py --input m.txt --out o.csv --names p5,p10,p20
    python monitor_to_csv.py --input m.txt --out o.csv --gauge          # 源数据已是表压
    python monitor_to_csv.py --input m.txt --out o.csv --window 0.6 --arrival-threshold 1000
"""
import argparse
import csv
import re
import sys
from collections import Counter

NUM = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def split_fields(line):
    """按逗号或空白切分，去掉外层引号与括号。"""
    if "," in line:
        toks = line.split(",")
    else:
        toks = line.replace("(", " ").replace(")", " ").split()
    return [t.strip().strip('"') for t in toks if t.strip()]


def parse(path):
    """返回 (header_names 或 None, rows)。"""
    header = None
    rows = []
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            # 带引号的列名行（形如 ("Time Step" "mon_p5" ... "flow-time")）
            if header is None and line.startswith("(") and '"' in line:
                names = re.findall(r'"([^"]+)"', line)
                if len(names) >= 2:
                    header = names
            toks = split_fields(line)
            if len(toks) < 2:
                continue
            if all(NUM.fullmatch(t) for t in toks):
                rows.append([float(t) for t in toks])
    return header, rows


def first_crossing(t, p, level):
    for i in range(1, len(t)):
        if p[i] >= level > p[i - 1]:
            f = (level - p[i - 1]) / (p[i] - p[i - 1])
            return t[i - 1] + f * (t[i] - t[i - 1])
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--names", default=None, help="覆盖测点名，逗号分隔，如 p5,p10,p20")
    ap.add_argument("--op-pressure", type=float, default=101325.0)
    ap.add_argument("--gauge", action="store_true", help="源数据已是表压，不再减操作压力")
    ap.add_argument("--window", type=float, default=0.6, help="首峰搜索窗口占比，默认 0.6")
    ap.add_argument("--arrival-threshold", type=float, default=1000.0, help="到达判据 Pa")
    ap.add_argument("--decimal", type=int, default=6)
    args = ap.parse_args()

    header, rows = parse(args.input)
    if not rows:
        sys.exit("未从 %s 解析出任何数值行" % args.input)

    # 统一列数：取出现次数最多的长度
    mode_len = Counter(len(r) for r in rows).most_common(1)[0][0]
    rows = [r for r in rows if len(r) == mode_len]

    if header and len(header) == mode_len:
        low = [h.lower() for h in header]
        step_i = low.index("time step") if "time step" in low else None
        time_i = None
        for key in ("flow-time", "flow time", "flow_time"):
            if key in low:
                time_i = low.index(key)
                break
        if time_i is None:
            time_i = mode_len - 1
        data_i = [i for i in range(mode_len) if i not in (step_i, time_i)]
        auto_names = [header[i] for i in data_i]
        print("表头: %s" % header)
        print("时间列 = %d (%s) | 数据列 = %s" % (time_i, header[time_i], auto_names))
    elif mode_len == 2:
        time_i, data_i, auto_names = 0, [1], ["p1"]
        print("未找到带引号表头，按两列 (time, p) 解析")
    else:
        time_i, data_i = mode_len - 1, list(range(1, mode_len - 1))
        auto_names = ["p%d" % (i) for i in range(1, len(data_i) + 1)]
        print("未找到带引号表头，按 (步号, 数据..., flow-time) 解析")

    names = [x.strip() for x in args.names.split(",")] if args.names else []
    if len(names) != len(data_i):
        names = auto_names

    times = [r[time_i] for r in rows]
    off = 0.0 if args.gauge else args.op_pressure
    series = {nm: [r[i] - off for r in rows] for nm, i in zip(names, data_i)}

    with open(args.out, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["time_s"] + ["overpressure_%s_Pa" % nm for nm in names])
        for i, t in enumerate(times):
            w.writerow([("%.{0}f".format(args.decimal)) % t] +
                       ["%.3f" % series[nm][i] for nm in names])

    print()
    print("wrote %s  rows=%d" % (args.out, len(times)))
    print("时间范围 %.6f ~ %.6f s" % (times[0], times[-1]))
    print()
    hdr = "%-10s %14s %16s %14s" % ("测点", "全程峰值Pa", "首峰Pa(窗口%.1f)" % args.window,
                                    "到达s@%gPa" % args.arrival_threshold)
    print(hdr)
    k = max(1, int(len(times) * args.window))
    for nm in names:
        p = series[nm]
        arr = first_crossing(times, p, args.arrival_threshold)
        print("%-10s %14.1f %16.1f %14s" % (
            nm, max(p), max(p[:k]), ("%.5f" % arr) if arr is not None else "-"))
    print()
    print("提示：若'全程峰值'明显高于'首峰'，说明该测点受了边界反射影响；")
    print("      做衰减拟合时应使用首峰，并在结果口径中说明。")


if __name__ == "__main__":
    main()
