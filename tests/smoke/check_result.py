#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""冒烟测试第 4 步：用解析解校核 CFD 结果（不需要 Fluent）。

矩形管道充分发展层流的 Fourier 级数解（White, *Viscous Fluid Flow*, §3-3）：

    u(y,z) = (16 a² / (μ π³)) (-dp/dx) Σ_{n 奇} (-1)^((n-1)/2) / n³
             · [1 - cosh(nπ z / 2a) / cosh(nπ b / 2a)] · cos(nπ y / 2a)

其中 2a = 高 H（y 方向），2b = 宽 W（z 方向），原点在截面中心。
u_max 在 (0,0)；U_mean 由面积分得到。两者之比与 μ、dp/dx 无关，只取决于高宽比。

**两段判据**（为什么要两段）：

  1. **连续性**：出口面积加权平均速度必须等于入口均匀速度。
     这一条对网格分辨率几乎不敏感，但任何"边界条件设错 / 体区域是 solid /
     单位缩了 1000 倍 / 进出口接反"都会立刻把它打偏。**卡 2%**。
  2. **剖面形状**：`u_max / U_mean` 落在解析解附近的带内。
     这一条对网格敏感 —— 多面体网格 + 窄缝层数不足会系统性低估峰值，
     所以带宽按实测收敛性给，不假装能做到 3%。**卡 ±12%**。

只有两条都过才算 PASS。第 2 条失败但第 1 条过，说明"算对了但网格不够细"，
不是流程坏了 —— 这个区分很重要，否则换台机器会误判成 skill 失效。

用法：
    python check_result.py                            # 只打印理论比值
    python check_result.py --result <工作目录>/result.json
    python check_result.py --umax 0.16 --uavg 0.1 --uin 0.1
"""
import argparse
import io
import json

import numpy as np

H = 0.1          # 高（m），H = 2a
W = 0.02         # 宽（m），W = 2b
U_IN = 0.1       # 入口均匀速度（m/s）

CONT_TOL = 0.02      # 连续性允许相对偏差
SHAPE_BAND = 0.10    # u_max/U_mean 相对解析解的允许带宽

# 带宽标定依据（本机 Fluent 2024R2 / 多面体网格 / 300 步，2026-10-23 实测）：
#   网格 2.5 mm / 13.5 万单元 -> 1.5300  偏差 -11.2%  （落在带宽外，应当判 FAIL）
#   网格 1.5 mm / 53.1 万单元 -> 1.6233  偏差  -5.8%  （落在带宽内，PASS）
# 也就是说这条判据能抓住"网格明显偏粗"，同时不会因为正常的离散误差误报。
# 想做到 ±3% 需要约 1.0 mm 网格（约 260 万单元），那已超出"冒烟测试"的代价预算。


def ratio_umax_over_umean(height=H, width=W, n_max=399, n_grid=401):
    """返回 u_max / U_mean（充分发展、矩形截面、层流）。

    用级数求 u(y,z)，再在截面上做数值积分求 U_mean —— 比闭式积分不容易推错。
    cosh 用指数形式改写，避免 n 大时溢出。

    自检（本函数输出，可复查）：
        正方形 2.107（文献 2.096，差 0.5%）
        高宽比 20 以上趋近 1.5（无限大平行平板极限）
    """
    a, b = height / 2.0, width / 2.0
    y = np.linspace(-a, a, n_grid)
    z = np.linspace(-b, b, n_grid)
    Y = y[:, None]
    Z = z[None, :]

    u = np.zeros((n_grid, n_grid))
    for n in range(1, n_max + 1, 2):
        s = (-1) ** ((n - 1) // 2)
        alpha = n * np.pi / (2.0 * a)
        # 1 - cosh(α z)/cosh(α b)，用指数改写：exp(α(|z|-b))·(1+e^{-2α|z|})/(1+e^{-2αb})
        aZ = np.abs(Z)
        shape = 1.0 - np.exp(alpha * (aZ - b)) * (1.0 + np.exp(-2.0 * alpha * aZ)) / (
            1.0 + np.exp(-2.0 * alpha * b)
        )
        u += s / n ** 3 * shape * np.cos(alpha * Y)

    return u.max() / u.mean()


def load_result(path):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def print_mesh(mi):
    """把 run_case 带出来的网格参数打出来 —— 判据偏差大小直接取决于它。"""
    if not mi:
        return
    print("网格: 物理尺寸 %.3g ~ %.3g mm（STEP 声明单位 %s）/ %.1f MB"
          % (mi.get("min_size_m", 0.0) * 1e3, mi.get("max_size_m", 0.0) * 1e3,
             mi.get("step_declared_unit", "?"), (mi.get("mesh_bytes") or 0) / 1e6))


def main():
    ap = argparse.ArgumentParser(description="矩形管道层流解析解校核")
    ap.add_argument("--height", type=float, default=H)
    ap.add_argument("--width", type=float, default=W)
    ap.add_argument("--result", help="run_case.py 产出的 result.json")
    ap.add_argument("--umax", type=float, help="出口最大速度 (m/s)")
    ap.add_argument("--uavg", type=float, help="出口面积加权平均速度 (m/s)")
    ap.add_argument("--uin", type=float, default=U_IN, help="入口均匀速度 (m/s)")
    ap.add_argument("--cont-tol", type=float, default=CONT_TOL)
    ap.add_argument("--band", type=float, default=SHAPE_BAND)
    args = ap.parse_args()

    umax, uavg, uin = args.umax, args.uavg, args.uin
    if args.result:
        d = load_result(args.result)
        umax, uavg, uin = d.get("umax"), d.get("uavg_out"), d.get("u_in", U_IN)
        print_mesh(d.get("mesh_info"))

    r = ratio_umax_over_umean(args.height, args.width)
    print("几何: H=%.4g m, W=%.4g m, 高宽比=%.2f" % (args.height, args.width,
                                                 args.height / args.width))
    print("理论 u_max/U_mean = %.4f   （无限大平行平板极限 1.5）" % r)
    print("入口均匀速度 U_in = %.6g m/s" % uin)

    if umax is None or uavg is None:
        print("\n（未给 --result / --umax --uavg，只打印理论值）")
        return 0

    got = umax / uavg if uavg else float("nan")
    shape_err = abs(got - r) / r
    cont_err = abs(uavg / uin - 1.0)
    print("\nCFD  u_max          = %.6g m/s" % umax)
    print("CFD  出口面积加权平均 = %.6g m/s" % uavg)
    print("CFD  u_max/U_mean   = %.4f" % got)

    ok1 = cont_err <= args.cont_tol
    ok2 = shape_err <= args.band
    print("\n[1] 连续性    偏差 %.2f%%   容差 %.0f%%   %s"
          % (cont_err * 100, args.cont_tol * 100, "PASS" if ok1 else "FAIL"))
    print("[2] 剖面形状  偏差 %.2f%%   带宽 ±%.0f%%  %s"
          % (shape_err * 100, args.band * 100, "PASS" if ok2 else "FAIL"))

    if ok1 and ok2:
        print("\nPASS")
        return 0
    if ok1 and not ok2:
        print("\nFAIL —— 连续性通过但峰值偏低，通常是网格分辨率不够"
              "（多面体网格 + 窄缝层数不足会低估层流峰值），不是流程坏了。"
              "把 make_mesh.py 的 MAX_SIZE_MM 调小后重跑。")
    else:
        print("\nFAIL —— 连续性就不通过，先查边界条件 / 体区域是否 fluid / 单位 / 进出口是否接反。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
