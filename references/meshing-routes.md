# 网格路线选择

> 各类算例的几何差异大（长细高压釜、大厂房、小泄漏孔、弹道管），**没有任何一条网格路线通吃**。
> 本文件给出三条已验证路线的适用边界与踩过的硬限制。

---

## 0. 决策树

```
几何能否复用已有网格？
├─ 能（同设备/同厂房，只改泄漏口位置）
│    → 路线 A：复用 + 局部替换。最快，优先。
└─ 不能
     ├─ 几何规则、可用脚本参数化（板/箱/管/球/圆柱）
     │    → 路线 C：gmsh 脚本化（可批处理、可复现、批量算例首选）
     └─ 几何来自 CAD（scdoc/step，多 body 装配）
          → 路线 B：Fluent Meshing Watertight Geometry（GUI 工作流）
```

---

## 1. 路线 A：复用既有网格

**适用**：L4 / G3 同为高压釜 + 10×10 厂房；B2 与 G3 共享高压釜模型（一次建模两次使用）。

**做法**：

1. 复制源目录的 `*.msh.h5` 与 `_setup.cas.h5`；
2. 只在 Fluent 里改**边界条件**（泄漏口位置由 zone 指定）、**材料/模型**、**patch 值**；
3. 若需改zone类型（如 wall → interior），改完**立即 `write-case`**。

**优点**：省掉全部网格时间。**凡是能归到 L4/G3 设备族的算例，一律先试这条。**

**已知收益**：G3 的几何/厂房布局/网格全部复用 L4，省去建模时间；这是 G3 被选为"最简场景"的核心理由之一。

---

## 2. 路线 B：Fluent Meshing Watertight Geometry（GUI 工作流）

**适用**：CAD 装配体（多 body）→ 全流体域体网格。

**工作流（逐面板）**：

1. **Import Geometry**：导入 CAD（scdoc/step）。TGrid CADReader 会报识别的 Body/Face 数（例：5 Body / 18 Face）。
2. **Add Local Sizing**（可选）：弹道管、泄漏孔等小特征处局部加密。
3. **Generate the Surface Mesh**：先出面网格（例：10782 nodes / 18626 faces / 10 zones）。
4. **Share Topology**：把多个独立 parts 合成共享拓扑。**漏了这步，各部件之间不连通，体网格生成会失败或产生孤立体。**
5. **Describe Geometry**：识别边界类型（fluid / solid / wall），确定是否"only fluid"。
6. **Create Regions**（视需要）。
7. **Generate the Volume Mesh**：出体网格。

### 2.1 ⚠️ 硬限制：Workbench batch 无法动态构建 Fluent Meshing task chain

实测：`sys_ff.GetContainer("Mesh")` 返回的是 `Ansys.Fluent.Addin:TGridContainer`（很薄的 `DataContainerReference`），**只有** `GetAllParameters / GetFiles / Name / ToString`。

**没有任何 task chain 操作 API**：

- ❌ `AddTask` / `InsertTask` / `RemoveTask`
- ❌ `TaskObjects` / `GetTasks` / `GetWorkflow`
- ❌ `GetChildren` / `Items`

**结论**：**task chain 必须在 GUI 里预先建好**（右键 Add → Share Topology / Describe Geometry / Volume Mesh），保存工程，再 batch 跑。任何"在 batch 里动态构造 Fluent Meshing workflow"的尝试都是徒劳——这是 Workbench 架构层面的限制，不是脚本能绕过的。

### 2.2 ⚠️ `-meshing` 启动开关在批处理下无效

实测：`fluent.exe -driver null -meshing` 启动后**首提示符仍是 Solver Mode**，Meshing Mode 未进入。
`/file/import-geometry` **不存在**（TUI 必须单行完整路径，且无此命令）。

**因此 Meshing Mode 不适合脚本化**，只适合 GUI 手操。

### 2.3 中间产物

`*_files/dp0/<系统>/Fluent/` 下有 `Solution.trn`（完整执行日志，排查网格失败的第一现场）与 `FM_<机器名>/`（.tgf/.sf 等 Meshing 中间文件）。

---

## 3. 路线 C：gmsh 脚本化（VOF / 需要精细局部加密时首选）

> ⚠️ **2026-10-23 实测警告：这条路线在本机 Fluent 2024R2 上走不通** ——
> gmsh 写出的 `.msh`（2.2 ASCII，四边形与三角形都试过）在 `/file/read-case` 时
> **在 `Building... mesh` 处 SIGSEGV**，CGNS 同样崩，六组对照实验排除了格式/核数/路径/PATH 四个变量。
> 判据与处置见 `troubleshooting.md` 的 **K 类**。
> **可行的替代**：gmsh 只生成几何（`.step`），网格交给 Fluent Meshing watertight，
> 输出原生 `.msh.h5` —— 见 `../tests/smoke/make_mesh.py`（已验证跑通）。
> 若你的机器上 gmsh 网格能正常导入，本路线仍按下面写法使用。

