# 离线后处理：用 h5py 直接读 Fluent 的 `.cas.h5` / `.dat.h5`

**一句话**：Fluent 2024R2 的 `.h5` 结果文件**本身就是标准 HDF5**，用 `h5py`
就能读出全部网格拓扑与场数据 —— **不需要启动 Fluent、不需要许可、不吃内存**，
每帧秒级完成。凡是"后处理只是取数算指标"的需求，优先走这条路。

本文全部路径/数字来自 **PL V2（452k 四面体 + 15 个面区 + VOF + DO 辐射）**
在 **pyfluent 0.42.1 / Fluent 2024R2** 下的实测。

---

## 1. 为什么值得绕开 Fluent 会话

用 PyFluent 会话做后处理的代价：

| 代价 | 说明 |
|---|---|
| 时间 | 每场景重起会话 + 逐个存档 `file/read-data`，每帧 60~90 s |
| 资源 | 独占内存（本项目提交门槛 9 GB）与 license，**长跑期间无法并行** |
| 可靠性 | 依赖 CFF 定义、iso-clip、`report_definitions` 等**少实测**的接口 |
| 失败模式 | **静默**：不报错，只是"看起来这场仿真没数据" |

离线读 h5 把这些一次性消掉，且结果是**可逐位复现**的（不受会话状态影响），
改一行脚本即可重算全部历史帧。

---

## 2. 结构速查（实测路径）

```
/meshes/1/nodes/coords/<id>            (nnode, 3) float64   节点坐标，**1-based**
/meshes/1/faces/nodes/1/nnodes         (nface,)   int16     每面节点数
/meshes/1/faces/nodes/1/nodes          (Σnnodes,) uint32    面→节点，CSR 展平，**1-based**
/meshes/1/faces/c0/1                   (nface,)   uint32     面左侧 cell（**1-based**）
/meshes/1/faces/c1/1                   (nint,)    uint32     面右侧 cell（仅内部面）
/meshes/1/faces/zoneTopology/          —— 见 §3
/meshes/1/cells/zoneTopology/maxId     [0] = 总 cell 数

/results/1/phase-<p>/cells/SV_XXX/1    (ncell,)              体心场，**按 cell id 直接索引**
/results/1/phase-<p>/faces/SV_XXX/<part>                     面场，**口径见 §4**
```

**面→节点的 CSR 展开**（本文件所有实现都靠这段）：

```python
import h5py, numpy as np
with h5py.File(cas, "r") as f:
    nn = f["/meshes/1/faces/nodes/1/nnodes"][()].astype(np.int64)
    nl = f["/meshes/1/faces/nodes/1/nodes"][()].astype(np.int64)
    coords = f["/meshes/1/nodes/coords/17"][()]
off = np.zeros(nn.size + 1, dtype=np.int64)
np.cumsum(nn, out=off[1:])          # 面 fid（0-based）的节点区间 = off[fid] : off[fid+1]
```

**三角形面的面积/面心**（本项目网格 `nnodes` 恒为 3，实测 `Σnnodes = 3 × nface`）：

```python
def tri_geo(fid0, fid1):            # 面区间 [fid0, fid1)，0-based
    ni = nl[off[fid0]:off[fid1]].reshape(-1, 3) - 1      # 1-based → 0-based
    P = coords[ni]                                        # (n, 3, 3)
    A = 0.5 * np.linalg.norm(np.cross(P[:,1]-P[:,0], P[:,2]-P[:,0]), axis=1)
    return A, P.mean(axis=1)
```

> 若 `nnodes` 出现 4，说明有四边形/多面体面，面积公式要改成扇形分解。

---

## 3. `zoneTopology` 的实际编码（**容易踩**）

`name` 不是字符串数组，而是**一条分号拼接的字符串**，`shape=(1,)`：

