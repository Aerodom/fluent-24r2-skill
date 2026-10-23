# S1 泡沫渣 VOF 案例：可复用结论（2026-09-21 实测，Fluent 2024R2 / PyFluent）

> 场景：泡沫渣喷溅（VOF 两相 + 能量 + 表面张力关闭）。案例卡片见 `../cases/S1-foam-slag-splashing.md`。
> 本文只记**跨案例可复用**的东西；S1 的项目细节见项目 MEMORY.md §七。

---

## 1. `/file/import/cgns/mesh` 崩在 `Importing` 之后 —— 新的排查范式

**症状**：`Importing "X.cgns"` 之后立刻 `Fatal failure in fluent (disconnected /
ended abnormally)`，无栈、无 TUI 报错、无 `Opening library devtools4.4.6.dll` 行。

**★ 不要一上来就查 PATH**（那是最常见的解释，但本例不是）。按下面的**二分**走，
每步都要有实测依据：

| # | 实验 | 判读 |
|---|---|---|
| C | 导一份**历史上成功过**的 CGNS | 成功 ⇒ 环境正常，问题在本文件；失败 ⇒ 环境级（许可/MPI/内存），别改网格 |
| F | 全量网格体检（见 §1.1） | 全过 ⇒ 网格质量不是原因 |
| R | 把参数回退到**上次成功**的配置重生成 | 仍失败 ⇒ 不是参数 |
| T | 把 `TEMP` 指到另一个盘再试 | 仍失败 ⇒ 不是临时空间 |
| M | 加内存（2→4 GB）再试 | 仍失败 ⇒ 不是内存 |

**本例结论（★ 已于 2026-09-22 被推翻，见下）**：C 通过、F 全过、R 失败、T 失败、M 失败
⇒ 当时判定"是这份 gmsh 重导出的 CGNS 本身（结构自洽但读取器不接受）"。240k 与 287k 两版都一样。

**★★ 更正（2026-09-22 实测）：真正坏的是 `fluent.exe -i journal` 这条启动路径，不是 CGNS 文件。**
改用 **PyFluent** 导入同类 gmsh 导出文件：
`S1.cgns`（241 487 四面体）**第 1 次即成**；后续 `S1v2.cgns`（1 628 493 四面体）同样
**第 1 次即导入成功**（57 s，日志正常打出 `1628493 cells, 1 zone / 3276279 faces, 15 zones`）。
⇒ 上面那张二分表（C/F/R/T/M）**全部是在坏路径上做的**，"文件本身有问题"的结论不成立。
**现行做法**：CGNS 导入一律走 **PyFluent + 重试**，不再用 `fluent.exe -i journal`。
（§1.1 的全量网格体检仍保留，作为独立于导入路径的质量把关。）

**⚠️ 反例警告（PL 的 `diag_import.py`）**：当年那份"二分结论"表把 U 组（UNV 路线）
判成**通过**，实际是 journal 里 `/file/import/ideas` 是**非法命令**、Fluent 退 0 且无
`Fatal failure`，被 runner 的 `"Fatal failure" not in out and "EXIT: 0" in out`
判据误判。⇒ **判"导入成功"只能看日志里出现 `1 cell zone, N face zones`，
绝不能看 exit code，也不能只看"无 Fatal failure"。**

### 1.1 全量网格体检（离线、30 秒，不启 Fluent）
在 h5py 直读 CGNS 上做，判据（本例全部通过，却依然导不进）：
- 体单元含**重复顶点**个数 = 0
- 四面体**最小体积** > 0（本例 3.1e-6 m³）
- 面单元**零面积**个数 = 0
- 边界面**全部**能对应到体单元的面（孤儿数 = 0）
- **自由面数 == 边界面数**；被 ≥3 个单元共用的面 = 0 ⇒ 水密、流形、共形
- `Zone_t` 声明的 `VertexSize/CellSize` 与实际数组长度一致
- `ElementRange` 连续无空洞

