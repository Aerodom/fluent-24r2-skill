---
id: S2
name: 放出口喷溅导致的喷溅事故
class: vof-free-surface
status: verified          # verified | partial | untested
last_run: 2026-09
keywords: [VOF, 有限液块, register patch, 半域对称, 弹道, 溅开, PyFluent, 高密度比, node_value]
reuse_of: ""
---

# S2 · 放出口喷溅导致的喷溅事故

> **一句话画像**：放出口喷出**一团有限熔渣**（不是连续喷流）→ 抛物线飞行 → 落地溅开铺展（亚秒~秒级）。
> **状态**：★ 实测跑通｜**最后实测**：2026-09（Fluent 2024R2 / **PyFluent 0.42.1**）｜**本案例是"有限液块"类问题的样板**。

## 1 选型卡

| 项 | 取值 |
|---|---|
| 物理类型 | 高密度比多相 + 有限液块飞行（B 类） |
| 求解器 | 压力基 |
| 时间 | 瞬态 |
| 多相 | VOF **隐式**（主相 air / 次相 slag） |
| 湍流 | 层流 |
| 能量 | 本案例未强耦合（如需温差熔渣再加） |
| 重力 | **沿 Y = −9.81 m/s²** |
| 时间步 | **1e-4 s（前 100 步斜坡）→ 5e-4 s** |
| 网格量级 | **632,718 单元** |
| 单步耗时 | 6~7 s/步（`processor_count=6`，峰值内存 **5.8 GB**） |
| 验收量 | 弹道落点、地面覆盖面积/铺展尺寸、域内次相体积守恒 |

## 2 几何与计算域

| 项 | 值 |
|---|---|
| 计算域（**半域**） | **X ∈ [6, 6.5]（X=6 为 symmetry）**，Y ∈ [0, 2]，Z ∈ [0, 3.5] m |
| 竖直轴 | **Y** |
| 放出口 | Ø100 mm，位于 Z=0 墙面，圆心 (X=6, Y=0.8) |
| 喷射 | 5 m/s、**15° 仰角** → 速度分量 `(0, 1.29, 4.83)` m/s |
| 液块 | Ø150 mm 球，球心 **(6, 0.8, 0.15)**，次相体积分数 = 1 |
| 理论弹道 | 落地 `t ≈ 0.556 s`、`Z ≈ 2.84 m`：`Z = 0.15 + 4.83t`，`Y = 0.8 + 1.29t − 4.905t²` |

## 3 网格

| 项 | 值 |
|---|---|
| 单元数 | **632,718** |
| 加密 | **弹道走廊 Box 场 0.012 m** + 落地区 0.01 m |
| 液块占格 | **≈ 9.8 格 / 2402 单元** |
| 关键判据 | 液块直径 / 当地网格 ≥ **7~10 格**（**0.020 m 网格只有 7.5 格 ⇒ 液块被打散，失败**；0.012 m 才成立） |
| ⚠️ | **不要用 Distance 场**做加密（实测球心处失效，液块只剩 153 单元）、**不要用原 DPM 网格**（0.15 m，液块 1 格宽） |

## 4 材料与相

| 相 | 密度 | 粘度 | 表面张力 |
|---|---|---|---|
| 主相 air | 1.225 | 1.7894e-5 | — |
| 次相 slag | **3500**（设计值） | 0.5 | σ = 0.45 N/m（工程假设） |

- 密度比 **2857 : 1** ⇒ 极高，**必须开隐式体积力**。
- 表面张力按 `Bo = ρgL²/σ ≈ 千量级 ≫ 1` **关闭**（物理可忽略，且 CSF 会寄生流速）。
- 若出现 Courant 病态（0.6 → 几百），**降重相密度 3500 → 1200** 是有效解法（弹道/溅开由 Fr 主导），交付文档标注为数值妥协。

## 5 模型与求解设置

| 项 | 值 |
|---|---|
| VOF 形式 | **implicit**（**先于**时间格式设置；启用 VOF 会重置时间格式） |
| 压力-速度耦合 | **PISO** |
| 梯度 | **Green-Gauss Node-Based** |
| 压力 | **PRESTO!** |
| 体积分数 | **Compressive** |
| 动量 | 二阶迎风 |
| 隐式体积力 | **开** |
| 表面张力 | 关 |
| 禁用 | **`geo-reconstruct`**（隐式 VOF 下实测崩进程）、二次迎风（糊界面） |

**相材料赋值是交互式命令，最容易静默失败**：

```python
# ❌ 不报错但完全不生效 → phase-2 仍是 air，"熔渣块"其实是空气泡（不下落、不溅开）
# ✅ 正确：斜杠路径 + yes 交互应答
tui.define.phases.set_domain_properties.phase_domains["phase-2"].material("yes", "slag")
# 验证：用场数据反查 phase-2-density 是否 ≡ 3500（不是 1.225）
```

## 6 边界条件

| zone | 类型 | 值 |
|---|---|---|
| X = 6 | **symmetry** | — |
| Z = 0 墙面 | wall（放出口所在面） | — |
| 顶部 / 远墙 | pressure-outlet | 表压 0 |
| 地面 | wall 无滑移 | — |

## 7 初始化与 patch