**适用**：几何规则、可参数化；尤其 VOF 需要**精确控制界面区网格尺寸**。

**为什么 S2 用 gmsh 而不是 Watertight**：Fluent Meshing Watertight 的 GUI 工作流**极难批处理自动化**；gmsh 全参数化可控、可复现、可脚本化。S2 的几何（12×6×8 m 车间 + Ø100 mm 孔 + 弹道管）恰好规则。

**S2 实测网格规格**：

| 区域 | 目标尺寸 | 理由 |
|---|---|---|
| 弹道管（放出口前方 Z∈0~3 m，Ø~0.3 m 柱体） | **0.02 m** | 液块 Ø150 mm ≈ 7~8 个网格宽，界面可分辨 |
| 落地溅开区（Z∈2.3~3.2 m 地面 ±0.15 m） | **0.02 m** | 撞击铺展、二次溅滴的生成区 |
| 车间其余空间 | **0.2~0.3 m** | 空气背景，粗网格即可 |
| 放出口面 | 0.02 m（继承） | 面单元够细 |

合计约 **5 万单元**，VOF 瞬态几分钟~十几分钟可算完。

**流程**：gmsh 脚本 → 导出 CGNS / UNV → `fluent.exe` 导入（`S2_vof.cgns` / `S2_vof.unv` 都已验证可导入）。

### 3.0 ⚠️ CGNS 导入的三个"看起来像崩溃、其实是别的问题"（PL 实测 2026-09-17）

这三条踩了很久才分清，**现象几乎一样**（都是 `Importing "..."` 之后紧接
`Fatal failure in fluent (disconnected / ended abnormally) - exiting...`），
但根因完全不同。**遇到这个报错，先按顺序排除下面三条，不要一上来怀疑网格。**

| # | 根因 | 独有特征 | 处置 |
|---|---|---|---|
| 1 | **环境 PATH 缺 ANSYS/MPI 目录** | 日志里**没有** `Opening library ... devtools4.4.6.dll... done.` 这一行 | 启动 fluent.exe 前把 PATH 补全，见下 |
| 2 | **物理内存不足**（实测门槛 ≈ 2~3 GB 空闲） | 同样缺 `Opening library` 行；伴随启动时出现 `... is already loaded (34.4). Process affinity not being set.`（负载异常高） | 腾内存后再跑；40 万格导入峰值约 2~3 GB |
| 3 | **`/exit` 触发的关停崩溃**（假阳性） | 出现 `Opening library` ✅、`Read N nodes` ✅、`1 cell zone, N face zones` ✅，**然后**在 `/exit` + `OK to discard? yes` 之后才报 Fatal | **journal 里不要写 `/exit`**，让文件自然到 EOF（打印 `Halting due to end of file on input`）即干净退出 |

**判据（重要）**：CGNS 导入是否成功，**看日志里有没有
`1 cell zone, N face zones`，不要看进程 exit code**。第 3 种情形下
exit code 是 1，但网格已经完全导入、`write-case` 也已落盘。

**正确的 PATH**（缺一个都可能死在第 1 条）：

```bash
export PATH="/c/Windows/System32:/c/Windows:/usr/bin:/bin"
PATH="$PATH:<ANSYS 安装目录>/fluent/ntbin/win64"
PATH="$PATH:<ANSYS 安装目录>/fluent/fluent24.2.0/vki/win64"
PATH="$PATH:<ANSYS 安装目录>/fluent/fluent24.2.0/win64"
PATH="$PATH:/c/Program Files/Microsoft MPI/Bin"      # MS-MPI（默认安装位置）
PATH="$PATH:<Intel MPI 安装目录>/intel64/bin"         # Intel MPI（本机用哪个就填哪个）
```

> 盘符、版本号、MPI 厂商按本机实际替换。

> **为什么只在导入时暴露**：求解器不需要这些 DLL，所以 PATH 不全时
> **求解全部正常**，只有 CGNS 导入会崩 —— 极易误判成"网格/文件坏了"。
> 建议把上面这段存成算例目录下的 `fluent_env.sh`，每次开新 shell 先 `source` 它。

**另一条同时成立的铁律**：CGNS **导入必须单进程**（`-t1`）；
导入 + 并行会触发 `Auto_Partition` 段错误（§见 SKILL.md §1.3）。
即：**导入串行、求解并行**。

### 3.0b ⚠️ 重新导入网格后 zone ID 整体重排 —— "同名不同 ID"的静默陷阱（PL V2 实测）

**现象**：同一套几何、同一套 gmsh 脚本，只把计算域某一侧加大后重新导出 CGNS 再导入，
Fluent 给每个 face zone 分配的 **id 完全变了**。若下游脚本（`zone-type` 转换、边界条件
挂载、monitor 面）里写死了 id，就会**静默地把设置贴到错误的面上** —— 不报错、不崩溃，
一直要到结果离谱才被发现。

V1 → V2 实测对照（同一几何，仅 +X 侧 5 m → 11 m）：

