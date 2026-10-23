# PyFluent 有限液块喷溅（VOF）实战 —— S2 放出口喷溅已跑通记录

> 来源：**有限液块喷溅**案例的完整调试（ANSYS Fluent 2024R2 / PyFluent 0.42.1 / 3ddp）。案例卡片见 `../cases/S2-tapping-splashing.md`。
> 该场景用 **PyFluent 程序化操控**（非 journal）完成，本文记录全部已验证的 API 路径与踩过的坑。
> 与 `troubleshooting.md` §B5/B6（VOF 物理与网格）互补：**本文侧重"PyFluent 编程接口层面"的故障。**

## 0. 基准算例设定（同类问题的模板）

| 项 | 值 |
|---|---|
| 物理图像 | 放出口喷出**一团有限熔渣**（非连续喷流）→ 抛物线飞行 → 落地溅开铺展 |
| 液块 | Ø150 mm 球，球心 (6, 0.8, 0.15)，初速 5 m/s、15° 仰角 → `(0, 1.29, 4.83)` |
| 理论弹道 | 落地 t≈0.556 s、落点 Z≈2.84 m；`Z=0.15+4.83t`、`Y=0.8+1.29t−4.905t²` |
| 计算域 | 对称半域 X∈[6,6.5]（X=6 为 symmetry）、Y∈[0,2]、Z∈[0,3.5] |
| 网格 | 632,718 单元；弹道走廊 Box 加密 0.012 m、落地区 0.01 m；**液块 2402 单元** |
| 求解 | PISO + compressive + PRESTO! + 二阶迎风 + 隐式体积力；dt 1e-4（前 100 步斜坡）→ 5e-4 |
| 结果 | 落点 Z=2.93 m（误差 3%）、地面覆盖 0.137 m²、铺展 0.81 m × 0.63 m |

## 1. 环境与启动（PyFluent 形态）

| 项 | 值 |
|---|---|
| PyFluent Python | `<venv>/Scripts/python.exe`（PyFluent 0.42.1） |
| 启动 | `pyfluent.launch_fluent(precision="double", processor_count=6, mode="solver", ui_mode="no_gui_or_graphics", cwd=case_dir, start_watchdog=False, env=os.environ.copy())` |
| 许可证 | `ANSYSLMD_LICENSE_FILE=1055@localhost` |
| 卸载后重装的环境变量 | `AWP_ROOT242="<ANSYS_INSTALL>"` —— **重启系统后该变量会丢**，脚本里一律用 `os.environ.setdefault("AWP_ROOT242", ...)` 兜底 |

**并行核数（PyFluent 形态的实测修正）**：
- `processor_count=6` 在 **632k 单元 / 双精度 / 16 GB 机器**上**可稳定长跑**（峰值约 **5.8 GB**，留 1.3 GB 余量）。
- 同机器 **878k 单元用 6 核会 OOM 静默崩溃**（空闲内存从 7.4 GB 掉到 2.9 GB 后进程消失，**无 Windows 应用错误弹窗**）→ 先减网格或降核数。
- 与命令行 `-t8` 的 MPI 共享内存限制（见 `troubleshooting.md` §A2）是**两个不同问题**：命令行受 MPI 限制，PyFluent 形态受物理内存限制。

**内存预算法则**（本机 16.2 GB）：
```
Fluent 预算 ≈ 空闲物理内存 − (WorkBuddy ~2.3 G + 系统 ~6.5 G + 杀软 ~0.5 G) ≈ 7 GB
VOF 双精度 ≈ 3.3 KB/单元；峰值 ≈ 稳态(含 fl2420+cx2420 固定 ~1.3 G) × 1.7
```
→ 632k 单元峰值 ≈ 5.8 GB（安全）；878k ≈ 8 GB（OOM）。

## 2. 相材料赋值：`material` 是交互式命令（静默失败陷阱）

**症状**：仿真"能跑"，但液块**悬在空中不下落**、速度从 5 m/s 衰减到 0.6 m/s、地面覆盖面积为 0。
**根因**：给 phase-2 赋材料的 TUI 命令写错，**静默失败**——phase-2 仍是 air（ρ=1.225），"熔渣块"其实是**空气泡**（密度比 1:1），不受重力下落。

