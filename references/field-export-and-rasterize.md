# 场数据导出与栅格化接口规范

> 目标：把 Fluent 的**单元场数据**（浓度、体积分数、压力）转成下游（疏散仿真 / 风险分析 / 汇报图件）能直接消费的**危险区栅格掩膜**，
> 并保证"CFD 云图"与"下游动画"用**同一份口径**、可逐格校验。

---

## 1. 全链路

```
Fluent case + 多帧 data.h5
   ↓  /file/export/ascii         （后处理，串行一次会话）
so2_<step>.xyz   ← 表头 cellnumber x-coordinate y-coordinate z-coordinate molef-so2
   ↓  切片带 + 最近邻插值 + 阈值化 + （高密度）形态学去噪
NG×NG 细网格掩膜
   ↓  块内占比聚合
NX×NX 栅格掩膜 → 宽表 CSV（time, R_0..R_n, Y_0..Y_n）
   ↓  宽表 → 长表
G3_grid_<NX>x<NX>.csv（time, cell, red, yellow）→ 下游
```

生成脚本：`scripts/export_field_journal.py`（第 1 步）+ `scripts/rasterize_field_to_grid.py`（第 2~4 步）。

---

## 2. 第 1 步：批量导出场数据（`/file/export/ascii`）

### 2.1 交互式答案序列（实测转录）

```text
> /file/export/ascii "<CASE_DIR>/export/so2_00000.xyz"
()                       <- Surfaces(1) [()]        空 = 全部
no                       <- Delimiter/Comma?         no = 空格分隔
molef-so2                <- ASCII scalar(1)
()                       <- ASCII scalar(2)          空 = 结束变量列表
yes                      <- Location/Cell-Centered?  yes = 单元中心值
```

**必须逐行写在 journal 里**，这些是交互提示，少一行就会吃掉后续命令。

### 2.2 关键词

- **`Location/Cell-Centered?` 选 `yes`**：导出**单元中心值**。选 `no` 会输出节点插值值，节点数 ≠ 单元数，栅格化时对不上。
- **`Delimiter/Comma?` 选 `no`**（空格分隔）。选 yes 会出逗号分隔，解析脚本要相应调整。
- 一次可以导出多个变量：在 `ASCII scalar(1)` 输 `molef-so2`、`ASCII scalar(2)` 输 `pressure`……最后用 `()` 结束。列序与输入顺序一致。

### 2.3 多帧最小 journal 结构

```text
/file/read-case "case.cas.h5"

/file/read-data "frame_00000.dat.h5"
/file/export/ascii "export/so2_00000.xyz"
()
no
molef-so2
()
yes

/file/read-data "frame_00200.dat.h5"
/file/export/ascii "export/so2_00200.xyz"
()
no
molef-so2
()
yes

/exit
```

- **read-case 一次，read-data 逐帧**，全在一个会话内串行完成。这是实测最快的方式。
- 13 帧 74796 单元，日志约 1.6 万行，耗时分钟级。
- 用 `scripts/export_field_journal.py` 生成，避免手写重复块。

---

## 3. 第 2 步：切片带 + 最近邻插值

### 3.1 切片带（必写进口径）

```python
Y0, DY = 1.5, 0.10            # 呼吸高度 ±0.1 m
m = (y >= Y0 - DY) & (y <= Y0 + DY)
```

**这个数字必须写进脚本注释、CSV 说明、报告三处。** 不同高度得到的危险区面积差异很大，漏写口径数据就不可复现。

### 3.2 最近邻实现：**用逐点 argmin，不要用 scipy griddata**

```python
def nearest_grid(x, z, c, NG, xlim, zlim):
    xi = np.linspace(*xlim, NG); zi = np.linspace(*zlim, NG)
    XI, ZI = np.meshgrid(xi, zi)
    pts = np.column_stack([XI.ravel(), ZI.ravel()])
    src = np.column_stack([x, z])
    out = np.empty(len(pts))
    B = 2000                                   # 分块，避免超大中间矩阵
    for i in range(0, len(pts), B):
        blk = pts[i:i+B]
        d2 = ((blk[:, None, 0] - src[None, :, 0])**2 +
              (blk[:, None, 1] - src[None, :, 1])**2)
        out[i:i+B] = c[np.argmin(d2, axis=1)]
    return out.reshape(NG, NG)                 # [z_idx, x_idx]
```