| 语义 | V1 id | V2 id | 危险点 |
|---|---|---|---|
| `outlet_xmax` | 7 | 3 | — |
| `outlet_zmin` | 9 | 5 | — |
| `outlet_zmax` | 5 | 10 | — |
| `outlet_xmin` | 10 | 16 | — |
| `floor` | — | 7 | **V1 的 7 是 outlet_xmax** |
| `furnace_wall_side` | — | 9 | **V1 的 9 是 outlet_zmin** |
| `breach_l1` | 13 | 8 | **V1 的 13 在 V2 是 breach_l2** |

即：沿用 V1 表会把 **地板 `floor`(id 7)** 和 **炉壁 `furnace_wall_side`(id 9)**
误转成 `pressure-outlet` —— 铺展/成膜分析直接作废；还会把破口类型贴到别的破口上
（L1 变 L2，质量流量差一倍）。

**根因**：Fluent 的 zone id 在**导入时按顺序分配**，既不是 gmsh tag、也不是稳定标识。
任何"局部改几何 → 重导出 → 重导入"都会重排。

**防御（三条，缺一不可）**：

1. **落地一张实测映射表**。导入成功后立刻探测并存 JSON：

   ```python
   solver.tui.define.boundary_conditions.list_zones()   # 打印 id/name
   ```

   存成 `zone_id_map.json`：`[{"id": 8, "gmsh_tag": 17, "semantic": "breach_L1"}, ...]`。
   **gmsh tag 是稳定的**，可作为跨版本锚点。

2. **下游脚本一律从 JSON 派生 id，禁止写死**：

   ```python
   sem2id = {r["semantic"]: r["id"] for r in json.load(open(MAP)) if r["semantic"]}
   OUTLET_IDS = {sem2id[s]: s for s in OUTLET_SEMS}    # 数字 → 语义
   breach_zid = sem2id["breach_l1"]                    # 语义 → 数字
   ```

   JSON 缺失时**必须打印醒目告警**再退回旧表，不要静默退化。

3. **能不用 id 就不用**：`S.boundary_conditions.wall["floor"]`、
   `mass_flow_inlet["breach_l1"]` 这类按名字取对象的写法与 id 无关，最安全。
   只有 `zone-type` 这类 TUI 命令不支持名字，才必须用 id。

> **自查口径**：改完几何重新导入后，第一步就跑一遍"数字 id → 语义名"对照打印，
> 与上一版逐行比。**只要有一行不一样，就必须全链路重新派生。**

### 3.1 网格尺寸的下限判据

**界面/液块宽度至少要有 7~8 个网格**，否则界面糊死、物理行为（如溅开）出不来。

反例：S2 最初的 DPM 网格弹道区只有 **0.15 m**（为 DPM 粒子轨迹打的，对粒子够用），
但 VOF 要解析 Ø150 mm 的液块 → 0.15 m 格子 = **液块宽 1 格** → 界面糊死、溅不开。
**换物理模型 = 换网格要求，原网格通常不可复用。**

### 3.2 高密度比 VOF 的额外要求

密度比 > 1000（S2 实测 3500/1.225 ≈ **2857:1**）时：

- 必须开 **Implicit Body Force**（隐式体积力），否则界面压力震荡；
- 界面格式用 **Compressive / Modified HRIC**（二次迎风会糊）；
- 时间步受 CFL + 表面张力稳定性双重约束（S2 用 1e-3 s）。

若网格太粗导致稳定性过不去：先用**降低密度比**（如 ρ=1000）把流程调通，再上真实物性；或继续加密界面区。

---

## 4. 选型速查

| 情形 | 路线 | 关键动作 |
|---|---|---|
| 同设备族复用（L1–L3 对 L4；B1/B3/B4 对 B2；G1/G2 对 G3） | A | 复制 msh + setup，只改 BC/模型/patch |
| CAD 装配体、多 body | B | GUI 建 task chain（含 **Share Topology**），再 batch |
| 规则几何 / VOF 精细界面 / 批量算例 | C | gmsh 参数化脚本 → CGNS/UNV |
| Meshing Mode 想脚本化 | ❌ | 无解，改 GUI 或 gmsh |

---

## 5. 检查清单

| # | 检查 | 期望 |
|---|---|---|
| 1 | 已 `/mesh/check` | 最小体积为正，域范围与预期一致 |
| 2 | 已列出全部 zone 的 ID/类型/单元数/面数 | 后续一律用 ID 操作 |
| 3 | （路线 B）Share Topology 已执行 | 多 part 已合拓扑 |
| 4 | （路线 B）Describe Geometry 已识别边界 | 无未知类型 |
| 5 | （路线 C）界面区网格 ≥ 7 格宽 | 见 §3.1 |
| 6 | 高压气区/液块区**与外界有 fluid-fluid 连通通道** | 若被自身 wall 封死 → 改 interior |
| 7 | 改过 zone 类型后已 `write-case` | 否则无法续算 |