```python
# ❌ 错误写法（空格分隔 + 缺 yes）：不报错，但完全不生效
'(ti-menu-load-string "/define/phases/set-domain-properties/phase-domains phase-2 material slag")'

# ✅ 正确写法：斜杠路径 + "yes" 交互应答
'(ti-menu-load-string "/define/phases/set-domain-properties/phase-domains/phase-2/material yes slag")'
```

**必须做的验证（不能只看 TUI 没报错）**：
用场数据查块内实际密度，确认材料真的赋上了：
- `phase-1-density` 应 ≈ 1.225（air）
- `phase-2-density` 块内应 = 设定值（如 1200），**若仍是 1.225 说明赋值失败**

> 通用教训：**TUI 交互式命令（material / patch / define 类）写错不会报错，只会静默不生效。**
> 任何"设定后应该改变物理行为"的命令，都必须用**场数据反查**（密度、速度、体积分数）确认，
> 不能以"命令执行没报错"作为通过标准。

## 2b. 模型开关之间有**顺序耦合**，而且失败是静默的（启用 VOF 会重置时间格式）

**症状**：把时间格式设成 2 阶，**当场回读确实是 `unsteady-2nd-order`**，但写盘后
重新读回变回 `unsteady-1st-order` —— 看起来像"Fluent 存不住设置"，其实是**被后面的操作重置了**。

**根因（PL V2 实测，24R2）**：
- 脚本顺序是「设 `general.solver.time = unsteady-2nd-order` → … → **启用 VOF**」。
  **启用 VOF 会把时间格式重置回 1 阶。**
- 更坑：VOF 配方未就绪时，`methods.transient_formulation.set_state("unsteady-2nd-order")`
  **不抛异常**，但 `get_state()` 立刻回读仍是 `unsteady-1st-order`（静默 no-op）。
- `methods.transient_formulation.allowed_values` 正常列出 3 个可选值，
  **能列出 ≠ 能设上**。

**正确顺序**（实测"写盘→重开→读回"可保住）：

```python
# ① 先定 VOF 配方
'(ti-menu-load-string "/define/models/multiphase'
'/volume-fraction-parameters/formulation implicit\\n")'
# ② 再设时间格式（必须在 ① 之后）
methods.transient_formulation.set_state("unsteady-2nd-order-bounded")
```

- VOF 配方 TUI 提示 `vof formulation ( implicit explicit ) [implicit]`；R2 默认 implicit。
- 时间可选 `unsteady-1st-order / unsteady-2nd-order / unsteady-2nd-order-bounded`，
  **VOF 场景用 `bounded`**（抗界面振荡）。
- 同族的 `discretization_scheme` 是 **Map 容器**：`ds.mp = '...'` 报
  `AttributeError: mp`，必须 `ds['mp'] = 'compressive'`（本项目 A2b/A2c 实测）。
  它之所以没被重置，是因为设在 VOF 启用**之后**。

**判据（关键）**：`set_state()` 当场回读一致**不算通过**。必须
**写盘 → 另起一个会话 → 读回**再看 `general.solver.time`。
只看"设置那一瞬间"的返回值会被静默 no-op 骗过去。

> 一般化：**任何"改模型 / 改相设置"的调用，都可能重置之前设好的数值格式。**
> 所有数值格式（时间格式、离散格式）应在**模型全部启用之后**统一设一遍，
> 并在**每个落盘步骤之前重申**。本项目已固化为
> `numerics_helper.set_vof_and_time(solver)`，落盘后用 `probe_stageA.py`
> 在全新会话里核验真值。

## 3. register + patch 液块：三条顺序铁律

用 PyFluent 注册球形 region 再 patch 次相体积分数与速度。**顺序错一步就标 0 个单元。**

