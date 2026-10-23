#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""冒烟测试第 3 步：求解器侧 —— 读网格 / 拆 zone / 按面积认进出口 / 求解 / 取数。

**为什么这里不"正常"地调 API**（PyFluent 0.42.1 实测，2026-10-23）：

    `m.tui.file.*`   整条不可用 -> RuntimeError: eval: unbound variable / Error Object: file
    `m.results.report.surface_integrals.area(...)`   不抛错但**返回 None**
    `report_definitions` 里**没有** `surface_area` 属性

所以本脚本的取数方式是：**开转录 → 执行报表 → 停转录 → 正则解析 .trn**。
报表值确实算出来了，只是不通过返回值给你，而是打印进转录：

                                Area                [m^2]
    -------------------------------- --------------------
    wall:1:001                                       0.002

另外两个关键字坑：
    - `facet_max` 的场变量参数叫 **`report_of`**，叫 `field` 会报
      "Unknown keyword 'field'" 并忽略（然后报 'report-of' is a required argument）。
    - `area_weighted_avg` 在没有流场数据时是 **inactive**，未初始化前调会抛
      InactiveObjectError。

进出口识别：6 个面 zone 中，**两个最小面积的必然是端面**
（0.1x0.02 = 0.002 m²；侧壁 0.02、上下壁 0.1，三者相差 10 倍，不会认错）。
端面之间的朝向再靠 `facet_max(report_of="x-coordinate")` 定；拿不到就把两个端面
按名字排序，并在结果里标 `orientation="assumed"`，同时用 abs(max) 与 abs(min) 兜底。

用法：
    python run_case.py [工作目录]