**为什么不用 `scipy.interpolate.griddata(method="nearest")`**：它基于 Delaunay 三角剖分的凸包，对**重复点、边界外点**的处理与逐点 argmin 不同。实测同一份 G3 数据，t=10 s 红区面积 griddata 得 **32.27 m²**，逐点 argmin 得 **40.57 m²**（偏小 20%），而后者才与 post 基准一致。

> **验证面积口径时，必须用与交付脚本相同的 argmin 实现。**

### 3.3 二值掩膜禁止用线性插值

`griddata(method="linear")` 会把峰值抹开：同一数据实测面积从 40.6 暴涨到 **80.9 m²**。

**规则**：连续色标云图可以用线性；**二值掩膜只能用最近邻**。

---

## 4. 第 3 步：阈值化与高密度去噪

### 4.1 阈值

```python
RED_THRESHOLD    = 1e-4    # 100 ppm（IDLH）
YELLOW_THRESHOLD = 2e-5    # 20 ppm
red_mask = CG >= RED_THRESHOLD
yel_mask = CG >= YELLOW_THRESHOLD
```

**黄色必须是红色的超集**（黄区 ⊇ 红区），聚合时用 `yellow = yellow or red` 保证。

### 4.2 为什么高密度必须去噪

CFD 单元数 << 目标格点数时，最近邻会产生**马赛克噪点**。

G3 实测：呼吸层只有 **1923 个单元**（平均间距 ~0.23 m），铺到 100×100（0.1 m 网格）后，t=10 s 红区：

| 指标 | 原始 nearest | 去噪后 |
|---|---|---|
| 连通块数 | **38** | **7** |
| 最大块占比 | 59.1% | **84.8%** |
| 面积 (m²) | 40.57 | 43.48（+7%） |

还有"四角误标红"的现象——粗网格的"块内占比 ≥ 0.5"判据恰好把它抹平，一提高分辨率就全部暴露。

### 4.3 去噪方案实测对比（t=10 s）

| 方案 | 面积 | 连通块 | 最大占比 |
|---|---|---|---|
| 原始 nearest | 40.57 | 38 | 59.1% |
| median 3×2 | 40.43 | 17 | 58.3% |
| median 3×3 + closing 3 | 38.89 | 10 | 60.1% |
| **closing 3 + median 3×2（选用）** | **43.48** | **7** | **84.8%** |
| closing 5 + opening 3 | 47.39 | 6 | 88.3% |

**选用 `closing3 + median3×2`**，并在 `NX >= 50` 时才启用（不改变低密度已验证结果）：

```python
def smooth_mask(mask):
    m = ndimage.binary_closing(mask, structure=np.ones((3, 3)))
    m = ndimage.median_filter(m, size=3)
    m = ndimage.median_filter(m, size=3)
    return m
```

代价：面积 +7%（闭运算填补了碎裂边界）。**若验收要求严格对齐 post 基准面积，退回 10×10 或 50×50。**

> 残留的细窄白缝（最近邻上采样的马赛克残留）**无法靠闭运算填**——查过内部封闭孔洞 = 0，即细缝都连通到边界。下游画布单格仅 4 px 时肉眼几乎不可见。

### 4.4 聚合到 NX×NX

```python
bx, bz = NG // NX, NG // NZ
for i in range(NX):          # i → X（房间宽）
    for j in range(NZ):      # j → Z（房间深）
        rb = red_m[j*bz:(j+1)*bz, i*bx:(i+1)*bx]
        k = i * NZ + j       # ★ 全链路统一的 cell 编号
        red[k]    = 1 if rb.mean() >= 0.5 else 0
        yellow[k] = 1 if (yb.mean() >= 0.5 or red[k]) else 0
```

块内占比阈值 0.5 的作用：避免粗网格把 X 形对角线之间的死区污染成危险区。

---

## 5. 索引、转置、镜像 —— 跨工具一致性的三个雷

### 5.1 cell 编号

```
k = i * NZ + j        i → X（房间宽），j → Z（房间深）
```

