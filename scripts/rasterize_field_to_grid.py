#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
场数据（.xyz）→ 下游栅格掩膜宽表 + 长表 CSV
================================================================
口径与 post 云图保持一致，保证下游动画与汇报云图逐格可比。

链路：
    so2_<step>.xyz  (cellnumber x y z <var>)
       → 特征高度切片带
       → 最近邻插值到 NG×NG 细网格
       → 阈值化（红 / 黄）
       → （NX>=50 自动）形态学去噪
       → 块内占比聚合到 NX×NX
       → 宽表 <prefix>_zone_<NX>x<NX>.csv   (time, R_0..R_n, Y_0..Y_n)
       → 长表 <prefix>_grid_<NX>x<NX>.csv   (time, cell, red, yellow，无表头)

★ 三个必须遵守的口径（都踩过坑，见 references/field-export-and-rasterize.md）：
  1. 切片带高度必须显式给定并写进文档（本脚本打印 + 写入摘要 CSV 注释）。
  2. 最近邻用「逐点 argmin」，**不要**用 scipy.interpolate.griddata(method='nearest')。
     后者基于 Delaunay 凸包，实测面积偏小 20%（40.57 → 32.27 m²）。
  3. 二值掩膜**禁用线性插值**（实测面积 40.6 → 80.9 m²）。
  4. cell 编号 k = i*NZ + j，i → X（横），j → Z（纵）；下游消费端与渲染脚本必须一致。

用法：
    python rasterize_field_to_grid.py <输入目录> <输出目录> [每边格数]

    例：python rasterize_field_to_grid.py <CASE_DIR>/export <CASE_DIR>/downstream 20

常用参数覆盖（改文件内 CONFIG 或加命令行参数）：
    --prefix so2        .xyz 文件名前缀（默认 so2）
    --var  molef-so2    场变量名（默认按表头自动识别最后一列）
    --y0 1.5 --dy 0.10  切片带中心与半厚（默认呼吸高度）
    --red 1e-4 --yellow 2e-5   阈值
    --block-ratio 0.5   块内危险面积占比阈值
    --no-smooth         关闭去噪（默认 NX>=50 自动开启）

