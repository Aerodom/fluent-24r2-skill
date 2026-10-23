#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""冒烟测试第 1 步：生成矩形管道 STEP 几何（gmsh，无需 Fluent 许可证）。

为什么用 STEP 而不是 STL：
    Fluent Meshing 的 watertight 工作流**不接受面片格式**，会直接报
    "Faceted formats, like '.stl', '.tgf' and 'fmd' are not yet supported."

几何：长 L=1.0、高 H=0.1、宽 W=0.02（高宽比 5:1），长宽比足够让出口充分发展。

⚠️ **单位陷阱（本机实测，2026-10-23）—— 不设这一行，几何会缩 1000 倍**

    gmsh 的 OCC STEP 写出器**永远**声明 `SI_UNIT(.MILLI.,.METRE.)`，
    但默认把模型坐标**原样**写进去。也就是 `addBox(..., 1.0, 0.1, 0.02)` 写出的
    文件声明"毫米"、数值仍是 1.0 / 0.1 / 0.02 —— Fluent 如实按毫米换算，
    于是你拿到的是 1 mm × 0.1 mm × 0.02 mm 的管道（缩了 1000 倍）。

    症状不是报错，而是**物理全错且不显眼**：端面面积 1e-07 m²（应为 2e-3），
    Re 从 222 掉到 0.2，入口段长度远大于管长，出口根本没发展，
    `u_max/U_mean` 判据永远对不上。

    正确做法是 `gmsh.option.setString("Geometry.OCCTargetUnit", "M")`
    （放在 `model.add` 之前），gmsh 会把数值乘 1000 再写，声明仍是毫米，
    Fluent 读进来正好是米。三种组合的实测对照：

        | 设置                        | 文件内最大坐标 | 声明   | Fluent 实际得到 |
        |-----------------------------|---------------|--------|----------------|
        | 默认                        | 1.0           | MILLI  | 0.001 m  ✗     |
        | OCCTargetUnit="M"           | 1000.0        | MILLI  | 1.0 m    ✓     |
        | 默认 + 自己把尺寸乘 1000     | 1000000.0     | MILLI  | 1000 m   ✗     |

    **不要**去改文件里的 `MILLI METRE` 声明 —— 数值已经同步放大，改声明就错了。
    导出后请用本脚本的 `step_physical_extent()` 复核，别靠肉眼。

用法：
    python make_geometry.py [输出目录]
"""
import io
import os
import re
import sys

import gmsh

L, H, W = 1.0, 0.1, 0.02      # 米
STEP_TARGET_UNIT = "M"        # 必须是 M：见上面的单位陷阱

PAT_POINT = re.compile(r"CARTESIAN_POINT\('[^']*',\s*\(([^)]*)\)")
PAT_UNIT = re.compile(r"SI_UNIT\(([^)]*)\)")


def step_physical_extent(path):
    """读回 STEP，返回 (声明单位, 文件内最大坐标, 换算后的物理最大尺寸 m)。

    这是本脚本唯一诚实的自检：不信任"我设了单位"，只信文件里写了什么。
    """
    txt = io.open(path, encoding="utf-8", errors="replace").read()
    units = [u for u in PAT_UNIT.findall(txt) if "METRE" in u]
    declared = units[0] if units else "?"
    scale = 1e-3 if "MILLI" in declared else 1.0
    nums = []
    for grp in PAT_POINT.findall(txt):
        vals = [float(v) for v in grp.split(",") if v.strip()]
        if len(vals) == 3:
            nums.append(max(vals))
    if not nums:
        raise RuntimeError("STEP 里没找到三维 CARTESIAN_POINT：%s" % path)
    return declared, max(nums), max(nums) * scale


def build(out_dir):
    path = os.path.join(out_dir, "duct.step")
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        # 关键一行：必须在 model.add / addBox 之前设置
        gmsh.option.setString("Geometry.OCCTargetUnit", STEP_TARGET_UNIT)
        gmsh.model.add("duct")
        gmsh.model.occ.addBox(0.0, 0.0, 0.0, L, H, W)
        gmsh.model.occ.synchronize()
        gmsh.write(path)
    finally:
        gmsh.finalize()
    return path


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "work")
    os.makedirs(out, exist_ok=True)
    path = build(out)
    declared, raw, physical = step_physical_extent(path)

    print("[ok] STEP: %s (%d bytes)" % (path, os.path.getsize(path)))
    print("     几何 L=%.3g H=%.3g W=%.3g（高宽比 %.1f）" % (L, H, W, H / W))
    print("     声明单位=%s  文件内最大坐标=%.6g  换算物理尺寸=%.6g m"
          % (declared, raw, physical))

    err = abs(physical - L) / L
    if err > 0.01:
        print("[FAIL] 物理尺寸应为 %.4g m，实际 %.6g m（差 %.1f%%）"
              % (L, physical, err * 100))
        print("       多半是 Units 陷阱：检查 OCCTargetUnit 是否在 model.add 之前设为 M")
        return 1
    print("[ok] 单位自检通过（偏差 %.3f%%）" % (err * 100))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
