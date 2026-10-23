#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""冒烟测试第 1 步：生成矩形管道 STEP 几何（gmsh，不需要 Fluent 许可证）。

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

    正确做法是 `Geometry.OCCTargetUnit = "M"`（放在 `model.add` 之前），
    gmsh 把数值乘 1000 再写，声明仍是毫米，Fluent 读进来正好是米。
    **不要**去改文件里的 `MILLI METRE` 声明 —— 数值已经同步放大，改声明就错了。

    三种组合的实测对照见 `_common.step_unit()` 的 docstring。
    本脚本导出后会用 `_common.step_extent()` 读回复核，不靠肉眼。

用法：
    python make_geometry.py [输出目录]
      - 不传时用脚本旁的 work/；若该路径含非 ASCII，自动退回系统临时目录
      - 输出目录必须是纯 ASCII（Meshing 的 CAD 导入器要求，见 _common.require_ascii）
"""
import os
import sys

import _common as common
import gmsh

L, H, W = 1.0, 0.1, 0.02      # 米
STEP_TARGET_UNIT = "M"        # 必须是 M：见上面的单位陷阱


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
    out = sys.argv[1] if len(sys.argv) > 1 else common.default_work(__file__)
    common.require_ascii(out, "输出目录")      # 坑 2：先于 gmsh 就拦下
    os.makedirs(out, exist_ok=True)

    path = build(out)
    ext = common.step_extent(path)

    print("[ok] STEP: %s (%d bytes)" % (path, os.path.getsize(path)))
    print("     几何 L=%.3g H=%.3g W=%.3g（高宽比 %.1f）" % (L, H, W, H / W))
    print("     声明单位=%s  文件内最大坐标=%.6g  换算物理尺寸=%.6g m"
          % (ext["declared"], ext["max_coord"], ext["extent_m"]))

    err = abs(ext["extent_m"] - L) / L
    if err > 0.01:
        print("[FAIL] 物理尺寸应为 %.4g m，实际 %.6g m（差 %.1f%%）"
              % (L, ext["extent_m"], err * 100))
        print("       多半是 Units 陷阱：检查 OCCTargetUnit 是否在 model.add 之前设为 M")
        return 1
    print("[ok] 单位自检通过（偏差 %.3f%%，声明单位 %s 已按 %.0e m 换算）"
          % (err * 100, ext["declared"], ext["scale_to_m"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