```python
zt = f["/meshes/1/faces/zoneTopology"]
names = zt["name"][0].decode("utf-8", "replace").split(";")   # 长度 = 区数
ids   = zt["id"][:].tolist()        # 与 names 一一对应
los   = zt["minId"][:].tolist()     # 全局 1-based 面 id 区间
his   = zt["maxId"][:].tolist()
```

写成 `[n.decode() for n in zt["name"][:]]` 会得到一个**长度 1 的列表**，
后续按名字查 zone 一律 `KeyError` —— 而且报错信息看起来像"网格里没有 floor"。

其余字段：`fields` 是布局说明（同样分号拼接）、`zoneType`（2=interior,
3=wall, 5=pressure-outlet, ...）、`c0`/`c1`/`childZoneId`/`shadowZoneId`/`flags`/`dimension`/`faceType`。

**interior 面区**的名字形如 `default_interior-<n>`，其 `maxId` 即
`interior_max`（本项目 873069），是 §4 换算的关键常数。

---

## 4. ⚠️ 面场的下标口径**按字段而异** —— 必须按长度判别

这是最容易造成**静默错位**的地方。`.dat.h5` 里不同面场用的下标体系**不一致**：

| 数组长度 | 口径 | 下标换算 | 本项目实例 |
|---|---|---|---|
| **= 总面数**（935799） | **全局 face id（1-based）** | `k = id − 1` | `SV_VOF`、`SV_P`、`SV_DENSITY`、`SV_FLUX`、`SV_VFLUX` |
| **= 边界面数**（62730） | **仅边界面**，按 id 顺序跳过 interior | `k = id − interior_max − 1` | `SV_T`、`SV_RAD_HEAT_FLUX`、`SV_HEAT_FLUX`、`SV_H`、`SV_K`、`SV_U/V/W` |
| 按"壁面分组"分 part | 各 part 对应一组壁面 | — | `SV_WALL_YPLUS`、`SV_WALL_T_INNER`、`SV_WALL_SHEAR`、`SV_DO_IRRAD_SHELL` |

**稳健写法 —— 让长度自己说话**：

```python
def zone_idx(mesh, n, name):
    _, lo, hi = mesh.zone(name)                 # 全局 1-based 面 id 区间
    if n == mesh.n_face:                        # 全局口径
        return lo - 1, hi, "global"
    if n == mesh.n_bnd:                         # 边界口径
        return lo - mesh.interior_max - 1, hi - mesh.interior_max, "bnd"
    raise RuntimeError(f"{name}: 长度 {n} 无法判别口径")

def zone_values(mesh, fd, field, phase, name):
    g = f"/results/1/phase-{phase}/faces/{field}"
    ks = sorted(fd[g].keys(), key=int)          # 多 part → 拼接
    arr = fd[f"{g}/{ks[0]}"][()] if len(ks) == 1 else \
          np.concatenate([fd[f"{g}/{k}"][()] for k in ks])
    k0, k1, lay = zone_idx(mesh, arr.size, name)
    return arr[k0:k1], lay
```

其中 `n_bnd = n_face − interior_max`。

### 4.1 实测的错位代价（务必引以为戒）

初版对两类字段**统一套用边界偏移**，把 `SV_VOF` 错位切片，结果是：

| 量 | 错值 | 真值 |
|---|---|---|
| `∮α₂dA`（floor 上） | 0.46025 m² | **0.421395 m²** |
| `αmax` | 1.0000 | **0.06156** |
| 熔体覆盖面积 | 32.54 m² | **27.44 m²** |

**错值不报错、不警告、量级也"像那么回事"**（0.46 vs 0.42），
只有和外部真值对照才能发现。

### 4.2 **唯一可靠的判据**：与 Fluent 自己报的数逐位对齐

`monitors_<S>.csv` 里 Fluent 通过 `report_definitions` 报出的 `spread_area_m2`
（即 `∮α₂dA`）就是**外部真值**：

