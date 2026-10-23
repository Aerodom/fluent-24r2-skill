#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""冒烟测试第 2 步：Fluent Meshing watertight 工作流 → 原生 .msh.h5。

**本步骤已在本机实测跑通**（2024R2 / PyFluent 0.42.1 / 2 进程）。

为什么非要用这条路：Fluent 2024R2 在本机**读不了外部格式网格**
（gmsh 2.2 的四边形/三角形、CGNS 全部在 `Building... mesh` 处 SIGSEGV，
六组对照实验见 `../../references/troubleshooting.md` 的 K 类）。
原生 Meshing 生成 + 原生 `.msh.h5` 读取是唯一验证可用的路线。

四个踩过的坑（改脚本前先看）：
  1. **不收 STL** —— watertight 只吃 CAD 面（STEP/IGES/Parasolid）。
  2. `describe_geometry.capping_required` 取值必须是 `"No"` / `"Yes"`，
     小写 `"no"` 会报 "Provided value(s): no"。
  3. **所有 CAD 面会被合并成一个 zone**（本机实测：整个长方体只有
     `...-1:1` 一个 wall）。要在求解器里用 `sep_face_zone_angle` 按角度拆开。
  4. **网格尺寸的单位是"文件声明的单位"，不是米。** gmsh 写的 STEP 声明
     `MILLI METRE`（见 make_geometry.py 的单位陷阱），Meshing 日志会打
     `length unit = [mm]`；此时传 `min_size=0.0015` 会被当成 0.0015 mm，
     换算成 1.5e-06 m，在 1 m 长的管道上直接 `Error: Out of Memory`。
     `import_geometry.length_unit` 设了也不管用 —— **文件声明优先**。
     所以本脚本的尺寸常量一律用**毫米**（`_MM` 后缀），别改成米。

用法：
    python make_mesh.py [工作目录]
    ⚠️ 工作目录必须是**纯 ASCII 路径**。放在含中文的目录下会在 CAD 导入阶段报
       "Error in CAD Import"，与本脚本参数无关。
依赖：ansys-fluent-core、已配置许可证；`AWP_ROOT242` 指向安装根目录。
"""
import json
import os
import sys
import time

import ansys.fluent.core as pyfluent

STEP_NAME = "duct.step"
MESH_NAME = "duct.msh.h5"

# 单位：毫米（= STEP 文件声明单位）。见文件头坑 4。
# 几何 1000 x 100 x 20 mm。取 1.5 mm 上限 -> 长约 667 格、高约 67 格、宽约 13 格，
# 约 58 万单元。窄缝方向（20 mm）只有 13 层偏少，会让层流峰值偏低，
# 2.5 mm 时实测 u_max/U_mean = 1.53（解析解 1.724），所以取 1.5 mm。
MIN_SIZE_MM = 0.5
MAX_SIZE_MM = 1.5


def default_work():
    """默认工作目录：脚本旁边的 work/；若该路径含非 ASCII，退到系统临时目录。"""
    here = os.path.dirname(os.path.abspath(__file__))
    cand = os.path.join(here, "work")
    if cand.isascii():
        return cand
    import tempfile
    alt = os.path.join(tempfile.gettempdir(), "fluent_smoke")
    print("[warn] 脚本所在路径含非 ASCII（%s）" % here)
    print("       Fluent Meshing 的 CAD 导入器要求纯 ASCII 路径，改用 %s" % alt)
    return alt


def main():
    work = sys.argv[1] if len(sys.argv) > 1 else default_work()
    os.makedirs(work, exist_ok=True)
    if not work.isascii():
        raise SystemExit(
            "工作目录含非 ASCII 字符：%s\n"
            "Fluent Meshing 的 CAD 导入器在这个路径下会报 'Error in CAD Import'，\n"
            "请改用纯 ASCII 路径，例如 <WORK>" % work)
    step = os.path.join(work, STEP_NAME)
    mesh = os.path.join(work, MESH_NAME)
    if not os.path.exists(step):
        raise SystemExit("缺少几何 %s —— 先跑 make_geometry.py" % step)

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
            {"min_size": MIN_SIZE_MM, "max_size": MAX_SIZE_MM,
             "size_functions": "Curvature & Proximity"}
        )
        print("[ok] sizing %.4g ~ %.4g mm（文件声明单位）"
              % (MIN_SIZE_MM, MAX_SIZE_MM))

        wt.describe_geometry.capping_required.set_state("No")   # 大小写敏感
        print("[ok] describe_geometry (capping=No)")

        wt.create_surface_mesh()
        print("[ok] surface mesh")
        wt.update_boundaries()
        print("[ok] update boundaries")
        wt.create_regions()
        print("[ok] create regions")
        wt.create_volume_mesh()
        print("[ok] volume mesh")

        # 必须先删目标文件！`m.tui.file.write_mesh` 遇到同名文件会弹"是否覆盖"，
        # 非交互模式下它**静默放弃**，而 os.path.exists 仍然为真 —— 于是脚本
        # 会拿上一次的旧网格报成功，后面求解出来的全是不该出现的结果。
        if os.path.exists(mesh):
            os.remove(mesh)
        t0 = time.time()
        m.tui.file.write_mesh(mesh)
        if not os.path.exists(mesh) or os.path.getsize(mesh) == 0:
            raise SystemExit("写网格失败：%s 不存在或为空" % mesh)
        if os.path.getmtime(mesh) < t0 - 2:
            raise SystemExit("写网格失败：%s 是旧文件（mtime 没更新）" % mesh)
        print("[ok] wrote %s (%.1f MB)" % (mesh, os.path.getsize(mesh) / 1e6))
        with open(os.path.join(work, "mesh_info.json"), "w", encoding="utf-8") as f:
            json.dump({"step": STEP_NAME, "mesh": MESH_NAME,
                       "size_unit": "mm",
                       "min_size_mm": MIN_SIZE_MM, "max_size_mm": MAX_SIZE_MM},
                      f, indent=1)
    finally:
        try:
            m.exit()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    main()