⚠️ gmsh 写的 CGNS 里**所有数据集名都带前导空格**（`' data'`），且**根组名 = 文件名**
（`/<file>.cgns/<Part0>/...`）。

---

## 2. VOF 案例的 h5 槽位命名（★ 与单相案例完全不同）

单相/组分案例里 `results/1/<zone>` 的语义在 VOF 下**会整体挪位**。实测（2 相 VOF）：

| h5 组 | 实际内容 | 验证依据 |
|---|---|---|
| `results/1/phase-1` | **混合场**（`SV_T`/`SV_U`/`SV_P`/`SV_DENSITY`/`SV_MU_LAM`…16 字段，**无 VOF**） | 密度 1.225~1250 跨越两相 |
| `results/1/phase-2` | **第 1 相（主相）** | ρ≡1.225、μ≡1.7894e-5、`SV_VOF` = α₁ |
| `results/1/phase-3` | **第 2 相（次相）** | ρ≡1400.0000、μ≡1.0000、`SV_VOF` = α₂ |

⇒ **判据：不要按"phase-2 就是次相"去读**。用密度/黏度的**常数值**反查这是哪一相。

**网格组口径**：
- `meshes/1/faces/c0` 长度 = **总面数**；`c1` 长度 = **内部面数**。
  ⇒ 纯四面体：`4 × ncell = len(c0) + len(c1)`（可当场校验）
- `meshes/1/faces/nodes/1` 是 **CSR 扁平布局**：`nnodes`（每面节点数）+ `nodes`（扁平连接），
  **不是** `(nface, 3)` 二维数组。统一 `reshape(-1, cnt[0])`（cnt 全同）或按 offsets 切。
- `faces/zoneTopology/name` 是 `|S<N>` 字符串，**分号拼接**多个 zone 名，需 `decode().split(";")`。

---

## 3. 离线复算单元几何（四面体）—— 必须先用 ΣV 对齐 Fluent

```
faces_sorted = 按 c0/c1 把面归到每个单元（纯四面体 ⇒ 每单元恰好 4 个面，bincount 可验）
nodes12      = faces_sorted 的节点索引 → (ncell, 12)，每行 sort
v4           = nodes12[:, [0,3,6,9]]      # 四面体每个顶点在 4 个面里出现 3 次
centroid     = coords[v4-1].mean(1)
volume       = |det(p1-p0, p2-p0, p3-p0)| / 6
```

**★ 硬判据**：`Σ volume` 必须与 Fluent `/mesh/check` 自报的 `total volume` 吻合到
浮点精度（实测 rel **5.5e-8**）。不吻合就说明面/单元映射错了，后面所有积分都是错的。

---

## 4. register patch 的**单元量化**：先离线预演，再用 `N cells marked` 回读

**坑**：`cell_registers` 的 `sphere(inside=True)` 按**单元形心落格**标记。
当球半径 R 与当地网格尺度 h 同量级（本例 R=0.052~0.072 m vs h=0.070 m）时，
标记数在 0~19 之间剧烈抖动 —— 实测 **12 个球里 2 个标记 0 个单元（完全不存在）**，
单个体积误差 −100%~+69%。

**处置套路**
1. 先用离线几何**预演**每个球标到几个单元（`dist(centroid, center) <= R`），
   把团心**吸附到最近单元形心**（保证至少 1 个），半径取 `2R/h ≳ 1.7`。
2. 跑完后**回读 Fluent 的 `N cells marked`**（TUI 会逐次打印），与离线预测**逐团比对**。
   实测逐团精确吻合（5,3,1,6,1,1,16,2,1,24,5,1），这一步同时反证了离线几何与
   Fluent 的 register 语义一致。
3. **报"注入体积"要报量化值 `Σ V_cell(标记单元)`，不是解析值 `4/3πR³`**，
   后续体积守恒核验都以量化值为基准。

