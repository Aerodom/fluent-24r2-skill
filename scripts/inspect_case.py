#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""接手体检：离线读 .cas.h5 / .dat.h5 / .msh.h5，出"这份算例现在是什么状态"的报告。

设计前提（很重要，决定了它为什么这么写）
--------------------------------------------------
1. **不启动 Fluent**。领一个别人的算例，第一件事是搞清它是什么、缺什么，
   而不是先花 1 分钟起会话、再去面板里翻。不开会话 ⇒ 不占 license、不吃内存、
   可以在只有 8 GB 的笔记本上先做判断。
2. **只报告能读出来的事实**，读不到就写"读不到"，不猜。任何"看起来像"的推断
   都进"告警"段并标明是启发式。
3. **`.h5` 的内部布局是 Fluent 私有实现**。本脚本的路径与语义**只在
   2024R2 / v242 上实测过**（见 references/version-compatibility.md）。
   换版本时若某段读不到，脚本会明确报 `读不到`，不会伪造默认值。

用法
----
    python inspect_case.py <路径> [<路径> ...] [--json] [--out 报告.md] [--quiet]

`<路径>` 可以是文件，也可以是目录（自动在同目录里找 cas / dat / msh / trn / jou / wbpj）。

本机实测（2024R2，531k 单元管道层流，工作目录须为纯 ASCII 路径）：
    python inspect_case.py <CASE_DIR> --out report.md
