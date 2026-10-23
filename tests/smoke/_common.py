#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tests/smoke 共用守卫 —— 每个函数都钉住一个**实测踩过**的坑。

    坑                                                             守卫函数
    ------------------------------------------------------------   ------------------------
    1. gmsh 的 STEP 声明 MILLI METRE，但坐标不缩放（几何缩 1000 倍）  step_unit() / step_extent()
    2. 工作目录含非 ASCII 时 CAD 导入失败，报错还甩锅给文件格式        require_ascii()
    3. 网格尺寸按"文件声明单位"解释，按米传就成了微米，直接 OOM        size_in_file_unit()
    5. PyFluent 0.42.1 上 session.tui.file.* 整条不可用              call_file()
    7. write_mesh / write_case_data 遇同名文件静默不覆盖             fresh_write()
    7'. 上一轮的旧网格被当成新网格用                                 check_mesh_not_stale()

设计约束：本模块**只依赖标准库**，不 import pyfluent / gmsh。这样每个脚本都能在
启动 Fluent（约 1 分钟）**之前**先把守卫跑完 —— 一分钟的启动时间不值得为一条
路径检查反复浪费。

用法（四个脚本都在自己的目录下 import）：
    import _common as common
"""
import io
import os
import re
import tempfile
import time

# STEP 里的两个实体：单位声明与点坐标（Part 21 明文，直接正则比装 STEP 解析器划算）
STEP_UNIT = re.compile(r"SI_UNIT\(([^)]*)\)")
STEP_POINT = re.compile(r"CARTESIAN_POINT\('[^']*',\s*\(([^)]*)\)")

# 长度单位 -> 1 个该单位等于多少米
_UNIT_TO_M = (
    ("MILLI", 1e-3),
    ("CENTI", 1e-2),
    ("DECI", 1e-1),
    ("MICRO", 1e-6),
)

ASCII_HINT = (
    "  Fluent Meshing 的 CAD 导入器在这里会报 'Error in CAD Import'，\n"
    "  而且报错文字会把责任推给文件格式 / CAD Reader，极具误导性 ——\n"
    "  格式没问题，是路径里的非 ASCII 字符。\n"
    "  换一个纯 ASCII 路径，例如 <DRIVE>:/smoke_work 或 %%TEMP%%/fluent_smoke。"
)


# --------------------------------------------------------------------------- 路径


def require_ascii(path, what="工作目录"):
    """坑 2：Fluent 的 CAD 导入器不接受非 ASCII 路径。

    在启动 Fluent 之前调用，失败立刻退出，省一分钟。
    """
    ap = os.path.abspath(path)
    if ap.isascii():
        return ap
    raise SystemExit("[FAIL] %s 含非 ASCII 字符：\n  %s\n%s" % (what, ap, ASCII_HINT))


def default_work(script_file):
    """默认工作目录 = 脚本旁边的 work/；若脚本所在路径本身不是 ASCII，退回临时目录。"""
    here = os.path.dirname(os.path.abspath(script_file))
    cand = os.path.join(here, "work")
    if cand.isascii():
        return cand
    alt = os.path.join(tempfile.gettempdir(), "fluent_smoke")
    print("[warn] 脚本所在路径含非 ASCII：%s" % here)
    print("       改用纯 ASCII 的临时目录：%s" % alt)
    return alt


# --------------------------------------------------------------------------- 单位


def step_unit(step_path):
    """坑 1：读 STEP **文件里**声明的长度单位，返回 (声明文本, 1 单位 = 多少米)。

    gmsh 的 OCC 写出器永远声明 `SI_UNIT(.MILLI.,.METRE.)`。所以绝不能假定
    "我按米建模，文件就是米" —— 必须读文件。本机三种组合的实测：

        | 设置                  | 文件内最大坐标 | 声明  | Fluent 实际得到 |
        |-----------------------|---------------|-------|----------------|
        | 默认                  | 1.0           | MILLI | 0.001 m  ✗     |
        | OCCTargetUnit="M"     | 1000.0        | MILLI | 1.0 m    ✓     |
        | 默认 + 自己把尺寸 ×1000 | 1000000.0     | MILLI | 1000 m   ✗     |
    """
    with io.open(step_path, encoding="utf-8", errors="replace") as f:
        txt = f.read()
    units = [u for u in STEP_UNIT.findall(txt) if "METRE" in u]
    if not units:
        return "?", 1.0          # 无声明时按 SI 基本单位（米）处理
    declared = units[0]
    for token, scale in _UNIT_TO_M:
        if token in declared:
            return declared, scale
    return declared, 1.0


def step_extent(step_path):
    """读回 STEP，返回物理尺寸信息（全部换算成米）。

    {"declared": 声明单位, "scale_to_m": 换算系数,
     "max_coord": 文件内最大坐标, "extent_m": 换算后的物理最大尺寸}

    这是唯一诚实的自检：不信"我设了单位"，只信文件里写了什么。
    """
    declared, scale = step_unit(step_path)
    with io.open(step_path, encoding="utf-8", errors="replace") as f:
        txt = f.read()
    nums = []
    for grp in STEP_POINT.findall(txt):
        vals = [float(v) for v in grp.split(",") if v.strip()]
        if len(vals) == 3:
            nums.append(max(vals))
    if not nums:
        raise RuntimeError("STEP 里没找到三维 CARTESIAN_POINT：%s" % step_path)
    max_coord = max(nums)
    return {"declared": declared, "scale_to_m": scale,
            "max_coord": max_coord, "extent_m": max_coord * scale}


def size_in_file_unit(size_m, scale_to_m):
    """坑 3：把物理尺寸（米）换算成"文件声明单位"下的数值。

    Meshing 的 `cfd_surface_mesh_controls` 用的是**文件声明单位**，不是米。
    STEP 声明毫米时，传 0.0015（本意 1.5 mm）会被当成 1.5e-06 m，
    在 1 m 长的管道上直接 `Error: Out of Memory` 并挂死。
    实测 `import_geometry.length_unit` 设了也不管用 —— 文件声明优先，
    所以只能在传参前自己换算。
    """
    return size_m / scale_to_m


# --------------------------------------------------------------------------- 文件 API


def call_file(session, method, forms):
    """坑 5：跨 PyFluent 0.42.1 调 `session.file.*` 的方法。

    实测：solver 会话里 `session.tui.file` 整条被路由到 settings 求值，直接抛
    `RuntimeError: eval: unbound variable / Error Object: file`；只有
    `session.settings.file.<method>` 能用。meshing 会话里反过来 —— `write_mesh`
    只挂在 tui 侧。所以这里**两条路都探**，谁成算谁。

    forms: [(args, kwargs), ...]，依次尝试的调用形式（同名方法在不同会话下
           可能只接受位置参数或只接受关键字参数）。只有一次真正写成功才返回。

    返回 "settings.file.write_mesh" 这样的描述，便于日志里看出走的哪条路。
    """
    tried = []
    for api_name, getter in (("settings.file", lambda: session.settings.file),
                             ("tui.file", lambda: session.tui.file)):
        try:
            api = getter()
        except Exception as exc:                                  # noqa: BLE001
            tried.append("%s 拿不到：%s" % (api_name, exc))
            continue
        try:
            fn = getattr(api, method)
        except Exception as exc:                                  # noqa: BLE001
            tried.append("%s.%s 不存在：%s" % (api_name, method, exc))
            continue
        for args, kwargs in forms:
            try:
                fn(*args, **kwargs)
                return "%s.%s%s" % (api_name, method,
                                    tuple(sorted(kwargs)) or tuple(args))
            except Exception as exc:                              # noqa: BLE001
                tried.append("%s.%s%s 失败：%s"
                             % (api_name, method,
                                tuple(sorted(kwargs)) or tuple(args), exc))
    raise RuntimeError("file.%s 没有任何一条路成功：\n  %s"
                       % (method, "\n  ".join(tried)))


def fresh_write(target, writer, label="文件"):
    """坑 7：证明"这次真的写了"，而不是复用了上一轮的旧文件。

    Fluent 写文件遇到同名目标会弹"是否覆盖"，非交互模式下**静默放弃**；
    而 `os.path.exists` 仍然为真 —— 脚本于是拿旧网格/旧 case 报成功，
    后面算出来的全是"看起来合理"的错结果（本机真的踩到过）。

    所以这里做四件事：先删 → 记时间 → 写 → 三查（存在 / 非空 / mtime 真变了）。
    """
    if os.path.exists(target):
        os.remove(target)
    started = time.time() - 1.0        # 容忍文件系统的秒级时间戳精度
    writer()
    if not os.path.exists(target):
        raise SystemExit("[FAIL] %s 没被写出来：%s" % (label, target))
    size = os.path.getsize(target)
    if size == 0:
        raise SystemExit("[FAIL] %s 是空文件：%s" % (label, target))
    mtime = os.path.getmtime(target)
    if mtime < started:
        raise SystemExit(
            "[FAIL] %s 的 mtime 没更新（%.3f < %.3f），这是上一轮的旧文件：\n  %s\n"
            "       多半是写盘时遇到同名文件被静默拒绝了。" % (label, mtime, started, target))
    return size


def check_mesh_not_stale(step, mesh):
    """坑 7'：网格比几何旧 ⇒ 算的是旧几何。

    `fresh_write` 管"这一次写成功了"，本函数管"下游用的是不是最新的"。
    改了几何忘了重建网格时，报错比结果更值钱。
    """
    if not (os.path.exists(step) and os.path.exists(mesh)):
        return
    if os.path.getmtime(mesh) < os.path.getmtime(step):
        raise SystemExit(
            "[FAIL] 网格比几何旧：\n"
            "       几何 %s  (%.0f)\n"
            "       网格 %s  (%.0f)\n"
            "       先重跑 make_mesh.py，否则算的是旧几何。"
            % (step, os.path.getmtime(step), mesh, os.path.getmtime(mesh)))