**patch 顺序（S2/solve_vof.py 已验证）**：
`重设 register.type` → `standard_initialize()` → `calculate_patch(...)`。
- register 必须**预置在 case 里**，运行时"复用 + 重设 `.type`"才会真正标记单元；
  PyFluent 下**新建** register 会报 `0 cells marked`。
- register 创建必须在 `standard_initialize` **之后**，否则保存的 case 读回会报
  `wta(1st) to string->symbol`。
- 相分数：`domain="phase-2", variable="mp", value=1.0`；速度：`domain="mixture",
  variable="x-velocity" | "y-velocity" | "z-velocity"`；温度：`domain="mixture",
  variable="temperature"`。
- `reference-frame is not set as it is inactive` 是**无害提示**，patch 仍生效。

### 4.1 ★★ 多 register 必须"一次调用合传"，逐个调用不累积（2026-09-21 实测）

**症状**：12 个球团、12 个 register，循环里逐个 `calculate_patch` 打相分数。
TUI 每次都打印正确的 `N cells marked`（与离线预测逐团吻合）、**不报任何错**，
但离线读回发现：
- **α patch 只有 3/12 个团生效**，其余 9 团 α **精确 = 0**；
- 同期打的**温度 patch（同 register、同循环结构）12/12 全部生效**；
- 全域注入体积只有设计值的 **24.1%**，而且**求解器此后完全守恒**（t=0/1/2 步三位小数不动）
  ⇒ 亏空 100% 发生在 patch 时刻，与求解/网格无关。

**实测对照（同一 case、同一批 register，只改调用方式）**：

| 调用方式 | 全域 ΣαV | 命中团数 |
|---|---|---|
| 循环内**逐个** register 各调一次 | 0（单次调用）／24.1%（12 次累计） | 0 / 3 |
| **一次调用** `registers=[全部 12 个]` | **93.6%**（1.0477e-02 / 1.1197e-02） | **11 / 12** |

union 调用下，11 个团的 ΣαV 与离线 `ΣV(标记单元)` **逐位吻合**：
`14.28 11.80 6.86 10.89 7.07 9.07 9.52 11.27 6.08 11.64 7.46`（×1e-4 m³，
对离线 `… 7.46 7.20` 只差最后一个团）。

**★ 铁律**：
1. 相分数/温度/速度 patch **一律把全部 register 放进**一次 `calculate_patch` 调用；
   不要写 `for reg in regs: calculate_patch(registers=[reg], ...)`。
2. **patch 完必须存一帧 t=0 的 case-data，离线核验 `ΣαV` 是否 ≈ 离线 `ΣV(标记单元)`**，
   通过才允许长跑。这个"t=0 存盘 + 离线核验"是最便宜的把关（本例把 4.3 h 的长跑救回来了：
   否则跑完 600 步才发现注入只有 1/4）。核验脚本模板：`exp_s1_patch_probe.py` + `cmp_s1_exp.py`。
3. union 合传后**仍会漏**——而且不是"随机漏"，是**必然漏「本次调用中最后一个真正标记到单元的
   register」**。修法**不是**分组合传（那样只会漏更多，见 §4.2），而是**加一个牺牲位**。

**诊断范式（可复用）**：注入量对不上时，**把亏空在时间轴上切开**——
"patch 后 0 步"、"patch 后 1 步"、"patch 后 2 步"各存一帧。
- 三帧**完全一致** ⇒ 缺陷在 patch 时刻（抄本例）；
- 只有第 1 帧对 ⇒ 缺陷在求解器首步（查格式/CFL），不要去改 patch。

### 4.2 ★★ union 合传的残留缺陷：**末位 register 被涂抹** →「牺牲位」修法（2026-09-30 实测）

**症状**（S1 v2，5 团合成一次调用）：
- TUI 报告 5 团的 `N cells marked` 与离线逐团预测**逐位一致**（2446 / 2410 / 2554 / 2457 / 2482）；
- 但离线读回**相分数**：**只有末位那一团是糊的**——球内 687 个单元 α ∈ [0.43, 0.999]，
  另有 935 个单元在球外也被涂上了值；
