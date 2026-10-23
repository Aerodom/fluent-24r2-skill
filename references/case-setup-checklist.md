# 可压缩瞬态案例逐面板检查单（分支 A）

适用：爆炸 / 冲击波 / 高压气体泄放 / 高速喷流等**压力梯度（惯性）主导**的毫秒级过程。
用法：自上而下逐项核对；每项都给出"为什么"，避免漏设或照抄。

> **本文件按物理分支组织**：
> - **分支 A · 可压缩瞬态（本文件 §0–§14）** —— 爆炸、冲击波、高压气体泄放、高速喷流。
> - **分支 B · VOF 多相流（§15）** —— 液体泄漏、熔体泄漏、熔体喷溅、自由液面。
> - **分支 C · 组分输运（§16）** —— 有毒/可燃气体泄漏、烟气扩散。
>
> 先按 `../SKILL.md` §2 判物理类型（A/B/C/D），再只用对应那一节；有同类型案例时先看
> `../cases/README.md` 的索引。**不要跨分支照抄**——
> 例如把可压缩瞬态的"密度基 + 二阶瞬态 + 不开重力"套到 VOF 上，会直接得到错的结果。

---

## 0. 先确定场景物理与验收指标

| 项 | 需要明确的内容 |
|---|---|
| 几何与域 | 计算域尺寸、坐标轴含义、关键部件的坐标 |
| 高压源 | 压力、温度、介质、容积 |
| 环境 | 压力、温度 |
| 泄放口 | 位置、等效孔径、是否已开孔 |
| 测点 | 位置列表（相对哪个面/轴起算）、预期峰值量级 |
| 验收量 | 超压−时间曲线 / 破坏边界 / 云图 / 总量 |

**测点距离的起算基准必须写清楚**。若测点距离是从部件**侧壁**量的，而后续可视化里的圆以**轴线**为心，两者相差一个半径，必须显式加上，否则时间对齐会错。

## 1. 启动

| 项 | 设置 | 为什么 |
|---|---|---|
| Dimension | 3D | — |
| Options | Double Precision | 高压比（如 36 倍）必须双精度 |
| Processing | Parallel，4 进程 | `-t8` 会 MPI 共享内存失败 |
| Solver GPGPUs per Machine | **0** | 非 0 会报 license / GPGPU / 浮点异常 |
| 模式 | Solver（不是 Meshing） | 网格已生成时直接进 Solver |

## 2. 读网格与检查

- File → Read → Mesh，确认控制台输出的 cell / face zone 数量与预期一致。
- `/mesh/check`：确认**最小体积为正**、域范围与预期一致。
- 列出全部 zone，记录 ID / 类型 / 单元数 / 面积。**后续一律用 ID 操作。**

## 3. 几何缺陷核查（最容易漏，且不做则结果全错）

判断方法：如果高压源区域与外界**没有任何 fluid-fluid 相连的通道**，它就是被 wall 封死的。

- 典型成因：上游几何脚本用"中面薄壳"建模，在纯流体网格设置下薄壳被忽略，于是气区只剩一圈 wall 包着。
- 处理：把这层 wall 改成 `interior`。
- **改完立即 `/file/write-case` 保存**（该操作修改了网格）。

## 4. General

| 项 | 设置 | 为什么 |
|---|---|---|
| Solver Type | Density-Based | 可压缩激波必须密度基，压力基无法正确捕捉激波/膨胀波 |
| Time | Transient | 冲击波本质是随时间演化的波动过程 |
| Transient Formulation | Second Order Implicit | 二阶时间精度，波传播更准 |
| Gravity | 按时间尺度判定 | 见 §4.1 |
| Units | 压力 Pa、温度 K | 防止误用 atm / ℃ |

### 4.1 重力判定

- **毫秒级（0.1 s 内）冲击波**：不启用。重力 0.1 s 内速度增量约 1 m/s，不足激波速度的 0.3%，被完全淹没；主导机制是压力梯度。
- **秒级热气浮升 / 毒云漂移**：启用，Y = −9.81 m/s²。属另一个工况。

## 5. Models