```python
# ① register 必须"预置在 setup 阶段保存的 case 里"，solve 阶段复用它
#    （PyFluent 下"新建" register 不触发实际标记，patch 会报 0 cells marked）
cr = solver.solution.cell_registers
cr.create("liquid_block")
reg = cr["liquid_block"]
reg.type = {"option": "sphere",
            "sphere": {"inside": True, "center": [6.0, 0.8, 0.15],
                       "radius": 0.075, "create_volume_surface": False}}

# ② 顺序：reg.type → standard_initialize → patch
#    standard_initialize 会清空 register 标记，必须在它之前设 reg.type
init = solver.solution.initialization
init.standard_initialize()

# ③ patch：cell_zones 必须传空列表 []，靠 registers 定位
p = init.patch
p.calculate_patch(domain="phase-2", cell_zones=[], registers=["liquid_block"],
                  variable="mp", reference_frame="Absolute",
                  use_custom_field_function=False,
                  custom_field_function_name="", value=1.0)
p.calculate_patch(domain="mixture", cell_zones=[], registers=["liquid_block"],
                  variable="y-velocity", ..., value=1.29)
p.calculate_patch(domain="mixture", cell_zones=[], registers=["liquid_block"],
                  variable="z-velocity", ..., value=4.83)
```

| 铁律 | 说明 |
|---|---|
| register 要**预置**（setup 阶段创建并随 case 保存），solve 阶段**复用** | PyFluent **新建** register 时 `reg.type` 不触发标记 → `0 cells marked` |
| `reg.type` 必须在 `standard_initialize` **之前** | initialize 会清空 register 标记 |
| `calculate_patch` 的 `cell_zones` 传 **`[]` 空列表** | 靠 `registers=[...]` 定位，传 zone 列表反而标不到 |

**自检**：patch 日志必须出现 `2402 cells marked`（本例 Ø150 mm 球在 0.012 m 网格下）。
出现 `0 cells marked` 就是上面三条之一违反了。

### 3b. ★★ 多个 register 必须**一次调用合传**；逐个调用会静默丢失（S1 实测）

`N cells marked` 全部正确打印、**不报任何错**，但相分数只写进去一部分：

| 调用方式（12 个球团 register） | 全域 ΣαV 命中率 | 命中团数 |
|---|---|---|
| 循环内逐个 `calculate_patch(registers=[reg])` | 24.1%（12 次累计）／0（单次） | 3 / 12 |
| **一次调用** `calculate_patch(registers=[全部 12 个])` | **93.6%** | **11 / 12** |

同一批 register 上打的**温度 patch 12/12 全部生效** ⇒ 不是 register 坏，是**逐次调用不累积**。

**⇒ 铁律：patch 相分数/温度/速度时，把全部 register 放进一次 `registers=[...]`，
绝不写 `for reg in regs: calculate_patch(registers=[reg], ...)`。**
少数仍可能漏（12 漏 1）⇒ 换**分组合传**（6+6）重试，别退回逐个。

**★ patch 后必做"t=0 存盘 + 离线核验"**：存一帧 `file.write("case-data")`，
离线读 `∫α_second·dV`，与离线 `ΣV(register 标记单元)` 比对，≈100% 才允许开长跑。
**这一关价值极高**——本例长跑 4.3 h 跑完 600 步才发现注入只有设计值的 24%。
（诊断脚本模板见 `s1-foam-slag-vof.md` §4.1。）

**切割定位法**：注入量对不上时，存"patch 后 0 步 / 1 步 / 2 步"三帧——
三帧一致 ⇒ 缺陷在 patch 时刻；只有第 0 帧对 ⇒ 缺陷在求解器首步。

## 4. 6 核并行的 `wta(1st) to string->symbol` 崩溃

**症状**：6 核并行下访问 `solver.solution.cell_registers` 抛
`wta(1st) to string->symbol`，模型启动即失败。
**定位方法**（逐步二分）：单独做 VOF 模型查询**不触发**、单独设粘性模型**不触发**，
**两者组合**才触发 → 是 Fluent 并行模式下 register 内部状态被破坏。
**处理**：把 `cell_registers` 的访问/设置**移到 VOF 查询和粘性模型设置之前**。

```python
# ✅ 正确顺序：先处理 register，再查 / 设模型
solver.file.read(file_type="case", file_name=CAS_IN)
# ... register 相关操作放这里 ...
solver.models.multiphase.models()          # VOF 查询
solver.models.viscous.model = "laminar"    # 粘性模型设置
```

> 排查手法可复用：**"两个操作单独都不报错、组合才报错"时，优先怀疑顺序/状态污染，
> 用二分法（A / B / A+B）定位，再通过调整调用顺序解决。**

## 5. 场数据提取：`node_value` 默认值会让索引错位（重要）