依赖：ansys-fluent-core；工作目录见 make_mesh.py 的 ASCII 路径要求。
"""
import json
import os
import re
import sys

import ansys.fluent.core as pyfluent

U_IN = 0.1          # 入口均匀速度 m/s
ITERS = 300
SPLIT_ANGLE_DEG = 45.0

# 转录里的报表块：虚线分隔行 + 上一行表头 + 若干 "<名字> <数值>" 行
DASH = re.compile(r"^\s*-{10,}\s+-{10,}\s*$")
ROW = re.compile(r"^(\S+)\s+(-?\d+\.?\d*(?:[eE][+-]?\d+)?)\s*$")


def parse_tables(text):
    """把转录里的报表块抽成 [(表头, {名字: 数值}), ...]，保持出现顺序。"""
    lines = text.splitlines()
    out = []
    i = 0
    while i < len(lines):
        if DASH.match(lines[i]):
            header = lines[i - 1].strip() if i > 0 else ""
            rows = {}
            j = i + 1
            while j < len(lines) and lines[j].strip():
                if DASH.match(lines[j]):
                    break          # 汇总区（Net/Total）另起一段，不算 zone
                m = ROW.match(lines[j].strip())
                if m and m.group(1).lower() not in ("net", "total", "sum"):
                    rows[m.group(1)] = float(m.group(2))
                j += 1
            if rows:
                out.append((header, rows))
            i = j
        else:
            i += 1
    return out


class Reports:
    """把报表包成"一次调用 -> 一张表"的形态，靠转录拿结果。"""

    def __init__(self, solver, trn_path):
        self.m = solver
        self.trn = trn_path
        self.ri = solver.results.report.surface_integrals
        self.log = []

    def _reset(self):
        if os.path.exists(self.trn):
            os.remove(self.trn)

    def _tables(self):
        with open(self.trn, "r", encoding="utf-8", errors="replace") as f:
            return parse_tables(f.read())

    def run(self, kind, surfaces, report_of=None):
        """执行一次报表，返回 (表头, {面名: 值})；失败返回 (None, {})。"""
        self._reset()
        self.m.settings.file.start_transcript(file_name=self.trn)
        try:
            fn = getattr(self.ri, kind)
            kwargs = {"surface_names": list(surfaces), "write_to_file": False}
            if report_of is not None:
                kwargs["report_of"] = report_of
            fn(**kwargs)
        except Exception as exc:  # noqa: BLE001
            self.log.append("%s(%s) 失败: %s" % (kind, report_of, exc))
            return None, {}
        finally:
            try:
                self.m.settings.file.stop_transcript()
            except Exception:  # noqa: BLE001
                pass
        tables = self._tables()
        if not tables:
            self.log.append("%s(%s) 无输出" % (kind, report_of))
            return None, {}
        return tables[-1]


def pick_end_zones(areas):
    """两个最小面积 = 端面。返回 (端面列表, 落选列表)。"""
    ordered = sorted(areas.items(), key=lambda kv: kv[1])
    return [z for z, _ in ordered[:2]], [z for z, _ in ordered[2:]]


def main():
    work = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "work")
    work = os.path.abspath(work)
    mesh = os.path.join(work, "duct.msh.h5")
    if not os.path.exists(mesh):
        raise SystemExit("缺少网格 %s —— 先跑 make_mesh.py" % mesh)

    trn = os.path.join(work, "run_case.trn")
    result = {"ok": False, "u_in": U_IN, "iters": ITERS, "work": work}

    m = pyfluent.launch_fluent(
        dimension=3, precision="double", processor_count=2, mode="solver",
        ui_mode="no_gui_or_graphics", start_transcript=False, cwd=work,
    )
    try:
        m.settings.file.read_case(file_name=mesh)
        m.mesh.check()
        print("[ok] read-case + check")

        # 0) watertight 工作流建出来的体区域默认是 **solid**（日志里是 `solid aluminum`），
        #    直接给它贴 velocity-inlet 会报
        #      "Flow boundary zone found adjacent to solid zone.
        #       This problem MUST be fixed before solution proceed"
        #    所以先把 cell zone 类型改成 fluid。
        cz = m.settings.setup.cell_zone_conditions
        solids = list(cz.solid.keys())
        if solids:
            cz.set_zone_type(zone_list=solids, new_type="fluid")
            print("[ok] cell zone solid -> fluid：%s" % solids)

        # 1) 把合并成一个的 wall 按 45° 拆开（角度用度，PyFluent 内部转弧度）
        walls = list(m.settings.setup.boundary_conditions.wall.keys())
        m.tui.mesh.modify_zones.sep_face_zone_angle(walls[0], SPLIT_ANGLE_DEG)
        zones = list(m.settings.setup.boundary_conditions.wall.keys())
        print("[ok] 拆成 %d 个面 zone" % len(zones))

        # 2) 一次性问所有 zone 的面积
        rep = Reports(m, trn)
        header, areas = rep.run("area", zones)
        result["area_header"] = header
        result["areas"] = areas
        if len(areas) != len(zones):
            raise SystemExit("面积表行数(%d)与 zone 数(%d)不符，转录解析失败：%s"
                             % (len(areas), len(zones), rep.log))
        print("[ok] 面积（%s）：" % (header or "?"))
        for z, a in sorted(areas.items(), key=lambda kv: kv[1]):
            print("      %-55s %.6g m^2" % (z, a))

        caps, others = pick_end_zones(areas)
        result["caps"] = caps
        result["walls"] = others

        # 3) 先初始化一次，让"场量报表"从 inactive 变 active
        #    （`facet_max` / `area_weighted_avg` 在没有任何数据时会抛
        #      InactiveObjectError，这一步就是为它们铺路。此时还没设进出口，
        #      hybrid 会退化成常值初始化，够用。）
        m.settings.solution.initialization.hybrid_initialize()

        # 4) 定朝向：端面的 x 坐标
        orientation = "assumed"
        xmap, how = {}, None
        for kind, rpt in (("facet_max", "x-coordinate"),
                          ("area_weighted_avg", "x-coordinate"),
                          ("vertex_max", "x-coordinate")):
            header, vals = rep.run(kind, caps, report_of=rpt)
            got = {k: v for k, v in vals.items() if k in caps}
            if len(got) == 2:
                xmap, how = got, "%s(%s)" % (kind, rpt)
                break
        if xmap:
            inlet = min(xmap, key=xmap.get)     # x 小的当入口
            outlet = max(xmap, key=xmap.get)
            orientation = "detected"
            print("[ok] 按 x 坐标定向（%s）：inlet=%s  outlet=%s" % (how, inlet, outlet))
        else:
            inlet, outlet = sorted(caps)
            print("[warn] 拿不到端面 x 坐标，按名字排序定朝向（%s -> %s）"
                  % (inlet, outlet))
        result.update({"inlet": inlet, "outlet": outlet,
                       "orientation": orientation, "cap_x": xmap})

        # 5) 设边界（层流、定常、压力基显式写死，不靠默认值）
        m.settings.setup.general.solver.type.set_state("pressure-based")
        m.settings.setup.models.viscous.model.set_state("laminar")
        bc = m.settings.setup.boundary_conditions
        bc.set_zone_type(zone_list=[inlet], new_type="velocity-inlet")
        bc.set_zone_type(zone_list=[outlet], new_type="pressure-outlet")

        # velocity-inlet 的速度怎么设，取决于 velocity_specification_method：
        #   默认 "Magnitude, Normal to Boundary" -> 用 `velocity`，且它是带 option 的
        #   命名对象，state 形如 {"option": "value", "value": 0}
        #   此时 `velocity_magnitude` 不存在、`velocity_components` 是 inactive。
        vi = bc.velocity_inlet[inlet]
        mom = vi.momentum
        try:
            mom.velocity.set_state({"option": "value", "value": U_IN})
        except Exception:  # noqa: BLE001
            mom.velocity_magnitude.set_state(U_IN)
        print("[ok] inlet=%s %.3g m/s / outlet=%s 0 Pa" % (inlet, U_IN, outlet))

        # 6) 正式初始化 + 迭代
        m.settings.solution.initialization.hybrid_initialize()
        m.settings.solution.run_calculation.iterate(iter_count=ITERS)
        print("[ok] %d iterations" % ITERS)

        # 6) 取出口最大/最小 x 速度（流向若反了，最大值会接近 0，靠 min 兜底）
        header, vmax = rep.run("facet_max", [outlet], report_of="x-velocity")
        _, vmin = rep.run("facet_min", [outlet], report_of="x-velocity")
        result["vmax_header"] = header
        result["vmax_raw"] = vmax
        result["vmin_raw"] = vmin
        cands = [abs(v) for v in list(vmax.values()) + list(vmin.values())]
        if not cands:
            raise SystemExit("取不到出口速度：%s" % rep.log)
        umax = max(cands)

        # 连续性校核：出口面积加权平均 x 速度必须等于入口均匀速度。
        # 这条对网格几乎不敏感，是抓"边界条件/流体域/单位搞错"最锋利的指标。
        uavg = None
        for kind in ("area_weighted_avg", "mass_weighted_avg"):
            _, vals = rep.run(kind, [outlet], report_of="x-velocity")
            got = [abs(v) for v in vals.values()]
            if got:
                uavg = got[0]
                result["uavg_kind"] = kind
                break
        result.update({"umax": umax, "uavg_out": uavg, "ok": True})
        print("[ok] 出口 max|x-velocity| = %.6g m/s（U_in=%.3g）" % (umax, U_IN))
        print("     比值 u_max/U_mean = %.4f（U_mean=U_in，连续性）" % (umax / U_IN))
        if uavg is not None:
            result["continuity_err"] = abs(uavg / U_IN - 1.0)
            print("     出口面积加权平均 = %.6g m/s，连续性偏差 %.2f%%"
                  % (uavg, result["continuity_err"] * 100))
        else:
            print("[warn] 取不到出口平均速度，跳过连续性校核：%s" % rep.log)

        m.settings.file.write_case_data(
            file_name=os.path.join(work, "duct.cas.h5"))
        print("[ok] wrote case+data")
    finally:
        result["report_log"] = getattr(locals().get("rep", None), "log", [])
        with open(os.path.join(work, "result.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        try:
            m.exit()
        except Exception:  # noqa: BLE001
            pass
    if not result.get("ok"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