**三条顺序铁律**（违反任一条都会 `0 cells marked`）：

1. **register 必须"预置在 setup 阶段保存的 case 里"**，solve 阶段**复用 + 重设 `.type`**。PyFluent 下**新建** register 不触发实际标记。
2. **顺序：`reg.type` → `standard_initialize()` → `calculate_patch()`**。`standard_initialize` 会清空 register 标记，所以 `reg.type` 必须在它之前。
3. **patch 的 `cell_zones` 必须传空列表 `[]`**，靠 `registers` 定位。

```python
# patch 相分数 / 速度
solver.solution.calculate_patch(registers=[blob], domain="phase-2", variable="mp", value=1.0)
solver.solution.calculate_patch(registers=[blob], domain="mixture", variable="z-velocity", value=4.83)
```

- 多个 register 必须**一次调用合传**（逐个调用不累积，实测 12 团只生效 3 团）。S2 只 1 团，但同法适用；多团时还要加"牺牲位"，见 [S1](S1-foam-slag-splashing.md) §11。
- `reference-frame is not set as it is inactive` 是**无害提示**，patch 仍生效。
- **t=0 核验（必做）**：存一帧 case-data，离线算 `ΣαV`，与 `ΣV(标记单元)` 对齐（**不用解析式 4/3πR³**）。

## 8 推进策略

- `dt = 1e-4` 前 100 步（打通初始射流、避免开局 Courant 爆）→ 切 `5e-4` 跑到 ~1.5 s。
- 并行：`processor_count=6`（632k/双精度/16 GB 稳定）；**878k 用 6 核会 OOM 静默崩溃**（无弹窗）。
- `auto_save.root_name` 只写**纯文件名**（不带目录）。

## 9 监控与验收判据

| 判据 | 标准 | 来源 |
|---|---|---|
| 弹道落点 | **2.5~3.0 m**（手算 2.84 m；**实测 2.93 m，误差 3%**） | 弹道手算 vs CFD |
| 落地溅开 | 铺展成片（X/Z 双向均有宽度）；实测覆盖 **0.137 m²**、摊开 **0.81 m × 0.63 m** | 用户核心诉求 |
| 溅开能量判据 | `K = Oh·Re^1.25 ≈ 130 ≫ 57.7` ⇒ **必溅** | Fluent Theory Guide §12.9.3 |
| 质量守恒 | 域内次相体积随时间守恒（无进出口泄漏） | VOF 本质约束 |

## 10 后处理与交付

- **取场数据必须 `node_value=False`**：`ScalarFieldDataRequest` 默认 True 返回**逐节点值**（与面心错位），实测 sym 面报 9891 个值而面心是 19581 个。
- 标量请求**只返回值、不给坐标**（0.42.1 实测），要坐标另行取 `FacesCentroid`。
- 场名不要硬编码：先列出 case 的可用场再挑。
- 交付：地面覆盖区（`phase-2-vof > 0.5`）→ 多边形/同心层（形态 D）；面积用**阈值足迹** `A(α>ε)`，不要用 `∮αdA`（会退化成 `V/Δ`）。

## 11 已知坑（本案例专属）

| 现象 | 根因 | 处理 |
|---|---|---|
| **液块悬空不下落、速度从 5 衰减到 0.6 m/s、地面覆盖为 0** | 相材料赋值静默失败 ⇒ phase-2 仍是 air（密度比 1:1，不受重力） | `material("yes","slag")` + **反查 `phase-2-density`** |
| patch 报 `0 cells marked` | 会话内新建 register / `reg.type` 在 `standard_initialize` 之后 / `cell_zones` 没传 `[]` | 三条顺序铁律 |
| 6 核访问 `cell_registers` 报 `wta(1st) to string->symbol` | "VOF 查询 + 粘性模型设置"组合在并行下破坏 register 状态 | **把 register 操作移到这两者之前** |
| 场数据"值对但位置怪" | `node_value` 默认 True（逐节点值） | `node_value=False` |
| 液块散成雾、落点消失 | 网格 0.020 m（液块仅 7.5 格） | 加密到 0.012 m（9.8 格）；或用"等效雾团"并标注为工程假设 |
| 打印 PyFluent 包装对象报 `TypeError: must be real number, not value_11` | 属性返回 `value_N` 包装对象 | 取 `.value`；**这不是设置失败**（曾据此误报 4 条 FAIL） |
| 边界压力读不到 `bc[z].pressure` | 路径是 `bc[z].phase["mixture"].momentum.gauge_pressure` | 按真实路径读；出厂默认即目标值时可只读不写 |

## 12 复现入口

```python
pyfluent.launch_fluent(precision="double", processor_count=6, mode="solver",
                       ui_mode="no_gui_or_graphics", cwd=case_dir, start_watchdog=False)
# 完整脚本与 API 路径见 references/pyfluent-vof-sputtering.md
```

## 13 复用与差异

- **可以直接照抄的**：VOF 配方、register+patch 三条铁律、半域对称、弹道校验、`node_value=False`、内存预算。
- **必须改的**：液块尺寸/初速/仰角、放出口位置、网格尺度（**按液块直径反算**）、次相物性。
- **不能照抄的**：0.02 m 网格（会失败）；`processor_count` 不要直接给 878k 单元用。