**症状**：探针报 `max_vof=1.000`（液块成块、未耗散），但**位置完全不对**
（t=0.01 s 时报告 Z≈1.8，理论应为 Z≈0.2），且 vof>0.5 的面片"散布全域"。

**根因**：`ScalarFieldDataRequest` 的 `node_value` 默认 **True** → 返回**逐节点**值；
而 `FacesCentroid` 返回**逐面心**坐标。两者数量和顺序都不同，**按索引配对即错位**。

```python
# ❌ 默认 node_value=True → 返回 9891 个节点值（sym 面）
vv = fd.get_field_data(ScalarFieldDataRequest(field_name="phase-2-vof", surfaces=["sym"]))

# ✅ node_value=False → 返回 19581 个面心值，与 FacesCentroid 一一对应
vv = fd.get_field_data(ScalarFieldDataRequest(field_name="phase-2-vof",
                                              surfaces=["sym"], node_value=False))
```

**只读验证方法**（不改模型，起 1 核读 checkpoint 即可）：

| 请求 | 返回长度（sym 面，本例） | 说明 |
|---|---|---|
| `SurfaceFieldDataRequest(FacesCentroid)` | **19581** | 逐面心 |
| `SurfaceFieldDataRequest(Vertices)` | 9891 | 逐顶点 |
| `node_value=True`（默认） | **9891** | 逐节点 ← 与面心错位 |
| `node_value=False` | **19581** | 逐面心 ✓ 与面心对齐 |

对齐后验证：t=0.035 s 时 vof>0.5 面片 204 个、Y[0.723,0.906] Z[0.183,0.296]，
质心 (0.822, 0.243)，argmax vof=1.000 @ Y=0.864/Z=0.201 —— 与理论弹道吻合、成块紧凑。

> **通用教训**：**PyFluent 中"坐标"与"标量"是两次独立请求，必须保证采样位置一致
> （`node_value=False`）**。任何"值对但位置怪"的现象，先查这一条。

### 5b. 返回结构：标量请求**只给值、不给坐标**（附 0.42.1 源码实证）

上面那条的自然延伸，而且**更阴**：以为一个请求就能同时拿到值和坐标。

```python
# ❌ 错误：以为 raw 里带 x-coordinate / z-coordinate
raw = fd.get_field_data(ScalarFieldDataRequest(field_name="rad-heat-flux",
                                               surfaces=["floor"],
                                               node_value=False))
node = raw.get("floor", raw)
x = node.get("x-coordinate")     # ← 永远是 None
z = node.get("z-coordinate")     # ← 永远是 None
```

**后果静默且彻底**：每帧都因 `len(x) != len(q)` 被判"字段长度不匹配"而 skip，
最后报"没有任何结果行" —— 看起来像"这场仿真没有辐射数据"，
**实际是解析代码错了，与物理无关**。

**实证**（pyfluent 0.42.1，`ansys/fluent/core/fields/field_data_interfaces.py`）：

| 请求类型 | 返回 |
|---|---|
| `ScalarFieldDataRequest` | `{面名: np.ndarray}` —— **只有场值**（`_ReturnFieldData._scalar_data`）|
| `VectorFieldDataRequest` | `{面名: np.ndarray}`，形状 (n,3) |
| `SurfaceFieldDataRequest` | `{面名: SurfaceData}` —— 坐标在 `SurfaceData.face_centroids` (n,3) |

⇒ 要"值 + 位置"必须**发两次请求**：

```python
q = fd.get_field_data(ScalarFieldDataRequest(field_name=F, surfaces=[S],
                                            node_value=False))[S]
sd = fd.get_field_data(SurfaceFieldDataRequest(
        surfaces=[S], data_types=[SurfaceDataType.FacesCentroid]))[S]
x, z = sd.face_centroids[:, 0], sd.face_centroids[:, 2]
assert len(q) == len(x)      # 面心值 ↔ 面心坐标，必须等长
```

两句都从顶层可导入（**可离线验证**，不用起 Fluent）：
`from ansys.fluent.core import ScalarFieldDataRequest` ✓ 0.42.1；
`SurfaceDataType` / `SurfaceFieldDataRequest` 在
`ansys.fluent.core.fields.field_data_interfaces`。