| 项 | 设置 | 为什么 |
|---|---|---|
| Energy | 开启 | ideal-gas 要求开启；冲击波是热力学过程 |
| Viscous | SST k-omega | 近壁/远场兼顾，冲击波通用；远场超压对其不敏感 |
| Radiation | 不开启 | 常温空气近红外辐射弱，0.1 s 尺度对超压无影响 |

## 6. Materials

- Density = **ideal-gas**（`rho = p/(R*T)` 自动更新，这是高压气膨胀产生冲击波的物理核心）。
- 其余（Cp、分子量）用默认。

## 7. Cell Zone Conditions

- Operating Pressure = 101325 Pa。**这是后面所有 gauge 的基准**，patch 值必须与之口径一致。
- 各 cell zone 保持 fluid + 对应材料。

## 8. Boundary Conditions

| 边界 | 设置 | 为什么 |
|---|---|---|
| 计算域外边界 | `pressure-far-field`（表压 0、Mach 0、T 298 K） | Riemann 无反射边界；**保持 wall 会让激波反射回来污染远场测点** |
| 内部面 | interior，默认 | — |

## 9. Solution Methods（密度基专属）

| 项 | 设置 |
|---|---|
| Flux Type | Roe-FDS（默认） |
| Gradient | Least Squares Cell Based |
| Flow | Second Order Upwind |
| Turbulence | Second Order Upwind |
| Transient Formulation | Second Order Implicit |

## 10. Solution Controls

- Courant Number：起步 0.5 求稳，跑稳后再升到 1。
- 欠松弛保持默认；发散时先降 dt 与 Courant，而不是大改松弛因子。

## 11. Monitors

- Residuals：默认判据即可。瞬态问题**不必苛求每步残差收敛**，重点是测点压力曲线形态正确。
- 测点压力：用 Report Definitions（Surface Report / Vertex Average，field = Static Pressure），勾选写文件。**不要用 point-surface + 求解 journal 的组合**（会段错误）。

## 12. Initialization 与 Patch

1. Standard Initialization，初值：表压 0、温度 298 K、速度 0、湍流参数给合理非零值。
2. **不要**用 pressure-far-field 边界作为初始化参数来源——若该边界湍流参数不完整，点 Initialize 会直接崩溃。
3. Patch 高压区：`pressure` = 高压 **表压**，`temperature` = 高温值。
   - 单位陷阱：界面 `pressure` 字段通常是 gauge；若标着 Absolute 才填绝对值。
4. patch 后若出现 `absolute pressure limited to 1.0 in N cells`，检查环境区初值是否被误覆盖。

## 13. Run Calculation

| 项 | 建议 |
|---|---|
| Time Step Size | 先按 CFL 估算；本项目 0.0005 s 对应 CFL≈4.5，发散则降到 0.0001（CFL≈0.9） |
| Number of Time Steps | 由物理总时长 / dt 决定，需覆盖最远测点主峰 |
| Max Iterations / Time Step | 20 |
| Autosave | 每 5 步一存；**预估磁盘占用**：单帧可达数百 MB |

## 14. 退出前

1. `/file/write-case <name>_setup.cas.h5` + `ok`（**必做**，保证可续算）。
2. 记录本次求解的关键参数（dt、步数、边界类型、patch 值），便于结果口径说明。

---

## 15. 分支 B · VOF 多相流（液体泄漏 / 熔体泄漏 / 熔体喷溅）

| 项 | 设置 | 为什么 |
|---|---|---|
| Solver Type | **Pressure-Based** | VOF 走压力基，**不要**切 density-based |
| Time | Transient | |
| Multiphase | **VOF（Implicit 隐式）** | 显式对高密度比不稳 |
| 主相 / 次相 | air / 重相（acid、slag、熔体…） | 酸液实测：acid 作 phase-2，ρ=1200、μ=0.002 |
| 表面张力 | **CSF**，σ 按物性；`Bo = ρgL²/σ ≫ 1` 时**建议关闭** | 高密度比下 CSF 会产生寄生流速导致发散 |
| Gravity | Y = −9.81 m/s²（**按实际轴向**）；**Implicit Body Force 必须开启** | 密度比 2857:1 这类算例不开会界面压力震荡 |
| Pressure-Velocity Coupling | **PISO** | 瞬态多相首选 |
| Gradient | **Green-Gauss Node-Based** | |
| Pressure | **PRESTO!** 或 Body Force Weighted | |
| **Volume Fraction** | **Compressive 或 Modified HRIC** | ⚠️ 二次迎风会糊界面 |
| Momentum | Second Order Upwind | |
| 时间步 | 1e-3 ~ 2e-3 s（CFL + 表面张力双约束）；有限液块起步可 1e-4 斜坡 | 见 §15 前置检查 |
| 初始化 / patch | patch **次相体积分数**（液块 = 1，其余 = 0）；有限液块另 patch 混合相速度 | "喷出一部分"用有限液块 patch，不是连续速度入口 |
| 边界 | 顶部/远墙设 `pressure-outlet` 泄压；底面 `wall` 无滑移 | 液块撞不到的地方只让空气被排挤时泄出 |