- 同期**温度 patch 完全正常**（12349 个单元 = 5 团并集，逐位吻合）。
⇒ 缺陷**只出现在相分数域**，且**只落在末位 register**。

**对照实验**（同一 case，只改顺序 / 分组，看缺陷落在哪）：

| 变体 | 调用方式 | 出问题的团 |
|---|---|---|
| 正序 | 5 团一次调用，末位 = `blob_05` | **`blob_05`** |
| 逆序 | 5 团一次调用，末位 = `blob_01` | **`blob_01`** |
| 分组 | 3 + 2 两组各调一次 | **`blob_03` 和 `blob_05`**（两组各自的末位） |
| 单个 | 只 patch `blob_05` | **`blob_05`** |

⇒ **规律：被涂抹的是「本次调用中最后一个真正标记到单元的 register」，与它的几何位置无关。**
分组合传**只会多漏**（每组漏一个）⇒ §4.1 铁律 3 里旧的"换分组合传"建议**是错的，已作废**。

**两个"看着像牺牲位、实际不能用"的陷阱**（都实测过）：

- 在列表末位放一个 **0 单元**的新 register ⇒ Fluent **直接忽略**，等于没加（结果与不加逐位相同）；
- 会话内**新建**的 register（哪怕圈到了单元）⇒ **不参与标记**，`N cells marked` 报 0。
  **register 必须烘焙进 case**（写 case → 另起会话读回）才真正生效。

**可用修法：把牺牲位做成"藏在队头团内部的微型球"，并烘焙进 case**

1. 在 case 里预置一个很小的 register（本例 `zz_sac0`，**R = 0.030 m、118 个单元**），
   球心放在 **`blob_01` 的球心** ⇒ 它**完全被 `blob_01` 包住**；
2. 用**写 case → 读回**的方式让它真标记（读回后才生效）；
3. `calculate_patch` 时把 `blob_01..blob_05` + `zz_sac0` **一次合传**，牺牲位放**列表末位**。

**结果（S1 v2 正式 t=0 帧）**：

| 指标 | 值 |
|---|---|
| ΣαV | **1.121476e-02 m³**（与离线预测相对偏差 **3.1e-16**，机器精度） |
| 五团 αmean | **全部 1.0000**（`n\|0\|0` —— 无一团被涂抹） |
| `α>0` 单元数 | **12349 = `T>1000K` 单元数**（完全一致） |
| 溢出球外的单元 | **0** |

**为什么牺牲位不污染 `blob_01`**：牺牲球整体位于 `blob_01` 内部，两者相分数的**并集仍是 `blob_01`**，
且被赋同样的值（α = 1）⇒ 对注入总量与形状**零影响**。
代价是多一个 register，收益是把"随机漏一团"变成"确定性不漏"。

**核验判据要三条一起看**（只看总量会漏掉"糊了一团但总量守恒"）：
① ΣαV ≈ 离线预测；② **逐团 αmean 是否全为 1.0000**；
③ **`α>0` 单元数是否等于 `T>1000K` 单元数**（本例 12349 = 12349）。

---

## 5. PyFluent 站点（24R2 / 0.42 实测）

1. **`settings.solution.run_calculation` 在读入 case 之前是 inactive**
   ⇒ `InactiveObjectError`。必须先 `file.read(case)` 再取 `run_calculation.transient_controls`。
2. **材料比热属性名是 `specific_heat`**，不是 `cp`（`fluids["x"].cp` → AttributeError，
   `__getattr__` 会列出可用名）。
3. **`/define/phases/set-domain-properties/phase-domains/<phase>/material yes <mat>`**
   —— `yes` 不能省，省了**静默失败**（相仍绑定 air）。
4. **打印 PyFluent 包装对象别用 `%.4f`**：属性读取返回的是 `value_N` 包装对象，
   `%` 格式化会 `TypeError: must be real number, not value_11` ⇒
   **会被误读成"设置失败"**（本例误报了 4 条 `[FAIL]`，实际全部写入成功，回读值正确）。
   要打印就取 `.value`。