`_Fields` 自身只暴露 `allowed_values / allowed_variables / is_active`，
**没有** `get_field_data` —— 它在 `solver.fields.field_data`（`FieldDataSource`）上。

### 5c. 场名不要硬编码：先列出 case 的可用场再挑

**场名随版本/模型差异极大，而且 V1 的"实测命中"常常是误记**
（例：PL 里 `rad-heat-flux` 被注为"probe_radheat.py 实测命中"，
实际那个探针用的是 `rd.flux` **报告** + `report_type=flux-radheattransfer`，
**从没验证过它作为"场名"存在**）。

可靠做法：**运行时列出全部标量场 → 按关键词优先级挑 → 挑不到退温度场兜底**。

```python
def discover_fields(solver):
    for path in (lambda: solver.fields.field_info.get_fields_info(),
                 lambda: solver.fields.field_info.get_scalar_fields_info(),
                 lambda: solver.fields.allowed_values):
        try:
            r = path()
            if callable(r):
                r = r()
            names = sorted(set(_collect_names(r)))   # 递归收 dict/list 里的字符串键
            if names:
                return names
        except Exception:
            continue      # 三种探测方式逐个降级
    return []
```

两条配套经验：

1. **关键词优先级要"逐关键词"地先精确、再子串**。
   若写成"先扫完全部精确、再扫全部子串"，prefer 的顺序会**失去全局优先级**
   （实测：列表里同时有 `wall-rad-heat-flux` 与 `surface-incident-radiation` 时，
   会挑中排在 prefer 末尾的后者）。
2. **必须留一条"物理上一定存在"的兜底场**。本 case 用
   `temperature`（地面超温半径同样是合法的"热影响半径"），
   这样即使辐射场名全猜错，交付也不会落空。

> ⚠️ 还要防**首帧全败后的逐帧重试**：取数失败是**环境/API 结论**，不随帧而变。
> 首帧就失败时应立即停止（写空结果 + 诊断），而不是把 7 个存档都读一遍才发现，
> 更不能返回非零去触发整链重试。

## 6. 高密度比病态：降密度比是解法，不是表面张力

**症状**：ρ_slag=3500（密度比 2857）时，求解第 8~9 步 Courant 从 0.6 跳到 **210**、压力修正发散。
**排查（两个被排除的假设）**：
- 关表面张力 → 无效（Bo = ρgL²/σ ≈ 1717 ≫ 1，表面张力物理上本就可忽略）；
- 步长降到 1e-4 斜坡 → **发散更快**。
**根因**：极高密度比使压力 Poisson 方程 + AMG 病态（**不是 CFL 问题**）。
**处理**：ρ 3500 → **1200**（密度比 980），Courant 立刻稳定在 0.09~0.10。
> 弹道/溅开由 Fr 数主导，与密度绝对值无关 → **降密度不改变物理图像**，是安全的数值手段。

**格式选择（反直觉，实测）**：
- 隐式 VOF 下用 **geo-reconstruct 会导致进程崩溃**（Abnormal Exit / Connection refused）；
- 用 **compressive + PRESTO! + 二阶迎风** 稳定（"更稳健"的 body-force-weighted + 一阶反而崩）。
- 固化组合：`PISO` + `mom=second-order-upwind` + `mp=compressive` + `pressure=presto!`
  + `expert.numerics_pbns.implicit_bodyforce_treatment = True`

## 7. 发散后的收尾：最后一个 checkpoint 仍是有效交付

S2 在 **step 1370（t≈0.645 s）因 floating point exception 发散**（落地溅开、界面破碎、Courant>1），
没能跑到计划的 1600 步。**但 checkpoint 1350（t=0.635 s）已完整包含"落地溅开"的物理结果**，
后处理与全部交付数据均基于它 —— 结论有效。

> 处理原则：**长瞬态求解发散时，先确认"发散的最后一帧"是否已越过关键物理事件**
> （本例落地 t≈0.556 s）。已越过 → 用前一帧出结果即可，不必重算；
> 未越过 → 才需要降 dt 重跑。**不要因为"没跑完"就丢弃已完成的有效数据。**
> 若需更充分溅开，把落地后的 dt 从 5e-4 减到 2.5e-4 续算即可。

## 8. 弹道/落地区网格加密（gmsh Box 场）

