#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""冒烟测试第 2 步：Fluent Meshing watertight 工作流 → 原生 .msh.h5。

**本步骤已在本机实测跑通**（2024R2 / PyFluent 0.42.1 / 2 进程）。

为什么非要用这条路：Fluent 2024R2 在本机**读不了外部格式网格**
（gmsh 2.2 的四边形/三角形、CGNS 全部在 `Building... mesh` 处 SIGSEGV，
六组对照实验见 `../../references/troubleshooting.md` 的 K 类）。
原生 Meshing 生成 + 原生 `.msh.h5` 读取是唯一验证可用的路线。

四个踩过的坑（都已变成代码里的守卫，改脚本前先看）：
  1. **不收 STL** —— watertight 只吃 CAD 面（STEP/IGES/Parasolid）。
  2. `describe_geometry.capping_required` 取值必须是 `"No"` / `"Yes"`，
     小写 `"no"` 会报 "Provided value(s): no"。大小写敏感。
  3. **所有 CAD 面会被合并成一个 zone**（本机实测：整个长方体只有
     `...-1:1` 一个 wall）。要在求解器里用 `sep_face_zone_angle` 按角度拆开。
  4. **网格尺寸的单位是"文件声明的单位"，不是米。** gmsh 写的 STEP 声明
     `MILLI METRE`（见 make_geometry.py 的单位陷阱），Meshing 日志会打
     `length unit = [mm]`；此时传 `min_size=0.0015` 会被当成 0.0015 mm，
     换算成 1.5e-06 m，在 1 m 长的管道上直接 `Error: Out of Memory` 并挂死。
     `import_geometry.length_unit` 设了也不管用 —— **文件声明优先**。

     所以本脚本的尺寸常量一律用**米**（物理量），运行时读 STEP 的声明单位
     自动换算（`_common.size_in_file_unit`）。这样换一份声明为米的 STEP 也不会错。

用法：
    python make_mesh.py [工作目录]
    ⚠️ 工作目录必须是**纯 ASCII 路径**（脚本会在启动 Fluent 之前检查）。
依赖：ansys-fluent-core、已配置许可证；`AWP_ROOT242` 指向安装根目录。
"""
import json
import os
import sys

import _common as common
import ansys.fluent.core as pyfluent

STEP_NAME = "duct.step"
MESH_NAME = "duct.msh.h5"

# 物理尺寸（米）。换算成"文件声明单位"由 common.size_in_file_unit 负责。
# 几何 1.0 x 0.1 x 0.02 m，取 1.5 mm -> 长约 667 格、高约 67 格、宽约 13 格，
# 实测 53.1 万单元 / 124 MB / 约 2 min，u_max/U_mean = 1.6221（解析 1.7236）。
# 2.5 mm 时只有 13.5 万单元，比值掉到 1.5300（-11.2%），所以不要放宽。
MIN_SIZE_M = 0.5e-3
MAX_SIZE_M = 1.5e-3


def main():
    work = sys.argv[1] if len(sys.argv) > 1 else common.default_work(__file__)
    common.require_ascii(work, "工作目录")      # 坑 2：Fluent 起来之前就拦
    os.makedirs(work, exist_ok=True)

    step = os.path.join(work, STEP_NAME)
    mesh = os.path.join(work, MESH_NAME)
    if not os.path.exists(step):
        raise SystemExit("缺少几何 %s —— 先跑 make_geometry.py" % step)

    ext = common.step_extent(step)              # 坑 1：读文件，不信"我按米建模"
    min_size = common.size_in_file_unit(MIN_SIZE_M, ext["scale_to_m"])
    max_size = common.size_in_file_unit(MAX_SIZE_M, ext["scale_to_m"])
    print("[ok] 几何物理尺寸 %.6g m，STEP 声明单位 %s（1 单位 = %.0e m）"
          % (ext["extent_m"], ext["declared"], ext["scale_to_m"]))
    print("[ok] sizing 物理 %.4g ~ %.4g mm  ->  按文件单位传 %.4g ~ %.4g"
          % (MIN_SIZE_M * 1e3, MAX_SIZE_M * 1e3, min_size, max_size))

    m = pyfluent.launch_fluent(
        mode="meshing", dimension=3, precision="double", processor_count=2,
        ui_mode="no_gui_or_graphics", start_transcript=False, cwd=work,
    )
    print("launched meshing", pyfluent.__version__)
    try:
        wt = m.watertight()
        wt.import_geometry.file_name.set_state(step)
        print("[ok] import geometry")

        srf = wt.create_surface_mesh
        srf.cfd_surface_mesh_controls.set_state(
            {"min_size": min_size, "max_size": max_size,
             "size_functions": "Curvature & Proximity"}
        )

        wt.describe_geometry.capping_required.set_state("No")   # 坑 2：大小写敏感
        print("[ok] describe_geometry (capping=No)")

        wt.create_surface_mesh()
        print("[ok] surface mesh")
        wt.update_boundaries()
        print("[ok] update boundaries")
        wt.create_regions()
        print("[ok] create regions")
        wt.create_volume_mesh()
        print("[ok] volume mesh")

        # 坑 7：write_mesh 遇到同名文件会弹"是否覆盖"，非交互模式下静默放弃。
        # fresh_write 先删再写，并三查存在 / 非空 / mtime 是否真的变了。
        # 坑 5：meshing 会话里 write_mesh 只挂在 tui 侧，solver 会话里
        #       tui.file 整条不可用 —— call_file 两条路都探。
        used = []

        def _write():
            used.append(common.call_file(
                m, "write_mesh",
                [((mesh,), {}), ((), {"file_name": mesh})]))

        size = common.fresh_write(mesh, _write, "网格")
        print("[ok] wrote %s (%.1f MB, via %s)" % (mesh, size / 1e6, used[0]))

        with open(os.path.join(work, "mesh_info.json"), "w", encoding="utf-8") as f:
            json.dump({"step": STEP_NAME, "mesh": MESH_NAME,
                       "step_declared_unit": ext["declared"],
                       "step_scale_to_m": ext["scale_to_m"],
                       "step_extent_m": ext["extent_m"],
                       "min_size_m": MIN_SIZE_M, "max_size_m": MAX_SIZE_M,
                       "file_unit_min": min_size, "file_unit_max": max_size,
                       "mesh_bytes": size}, f, indent=1)
    finally:
        try:
            m.exit()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    main()