"""

from __future__ import print_function

import argparse
import fnmatch
import glob
import io
import json
import os
import re
import sys
import time

# 中文 Windows 控制台是 GBK：本报告的 `✗` / `→` 编不出来，print 会直接终止进程。
# 这条坑在 SKILL.md §10 记过（`UnicodeEncodeError: 'gbk'`），入口统一兜底。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

try:
    import h5py
    import numpy as np
except ImportError as exc:  # 明确报出来，别让它变成"读不到"
    sys.stderr.write(
        "需要 h5py 与 numpy（离线读 .h5 用）：%s\n"
        "  <venv>/Scripts/pip install h5py numpy\n" % exc)
    raise SystemExit(2)


# ----------------------------------------------------------------------------
# zone 类型码
#   「实测」= 在本机 2024R2 的真实算例上核对过（管道层流那只，进/出口/壁面已知）
#   「惯例」= Fluent 长期稳定的取值，但本机没有直接证据 —— 报的时候带问号
# 刻意不把整张 Fluent 常数表抄进来：抄错一个码，接手的判断就整个歪掉。
# ----------------------------------------------------------------------------
CELL_TYPES = {
    1: ("fluid", "实测"),
    2: ("solid", "惯例"),
}
FACE_TYPES = {
    2: ("interior", "实测"),
    3: ("wall", "实测"),
    5: ("pressure-outlet", "实测"),
    10: ("velocity-inlet", "实测"),
    4: ("pressure-inlet", "惯例"),
    7: ("symmetry", "惯例"),
    8: ("periodic", "惯例"),
    9: ("periodic-shadow", "惯例"),
    14: ("mass-flow-inlet", "惯例"),
    36: ("outflow", "惯例"),
}

# 残差判据（Fluent 默认收敛标准的大致量级，仅用于"像不像收敛"的启发式）
RES_TOL = 1e-3

# Fluent 打印的残差 = data[:,0] / data[:,1]。
# 本机实测核对：continuity 末行 6.953693e-07 / 7.411549e-04 = 9.3822e-04，
# 与转录里 "39 9.3822e-04" 逐位吻合。**直接把第 0 列当残差会小三个量级。**
RES_RAW, RES_NORM = 0, 1


def _txt(b):
    """h5py 的 S 型字节串 → str，容忍 None / 数组 / 已解码。"""
    if b is None:
        return ""
    if isinstance(b, bytes):
        return b.decode("utf-8", "replace")
    if isinstance(b, np.ndarray):
        if b.size == 0:
            return ""
        return _txt(b.flat[0])
    if isinstance(b, np.generic):
        return _txt(b.tobytes())
    return str(b)


def _is_h5(path):
    """HDF5 签名是 8 字节 \\x89HDF\\r\\n\\x1a\\n。别用后缀判断 —— .cas 与 .cas.h5 同名不同质。"""
    try:
        with open(path, "rb") as f:
            return f.read(8) == b"\x89HDF\r\n\x1a\n"
    except OSError:
        return False


def _human(nbytes):
    n = float(nbytes)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f %s" % (n, unit)
        n /= 1024.0


def _mtime(path):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(path)))


# ----------------------------------------------------------------------------
# 资产发现
# ----------------------------------------------------------------------------
ASSET_KINDS = (
    # (标签, 后缀模式, 说明)
    ("case", ("*.cas.h5", "*.cas"), "算例设置 + 网格"),
    ("data", ("*.dat.h5", "*.dat"), "场结果"),
    ("mesh", ("*.msh.h5", "*.msh", "*.cgns"), "网格"),
    ("cad", ("*.step", "*.stp", "*.igs", "*.iges", "*.x_t", "*.prt"), "几何"),
    ("trn", ("*.trn",), "Fluent 转录（最硬的证据）"),
    ("journal", ("*.jou", "*.wbjn"), "驱动脚本"),
    ("project", ("*.wbpj",), "Workbench 工程"),
)


def discover(paths):
    """把输入展开成 {kind: [文件...]}。目录就在它下面找，不递归到子目录以外。"""
    found = {k: [] for k, _, _ in ASSET_KINDS}
    others = []
    for p in paths:
        p = os.path.abspath(p)
        if os.path.isdir(p):
            for kind, pats, _ in ASSET_KINDS:
                for pat in pats:
                    found[kind] += glob.glob(os.path.join(p, pat))
            for extra in ("*.md", "*.txt", "*.log"):
                others += glob.glob(os.path.join(p, extra))
        elif os.path.isfile(p):
            low = p.lower()
            hit = False
            for kind, pats, _ in ASSET_KINDS:
                for pat in pats:
                    if fnmatch.fnmatch(os.path.basename(low), pat.lower()):
                        found[kind].append(p)
                        hit = True
                        break
                if hit:
                    break
            if not hit:
                others.append(p)
        else:
            sys.stderr.write("跳过不存在的路径：%s\n" % p)
    for k in found:
        found[k] = sorted(set(found[k]))
    return found, sorted(set(others))


# ----------------------------------------------------------------------------
# 读：身份 / 网格 / 区域
# ----------------------------------------------------------------------------
def read_identity(h5):
    """版本与来源。.cas.h5 有 Version；.msh.h5 只有 Origin/Solver，得从 Origin 里抠。"""
    out = {"version": "", "build": "", "solver": "", "origin": ""}
    st = h5.get("settings")
    if st is None:
        return out
    for key, field in (("Version", "version"), ("Solver", "solver"), ("Origin", "origin")):
        if key in st:
            out[field] = _txt(st[key][0]).strip()
    m = re.search(r"Build\s+(\d+)", out["origin"])
    if m:
        out["build"] = m.group(1)
    if not out["version"]:
        m = re.search(r"(\d{4})\s*R(\d)", out["origin"])   # "ANSYS FLUENT MESHING 2024 R2"
        if m:
            out["version"] = "%sR%s" % (m.group(1), m.group(2))
        elif re.search(r"(\d{4})", out["origin"]):
            out["version"] = re.search(r"(\d{4})", out["origin"]).group(1)
    return out


def _mesh_groups(h5):
    """meshes/ 下每个 mesh 对象。多体/多网格时会有多个。"""
    root = h5.get("meshes")
    if root is None:
        return []
    return [(k, root[k]) for k in root.keys() if isinstance(root[k], h5py.Group)]


def read_mesh(h5):
    """返回 counts / bbox / cell_zones / face_zones。只统计，不读单元体积。"""
    res = {"counts": {}, "bbox": None, "cell_zones": [], "face_zones": [], "nmesh": 0}
    groups = _mesh_groups(h5)
    res["nmesh"] = len(groups)
    if not groups:
        return res

    cells = faces = 0
    lo = np.array([np.inf] * 3)
    hi = np.array([-np.inf] * 3)

    for _, mg in groups:
        # --- cell zones
        cz = mg.get("cells/zoneTopology")
        if cz is not None and "id" in cz:
            nzone = len(cz["id"])
            names_str = _txt(cz["name"][0]).split(";") if "name" in cz else []
            # ★ 只有 zoneType 是"区域类型（fluid/solid）"。
            #   `cellType` 是**单元形状码**（本例 = 7，多面体），千万别当区域类型用：
            #   实测 .msh.h5 里只有 cellType 没有 zoneType，说明网格还没被求解器定型；
            #   拿形状码去查 fluid/solid 表会得到"unknown"，进而误报"全是 solid"。
            for i in range(nzone):
                zid = int(cz["id"][i])
                if "zoneType" in cz:
                    zt = int(cz["zoneType"][i])
                    ztype, zsrc = CELL_TYPES.get(zt, ("unknown", "未映射"))
                else:
                    zt = None
                    ztype, zsrc = "未定型", "无 zoneType 键"
                n = int(cz["maxId"][i]) - int(cz["minId"][i]) + 1
                cells += n
                res["cell_zones"].append({
                    "id": zid,
                    "type_code": zt,
                    "type": ztype,
                    "type_src": zsrc,
                    "shape_code": int(cz["cellType"][i]) if "cellType" in cz else None,
                    "name": names_str[0].strip() if names_str else "",
                    "cells": n,
                })

        # --- face zones
        fz = mg.get("faces/zoneTopology")
        if fz is not None and "id" in fz:
            nzone = len(fz["id"])
            names = _txt(fz["name"][0]).split(";") if "name" in fz else []
            for i in range(nzone):
                zid = int(fz["id"][i])
                zt = int(fz["zoneType"][i]) if "zoneType" in fz else -1
                n = int(fz["maxId"][i]) - int(fz["minId"][i]) + 1
                faces += n
                res["face_zones"].append({
                    "id": zid,
                    "type_code": zt,
                    "type": FACE_TYPES.get(zt, ("unknown", "未映射"))[0],
                    "type_src": FACE_TYPES.get(zt, ("unknown", "未映射"))[1],
                    "name": names[i].strip() if i < len(names) else "",
                    "faces": n,
                    "shadow": int(fz["shadowZoneId"][i]) if "shadowZoneId" in fz else 0,
                })

        # --- 包围盒：节点坐标分块读，避免大网格一次性吃满内存
        nodes = mg.get("nodes/coords")
        if nodes is not None:
            total = 0
            for key in nodes.keys():
                ds = nodes[key]
                if ds.ndim != 2 or ds.shape[1] < 3:
                    continue
                total += ds.shape[0]
                step = 500000
                for s in range(0, ds.shape[0], step):
                    chunk = ds[s:s + step, :3]
                    lo = np.minimum(lo, chunk.min(axis=0))
                    hi = np.maximum(hi, chunk.max(axis=0))
            res["counts"]["nodes"] = res["counts"].get("nodes", 0) + total

    res["counts"]["cells"] = cells
    res["counts"]["faces"] = faces
    if np.isfinite(lo).all():
        res["bbox"] = {"min": [float(x) for x in lo], "max": [float(x) for x in hi],
                       "size": [float(x) for x in (hi - lo)]}
    return res


# ----------------------------------------------------------------------------
# 读：data 侧 —— 场、时间、配对
# ----------------------------------------------------------------------------
def read_data(h5):
    """稳态/瞬态、相数、场清单、配对路径。Data Variables 是 Fluent 的 sexp 文本。"""
    out = {
        "version": "", "origin": "", "case_ref": "", "steady": None,
        "flow_time": None, "dt": None, "op_pressure": None,
        "phases": [], "cell_fields": [], "face_fields": [],
        "time": None, "incomplete": False,
    }
    st = h5.get("settings")
    if st is not None:
        for key, field in (("Version", "version"), ("Origin", "origin"), ("Case File", "case_ref")):
            if key in st:
                out[field] = _txt(st[key][0]).strip()

        blob = _txt(st["Data Variables"][0]) if "Data Variables" in st else ""

        def grab(key, cast=float):
            m = re.search(r"\(%s\s+(-?[0-9.eE+]+)\)" % re.escape(key), blob)
            if not m:
                return None
            try:
                return cast(m.group(1))
            except ValueError:
                return None

        u = re.search(r"\(unsteady\?\s*\.\s*(#[ft])\)", blob)
        out["steady"] = (u.group(1) == "#f") if u else None
        out["flow_time"] = grab("flow-time")
        out["dt"] = grab("physical-time-step")
        out["op_pressure"] = grab("operating-pressure")

        # autosave/solution-points 里记的是写入时的 case/data 绝对路径 —— 判断配对的金线索
        m = re.search(r'\(case-file\s*\.\s*"([^"]+)"\)', blob)
        if m:
            out["case_ref"] = m.group(1) if not out["case_ref"] else out["case_ref"]
            out["solution_case_path"] = m.group(1)
        m = re.search(r'\(data-file\s*\.\s*"([^"]+)"\)', blob)
        if m:
            out["solution_data_path"] = m.group(1)

    res = h5.get("results")
    if res is None:
        out["incomplete"] = True
        return out

    # ★ results/ 下有两类节点，而且相不在第一层：
    #     results/residuals/phase-1          <- 残差（兄弟节点，不是相）
    #     results/1/phase-1/cells|faces      <- 相的场（多一层编号）
    #   只认键名会把 residuals 当成相；只看第一层会得出"没有 data"。
    #   判据统一成"往下找带 cells/ 或 faces/ 的组"。
    phases = []
    for top in sorted(res.keys()):
        g = res[top]
        if not isinstance(g, h5py.Group):
            continue
        if "cells" in g or "faces" in g:
            phases.append((top, g))
            continue
        for sub in sorted(g.keys()):
            sg = g[sub]
            if isinstance(sg, h5py.Group) and ("cells" in sg or "faces" in sg):
                phases.append((sub, sg))

    out["phases"] = [name for name, _ in phases]
    for _, g in phases[:1]:          # 只报第一相，避免多相时报表爆炸
        for part, key in (("cells", "cell_fields"), ("faces", "face_fields")):
            node = g.get("%s/fields" % part)
            if node is not None:
                try:
                    # 这个 blob 是**分号**分隔且带尾分号（`SV_U;SV_V;`），不是空格。
                    names = [x for x in re.split(r"[;\s]+", _txt(node[0])) if x]
                except Exception:
                    names = []
                # 去重保序，并把 SV_ 前缀留着（和 dat.h5 里的键一致，便于二次核对）
                seen, uniq = set(), []
                for nm in names:
                    if nm and nm not in seen:
                        seen.add(nm)
                        uniq.append(nm)
                out[key] = uniq
    return out


def read_residuals(h5):
    """每个方程：首值、末值、缩放后末值。

    ★ 列语义是实测出来的，不是文档：data[:,0] 是未归一化残差，data[:,1] 是归一化因子，
      Fluent 屏幕上打印的是两者之商。核对方式见文件头。
    """
    res = h5.get("results/residuals")
    if res is None:
        return {"equations": [], "iters": None}
    ph = sorted(res.keys())[0] if len(res.keys()) else None
    if ph is None:
        return {"equations": [], "iters": None}
    g = res[ph]
    eqs, iters = [], None
    for eq in g.keys():
        node = g[eq]
        if not isinstance(node, h5py.Group) or "data" not in node:
            continue
        d = node["data"][:]
        if d.ndim != 2 or d.shape[0] == 0 or d.shape[1] < 2:
            continue
        it = node["iterations"][:] if "iterations" in node else None
        if it is not None and len(it):
            iters = (float(it[0]), float(it[-1]), int(len(it)))
        raw = d[:, RES_RAW]
        nrm = d[:, RES_NORM]
        with np.errstate(divide="ignore", invalid="ignore"):
            scaled = np.where(nrm != 0, raw / nrm, raw)
        eqs.append({
            "name": eq,
            "n": int(d.shape[0]),
            "first_scaled": float(scaled[0]),
            "last_scaled": float(scaled[-1]),
            "min_scaled": float(np.nanmin(scaled)),
            "has_nan": bool(np.isnan(raw).any() or np.isinf(raw).any()),
            # 末三分之一的走向，用来区分"还在降"与"已经平了/在涨"
            "trend": _trend(scaled),
        })
    return {"equations": eqs, "iters": iters}


def _trend(y):
    """末 1/3 段的线性斜率（对 log10 值），>0 表示还在涨。"""
    y = np.asarray(y, dtype=float)
    if y.size < 6:
        return "样本太少"
    seg = y[int(len(y) * 2 / 3):]
    seg = seg[np.isfinite(seg) & (seg > 0)]
    if seg.size < 3:
        return "样本太少"
    x = np.arange(seg.size, dtype=float)
    k = np.polyfit(x, np.log10(seg), 1)[0]
    if k < -0.02:
        return "仍在下降"
    if k > 0.02:
        return "在上升"
    return "已平"


# ----------------------------------------------------------------------------
# 读：转录 —— 最硬的证据
# ----------------------------------------------------------------------------
ERR_PAT = re.compile(
    r"(Fatal|Error:|Divergence detected|out of memory|Null Domain Pointer|"
    r"floating point exception|SIGSEGV|invalid command)", re.I)


def scan_trn(trn_files, tail_bytes=400000):
    """从 .trn 里取：最后一条 solution is converged / Flow time / 报错行。"""
    out = {"file": "", "converged": [], "flow_time": None, "errors": [], "iterations": []}
    if not trn_files:
        return out
    latest = max(trn_files, key=os.path.getmtime)
    out["file"] = latest
    try:
        size = os.path.getsize(latest)
        with open(latest, "rb") as f:
            if size > tail_bytes:
                f.seek(size - tail_bytes)
            data = f.read()
    except OSError as exc:
        out["errors"].append("转录读不出：%s" % exc)
        return out

    text = data.decode("latin-1")          # 混合编码，latin-1 不丢字节
    # 收敛行可能不止一条（分段续算），全收但只报最后几条
    out["converged"] = re.findall(r"^\s*!?\s*(\d+)\s+solution is converged.*$", text, re.M)[-5:]
    ft = re.findall(r"Flow time\s*=\s*([0-9.eE+-]+)", text)
    if ft:
        out["flow_time"] = float(ft[-1])
    it = re.findall(r"^\s*(\d+)\s+[0-9.]+e[+-]\d+\s+[0-9.]+e[+-]\d+", text, re.M)
    if it:
        out["iterations"] = [int(it[-1])]
    seen = set()
    for m in ERR_PAT.finditer(text):
        line = text[max(0, m.start() - 60):m.start() + 120].strip().replace("\n", " ")
        key = line[:80]
        if key not in seen:
            seen.add(key)
            out["errors"].append(line)
        if len(seen) >= 8:
            break
    return out


# ----------------------------------------------------------------------------
# 判定：告警 + 接续锚点
# ----------------------------------------------------------------------------
def _stem(name):
    """把 flunet 的各种写法归一成同一个词干：duct / duct.cas.h5 / duct.cas / duct.dat.h5 → duct。

    data 里记的配对路径**经常没有扩展名**（实测 `(case-file . "...\\duct")`），
    直接比文件名会把每一份正常算例都报成"不配对"—— 那就是纯噪声，会训练人忽略告警。
    """
    b = os.path.basename(str(name)).lower()
    for suf in (".cas.h5", ".dat.h5", ".msh.h5", ".cas", ".dat", ".msh", ".h5", ".cgns"):
        if b.endswith(suf):
            return b[:-len(suf)]
    return b


def verdict(assets, mesh, data, resid, trn):
    """产出 (锚点阶段, 理由, 告警列表)。锚点按 SKILL.md §3 的 P0–P7 命名。"""
    warn, err = [], []
    has_case = bool(assets["case"])
    has_data = bool(assets["data"])
    has_mesh = bool(assets["mesh"])
    has_cad = bool(assets["cad"])
    has_wbpj = bool(assets["project"])

    # --- 结构告警
    if has_data and not has_case:
        err.append("有 data 没有 case —— 场数据脱离设置无法续算，必须先把 case 要回来")
    if has_case and not has_data:
        warn.append("只有 case 没有 data —— 这是一个「搭好但没算」的状态，从 P3 试跑开始")
    if not has_case and not has_mesh and has_cad:
        warn.append("只有几何 —— 从 P1 建网格开始")
    if has_case and not has_wbpj:
        warn.append("没有 .wbpj —— 交付前必须补 P6（用户双击打不开脚本跑的 cas）")

    # --- 区域层面（这是接手时最容易踩的）
    # 只在**已经有 case** 时才判这些：纯 .msh.h5 里区域类型本来就还没定型
    # （Meshing 只给 wall / interior），此时报"没有 inlet"是把正常状态当故障，
    # 会训练人忽略告警 —— 比不报还坏。
    fluid = [z for z in mesh.get("cell_zones", []) if z["type"] == "fluid"]
    solid = [z for z in mesh.get("cell_zones", []) if z["type"] == "solid"]
    # 先算出来，两个分支都要用（别塞进 if 里，后面还会引用）
    inlet_like = [z for z in mesh.get("face_zones", [])
                  if z["type"] in ("velocity-inlet", "mass-flow-inlet", "pressure-inlet")]
    outlet_like = [z for z in mesh.get("face_zones", [])
                   if z["type"] in ("pressure-outlet", "outflow")]
    if has_case:
        if mesh.get("cell_zones") and not fluid:
            err.append("没有任何 fluid 单元区域（全是 %s）—— 大概率是 Meshing watertight 建的 solid，"
                       "求解会报 'Flow boundary zone found adjacent to solid zone'"
                       % ", ".join(sorted({z["type"] for z in mesh["cell_zones"]})))
        if solid and fluid:
            warn.append("同时存在 fluid 与 solid 区域 —— 确认这是共轭传热，而不是忘了改类型")
        if mesh.get("face_zones"):
            if not inlet_like:
                err.append("没有任何 inlet 类边界 —— 待接管算例常见于「只建了网格，没设边界」")
            if not outlet_like:
                err.append("没有任何 outlet 类边界")
    elif has_mesh:
        warn.append("网格尚未被求解器接管：区域类型还是 mesh 侧初值（Meshing 通常只给 "
                    "wall / interior）。**这不是错误** —— 进 P2 读网格、改类型、设边界后"
                    "再跑一次体检")

    unknown = [z for z in mesh.get("face_zones", []) + mesh.get("cell_zones", [])
               if z["type"] == "unknown"]
    if unknown and has_case:
        warn.append("有 %d 个区域类型码未映射（%s）—— 本脚本的表只收实测值，"
                    "别按邻居猜，进 Fluent 用 zone 面板确认"
                    % (len(unknown), sorted({z["type_code"] for z in unknown})))

    # --- 版本
    ver = (data.get("version") or "").strip()
    if ver and not re.match(r"^24\.2", ver):
        warn.append("算例写自 Fluent %s，本 skill 只在 24.2 上验证过 —— 先按 "
                    "references/version-compatibility.md 跑六项探针" % ver)

    # --- 配对一致性
    ref = data.get("case_ref") or data.get("solution_case_path")
    if ref and has_case:
        stems = {_stem(c) for c in assets["case"]}
        if _stem(ref) and _stem(ref) not in stems:
            warn.append("data 记录的 case 是 %r（词干 `%s`），与目录里的 %s 对不上 —— "
                        "确认它们真是一对，别拿 A 的场配 B 的设置"
                        % (os.path.basename(ref), _stem(ref), sorted(stems)))
    try:
        if has_case and has_data:
            mc = max(os.path.getmtime(c) for c in assets["case"])
            md = max(os.path.getmtime(d) for d in assets["data"])
            if md < mc - 60:
                warn.append("data 比 case 旧 %.0f 秒 —— case 改过而 data 没重算，"
                            "这个 data 可能是过期的" % (mc - md))
        if has_case and has_mesh:
            mm = max(os.path.getmtime(m) for m in assets["mesh"])
            mc = max(os.path.getmtime(c) for c in assets["case"])
            if mm > mc + 60:
                warn.append("网格比 case 新 —— 网格重导过而 case 没重建，"
                            "zone ID 很可能已经重排（troubleshooting G）")
    except OSError:
        pass

    # --- 收敛证据
    eqs = resid.get("equations", [])
    if any(e["has_nan"] for e in eqs):
        err.append("残差里出现 NaN/Inf —— 上一次是发散了，不是没跑够")
    if trn.get("errors"):
        warn.append("转录里有 %d 条异常字样，见报告第 6 节" % len(trn["errors"]))

    # --- 定锚点
    # 阻断项优先：这些定死之后，后面再"按证据挑阶段"都是空的。
    # 比如单元区全是 solid 时，残差再漂亮也说明不了流动对。
    p2_blockers = []
    if has_data and not has_case:
        p2_blockers.append("只有 data 没有 case —— 网格在 case 里（§7.1 坑 1），"
                           "连离线后处理都做不了，先跟对方要 case")
    if has_case and mesh.get("cell_zones") and not fluid:
        p2_blockers.append("单元区域全是 %s —— 先在求解器里改成 fluid 再谈别的"
                           % ", ".join(sorted({z["type"] for z in mesh["cell_zones"]})))
    if has_case and mesh.get("face_zones") and not (inlet_like and outlet_like):
        p2_blockers.append("进出口类边界不全（inlet %d 个 / outlet %d 个）—— 先在 P2 补齐"
                           % (len(inlet_like), len(outlet_like)))

    if any(e["has_nan"] for e in eqs):
        anchor, why = "P3", ("残差出现 NaN/Inf —— 上一次是**跑崩了**，不是没跑够。"
                             "按 troubleshooting C 查发散，别在后处理上花时间")
    elif p2_blockers:
        anchor, why = "P2", p2_blockers[0]
    elif has_data:
        if trn.get("converged"):
            anchor, why = "P5", "转录里有 `solution is converged`，结果可用 —— 直接做后处理"
        elif eqs and max(e["last_scaled"] for e in eqs) <= RES_TOL:
            anchor, why = "P4/P5", ("末次残差全部 ≤ %.0e（启发式），但转录里没找到收敛行 —— "
                                    "先确认它是不是被上限截断" % RES_TOL)
        elif any(e["trend"] == "在上升" for e in eqs):
            anchor, why = "P3", "末段残差在上升 —— 回去做 P3 诊断，别在后处理上花时间"
        else:
            anchor, why = "P3", "残差未达判据且仍在下降 —— 大概率是跑得不够，先试续算"
    elif has_case:
        anchor, why = "P3", "case 已就位但无 data —— 从试跑自检开始（核 t=0 初始场）"
    elif has_mesh:
        anchor, why = "P2", "有网格无 case —— 读网格、修 zone、设边界，然后立刻 write-case"
    elif has_cad:
        anchor, why = "P1", "只有几何 —— 先选网格路线"
    else:
        anchor, why = "P0", "没认出可用的实体文件 —— 先跟对方确认交付物清单"
    return anchor, why, err, warn


# ----------------------------------------------------------------------------
# 渲染
# ----------------------------------------------------------------------------
def render(rep, quiet=False):
    L = []
    a = L.append
    a("# 接手体检报告")
    a("")
    a("> 离线读 `.h5`（h5py），**未启动 Fluent、未占 license**。")
    a("> 生成时间 %s｜脚本 `scripts/inspect_case.py`｜布局仅在 2024R2/v242 上实测。"
      % time.strftime("%Y-%m-%d %H:%M:%S"))
    a("")

    # 1 资产
    a("## 1 资产清单")
    a("")
    a("| 类别 | 文件 | 大小 | 修改时间 |")
    a("|---|---|---|---|")
    any_asset = False
    for kind, _, desc in ASSET_KINDS:
        for f in rep["assets"][kind]:
            any_asset = True
            a("| %s | `%s` | %s | %s |" % (kind, os.path.basename(f),
                                           _human(os.path.getsize(f)), _mtime(f)))
    for f in rep["others"]:
        any_asset = True
        a("| 其他 | `%s` | %s | %s |" % (os.path.basename(f),
                                         _human(os.path.getsize(f)), _mtime(f)))
    if not any_asset:
        a("| — | 没找到任何认得的文件 | | |")
    a("")

    # 2 身份
    ident = rep["identity"]
    a("## 2 身份")
    a("")
    if ident.get("version"):
        a("| 项 | 值 |")
        a("|---|---|")
        a("| 版本 | **%s**%s |" % (ident["version"],
                                   "（Build %s）" % ident["build"] if ident.get("build") else ""))
        a("| 求解器 | %s |" % (ident.get("solver") or "读不到"))
        a("| Origin | %s |" % (ident.get("origin") or "读不到"))
    else:
        a("读不到版本信息（可能不是 h5 格式，或 settings 布局不同）—— 别猜，"
          "用 Fluent 打开一次再另存为 `.cas.h5`。")
    a("")

    # 3 网格
    m = rep["mesh"]
    a("## 3 网格")
    a("")
    if m.get("counts"):
        a("| 项 | 值 |")
        a("|---|---|")
        a("| 单元 | %s |" % _fmt_int(m["counts"].get("cells")))
        a("| 面 | %s |" % _fmt_int(m["counts"].get("faces")))
        a("| 节点 | %s |" % _fmt_int(m["counts"].get("nodes")))
        if m.get("bbox"):
            bb = m["bbox"]
            a("| 包围盒 min | (%s) |" % ", ".join("%.6g" % v for v in bb["min"]))
            a("| 包围盒 max | (%s) |" % ", ".join("%.6g" % v for v in bb["max"]))
            a("| 物理尺寸 | (%s) |" % ", ".join("%.6g" % v for v in bb["size"]))
        a("")
        a("> 包围盒是**节点坐标的实际范围**，可以第一时间抓「几何缩了 1000 倍」"
          "（troubleshooting M）。单元尺度要 `/mesh/check` 才有，本脚本不读体积，不猜。")
    else:
        a("没读出网格（无 `meshes/` 或布局不同）。")
    a("")

    # 4 区域
    a("## 4 区域清单")
    a("")
    if m.get("cell_zones"):
        a("**单元区域**")
        a("")
        a("| ID | 类型 | 单元数 | 形状码 | 名称 |")
        a("|---|---|---|---|---|")
        for z in m["cell_zones"]:
            a("| %d | %s%s | %s | %s | `%s` |" % (
                z["id"], z["type"],
                "?" if z["type_src"] == "惯例" else "",     # 只有"惯例值"才配问号
                _fmt_int(z["cells"]),
                "—" if z.get("shape_code") is None else z["shape_code"],
                z["name"] or "—"))
        a("")
        a("> `形状码` 是 `cellType`（单元几何类型，本机实测多面体 = 7），**不是区域类型**；"
          "`未定型` 表示网格里还没有 `zoneType`（Meshing 写出的 `.msh.h5` 就这样，正常）。")
        a("")
    if m.get("face_zones"):
        a("**边界区域**")
        a("")
        a("| ID | 类型 | 面数 | 阴影 | 名称 |")
        a("|---|---|---|---|---|")
        for z in m["face_zones"]:
            a("| %d | %s%s | %s | %s | `%s` |" % (
                z["id"], z["type"],
                "?" if z["type_src"] == "惯例" else "",
                _fmt_int(z["faces"]),
                z["shadow"] or "—", z["name"] or "—"))
        a("")
        a("> 带 `?` 的类型码是**惯例值、本机未实测**；`unknown` 就进 Fluent 面板确认，"
          "别按邻居猜。**区域名可能是导入时自动生成的乱码串，认 ID 不认名字**。")
    if not m.get("cell_zones") and not m.get("face_zones"):
        a("读不到区域拓扑。")
    a("")

    # 5 场与时间
    d = rep["data"]
    a("## 5 场与时间（data 侧）")
    a("")
    if d.get("phases"):
        a("| 项 | 值 |")
        a("|---|---|")
        a("| 相 | %s（%d 个） |" % (", ".join(d["phases"]), len(d["phases"])))
        a("| 稳态/瞬态 | %s |" % ("稳态" if d.get("steady") else
                                  "瞬态" if d.get("steady") is False else "读不到"))
        if d.get("flow_time") is not None:
            a("| flow time | %s |" % ("%.6g s%s" % (
                d["flow_time"], "（稳态恒为 0）" if d.get("steady") else "")))
        # 稳态算例里 physical-time-step 是个残留值（默认 1 s），报出来会误导"这是瞬态"
        if d.get("dt") is not None and d.get("steady") is False:
            a("| 物理时间步 | %.6g s |" % d["dt"])
        if d.get("op_pressure") is not None:
            a("| 操作压力 | %.6g Pa |" % d["op_pressure"])
        a("")
        if d.get("cell_fields"):
            a("单元场：%s" % "、".join("`%s`" % x for x in d["cell_fields"][:24]))
            a("")
        if d.get("face_fields"):
            a("面场：%s" % "、".join("`%s`" % x for x in d["face_fields"][:24]))
            a("")
        if len(d["phases"]) > 1:
            a("> 多个 phase ⇒ 多相算例。**别拿单相的网格去续算**（铁律 4）。")
            a("")
    else:
        a("没有 data（或 data 里 `results/` 为空）—— 这是一份**没算过**的算例。")
        a("")
    if d.get("solution_case_path") or d.get("solution_data_path"):
        a("data 写入时记录的配对路径：")
        a("")
        a("- case：`%s`" % (d.get("solution_case_path") or "未记录"))
        a("- data：`%s`" % (d.get("solution_data_path") or "未记录"))
        a("")
        a("> 这两行是判断「这份 data 是不是这份 case 算出来的」的直接证据。"
          "路径来自别的机器/别的目录很常见，重点是**文件名是不是一对**。")
        a("")

    # 6 收敛证据
    a("## 6 收敛证据")
    a("")
    r = rep["residuals"]
    if r.get("iters"):
        a("残差采样：迭代 %d → %d，共 %d 个点。" % r["iters"])
        a("")
        a("| 方程 | 首值 | 末值 | 最小值 | 末段走向 |")
        a("|---|---|---|---|---|")
        for e in r["equations"]:
            a("| %s | %.3e | **%.3e** | %.3e | %s |" % (
                e["name"], e["first_scaled"], e["last_scaled"], e["min_scaled"], e["trend"]))
        a("")
        a("> 口径：这里报的是 **Fluent 屏幕上的缩放残差** = `data[:,0] / data[:,1]`。"
          "实测核对过（continuity 末行 6.953693e-07 / 7.411549e-04 = 9.3822e-04，"
          "与转录逐位吻合）；**直接把第 0 列当残差会小三个量级**。")
        a("> 采样点数 = 实际执行的迭代数（收敛会提前停），**别拿它当「应该跑多少步」。**")
    else:
        a("读不到残差历史。")
    a("")
    t = rep["trn"]
    if t.get("file"):
        a("转录（最硬的证据）：`%s`" % os.path.basename(t["file"]))
        a("")
        if t.get("converged"):
            a("- 收敛行：`%s solution is converged`（最后一次）" % t["converged"][-1])
        else:
            a("- **没有找到 `solution is converged`** —— 要么没收敛，要么被步数上限截断")
        if t.get("flow_time") is not None:
            a("- 最后 Flow time：%.6g s" % t["flow_time"])
        if t.get("errors"):
            a("- 异常字样 %d 条：" % len(t["errors"]))
            for e in t["errors"]:
                a("  - `%s`" % e[:160])
        a("")
    else:
        a("目录里没有 `.trn` —— 判断「跑没跑通」少了一条最硬的证据，"
          "只能靠残差与文件时间线推断。")
        a("")

    # 7 告警
    a("## 7 告警")
    a("")
    if rep["errors"]:
        a("**必须处理**")
        a("")
        for e in rep["errors"]:
            a("- ✗ %s" % e)
        a("")
    if rep["warnings"]:
        a("**需要注意**")
        a("")
        for w in rep["warnings"]:
            a("- ! %s" % w)
        a("")
    if not rep["errors"] and not rep["warnings"]:
        a("无。")
        a("")

    # 8 接续
    a("## 8 建议接续点")
    a("")
    a("**从 `%s` 接。** %s" % (rep["anchor"], rep["why"]))
    a("")
    a("> 接手不等于重搭。先按 `references/intake-existing-case.md` 走一遍"
      "「五个问题」，再决定改哪里 —— **能证明原设置错在哪，就只改那一处**。")
    a("")
    return "\n".join(L)


def _fmt_int(v):
    return "读不到" if v is None else "{:,}".format(int(v))


# ----------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="接手体检：离线读 Fluent .h5 算例，报告状态与接续点")
    ap.add_argument("paths", nargs="+", help="算例文件或目录（可多个）")
    ap.add_argument("--json", action="store_true", help="输出 JSON 而不是 Markdown")
    ap.add_argument("--out", help="把报告写到文件（.md 或 .json）")
    ap.add_argument("--quiet", action="store_true", help="不打印到屏幕")
    args = ap.parse_args(argv)

    assets, others = discover(args.paths)
    rep = {"assets": assets, "others": others, "identity": {}, "mesh": {},
           "data": {}, "residuals": {}, "trn": {}, "errors": [], "warnings": [],
           "anchor": "P0", "why": ""}

    # 身份 / 网格：case 优先，退到 mesh
    for f in assets["case"] + assets["mesh"]:
        if not _is_h5(f):
            rep["warnings"].append("`%s` 不是 HDF5（legacy 文本格式），本脚本不做深度解析"
                                   % os.path.basename(f))
            continue
        try:
            with h5py.File(f, "r") as h5:
                if not rep["identity"]:
                    rep["identity"] = read_identity(h5)
                if not rep["mesh"].get("counts"):
                    rep["mesh"] = read_mesh(h5)
        except OSError as exc:
            rep["warnings"].append("`%s` 打不开：%s" % (os.path.basename(f), exc))

    # data
    for f in assets["data"]:
        if not _is_h5(f):
            continue
        try:
            with h5py.File(f, "r") as h5:
                rep["data"] = read_data(h5)
                rep["residuals"] = read_residuals(h5)
            break
        except OSError as exc:
            rep["warnings"].append("`%s` 打不开：%s" % (os.path.basename(f), exc))

    rep["trn"] = scan_trn(assets["trn"])
    anchor, why, err, warn = verdict(assets, rep["mesh"], rep["data"],
                                     rep["residuals"], rep["trn"])
    rep.update({"anchor": anchor, "why": why, "errors": err, "warnings": warn})

    payload = rep if args.json else render(rep)
    if args.out:
        mode = "w" if args.json else "w"
        with io.open(args.out, mode, encoding="utf-8", newline="") as f:
            f.write(json.dumps(rep, ensure_ascii=False, indent=2) if args.json else payload)
    if not args.quiet:
        sys.stdout.write((json.dumps(rep, ensure_ascii=False, indent=2)
                          if args.json else payload) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