- 液块 Ø150 mm，**界面区需 ≥ 7~8 格宽** → 走廊网格 0.012 m（≈9.8 格）才够；旧网格 0.02 m 只有 7.5 格 → 液块被打散。
- **加密用 Box 场，不要用 Distance 场**：Distance 场在球心处会失效（液块只有 153 单元）；
  改用 5 段 Box 覆盖弹道走廊 + 落地区 Box 后，液块达到 **2402 单元**。
- 背景网格可放宽到 0.10 m；**弹道走廊 0.012 m / 落地区 0.01 m** 是精度与规模的平衡点（632k 单元）。

## 8b. ⚠️ `∮α₂dA` 作为"铺展面积"会退化成 `V/Δ` —— 指标本身失效（PL V1 实测）

**这是最容易骗过人的一个坑：结果数值看着"很合理、还随时间单调增长"，但它是假的。**

**症状**：147 kg 熔体"铺展"到 **0.155 m²** —— 等效半径 0.22 m、平均液深 0.32 m，
那是一坨**料堆**而不是铺展。而网格一加密，"面积"就跟着变，说明它跟物理无关。

**根因（可严格推导）**：定义 `spread_area = ∮_floor α₂ dA`。当液膜厚度 `h` **小于网格
尺寸 Δ**（膜完全未被解析）时，每个含膜单元里 `α₂ = h/Δ`，含膜单元数 `= A/Δ²`，于是

```
∮α₂ dA = (A/Δ²)·(h/Δ)·Δ² = A·h/Δ = V/Δ
```

**即"铺展面积"退化成"熔体体积 ÷ 网格尺寸"**，与真实铺展形状无关。
V1 印证：Δ=0.4、V=0.0491 m³ → V/Δ = 0.1226 m²，报出 0.15526 m²（量级吻合）。

**正确做法：阈值足迹面积** `A(α₂ > ε)`

```python
# 路线 A：自定义场函数（推荐）
#   melt_ind = IF(phase-2-vof > eps, 1, 0)
#   再对 floor 做 surface-integral(field=melt_ind) → 直接就是面积
'(ti-menu-load-string "/define/custom-field-functions/define'
' \\"melt_ind\\" \\"IF(phase-2-vof>0.02,1,0)\\" \\"\\"\\n")'
# 路线 B（兜底）：iso-clip 把 floor 按 phase-2-vof>eps 裁出新面，再报 area
```

- **ε 要扫描**（本项目取 0.02 / 0.1 / 0.5）：`A(ε)` 在 `ε < h/Δ` 区间是**平台**，
  平台值才是真足迹；ε 取得过大就会开始丢面积。只报一个 ε 无法自证。
- **体检口径**：同时报 `∮α₂dA`、`∫α₂dV`（熔体体积）与 `V/Δ`。
  若 `∮α₂dA ≈ V/Δ`，说明**液膜未解析**，此时的 `∮α₂dA` 不可当面积用。

> 配套的网格判据：铺展分析要求**落点带网格**足够细。V1 的落点带是 0.4 m
> （5 m² 只有 ~300 个面单元），V2 加密到 0.06 m（17 倍面单元）。
> **"地面加密盒"必须覆盖落点带，不能只罩住炉体根部** —— 否则最需要精度的地方是粗网格。

### 8b-1. 两条路线的**具体写法**（各自都有坑）

**路线 A 唯一没有实测先例的环节是 CFF 定义那行 TUI**：
`/define/custom-field-functions/define` 第三个参数是 `clear?`(boolean)，
传 `""` 还是 `no`、name 要不要加引号，随版本而异；而且
**命令不报错 ≠ CFF 真建出来了**（这类 TUI 的典型欺骗）。
所以要多种写法都试，并用**"报告能不能接受这个名字并算出数"**当判据：

```python
for label, cmd in (
    ("tui/no",    f'/define/custom-field-functions/define "{n}" "{e}" no'),
    ("tui/empty", f'/define/custom-field-functions/define "{n}" "{e}" ""'),
    ("tui/bare",  f'/define/custom-field-functions/define {n} "{e}" no'),
    ("tui/no3rd", f'/define/custom-field-functions/define "{n}" "{e}"'),
):
    try:
        _tui(solver, cmd)
    except Exception:
        pass
# 并行再建一个 named_expression（另一套机制，报告同样能接受它）
solver.settings.setup.named_expressions[n] = {"definition": expr}
# ★ 判据：rec.field=n / rec.surface_names=["floor"] / rd.compute(...) 真能取到值
```