```
t=3.0000 → 0.421395        ← monitors_<S>.csv
离线复算   → 0.421395        ← 逐位吻合 ⇒ 口径正确
```

另做**独立几何校验**：离线复算 floor 总面积 = **151.9594 m²**，
几何设计值 151.9580 m²，偏差 **0.0009%** ⇒ 面 id 取法与三角形面积公式都对。

**不要**用"数值看起来合理"当判据。

---

## 5. 相位语义：`SV_VOF` 是**空气**分数 —— 且**路径名不可信**

`/results/1/phase-2/faces/SV_VOF` 的**数值**是本项目**空气**的体积分数
⇒ **熔体分数 = `1 − SV_VOF`**。

⚠️ 但**别用路径名推相序**。本 case 实测（L1 的 `_final.dat.h5`）：

| 路径 | 实测 |
|---|---|
| `/results/1/` | 有 `phase-1` / `phase-2` / `phase-3` **三组** |
| `phase-1/faces/SV_VOF` | **不存在**（`KeyError`）—— 只有 `phase-2` 带面场 |
| `phase-2/SV_VOF` @floor | `[0.93844, 1.00000]`，`∮·dA = 151.538`（floor 总面积 151.959）⇒ 空气 |
| 上式的 `1 − v` @floor | `∮·dA = 0.421395` = Fluent 自报 `spread_area` **逐位吻合** ⇒ 熔体 |

而 Fluent 侧那份 surface-integral 报告取的字段名恰恰叫 **`phase-2-vof`**，
积出来却是**熔体**的量 —— 即**同一份输出里 "phase-2" 的指代不一致**
（成因不必深究，但**不能靠名字判断**）。

⇒ **唯一可信的锚定物是"与 Fluent 自报量逐位吻合"**：本站就是
`monitors_<S>.csv` 的 `spread_area_m2`。做法固定为：
把互补的两个候选 `v` 与 `1−v` 各积一次，谁与自报值吻合就取谁。

其余判据保留：出现"熔体分数 > 1"或"地面温度恒等于壁温以外的怪值"，
先怀疑相位反了。

---

## 6. 贴地流体单元量：用 `c0` 反查

地面是 Dirichlet 壁面时，**面温恒等于壁温**（毫无信息量）。
要问"地面附近被加热到多少 K"，得取 **floor 相邻的流体单元**：

```python
cids = mesh.c0[lo - 1: hi].astype(np.int64) - 1        # bnd 口径时注意换算
Tcell = f["/results/1/phase-1/cells/SV_T/1"][()][cids]
```

实测：floor 面温恒 300.0 K（BC 设定），而相邻单元最高 **1512 K**
（熔体注入 1523 K）—— 后者才是"热影响"的物理量。

---

## 7. 边界条件的"必然 0"：先查 BC 再选指标

本项目 `floor` 被设为**定温 300 K 壁面**（意图：诱导熔体触地凝固），于是：

- 任何"地面温度超阈值半径"都**恒为 0**，这是 BC 的几何必然，**不是缺数据**；
- 辐射热流最大仅 **338 W/m²**（熔体光学厚度 κ=1000 /m，辐射在毫米级薄层被吸收），
  远低于人员危害阈值 1600 W/m² → 辐射半径全为 0。

**正确做法**：热影响区改用**熔体足迹半径**（`α₂>ε` 的面心到落点最大距离）
＋**贴地单元温度**。若直接照搬"地面温度半径"，会得到一张全 0 的表，
评审会误以为仿真失败。

> 结论：**任何"恒为 0"的交付指标，先回去查它依赖的边界条件类型。**

---

## 8. 退化指标的识别：面积类指标先做 ε 扫描

`∮α₂dA` 在液膜薄于网格时**退化成 `V/Δ`**（恒等式：`h<Δ ⇒ α₂=h/Δ ⇒
∮α₂dA = A_cov·h/Δ = V/Δ`）。识别方法：算 `A(α₂>ε)` 的 **ε 扫描**。