5. 经验证的"已落盘"判据：**另起会话读回**（`get_state()`），不是设置瞬间的返回值。
6. **边界条件的压力不在 `bc[z].pressure`**（AttributeError）——真实路径是
   `bc[z].phase["mixture"].momentum.gauge_pressure`。出口表压 0 之类的值**出厂默认即目标值**时，
   **读值核验即可、不必写**（强行写反而可能踩 `InactiveObjectError`）。
7. **`operating_density` 是 method 型设置**（默认 `minimum-phase-averaged`），**没有 `.enable`** ——
   VOF 想要的"操作密度 = 最小相平均"就是它的默认行为，不要去"开启"它。
8. **`auto_save.append_file_name_with` 是子对象**：直接赋值 `a.append_file_name_with = "time-step"`
   报 `ASSQ: invalid argument [2]: improper list`；正确写法
   `a.append_file_name_with.file_suffix_type = "time-step"`（另有 `.file_decimal_digit`）。
   并且**逐项独立 try** —— 一项抛异常会静默吞掉同函数内后续所有赋值。
9. **梯度格式挂在 `methods` 下**（`solver.methods.gradient_scheme`），
   **不在** `discretization_scheme` 里；写错位置不报错、只是静默不生效。
10. **`Solution` 容器没有 `Import`**（class 是 `DataContainerReference`，调用抛 AttributeError）。
    它的 case 经 `MasterSources` 的 `FluentSetup` 数据依赖从 `Setup` 取得；
    这一步真正能做的只有 `ImportInitialData(FilePath=<dat>)`。
11. **`auto_save.root_name` 只写纯文件名**（如 `"S1v2_auto"`），**不要带目录** ——
    Fluent 写到"当前工作目录"，在 Workbench 里跑时即 `dp0/<系统节点名>/Fluent/`，
    自动与工程绑定；搬到别机也不会写错地方。

---

## 6. VOF 高密度比案例的配方取舍（S2 血泪，S1 继承）

- **表面张力（CSF）默认关闭**。判据用邦德数 `Bo = ρgL²/σ`：本例
  `1400×9.81×0.04/0.45 ≈ 1221 ≫ 1` ⇒ 物理上可忽略；而 S2 实测在高密度比下
  CSF 会产生**寄生流速**导致发散。`tui.define.phases.set_domain_properties.
  interaction_domain.forces.surface_tension.sfc_modeling("no")`
- **不要用 `geo-reconstruct` / `body-force-weighted`**：S2 实测在隐式 VOF 下会让
  Fluent 进程崩溃。可用组合：`mp=compressive` + `pressure=presto!` + `mom=2阶迎风`.
- 隐式 VOF 必须显式设：`/define/models/multiphase/volume-fraction-parameters/formulation implicit`，
  且**必须在设时间格式之前**（启用 VOF 会把时间格式重置）。
- 高密度比（>1000:1）时把重相密度适当下调可显著改善 AMG 压力方程条件数
  （S2：3500 → 1200）。**但这属于数值妥协，交付文档必须标明是工程假设。**

---

## 7. ★ 有限液块喷溅：先算"网格能否分辨液块"，再谈物理（判据前置）

**这是 S1 最贵的一课**：注入量、配方、边界全对了，结果依然不可用，因为**网格分辨不了液块**。

**量化判据**（S2 正例 vs S1 反例）：

| 案例 | 液块直径 | 走廊网格 | 液块跨单元数 | 结果 |
|---|---|---|---|---|
| S2（已验证成功） | Ø150 mm | **0.012 m** | **≈9.8 格**（液块 2402 单元） | 落点误差 3%、地面 α_peak=0.979、成片铺展 |
| S2（失败前置版） | Ø150 mm | 0.020 m | ≈7.5 格 | **液块被打散** |
| S1（失败） | Ø122 mm | **0.070 m** | **≈2.4 格** | α_max 由 1.0 崩到 0.1（0.1 s）→ 0.014（1.2 s） |