`report_definitions` 的用法**本身是已实测的**：
`rd.surface.create(name)` → `rec.report_type = "surface-integral"` →
`rec.field = ...` → `rec.surface_names = [...]` → 然后调**父对象**
`rd.compute(report_defs=[name])`，返回 `[{"name": [值, 索引]}]` 形态。
⚠️ **单个报告记录对象没有 `.compute()`**，别写成 `rec.compute()`。

**路线 B 的 iso-clip 参数序**（旧写法把 surface 当 cell zone 传，必然失败）：

```
/surface/iso-clip "<新面名>" <cell-zone> <field> <iso值> yes <clip 到哪个面>
# 例： /surface/iso-clip "_foot" fluid phase-2-vof 0.02 yes floor
```

### 8b-2. 真正的判据是**液深**，不是"面积 ÷ (V/Δ)"那个比值

`∮α₂dA = V/Δ` 只在**熔体全在地面上**时成立。所以比值
`r = spread_area / (V/Δ)` **混了两种完全不同的原因**，不能拿它判"膜解析/未解析"：

| r | 真实含义 |
|---|---|
| `r ≈ 1` | 熔体都在地面，且面积已退化成 `V/Δ` → 指标不可用 |
| `r < 1` | 有相当份额熔体**还在空中**（破口高时必然如此）→ 与膜解析度无关 |
| `r > 1` | 异常，需排查 |

**正确判据 —— 平均液深与网格之比**：

```
h = V / spread_area      # V = ∫α₂dV（体分），spread_area = ∮α₂dA（面分）

h >= 2Δ      → 深池：floor 邻近格 α₂≈1，∮α₂dA 就是**可信足迹**
Δ <= h < 2Δ  → 分辨极限，须用 A(α₂>ε) 复核
h < Δ        → 亚网格：已退化成 V/Δ，**不可交付**
```

PL 实证：V1 落点带 Δ=0.4 m，同样的物理图像**压在分辨极限之下**；
V2 加密到 Δ=0.06 m 后 `h = 0.147~0.156 m = 2.4~2.6Δ` → **深池，面积可信**。
**这才是"落点带加密"的真正价值** —— 不是把数字调好看，而是让判据成立。

> ⚠️ **长跑是长驻进程，改磁盘上的源码不影响它后续写出的行。**
> 所以长跑期间做的口径修正（补 `h_mean_m`、重写 `film_resolved`）
> 必须靠**跑完后统一 normalize 一遍**才能真正落到每个场景的 CSV 上，
> 否则会出现"同一批数据里前几行旧口径、后几行新口径"。

## 9. 诊断脚本清单（建议固化为模板）

| 脚本 | 用途 |
|---|---|
| `diag_phase.py` | 查块内 `phase-*-density`，验证**相-材料映射**（§2） |
| `diag_ckpt*.py` | 读 checkpoint，查 sym 面 vof>0.5 面片数 / 质心 / 范围，**对比理论弹道**（§5） |
| `verify_pos.py` / `verify_nodevalue.py` | 验证 `node_value` 长度对齐（§5） |
| `check_run.py` | **纯 Python** 巡检长跑：进度/ETA/质量守恒/液深判据 —— 不占 Fluent 许可（§8b-2）|
| `normalize_monitors.py` | 长跑**跑完后**统一补 `h_mean_m`、重写 `film_resolved`（§8b-2 的长驻进程问题）|
| `footprint_series.py` | 阈值足迹面积**时间序列** A(α₂>ε)：ε 三点扫描 + A/B/C 三路线互校（§8b-1）|
| `rad_radius.py` | 「阈值超限的最远半径」通用模板：**动态发现场名** + 温度兜底（§5b/5c）|
| `trace_block.py` | 跨多个 checkpoint 追踪块位置序列，判"耗散 / 悬停 / 正常飞行" |
| `diag_setup2.py` | 反查重力 `[0,-9.81,0]`、操作密度、材料列表等**设置是否真的写进 case** |
| `probe_stageA.py` | **新会话**读 case，打印"物理指纹"（求解器/时间格式/离散格式/多相/能量/重力/湍流/材料物性/BC 清单/zone 面数）——§2b 的判据工具 |
| `probe_zone_ids.py` | 探测 zone `id ↔ 语义名` 映射并存 `zone_id_map.json`（重导入后 ID 会重排，见 `meshing-routes.md` §3.0b） |
| `footprint_area.py` | 阈值足迹面积 `A(α₂>ε)`，ε 扫描 + 路线 A/B 双兜底（§8b） |
| `diag_massbalance.py` | 逐面 mass flux 反查，定位"熔体从哪个面流走了"（§8b 的边界版） |