⚠️ **但不要用"`∮α₂dA` 是否 ≈ `V/Δ`"来判亚网格 —— 这是个陷阱**。
恒等式的**前提是"全部熔体都在贴地单元内"**。若还有熔体在内部
（下落射流、撞击堆积区），则 `∮α₂dA < V/Δ`。

实测（L1 @ t=3.0 s）：把所有边界面区的 `∮αdA` 加起来只有 **0.4326**，
而 `V/Δ = 1.098` —— **相差 2.5 倍**，说明约 60% 的熔体仍在内部。
该算例 `∮α₂dA ≠ V/Δ`，若按"重合才失效"的判据就会**误判成"面积可信"**，
而逐面 `αmax = 0.0616` 明明说明它是亚网格。

⇒ **唯一可靠的判据是逐面 `αmax`**（见下），ε 扫描只用来判断
"面积指标是否网格依赖 / 能否给出平台值"。

- **有平台** ⇒ 指标稳健，取平台处面积；
- **单调下降、无平台**（实测：27.44 → 0 m²，ε 从 0 到 0.062）⇒
  数值扩散主导，面积**网格依赖**，只能给量级。

配合 `αmax` 一起看：`αmax < 1` 就说明**没有任何一个网格被相完全充满**，
膜厚 < Δ，此时 `∮α₂dA` 必然退化。

**反例警示**：曾用 `h = melt_vol / ∮α₂dA` 判"深池/亚网格"，得到
`h = 0.156 m = 2.6Δ ⇒ 深池、面积可信`。但该判据是循环的 ——
膜薄时 `∮α₂dA = V/Δ`，于是 `h = Δ`，**与真实膜厚无关**。
实测真实膜厚仅 2~4 mm，旧判据**高估 40 倍**。
⇒ **判"是否亚网格"只能用 `αmax`（逐面），不能用 `V/∮α₂dA`。**

---

## 9. 最小可用脚本骨架

```python
import h5py, numpy as np

class Mesh:
    def __init__(self, cas):
        with h5py.File(cas, "r") as f:
            self.coords = f["/meshes/1/nodes/coords/17"][()]
            self.nnodes = f["/meshes/1/faces/nodes/1/nnodes"][()].astype(np.int64)
            self.fnodes = f["/meshes/1/faces/nodes/1/nodes"][()]
            self.c0     = f["/meshes/1/faces/c0/1"][()]
            self.n_face = int(self.nnodes.size)
            self.n_cell = int(f["/meshes/1/cells/zoneTopology/maxId"][0])
            zt = f["/meshes/1/faces/zoneTopology"]
            names = zt["name"][0].decode("utf-8", "replace").split(";")
            ids, lo, hi = zt["id"][:], zt["minId"][:], zt["maxId"][:]
        self.zones, self.interior_max = {}, 0
        for nm, z, a, b in zip(names, ids, lo, hi):
            self.zones[nm] = (int(z), int(a), int(b))
            if nm.startswith("default_interior"):
                self.interior_max = int(b)
        self.n_bnd = self.n_face - self.interior_max
        self.off = np.zeros(self.nnodes.size + 1, dtype=np.int64)
        np.cumsum(self.nnodes, out=self.off[1:])

    def area(self, name):
        _, lo, hi = self.zones[name]
        ni = self.fnodes[self.off[lo-1]:self.off[hi]].reshape(-1, 3) - 1
        P = self.coords[ni]
        return 0.5 * np.linalg.norm(
            np.cross(P[:,1]-P[:,0], P[:,2]-P[:,0]), axis=1)
```

配套两个自检（**每次改脚本都要跑**）：

```python
assert abs(mesh.area("floor").sum() - A_DESIGN) / A_DESIGN < 1e-3   # 几何自检
assert abs(offline_flux - monitor_spread_area) < 1e-6               # 与 Fluent 对齐
```

---