**栅格化脚本、长表转换脚本、下游消费代码三处必须完全一致。** 改一处必须改三处。

### 5.2 显示前必须转置

`reshape(NG, NG)` 得到的是 `[X][Z]`；要按"横轴 = Z、纵轴 = X"显示（或反过来）必须转置：

```python
img = mask.reshape(NG, NG).T      # → [Z][X]
plt.imshow(img, origin='upper', extent=[0, 10, 10, 0])
```

漏转置的表现是**图左右/上下错位**，但数值总量是对的——很容易被误判成"数据有问题"。

### 5.3 下游画布与云图上下镜像

| 位置 | 下游 2D 画布（Y 轴向下） | post 云图（Z 轴向上） |
|---|---|---|
| 泄漏口 (X=5, Z=0) | **顶部**中央 | **底部**中央 |
| 门 (X 8~10, Z=10) | **底部**右侧 | **顶部**右侧 |

阈值、切片高度、数据源**完全相同**，唯一差别是镜像。

**并排对比前必须翻转其一**，否则会被误判成"下游没用 Fluent 数据"。

---

## 6. 宽表 / 长表两种 CSV 格式

### 6.1 宽表（栅格化脚本直接产出，人可读）

```
time,R_0,R_1,...,R_9999,Y_0,Y_1,...,Y_9999
0.0000,0,0,...,0,0,...
```

- 表头：`time` + 前 N 个 `R_k`（红）+ 后 N 个 `Y_k`（黄）。
- 便于核对、便于画图；**不适合下游直接读**（列数太多）。

### 6.2 长表（下游消费用）

```
time,cell,red,yellow
0.0000,0,0,0
0.0000,1,0,0
...
11.3100,9999,1,1
```

- **无表头**，4 列，按 time 升序、每个 time 内 cell 0..n−1 升序，共 `nTime × N` 行。
- 转换器从宽表**表头自动推断格数**，10×10 / 20×20 / 50×50 / 100×100 均通用，无需改代码。
- 100×100 × 13 时刻 = **130000 行**。下游若有读缓冲，要放到 200000（默认 20000 会越界）。

### 6.3 占位数据

框架搭建期可用物理上说得过去的占位数据先把下游框架跑通（危险区从泄漏口近似圆形扩散），等 CFD 出结果**零改动换真数据**。占位数据必须标注清楚，避免被当成真实结果（G3 就踩过"格子颜色与 PPT 云图对不上"）。

---

## 7. 逐格校验（证明下游用的就是 Fluent 数据）

**做法**：写一个渲染脚本，**直接 import 栅格化模块并调用同一函数**，即"与下游数据由同一份代码生成"，口径 100% 一致（同切片、同最近邻、同阈值、同去噪）。

G3 实测结果：13 个时刻与交付 CSV **累计差异 = 0 格**。这是评审时最有力的证据。

同时产出"口径对照图"（连续色标云图 / 边界叠加 / 二值掩膜 三栏并排），用来解释"为什么视觉上不同"——云图 turbo 对数色标下大片红色是 10⁴~10⁶ ppm 核心，而 **100 ppm 只对应色标中低端的青绿色**，两者量级差 100 倍以上。

---

## 8. 自检清单

| # | 检查 | 期望 |
|---|---|---|
| 1 | `.xyz` 表头 | `cellnumber x-coordinate y-coordinate z-coordinate <var>` |
| 2 | `.xyz` 数据行数 | = 网格单元数（如 74796） |
| 3 | `Location/Cell-Centered?` | 回答 `yes` |
| 4 | 切片带高度 | 写进注释/说明/报告三处 |
| 5 | 最近邻实现 | 逐点 argmin（不是 scipy griddata nearest） |
| 6 | 二值掩膜插值 | 最近邻（禁线性） |
| 7 | NX ≥ 50 | 已启用 closing3 + median3×2 |
| 8 | 黄区 | 是红区超集 |
| 9 | cell 编号 | 三处脚本/代码一致 `k = i*NZ + j` |
| 10 | 显示 | 已转置为 `[Z][X]`；并排对比已处理镜像 |
| 11 | 长表 | 4 列无表头；行数 = nTime × N |
| 12 | 复现性 | 重跑脚本 `diff -q` 逐字节一致 |