**⇒ 铁律：液块直径 / 当地网格尺度 ≥ 7~10 才勉强可辨，工程上取 ≥10 稳。**

**开工前必做**（30 秒，离线，不启 Fluent）：
```python
# 用已知网格尺度 h 反算"可分辨的最小注入体积"
R_min = 5 * h                    # 取 10 格直径
V_min = 4/3*pi*R_min**3
# 若设计注入体积 V_inj << V_min  ⇒ 该网格不能算这个案例，必须重新加密
```
本例：`h=0.0703` ⇒ `R_min=0.35 m` ⇒ `V_min=0.18 m³`，而设计 `V_inj=1.1e-2 m³`
—— **差 16 倍，直接判死**，不必跑。

**⚠️ 别被"设备复用"忽悠**：S1 本来打算复用 PL V2 网格（"零重新建模"）。但
**PL V2 的加密盒是为"地面薄膜"打的（地面中位 0.060 m），不是为"空中团块"打的**。
同一台设备、同一个计算域，**物理形态变了，网格加密目标必须重算**。

**三种补救方向**（按代价排序）：
1. **重新加密网格**（正解）：只沿**弹道走廊**（不是整个包围盒）+ 落地区加密成 Box 场，
   不要用 Distance 场（S2 实测 Distance 场在球心处失效，液块只剩 153 单元）。
2. **把注入改成"可分辨的雾团"**：同样的总质量/体积，摊在一个 Ø≈10h 的云团内
   （α = V_inj/V_cloud，本例 ≈0.17），物理上对应"泡沫破碎成稠密喷雾"。
   零建模成本，但初始形态与"若干独立液块"不同，**交付文档必须写明这是等效假设**。
3. **按亚网格口径交付**：报面峰值 αmax + 做 α 阈值 ε 扫描，明标"面积不可定量"
   （与 PL 薄膜的处理一致）。⚠️ 若 ε 扫描**无平台**（本例 αmax 只有 0.059，扫不出平台），
   则该项交付物实质不可用，不能靠"合理化"掩盖。

---

## 8. 交付形态：可移植 `.wbpj` 工程（"拷到别机、GUI 点运行"）

S1 v2 的最终交付**不是本机跑完的结果**，而是一个**已把 Fluent 设置全部配好**的 Workbench 工程：
用户拷到大内存机器 → 双击打开 → 点运行即可。配方与判据全文见
`wbpj-project-generation.md` §8（四步法则 / 静态判据 / 决定性验证）。这里只记 S1 特有的三条：

1. **素材 = `S1v2_t0.{cas,dat}.h5`**：阶段 A（`setup_s1v2.py`，40 项 0 失败）产出 case；
   阶段 B（`init_patch_s1v2.py`，含 §4.2 牺牲位配方）产出 patch 后的 t=0 帧，
   **离线核验 PASS 后才允许进工程**。
2. **`dat` 必须挂在 `Solution` 容器**（`ContainerAssociations: ["Solution"]`），
   且系统属性 `"Start from available data": "True"` —— 这两条决定用户点运行时**用不用得上注入初值**。
   ⚠️ **只把 dat 拷进目录是不够的**：那样它只是个"搭便车的散文件"，不会被当成初始场。
3. **别让用户走 `Setup` 入口**：Workbench 的 `Setup` 只读 case，用户会看到一个 α 全 0 的冷态，
   从而误判"没配好"。交付说明里要明确写：**更新 `Solution`**（或双击 `Solution`），
   并在 Fluent 控制台确认**既读了 case、也读了 dat**。

**这个案例最有价值的一条元结论**：交付"点一下就能算"的工程，
**验证必须覆盖到"点下去之后用的是不是对的初值"**，
而不是止步于"工程能打开、文件都在"。
