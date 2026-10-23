# 离线后处理（二）：**组分输运**算例的体心场、单元重构与初始化陷阱

> 配套 `offline-h5-postprocessing.md`。那篇以 **PL 的 VOF + 面场**为主；本篇讲
> **组分输运（species transport）** 算例的**体心场**读法与单元几何**反算**，全部
> 结论来自 **PG（G1/G2 有毒烟气泄漏，2024R2，107222 四面体 / 222886 面）** 实测。

---

## 1. 2024R2 的关键结构事实：**网格在 `.cas.h5`，场在 `.dat.h5`**

PL 那篇列路径时没有强调这一点，很容易踩：**2024R2 把两者分开了**。

```
<case>.cas.h5                                 <case>.dat.h5
  /meshes/1/nodes/coords/<id>   ← 节点坐标     /results/1/phase-1/cells/SV_XXX/<part>
  /meshes/1/faces/nodes/1/nnodes               /results/1/phase-1/faces/SV_XXX/<part>
  /meshes/1/faces/nodes/1/nodes                /settings/Data Variables  ← 含 dt 等
  /meshes/1/faces/c0/1
  /meshes/1/faces/c1/1
  /meshes/1/faces/zoneTopology/
  /meshes/1/cells/zoneTopology/maxId  ← 单元总数
```

⚠️ `dat.h5` 顶层**只有** `['results', 'settings']` —— **没有 `meshes`**。
拿 `dat.h5` 当网格读会直接 `KeyError: 'meshes'`，且报错很像"文件坏了"。
**后处理必须成对读 `.cas.h5` + `.dat.h5`。**

✅ 从 `dat.h5` 抠 dt（避免在脚本里写死）：
```python
raw = f["settings/Data Variables"][()]        # 一条 Scheme 风格长字符串
m = re.search(r"\(physical-time-step\s+([0-9.eE+-]+)\)", raw.decode(...))
```
同一条串里还有 `(time/total-timesteps 1200)`、`(flow-time 0.5)` 等，很好用。

---

## 2. ★ 单元形心与体积：**由 `c0`/`c1` 反算**（本机实测逐位吻合）

体心场（`cells/SV_*`）是**按 cell id 1..N 直接索引**的，不需要几何就能取值 ——
但要做**体素栅格化 / 切片 / 体积加权平均**，就必须知道**每个单元的形心与体积**。
`dat.h5` 不含这些，得自己算。方法如下（对**四面体**网格精确）：

### 2.1 关键恒等式：面-单元关联数 = 4 × 单元数

```
c0 覆盖**全部**面（每面一条）        → nface  条
c1 只覆盖**内部**面（边界面的 c1 不存）→ nint   条
```

拼接后总关联数 = `nface + nint`。
实测 PG：`222886 + 206002 = 428888 = 4 × 107222` ✓
（`nint` = `default_interior-*` 面区的 `maxId`；边界面无 `c1` 条目，不是 c1=0！）

**这个等式本身就是"网格是不是纯四面体"的判据** —— 每个四面体恰 4 个面。
若非四面体（六面体/棱柱/多面体）则比值 ≠ 4，此时下述解析法不适用，
需回退到面心面积加权（对棱柱精确、对一般多面体近似）。

### 2.2 反算顶点 → 精确形心与体积

```python
inc_cell = np.concatenate([c0, c1])                       # 1-based
inc_face = np.concatenate([np.arange(nface), np.arange(nint)])   # 0-based
order = np.argsort(inc_cell, kind="stable")
cs, fs = inc_cell[order], inc_face[order]
start = np.searchsorted(cs, np.arange(1, ncell + 1), "left")
end   = np.searchsorted(cs, np.arange(1, ncell + 1), "right")
# 每个单元的面 = fs[start[i]:end[i]]；其 3 个节点取 unique -> 四面体 4 个顶点
# 形心 = 4 顶点平均；体积 = |det(v1-v0, v2-v0, v3-v0)| / 6
```

**自检（必做）**：
- 顶点数分布应**全是 4**（`{4: 107222}`）；
- 体积**全为正**（若为负说明面节点定向与 c0/c1 相反）；
- `Σ体积` 与计算域包围盒同量级（PG：1929 m³，包围盒 18.5×9.5×12 = 2109 m³，
  差额 = 炉体等固体占位，合理）。