## 9.5 分区语义派生、足迹出图、粒子化（2026-10-01 S1 v2 实测）

### 9.5.1 ★ 别用"取第一个 S 类型数据集"的启发式来读 `zoneTopology`

`zoneTopology/fields`（`|S60`）与 `zoneTopology/name`（`|S117`）**都是 S 类型**，
而 h5py 的字典序里 `fields` 在 `name` 前面。所以

```python
for k in node.keys():                 # ← 错！
    v = node[k][()]
    if isinstance(v, np.ndarray) and v.dtype.kind == "S":
        return v.ravel()[0].decode().split(";")
```

会命中 `fields`，返回 **8 个名字**（`c0;c1;childZoneId;faceType;flags;shadowZoneId;zoneType;name`），
**不报任何错**。本次因此一度得到"face zone 数 = 8"，与实际的 15 个不符。

⇒ **显式取** `zt["name"][()].ravel()[0].decode()`。

另：本机 h5py 3.16 下 `grp.keys()[0]` 会抛
`TypeError: 'KeysViewHDF5' object is not subscriptable` ⇒ 一律 `list(grp.keys())[0]`。

### 9.5.2 ★ 分区语义要"**类型 + 几何 + 期望面积**"三重派生，不靠名字也不靠写死 id

gmsh 的语义名被 Fluent 改写成 `3_s_N` 后**不可逆**，而 `zone_map.json` 里的
`semantic` 只给了 `outlet` / `wall` 两组，**floor 混在 wall 里**。可靠判据：

```python
# 出口：zoneType == 5（pressure-outlet）
outs = [i for i in range(len(names)) if ztype[i] == 5]
# 地面：zoneType == 3 且形心 |y| < 1e-3 且面积 > 100 m²
#       再用设计期望面积交叉校验（< 0.1%）
```

实测（S1 v2，15 个 face zone）：

| 语义 | 判据 | 实测 | 期望 |
|---|---|---|---|
| 出口 ×5 | `zoneType==5` | ΣA = **420.000 m²** | 420.0 |
| 地面 | `zoneType==3` 且 `y_mean≈0` 且 A>100 | **152.035 m²** | 151.958（0.051%） |
| 炉壁 | 其余 wall 中 x_mean≈0 | 32.117 + 8.009 | 40.208 |

⚠️ **地面墙的 `zoneType` 也是 3**，与其它墙同型 ⇒ 单靠 zoneType 分不出来，必须叠加几何。
⚠️ 地面 zone 面积通常**小于**包围盒面积（S1：152.035 vs 16×10=160）——
差额是**炉体占位的圆形孔**（r≈1.6 m，7.97 m²），不是数据缺失。
出图时那块会是空白，别当成 bug。

### 9.5.3 ★★ 地面网格分辨率**极不均匀**时，足迹图必须按**真实面元**渲染

S1 v2 地面面等效边长从 **0.032 m（落点盒）到 0.77 m（远场）**，差 24 倍。后果：

| 画法 | 症状 |
|---|---|
| 散点（点大小 ∝ 面积） | 粗网格区**点数少** ⇒ 看起来"那里没有渣" ⇒ **假空洞** |
| 均匀细栅格统计 | 粗网格区一格摊不到一个面 ⇒ `NaN` ⇒ **假灰区** |

本次先后踩了这两次。**正确做法**：把 zone 的面元当成三角形直接渲染

```python
uniq, inv = np.unique(ftri, return_inverse=True)      # ftri: (nface,3) 0-based 顶点
tri = matplotlib.tri.Triangulation(coords[uniq,0], coords[uniq,2], inv.reshape(-1,3))
ax.tripcolor(tri, facecolors=alpha_face, cmap=cm, vmin=1e-4, vmax=0.5,
             edgecolors="none", shading="flat")
```

或按**物理量加权**做投影直方图（`histogram2d(..., weights=(alpha*vol))`）。
判据：**图上任何"空白"都要能用"面元尺寸/无面元"解释，不能用"浓度低"解释**。

