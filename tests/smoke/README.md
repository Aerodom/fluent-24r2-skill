# 冒烟测试（tests/smoke/）

**目的**：换机器、换版本、改流程之后，用**最小代价**判断"这套流程还能不能跑"。
判据不依赖任何历史实测数据 —— 用矩形管道层流的**解析解**。

```
make_geometry.py   gmsh → duct.step（无许可证，自带单位自检）
make_mesh.py       Fluent Meshing watertight → duct.msh.h5（约 2 min）
run_case.py        读网格 / 改流体域 / 拆 zone / 认进出口 / 设边界 / 求解 / 取数
check_result.py    解析解校核（不需要 Fluent，可单独跑）
```

几何：长 1.0 m × 高 0.1 m × 宽 0.02 m，高宽比 5:1。
介质：空气，层流（Re ≈ 220），入口均匀 0.1 m/s，出口压力出口 0 Pa。
网格：多面体，1.5 mm，53.1 万单元。

```bash
WORK=<ASCII_WORK>                 # 必须是纯 ASCII 路径，见下面第 2 条
python make_geometry.py  $WORK
python make_mesh.py      $WORK
python run_case.py       $WORK
python check_result.py   --result $WORK/result.json
```

> `<ASCII_WORK>` 是占位符 —— 本机实测用的是 `C:` 盘根下一个短英文目录。
> 别把真实路径抄进仓库，`scripts/audit_sensitive.py --strict` 会拦。

---

## 判据（两段，只有都过才算 PASS）

| # | 判据 | 容差 | 为什么 |
|---|---|---|---|
| 1 | 出口面积加权平均速度 = 入口均匀速度（连续性） | **2%** | 对网格几乎不敏感，但任何"边界条件错 / 体区域是 solid / 单位缩 1000 倍 / 进出口接反"都会立刻打偏 |
| 2 | `u_max / U_mean` 对解析解（1.7236） | **±10%** | 对网格敏感；带宽按实测收敛性标定，不假装能做到 3% |

分开两条的意义：第 1 条过、第 2 条不过，说明"算对了但网格不够细"，**不是流程坏了**。
否则换台机器很容易把正常的离散误差误判成 skill 失效。

---

## 实测状态（2026-10-23，Fluent 2024R2 / PyFluent 0.42.1 / 2 进程 / Windows x64）

**全链路已跑通，两条判据都 PASS。**

| 环节 | 状态 | 实测结论 |
|---|---|---|
| gmsh 生成 STEP | ✅ | 15.5 KB，6 个 `ADVANCED_FACE`；自带单位自检 |
| Meshing 导入 STL | ❌ | `Faceted formats, like '.stl' … are not yet supported` |
| Meshing watertight 全流程 | ✅ | STEP → `.msh.h5`，124 MB / 53 万单元 / 约 2 min |
| 求解器读原生 `.msh.h5` | ✅ | `read-case` + `mesh/check` 正常 |
| 求解器读 **gmsh `.msh`** | ❌ **SIGSEGV** | 四边形、三角形都在 `Building... mesh` 处崩（troubleshooting K） |
| 求解器读 **CGNS** | ❌ **SIGSEGV** | 同上 |
| `solid → fluid` 改体区域类型 | ✅ | 不改就报 "Flow boundary zone found adjacent to solid zone"（troubleshooting P） |
| `sep_face_zone_angle` 拆 zone | ✅ | 合并的 wall → 6 个面 zone |
| 按面积认端面 | ✅ | 面积 `0.1 / 0.02 / 0.002` 各两个，两个 0.002 就是端面，10 倍差距不会认错 |
| 按 x 坐标定进出口 | ✅ | `facet_max(report_of="x-coordinate")` → x=0 当入口、x=1 当出口 |
| 设边界 + 300 步 | ✅ | 层流、压力基、定常 |
| 出口取数 | ✅ | `facet_max` / `area_weighted_avg`，靠转录通道拿值（troubleshooting L） |
| 解析解校核 | ✅ | 自检：正方形 2.1068（文献 2.096，+0.5%）、5:1 = 1.7236、50:1 → 1.527 |

### 最终数字

```
CFD  u_max          = 0.162327 m/s
CFD  出口面积加权平均 = 0.100073 m/s      -> 连续性偏差 0.07%   PASS
CFD  u_max/U_mean   = 1.6221               -> 对 1.7236 偏差 -5.9%  PASS
```

### 网格收敛性（带宽标定的依据）

| 网格 | 单元数 | `u_max/U_mean` | 偏差 | 判据 |
|---|---|---|---|---|
| 2.5 mm | 13.5 万 | 1.5300 | −11.2% | FAIL（该判 FAIL） |
| 1.5 mm | 53.1 万 | 1.6221 | −5.9% | PASS |

方向是对的：网格加密 → 峰值升高 → 趋近解析解。这与多面体网格在窄缝方向层数不足
会低估层流峰值的已知行为一致。要做到 ±3% 需要约 1.0 mm（约 260 万单元），
在"冒烟测试"的代价预算里不值得。

---

## 跑不通时按这个顺序查

这几条都是本轮实测踩出来的，**每一条都在真实运行里发生过**：

1. **几何是不是小了 1000 倍**（troubleshooting M）：`make_geometry.py` 有单位自检，
   它会读回 STEP 算物理尺寸；先看它过不过。
2. **工作目录是不是有中文**（troubleshooting N）：`C:\Users\<中文名>\` 下 Meshing
   会在 CAD 导入报 "Error in CAD Import"，措辞完全误导。
3. **网格尺寸单位**（troubleshooting O）：Meshing 按 STEP 声明单位（毫米）解释尺寸，
   传成"米"会变成 1.5 µm 然后 OOM。
4. **体区域是不是 solid**（troubleshooting P）。
5. **网格文件是不是新的**（troubleshooting Q）：`write_mesh` 遇到同名文件静默不覆盖，
   最危险 —— 会拿旧网格跑出"看起来合理"的结果。

## 目录约定

生成物写在 `tests/smoke/work/`（已 gitignore），**不要提交网格与结果文件**。
该目录默认退回系统临时目录（脚本所在路径若含非 ASCII）。