> 不要用 `occ.getMass`（gmsh 打开 `.msh` 无 OCC 几何，恒返回 0）；
> 也不要用"节点平均"当形心（四面体下误差大）。

---

## 3. ★★ 组分初始化陷阱：**差减组分决定"环境大气"**

`standard_initialize()` 对组分用的是**混合物默认初值**，而 Fluent 的默认是
**把 `last_species`（差减组分）填 1、其余填 0**。

⇒ 若混合物写成 `{so2, o2, n2}` 且 `last_species='n2'`，
**整个计算域会被初始化成纯氮气**（实测 PG：`SV_Y` 第 3 列在
**106560 / 107222** 个单元里 = 1.0），O₂ 只能从出口回流慢慢渗入。

两个后果，都很要命：
1. **环境密度错**：N₂ 1.165 vs 空气 1.225 kg/m³（差 5%）⇒ 浮力参比失真，
   而热烟气扩散算例的核心就是浮力；
2. **评审一眼可见的物理不自洽**（"为什么初始场是纯氮气？"）。

### 正确做法：**用 `air` 作差减组分**，混合物 = `{so2, air}`

| 项 | 结论 |
|---|---|
| 环境 | `air` 差减 ⇒ 初始化**天然就是空气**，无需再 patch |
| 边界 | 只需指定 `so2`（`last_species` 由差减算出）；入口 `so2=1`，出口回流 `so2=0` |
| 组分方程 | 少一条（2 组分 vs 3 组分） |
| 与 G3 一致性 | **G3 本来就用 `air + so2`**（实测 `SV_Y` 形状 `(74796, 2)`）⇒ 口径统一，便于横向比较 |
| 代价 | 无。SO₂ 摩尔分数口径不变 |

⚠️ `air` **本来就是 Fluent 默认流体材料**（import 后的 `materials.fluid` 里已有
`['air']`）。再 `copy_by_name('air')` 会生成 **`air-1`** 这种重名副本 —— 于是
"按名取材料"变得脆弱（拿到的可能是 `air-1` 或 `air`，取决于是否重复拷过）。
**只从数据库拷 `sulfur-dioxide`**；`air` 直接复用，并按 `air` → `air-*` 的顺序做名解析。

---

## 4. 质量分数 → 摩尔分数（`molef-so2` 口径）

`cells/SV_Y` 是**质量分数**，交付/阈值用的是**摩尔分数**（"100 ppm" 指体积/摩尔分数）：

```python
M_SO2, M_AIR = 64.0648, 28.9660          # g/mol
n_so2 = Y[:, i_so2] / M_SO2
n_air = Y[:, i_air] / M_AIR
x_so2 = n_so2 / (n_so2 + n_air)
```

列序 = 混合物 `volumetric` 列表的顺序（PG 实测 `['so2','air']` →
列 0 = so2、列 1 = air）。**不要靠猜**，用下面两条锚定：
- `SV_Y.sum(axis=1) == 1` 恒成立（自检）；
- 若某列均值 > 0.9，它就是**环境大气**那一列。

---

## 5. 唯一可靠的核验：与 Fluent 自报量**逐位对齐**

`monitors_<S>.csv` 里 Fluent 通过 `report_definitions` 报出的
`so2_molef_volavg`（体 zone 的 volume-average of `molef-so2`）就是**外部真值**：

```
离线复算（体积加权）  = 4.607749836e-05
Fluent self-report    = 4.6077498e-05
相对偏差              = 7.855e-09        ← 逐位吻合
```

**这一个数字同时证明了三件事**：① 单元体积/形心反算正确；
② 质量→摩尔换算与 Fluent 口径一致；③ 组分列序没搞反。

⇒ 别用"数值看起来合理"当判据。**每次改后处理脚本都要重跑这个核验。**

---

## 6. 呼吸层栅格化：口径与 G3 完全对齐

组分输运的交付物（危险区）沿用 G3 那套已验证口径，**不要另立标准**：