> 每类"设置类"故障（材料、重力、patch、边界）都应有一个"**反查 case 实际值**"的脚本，
> 而不是相信"设置代码执行过了"。

## 10. 进程清理（Git Bash 环境注意）

Fluent 崩溃会残留 `fl2420.exe` / `cx2420.exe` / `fl_mpi2420.exe`。

```bash
# ⚠️ Git Bash 会把 //F 当路径 → 报"无效参数"；用单斜杠 /F
taskkill /F /IM fl_mpi2420.exe
taskkill /F /IM fl2420.exe
taskkill /F /IM cx2420.exe
```

- **`/IM` 不能连用多个**（`taskkill /F /IM a.exe /IM b.exe` 只会杀第一个）→ **必须分开写成多条**。
  坑：重试脚本里连写多个 `/IM`，导致残留进程累积、内存耗尽、系统卡死。
- 残留的 `cx2420.exe`（约 32 KB 的 cortex）无害，可忽略；`fl_mpi2420.exe` 才是内存大户（~4.3 GB）。

## 11. 交付下游的扇形顶点数据（S2 实测口径）

喷溅场景给下游（疏散仿真 / 危险区分析）的接口是**形态 D：多边形顶点 CSV**。

**生成口径（S2 实测）**：
1. 从地面（floor 面）提取 `phase-2-vof`，取**安全阈值 vof ≥ 0.1**（含全部熔渣痕迹 + 飞溅液滴，最保守）。
2. 相对放出口地面投影顶点(apex)算距离与半角：
   `dist = hypot(dz, dx)`、`半角 = |atan2(dx, dz)|`。
   - S2 实测：最远 R = 3.265 m、最大半角 9.46° → **取整留余量：R=3.3 m、半角 10°（全角 20°）**。
3. 扇形顶点 = `apex` + 沿弧采样 25 点 + 回到 `apex` 闭合，共 **27 行**，文件两列 `x_m,y_m`（含表头）。

**坐标映射（最易错，务必写进交付说明）**：

| CFD 轴 | → 下游 2D 轴 |
|---|---|
| CFD 的 **Z**（喷射方向） | 下游的 **X** |
| CFD 的 **X**（横向） | 下游的 **Y** |
| CFD 的 **Y**（高度） | 忽略（2D 疏散） |

- 即列表**按 (Z, X) 顺序写**就是下游的 (X, Y)，**不需要任何轴反转**。
- ⚠️ **踩过的坑**：生成脚本里多写了一次 `p[::-1]` 把 X/Y 反转，扇形变成"竖着"的，
  与喷溅覆盖图完全对不上。**生成数据后必须用实际数值反查验证**
  （判据：顶点应落在喷射起点 Z=0 侧，而不是横向中心）。见 `troubleshooting.md` §H4/H5。

**同时交付的数量级（供下游自检）**：
| 指标 | S2 实测值 |
|---|---|
| 落点 | Z = 2.93 m（理论 2.84 m，误差 3%） |
| 地面覆盖面积 | 0.137 m² |
| 铺展范围 | 横向 0.81 m × 纵向 0.63 m |
| 地面 vof 峰值 | 0.979 |

**可选交付：离散块清单**。若下游要"一块一块"的真实喷溅形态（主池 + 飞溅液滴）而非扇形包络，
可用连通性聚类（网格 0.02 m）把 vof≥0.5 的地面点聚成若干块，导出
`blob_id, n_points, center_z, center_x, radius`。S2 实测：**8 块**（1 个主池占 97.5% + 7 个液滴）。