**几何/网格前置检查**：

- **液块/界面宽度 ≥ 7~10 个网格**，否则界面糊死、溅不开。实测对照：Ø150 mm 液块用 0.012 m 网格（≈9.8 格 / 2402 单元）成功；用 0.020 m（≈7.5 格）**液块被打散**；Ø122 mm 液块配 0.070 m 网格（≈2.4 格）α 由 1.0 崩到 0.014。
- **换物理模型 = 换网格要求**，原网格通常不可复用（DPM 的 0.15 m 网格算不了有限液块）。

**验证判据（有限液块喷溅，实测参考）**：

| 判据 | 标准 | 来源 |
|---|---|---|
| 弹道落点 | 手算 ±10%（实测 2.93 m vs 手算 2.84 m，误差 3%） | 弹道手算 `v_h`、`t` |
| 撞击溅开 | 落地后铺展成片（X/Z 均有宽度） | 核心诉求 |
| 溅开能量判据 | K = Oh·Re^1.25 ≈ 130 ≫ 57.7 → 必溅 | Fluent Theory Guide §12.9.3 |
| 质量守恒 | 域内次相体积随时间守恒（无入口、无出口泄漏） | VOF 本质约束 |

## 16. 分支 C · 组分输运（有毒/可燃气体、烟气扩散）

| 项 | 设置 | 为什么 |
|---|---|---|
| Solver Type | **Pressure-Based** | 低速扩散问题 |
| Time | Transient | |
| Models → Species | **Species Transport**，volumetric reactions = no | 纯扩散，无反应 |
| Mixture Material | mixture-template；**差减组分用 `air`**（写成 `{so2, air}`） | ⚠️ 用 `{so2,o2,n2}` 且 last_species=n2 ⇒ 整个域被初始化成纯氮气 |
| Viscous | **Realizable k-ε** 或 SST k-ω | 远场浓度对湍流模型不敏感 |
| Gravity | **按需**：重气扩散（SO₂、As₂O₃）**必须开启**，Y = −9.81 | 重气下沉是主导机制 |
| Energy | 常温扩散可不开；烟气温度显著高于环境时要开 | 与爆炸分支不同 |
| 标量变量名 | `molef-so2` | 导出与云图都用这个名字，大小写敏感 |
| 时间步 | 5e-3 s（实测：2262 步 = 11.31 s） | 十秒级过程 |
| 边界 | 泄漏口：质量流入口 或 有限区域 patch；房间壁面 `wall` | 持续源用入口，瞬时释放用 patch |

**持续源 vs 瞬时源的差异**：炉顶/出烟口多为**持续源**（用**质量流入口或速度入口**，不是 patch；速度入口能保留射流动量）；As₂O₃ 为**颗粒态**，需要 DPM 或分相处理，**不要沿用单组分气相假设**。

**交付前置检查**：

- 呼吸高度切片带（实测口径：`y ∈ [1.5−0.1, 1.5+0.1] m`）**必须写进口径**；
- 阈值口径写清（实测口径：红 ≥1e-4 = 100 ppm IDLH；黄 ≥2e-5 = 20 ppm）；
- 场数据导出用 `/file/export/ascii` 且 `Location/Cell-Centered?` 答 `yes`；
- 栅格化后做**逐格自校验**（见 `field-export-and-rasterize.md` §7）。