| 项 | 值 |
|---|---|
| 切片带 | `y ∈ [1.5−0.10, 1.5+0.10] m`（**±0.1 m，必须写进注释/CSV说明/报告三处**） |
| 细网格 | 100×100，**最近邻**（逐点 argmin；**禁用** `scipy.griddata(method="nearest")`，实测偏小 20%） |
| 红（致死） | `x_SO2 >= 1e-4`（100 ppm, IDLH） |
| 黄（预警） | `x_SO2 >= 2e-5`（20 ppm），且**必须是红的超集** |
| 聚合 | NX×NX，块内占比 ≥ 0.5；`k = i*NZ + j`（i→X 宽，j→Z 深），三处一致 |
| 去噪 | `NX >= 50` 启用 `closing3 + median3×2` |
| 二值掩膜 | **只能最近邻**（线性插值会把面积从 40.6 吹到 80.9 m²） |

⚠️ **方位**：竖直轴是 **Y**（重力 `(0,-9.81,0)`），俯视图画 **X-Z** 平面。
`nearest_grid` 返回的数组是 `[z_idx, x_idx]`；用
`imshow(... , origin="lower", extent=[x0,x1,z0,z1])` 即得"横轴 X、纵轴 Z"，
**不需要转置**（转置规则是 PL 那套"横轴=Z"时的要求，照搬会上下/左右错位）。

⚠️ 本算例竖直轴是 Y 而不是 Z —— PL 的 VOF 算例里竖直轴是 Y 也一样，但
**Fluent 的 `gravity` 分量顺序永远是 (x,y,z)**，直接看 `gravity.components` 确认，
不要假设"第三分量是竖直"。

### 6.1 ★ 交付给下游的**文件集合与逐字格式**（PG 实测，与 G3 可互换）

只写"口径一致"不够 —— 下游是**按文件名 + 列布局**解析的。PG 与 G3 逐项对齐如下，
**新场景照抄这一组，下游解析代码零改动**：

| 文件 | 格式 | 备注 |
|---|---|---|
| `danger_zone_<NX>x<NX>.csv` | 宽表 `time, R_0..R_{N²−1}, Y_0..Y_{N²−1}`，值 0/1 | 有表头 |
| `grid_<NX>x<NX>.csv` | 长表 `time, k, red, yellow` | **故意无表头**（G3 同款） |
| `danger_summary_<NX>x<NX>.csv` | `time_s, red_cells, yellow_cells, red_area_frac, yellow_area_frac` | 红/黄**面积占比**（不是 m²） |
| `danger_zone_100x100.csv` | 宽表，**20 001 列** | 平滑动画用；**由内存里的细网格 `ravel()` 直接写，不重做最近邻** |

- 写 CSV 一律 `utf-8`（**不要 BOM**）—— BOM 会让 `Double.parseDouble` 在**第一个数**上炸，
  看起来像数据坏了。详见 `footprint-contours.md`。
- 100×100 宽表可直接由 `fine_red/fine_yel`（`[z_idx, x_idx]`）`.ravel()` 得到，
  即 `k = z_idx*NG + x_idx`；**不要**为此重跑一遍 argmin（10⁴×10⁵ 距离计算，白等几分钟）。

### 6.2 ⚠️ 「docstring 里声明了」≠「代码里实现了」

PG 实撞：`post_pg.py` 顶部注释列了
`downstream/PG_<S>_danger_summary_<NX>x<NX>.csv`，但
`grep -n summary post_pg.py` **只命中那一行注释** —— 整个脚本从未写出该文件。
因为"少一个文件"不会报错，交付时才发现下游缺数据。

✅ **正确规程：拿 docstring 的声明清单去 glob 真实落盘文件**（唯一可靠且可自动化的判据）

原理：**别去猜代码写没写**（写盘调用可能把文件名先赋给变量，如
`sum_csv = os.path.join(adir, "PG_%s_danger_summary_%dx%d.csv" % (...))` 再
`open(sum_csv, "w")` —— 字面量根本不在 `open()` 里）。**直接问文件系统**：
先跑一遍，再把声明里的 `<S>` / `<NX>x<NX>` 换成 `*` 去输出目录 glob。