### 9.5.4 亚网格膜的判据：`h_eq / 首层单元高度`

```
h_eq = ΣαV(地面层) / A(α>ε)
```

S1 v2 实测 `h_eq = 0.43 mm`，而**贴地首层单元高度中位 9.6 mm** ⇒ 比值 **1/20**。
⇒ 地面渣不是 α≈1 的连续膜，而是 **α∈[1e-3, 0.05] 的亚网格涂抹层**；
`A(α>ε)` 只表示"标记能到多远"，**不是可定量的膜面积**（详见 §8）。
同时 t=1.2 s 时**仅 45%** 的渣体积在地面层，其余仍在空中。

**交付话术**：报 `A(1e-3) ~ A(1e-4)` 的**区间** + 明标亚网格限度；
不要给单值还称其为"覆盖面积"。

### 9.5.5 粒子化：用**面邻接连通域**，并过滤单胞碎屑

不要用欧氏聚类（会把同一团切成几块、或把相近的两团并成一块）。用 `c0/c1` 建边：

```python
lut = np.full(ncell+1, -1); lut[idx] = np.arange(idx.size)   # idx = α>αc 的 1-based id
sel = (lut[edge_u] >= 0) & (lut[edge_v] >= 0)
n_cc, lab = connected_components(
    coo_matrix((np.ones(sel.sum()), (lut[edge_u][sel], lut[edge_v][sel])),
               shape=(idx.size,)*2).tocsr(), directed=False)
```

★ **必须过滤**：阈值稍低时会出现大量 `n_cells=1~3` 的连通域 —— 那是 VOF 界面涂抹，
不是物理渣团。实测未过滤时 939 条里 777 条是碎屑；加
`n_cells >= 4 and ΣαV >= 1e-8` 后剩 **162 条**，而**仍保留 92.6~100% 的渣体积**
⇒ 过滤掉的是噪声，不是质量。交付时把这个占比一并报出来。

每个粒子：`r_eff=(3V/4π)^(1/3)`、速度 = `ΣαV·u / ΣαV`。
S1 实测两段物理含义不同：**t<0.7 s 是飞行渣团（1~6 个）**，
**t≥0.7 s 是落地溅起碎片（峰值 44 个）** ⇒ 做动画不要用同一套渲染尺度。

### 9.5.6 ★ "稳定时刻"判据不能写成"从此以后都满足"

```python
for i, r in enumerate(rows):
    if all(abs(rr[key] - A_fin)/A_fin < 0.05 for rr in rows[i:]):
        stable = r["t"]; break          # ← 末帧后缀为空 ⇒ 恒真 ⇒ 永远报"已稳定"
```

本次因此把"覆盖稳定时刻"错报成 t_end。**必须要求最小后缀长度**：

```python
MIN_SUFFIX = 3
for i in range(0, len(rows) - MIN_SUFFIX + 1):
    ...
else:
    stable, note = None, "not_reached（模拟结束时仍在增长）"
```

修后正确结论：S1 在 t_end=1.2 s 时覆盖面积仍以 ≈2.4 m²/0.1 s 增长，
**完全没有稳定** ⇒ 设计要求的"持续时长 / 稳定时刻"本期给不出，需续算到 2.5~3.0 s。

---

## 10. 适用边界

**适合**：面积/通量/极值/阈值半径/时序曲线/给下游出 CSV 等"取数与算术"型后处理。

**不适合，仍需启动 Fluent**：

- 需要 Fluent 做**插值/重采样**的操作（如导出到另一个网格、等值面抽取为几何体）；
- 自定义场函数的**定义与求值**（CFF 落在 Fluent 侧）；
- 需要求解器再算的（如积分量之外的派生求解）。
  这类需求可以用"离线算不了的走 Fluent、能算的走离线"混合，但**不要**为了统一而把
  全部后处理塞回 Fluent。