依赖 numpy + scipy（用装好它们的虚拟环境，例：<venv>/Scripts/python.exe）
"""
import argparse
import csv
import glob
import os
import sys

import numpy as np
from scipy import ndimage

# ---- 默认 CONFIG（可用命令行覆盖）----
RED_THRESHOLD = 1e-4     # 红（致死）
YELLOW_THRESHOLD = 2e-5  # 黄（预警）
Y0 = 1.5                 # 切片带中心（m）
DY = 0.10                # 切片带半厚（m）
NG = 100                 # 细网格 100×100
BLOCK_RATIO = 0.5        # 块内危险面积占比阈值
LIM_X = (0.0, 10.0)      # 房间 X 范围（m）
LIM_Z = (0.0, 10.0)      # 房间 Z 范围（m）
SMOOTH_MIN_NX = 50       # NX >= 此值时自动去噪
DT_PER_STEP = None       # 步号 → 时间 的 dt；None = 用 (文件名最后一段数字)
PREFIX = "so2"
VARNAME = None           # None = 用 .xyz 表头最后一列


def smooth_mask(mask):
    """形态学去噪：3×3 闭运算填空/连断 + 两遍 3×3 中值去孤点。

    实测（G3, t=10s, 100×100）：连通块 38 → 7，最大块占比 59.1% → 84.8%，
    面积 40.57 → 43.48 m²（+7%，闭运算填补碎裂边界）。
    """
    m = ndimage.binary_closing(mask, structure=np.ones((3, 3)))
    m = ndimage.median_filter(m, size=3)
    m = ndimage.median_filter(m, size=3)
    return m


def parse_timestep(filename):
    """从 <prefix>_<digits>.xyz 取步号；返回 (步号, 物理时间)。"""
    stem = os.path.splitext(os.path.basename(filename))[0]
    tail = stem.split("_")[-1]
    digits = "".join(ch for ch in tail if ch.isdigit())
    step = int(digits) if digits else 0
    dt = DT_PER_STEP if DT_PER_STEP else 0.005
    return step, step * dt


def read_xyz(path):
    """读 .xyz。返回 (x, y, z, c, 表头变量名)。

    表头形如：cellnumber x-coordinate y-coordinate z-coordinate molef-so2
    """
    with open(path, encoding="utf-8", errors="replace") as fh:
        header = fh.readline().strip()
    names = header.split()
    varname = names[-1] if len(names) >= 5 else "field"
    d = np.loadtxt(path, skiprows=1)
    if d.ndim == 1:
        d = d.reshape(1, -1)
    return d[:, 1], d[:, 2], d[:, 3], d[:, 4], varname


def nearest_grid(x, z, c, ng, lim_x, lim_z):
    """逐点 argmin 最近邻填到 ng×ng 规则网格。

    ★ 不要替换成 scipy.interpolate.griddata(method='nearest')：
      它基于 Delaunay 凸包，对重复点/边界外点的处理与逐点 argmin 不同，
      实测同一数据面积偏小 20%（与 post 基准不符）。

    返回 CG[z_idx, x_idx]（第 0 维 = Z，第 1 维 = X）。
    """
    xi = np.linspace(lim_x[0], lim_x[1], ng)
    zi = np.linspace(lim_z[0], lim_z[1], ng)
    XI, ZI = np.meshgrid(xi, zi)
    pts = np.column_stack([XI.ravel(), ZI.ravel()])
    src = np.column_stack([x, z])
    out = np.empty(len(pts))
    B = 2000  # 分块，避免 N×M 超大中间矩阵
    for i in range(0, len(pts), B):
        blk = pts[i:i + B]
        d2 = ((blk[:, None, 0] - src[None, :, 0]) ** 2 +
              (blk[:, None, 1] - src[None, :, 1]) ** 2)
        out[i:i + B] = c[np.argmin(d2, axis=1)]
    return out.reshape(ng, ng)


def process_file(filepath, nx, nz, args):
    step, time_s = parse_timestep(filepath)
    x, y, z, c, varname = read_xyz(filepath)
    m = (y >= args.y0 - args.dy) & (y <= args.y0 + args.dy)
    x, z, c = x[m], z[m], np.clip(c[m], 0.0, None)

    if len(x) == 0:
        return step, time_s, [0] * (nx * nz), [0] * (nx * nz), 0, varname

    CG = nearest_grid(x, z, c, NG, args.lim_x, args.lim_z)   # [z_idx, x_idx]

    red_m = CG >= args.red
    yel_m = CG >= args.yellow
    if nx >= SMOOTH_MIN_NX and not args.no_smooth:
        red_m = smooth_mask(red_m)
        yel_m = smooth_mask(yel_m)

    bx = NG // nx
    bz = NG // nz
    red = [0] * (nx * nz)
    yellow = [0] * (nx * nz)
    for i in range(nx):          # i → X（横）
        for j in range(nz):      # j → Z（纵）
            rb = red_m[j * bz:(j + 1) * bz, i * bx:(i + 1) * bx]
            yb = yel_m[j * bz:(j + 1) * bz, i * bx:(i + 1) * bx]
            k = i * nz + j       # ★ 全链路统一的 cell 编号
            red[k] = 1 if float(rb.mean()) >= args.block_ratio else 0
            yellow[k] = 1 if (float(yb.mean()) >= args.block_ratio or red[k]) else 0

    return step, time_s, red, yellow, int(len(x)), varname


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("in_dir", nargs="?", help=".xyz 所在目录")
    ap.add_argument("out_dir", nargs="?", help="CSV 输出目录")
    ap.add_argument("nx", nargs="?", type=int, default=10, help="每边格数，默认 10")
    ap.add_argument("--prefix", default=PREFIX)
    ap.add_argument("--y0", type=float, default=Y0)
    ap.add_argument("--dy", type=float, default=DY)
    ap.add_argument("--red", type=float, default=RED_THRESHOLD)
    ap.add_argument("--yellow", type=float, default=YELLOW_THRESHOLD)
    ap.add_argument("--block-ratio", type=float, default=BLOCK_RATIO)
    ap.add_argument("--lim-x", nargs=2, type=float, default=list(LIM_X))
    ap.add_argument("--lim-z", nargs=2, type=float, default=list(LIM_Z))
    ap.add_argument("--no-smooth", action="store_true")
    args = ap.parse_args()

    if not args.in_dir or not args.out_dir:
        ap.print_help()
        sys.exit(1)

    nx = nz = args.nx
    if NG % nx != 0:
        opts = [n for n in (1, 2, 4, 5, 10, 20, 25, 50, 100) if NG % n == 0]
        sys.exit("[错误] 每边格数 NX=%d 必须整除细网格 %d，可选：%s" % (nx, NG, opts))

    os.makedirs(args.out_dir, exist_ok=True)
    files = sorted(glob.glob(os.path.join(args.in_dir, "%s_*.xyz" % args.prefix)))
    if not files:
        sys.exit("[错误] 找不到 %s_*.xyz：%s" % (args.prefix, args.in_dir))

    smooth_txt = "关闭" if (nx < SMOOTH_MIN_NX or args.no_smooth) else "开(闭3+中值3×2)"
    print("找到 %d 个时刻文件 | 切片带 y∈[%.2f, %.2f] m | 细网格 %d×%d | "
          "输出栅格 %d×%d（每格 %.3f m）| 块内阈值 %.2f | 去噪 %s"
          % (len(files), args.y0 - args.dy, args.y0 + args.dy, NG, NG,
             nx, nz, (args.lim_x[1] - args.lim_x[0]) / nx, args.block_ratio, smooth_txt))
    print("阈值：红 >= %g   黄 >= %g" % (args.red, args.yellow))

    results = []
    varname = "field"
    for fp in files:
        step, t, red, yellow, n, varname = process_file(fp, nx, nz, args)
        results.append((t, red, yellow, n))
        print("  t=%7.3fs  step=%-6d  层内点数=%6d  红格=%4d  黄格=%4d"
              % (t, step, n, sum(red), sum(yellow)))

    if not results:
        sys.exit("[错误] 没有处理到任何有效数据")
    results.sort(key=lambda r: r[0])

    tag = "%dx%d" % (nx, nz)
    wide = os.path.join(args.out_dir, "%s_zone_%s.csv" % (args.prefix, tag))
    with open(wide, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time"] + ["R_%d" % k for k in range(nx * nz)] +
                   ["Y_%d" % k for k in range(nx * nz)])
        for t, red, yellow, _ in results:
            w.writerow(["%.4f" % t] + red + yellow)

    summary = os.path.join(args.out_dir, "%s_summary_%s.csv" % (args.prefix, tag))
    with open(summary, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["# 切片带 y ∈ [%.3f, %.3f] m | 变量 %s | 阈值 红>=%g 黄>=%g | "
                    "去噪 %s" % (args.y0 - args.dy, args.y0 + args.dy, varname,
                                 args.red, args.yellow, smooth_txt)])
        w.writerow(["time_s", "red_cells", "yellow_cells",
                    "red_area_frac", "yellow_area_frac"])
        for t, red, yellow, _ in results:
            rc, yc = sum(red), sum(yellow)
            w.writerow(["%.4f" % t, rc, yc,
                        "%.4f" % (rc / (nx * nz)), "%.4f" % (yc / (nx * nz))])

    # ---- 宽表 → 长表（下游消费用）----
    long_path = os.path.join(args.out_dir, "%s_grid_%s.csv" % (args.prefix, tag))
    with open(wide, "r", newline="", encoding="utf-8") as fin, \
         open(long_path, "w", newline="", encoding="utf-8") as fout:
        rd = csv.reader(fin)
        header = next(rd)
        cells = (len(header) - 1) // 2
        w = csv.writer(fout)
        nrow = 0
        for row in rd:
            if not row:
                continue
            t = float(row[0])
            red = row[1:1 + cells]
            yellow = row[1 + cells:1 + 2 * cells]
            for k in range(cells):
                w.writerow(["%.4f" % t, k, red[k], yellow[k]])
            nrow += 1

    print()
    print("输出完成：")
    print("  宽表   ", wide)
    print("  摘要   ", summary)
    print("  长表   ", long_path, "（%d 格 × %d 时刻 = %d 行，无表头）"
          % (cells, nrow, cells * nrow))
    print()
    print("提醒：")
    print("  1) 长表直接给下游的表格读取组件用；读缓冲要放到行数的 1.5 倍以上")
    print("     （13 万行需 >= 200000，默认 20000 会越界）。")
    print("  2) 渲染成图前记得 reshape(NG,NG).T（[X][Z] → [Z][X]）；")
    print("     与 post 云图并排对比时注意上下镜像（下游画布 Y 向下）。")
    print("  3) cell 编号约定 k = i*NZ + j（i=X, j=Z），下游代码必须一致。")


if __name__ == "__main__":
    main()