```python
import io, os, re, glob

W = r"<PROJ>/PG"
DIRS = [os.path.join(W, "results", "G1", "post"),   # 改成本场景的实际输出目录
        os.path.join(W, "downstream"),
        os.path.join(W, "post")]

txt = io.open(os.path.join(W, "work", "post_pg.py"), encoding="utf-8").read()
doc = txt.split('"""')[1]        # ★ docstring 里的清单往往是无 #/* 前缀的纯文本行

missing = []
for n in sorted({os.path.basename(m) for m in
                 re.findall(r"[\w./<>-]+\.(?:csv|npz|png)", doc)}):
    pat = re.sub(r"<[^>]+>", "*", n)          # <S> / <NX>x<NX> -> *
    hits = sum(len(glob.glob(os.path.join(d, pat))) for d in DIRS)
    print("   %-46s %s" % (n, "OK ×%d" % hits if hits else "**未找到**"))
    if not hits:
        missing.append(n)
print("\n声明但未落盘（= 未实现）:", missing or "无")
```

实测（PG 修复后）：docstring 声明 8 个，**8 个全部命中**，
`danger_zone_<NX>x<NX>` 命中 2 个（20×20 与 100×100）——
这条正是把 `danger_summary` 揪出来的方式；阴性测试（把名字改一个字）能立刻报警。

⚠️ **`doc = txt.split('"""')[1]` 取的是第一个三引号块**，只适用于"清单写在文件顶部
docstring 里"的脚本；清单散落在多处函数注释里时，改成扫描全部注释行
（但**别漏掉无 `#` 前缀的 docstring 文本行** —— 交付清单十有八九写在那里）。
**不要**用"先筛出 `#`/`*` 开头的注释行、再在注释行里找名字"的写法：那样会把
docstring 里的清单**整行漏掉**，"声明集合"变成空集 ⇒ 检查**永远通过**、形同虚设。

⚠️ **`glob` 是最终判据，静态分析只能是筛查**。两条走不通的路（我都走过，别再走）：
1. **按频次判**：用「某文件名在全文出现 ≤1 次 ⇒ 只在注释里」当判据 **是错的** ——
   正常的写盘调用里那个文件名天然只出现 1 次，会**全部误报成"未实现"**。频次不是判据。
2. **按"是否出现在 `open()` 里"判**：写盘调用常把名字先赋给变量
   （`open(sum_csv, "w")`），**真写出文件的反而匹配不到**。

**同理**：脚本**互相搬运**时（G3 口径 → PG 实现）也要逐文件核对，不能只看算法段像不像。

### 6.3 ⚠️ 3D 体素场里的 **NaN ≠ 浓度 0**

体素边长（如 0.5 m）远大于单元尺寸时，厂房角落/薄壁处的体素里可能**没有单元形心**
→ 该体素记 NaN。下游若用 `np.nan_to_num(..., 0)` 会把"无数据"当成"无浓度"，
在图上画出假的洁净区。**判据**：NaN 体素数 / 总体素数应在个位数百分比量级；
报告里要明写"NaN = 该体素内无单元形心，非零浓度"。体素值用**体积加权单元平均**
（不是最近邻），保证 `Σ v_vox·C_vox ≈ Σ V_cell·C_cell`，这条要当自检项跑。

---

## 7. 脚本清单（PG 实测可用）

| 脚本 | 作用 |
|---|---|
| `pg_h5.py` | `PGCase`：读 cas 网格 → 反算单元形心/体积；读 dat 体心场；`so2_mole_fraction()`；面场口径自动判别 |
| `verify_offline_PG.py` | **口径核验**（§5）——改脚本后必跑 |
| `post_pg.py` | 离线后处理：3D 体素场（npz+长表）、呼吸层 100×100 细网格（npz）、危险区宽表/长表/摘要、单元级最终帧 CSV |
| `plot_pg.py` | 面积演化曲线 + 呼吸层云图/掩膜 + 口径对照三栏 + X-Y 纵剖面（证明 3D 数据可用） |

---

## 8. 适用边界

**适合**：体心场的取值、体积加权统计、3D 体素化、切片、阈值面积、给下游出 CSV。

**仍需启动 Fluent**：需要 Fluent 做插值/重采样（等值面抽取为几何体、导出到另一套网格）、
自定义场函数定义与求值。这类需求可以"能离线算的走离线、不能的走 Fluent"混合，
但**不要**为了统一而把全部后处理塞回 Fluent —— 离线路线每帧秒级、可逐位复现、不占许可。
