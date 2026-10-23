# Fluent 24.2 故障速查

## A. 启动与 license

### A1 一启动就报错，堆栈含 `inhomogeneous process distribution` / `GPGPU computing disabled` / `License is not available` / `floating point exception`

- **根因**：Fluent Launcher 里「Solver GPGPUs per Machine（每台机器 GPU 数）」被填了非 0 值，而本机 license 不含 GPU 加速。GPU 进程分布不均 → license 校验失败 → 浮点异常。
- **处理**：该值填 **0**；Processing Options 选 Parallel + Number of Processes = 4。

### A2 并行启动报 `MPIDU_Init_shm_alloc: unable to allocate shared memory`

- **根因**：Windows MPI 共享内存段限制，与物理内存余量无关。
- **处理**：进程数降到 `-t4`。`-t8` 必失败；`-t6` 未验证。

## B. 物理不成立（能跑但结果错）

### B1 气体完全不膨胀、压力场无变化

- **根因**：薄壳几何在"only fluid"网格设置下被忽略，导致高压气区 `gas_high` 被它自己的外表面 wall 完全封闭，泄放通道不存在。
- **处理**：把该 wall 改成 interior（`/define/boundary-conditions/zone-type <id> interior`），可自由泄放。
- **附带**：改完立即 write-case（见 C1）。

### B2 超压曲线出现多余假峰

- **根因**：计算域外边界保持 `wall`，激波到达后反射回来，在远场测点叠加反射峰。典型特征是反射峰出现在入射峰之后较晚的时刻，且幅值可能高于入射峰。
- **处理**：
  1. 正解：外边界改 `pressure-far-field`（表压 0、Mach 0、温度 298 K），物理上模拟无限大环境。**注意改了边界需要重算**。
  2. 临时：只取入射首峰（限定时间窗，如全时长的前 60%）作为衰减样本，并在报告中明确剔除反射。

### B3 峰值整体偏一个大气压

- **根因**：patch / 监控输出的 gauge 与 absolute 口径混用。
- **处理**：统一口径。监控输出一般是绝对压力，**超压 = 绝对值 − 操作压力（101325 Pa）**。

### B4 要不要启用重力

- 判断依据是**时间尺度**：
  - 毫秒级冲击波传播（如 0.1 s 内）：重力在 0.1 s 内只能产生约 `g*t ≈ 1 m/s` 的速度增量，不到激波速度（340–450 m/s）的 0.3%，可忽略；且主导机制是压力梯度（惯性），不是浮力。**不启用重力。**
  - 秒级热气浮升 / 毒气云漂移：必须启用重力，Y 方向 −9.81 m/s²。这是**另一个工况**，不要和冲击波阶段混在一起算。

### B5 VOF 界面震荡 / 糊化（高密度比）

- **现象**：液面抖动不停、界面糊成一片、落地不溅开。
- **根因**（按概率）：
  1. 未开 **Implicit Body Force**（高密度比必须开，否则界面压力震荡）；
  2. 体积分数离散用了**二次迎风**（会糊）——应为 **Compressive 或 Modified HRIC**；
  3. **网格太粗**：界面/液块宽度不足 7~8 个网格；
  4. 时间步过大（CFL + 表面张力稳定性双约束）。
- **处理**：按 1→2→3→4 顺序修。若仍不稳，先用**降低密度比**（如 ρ=1000）把流程调通，再上真实物性。

### B6 换了物理模型但沿用旧网格 → 结果物理上出不来

- **典型**：S2 从 DPM（粒子）改为 VOF（连续自由液面）后，仍用原 DPM 网格。原网格弹道区只有 0.15 m（对粒子轨迹够用），但 VOF 要解析 Ø150 mm 液块 → **液块宽仅 1 个网格** → 界面糊死、溅不开。
- **根因**：**换物理模型 = 换网格要求。**
- **处理**：重新按新模型的特征尺度划网格（界面区 ≥ 7~8 格宽）。VOF 弹道管用 0.02 m。

## C. 求解过程中的卡死与发散

### C1 续算报 `The mesh has been modified. Previously saved data files are incompatible`

- **根因**：`zone-type A interior` 这类操作会**修改网格**（缝合面、合并 zone），而 autosave 只保存场（data），不含修改后的网格。续算时读原始网格 → 网格与 data 不匹配。
- **处理**：改完 zone 与 setup 后**立即** `/file/write-case xxx_setup.cas.h5`。之后中断就从这个 case + 对应 autosave data 续算。

### C2 续算报 `Update_Time_Level: invalid data`

- **根因**：二阶瞬态需要前一时刻（N−1）的时间层，直接从单帧 data 续算缺这一层。
- **处理**：从 write-case 保存的 case 配合**连续两帧** data 载入，或改为一阶瞬态重启。

### C3 第 1 步 CPU 满负荷，长时间（数小时）不出 Flow time

按可能性排序排查：

1. **空闲内存不足**。本项目两次遇到此现象，一次真实根因是当时仅剩 2.95 GB 空闲；内存充足（7.8 GB）时同一 journal 第 1 步正常完成。**先查内存，再怀疑发散。**
2. **求解 journal 中含 point-surface** → 段错误（见 D1）。
3. 时间步过大导致 CFL 超标 → 降 dt（如 0.0005 → 0.0001），Courant 数降到 0.5。

### C4 残差飙升 / 发散

- 降 dt，降 Courant 数（密度基隐式起步建议 0.5，跑稳后再升到 1）。
- 首步可先用一阶精度启动，稳定后切二阶。
- 检查 patch 值是否合理（量级、gauge/absolute）。

## D. point-surface 与段错误

### D1 求解中进程崩溃，`fluent-2-error.log` 显示

```text
Update_Boundary_Velocity -> porous_interface_mom_source -> SIGSEGV
```

- **根因**：Fluent 24.2 的 bug——求解阶段存在 point-surface 会在边界速度更新路径上触发空指针。
- **处理**：**point-surface 只在后处理阶段创建**。需要测点时序时，改用 §4 的 report-definitions + report-files 方案（求解 journal 里不含 point-surface，只含 report-definitions），或在后处理中逐帧采样。

## E. journal 语法

### E1 报 `invalid command "xxx"` 后 journal 停止

- **根因**：该命令在 24.2 已废弃，或需要交互式多行输入，或参数数量不符。
- **处理**：查 `tui-commands.md` 的废弃对照表；对新命令先写单行探针 journal 验证。

### E2 后续 journal 行被"吃掉"

- **根因**：上一条命令弹出了交互提示（最常见是覆盖确认 `OK to overwrite? [cancel]`、或 `/solve/patch` 等交互命令），消费了下一行输入。
- **处理**：覆盖提示补一行 `ok`；交互命令补齐完整答案序列（如 patch 的 `zoneID` → `()` → `变量名` → `值`）。

### E3 生成的文件名带了 `_1_1` 后缀

- **根因**：`report-files` 目标文件已存在，覆盖确认消费了后续行，生成了新名字。
- **处理**：运行前删除旧输出文件，并**按实际生成的文件名**去读结果。

### E4 日志出现 `Overwrite confirmations ... are on -- will therefore ignore the following journal`

- **含义**：该行命令之后的多余参数（通常是行内的 `yes`/`no`）被当作另一条命令，既未生效也报了 `invalid command`。
- **根因**：给**不接受行内参数**的菜单项写了参数。已确认的有 `/display/set/contours/filled-contours`、`/display/set/contours/node-values`（它们的默认值本就是 yes，直接删掉这两行即可）。
- **不要**用关闭覆盖确认来消除告警。实测：开启时只是告警、journal 继续；关闭后同样的多余参数会升级为致命错误 `An error or interrupt occurred while reading the journal file`，**journal 直接中断**。详见 `tui-commands.md` §7.4。

### E5 report-files 输出的列序

- 实际列序是 `["Time Step", <各测点...>, "flow-time"]`——**flow-time 在最后一列**，不是第二列。
- 解析时读取第三行的带引号表头来确定列含义，不要靠位置猜。可直接用 `scripts/monitor_to_csv.py`。

## F. 进程与内存

### F1 求解进程突然消失 / 系统卡顿

- **根因**：崩溃残留 `cx2420.exe` / `fl2420.exe` / `fl_mpi2420.exe`（约 2.7 GB）。
- **处理**：三个一起杀；`taskkill fluent.exe` 无效。

```powershell
taskkill /F /IM cx2420.exe; taskkill /F /IM fl2420.exe; taskkill /F /IM fl_mpi2420.exe
```

### F2 出现两个求解实例并发

- **根因**：任务计划的 `Start-ScheduledTask` 重复触发，残留 trigger 排队。
- **判断**：数 `cx2420.exe` 的个数（每实例 1 个）。不要数 `fluent.exe`。
- **处理**：删除任务计划后重建，用 `schtasks /run` 单次触发。

### F3 会话结束后 Fluent 进程被杀

- **根因**：以非交互方式由当前会话拉起的子进程，会话结束时会被一同终止。
- **处理**：改用 Windows 任务计划，让进程完全脱离会话。

```bat
schtasks /create /sc once /st 23:59 /tn B2solve /tr "cmd /c <OUT_DIR>\run.bat"
schtasks /run /tn B2solve
```

### F4 `schtasks /create` 报 "拒绝访问"

- **根因**：Windows 10+ 上创建计划任务需要管理员权限。
- **处理**（免提权等效方案）：Python 里用 `creationflags` 让子进程脱离会话：

```python
DETACH_FLAGS = 0x00000008 | 0x00000200 | 0x08000000
# DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
subprocess.Popen(cmd, shell=True, cwd=WORK_DIR, creationflags=DETACH_FLAGS)
```

脚本退出后 Fluent 继续跑。配合"每 5 分钟触发一次的看门狗 + 分段限步续算"即可实现长任务自动接力，见 `auto-resume-and-guard.md`。

### F5 续算启动后第 1 步又卡死

- **根因**：上一段崩溃残留的 `cx2420/fl2420/fl_mpi2420`（约 2.7 GB）没清，内存不足。
- **处理**：先三个一起 taskkill，再启动续算。

## G. 网格（Meshing）

### G1 Workbench batch 里加不上 Fluent Meshing 的 task

- **现象**：`sys_ff.GetContainer("Mesh")` 返回的容器只有 `GetAllParameters/GetFiles/Name/ToString`；`AddTask` / `TaskObjects` / `GetWorkflow` 等**全部不存在**。
- **根因**：Workbench 架构限制——**没有 task chain 操作 API**，任何"batch 里动态构造 Fluent Meshing workflow"的尝试都是徒劳。
- **处理**：task chain 在 **GUI 里预先建好**（右键 Add → Share Topology / Describe Geometry / Volume Mesh），保存工程，再 batch 跑。见 `meshing-routes.md`。

### G2 `fluent.exe -meshing` 批处理启动后不进 Meshing Mode

- **现象**：首提示符仍是 Solver Mode；`/file/import-geometry` 报不存在。
- **根因**：`-meshing` 类开关在批处理模式下无效，且 TUI 无 import-geometry 命令。
- **处理**：Meshing Mode **只能 GUI 手操**；要脚本化改用 **gmsh → CGNS/UNV** 路线。

### G3 多 body 装配体出体网格失败 / 生成孤立体

- **根因**：漏了 **Share Topology** task，各部件之间没合拓扑。
- **处理**：在 GUI 任务树里补上 Share Topology，再 Describe Geometry → Volume Mesh。

## H. 栅格化与数据接口

### H1 栅格化后危险区面积与 post 基准对不上

- **根因**：用了 `scipy.interpolate.griddata(method="nearest")` 而不是逐点 argmin 最近邻。
  griddata 基于 **Delaunay 凸包**，对重复点/边界外点的处理与逐点 argmin 不同。
- **实测**：同一份 G3 数据 t=10 s，griddata 得 **32.27 m²**，逐点 argmin 得 **40.57 m²**（偏小 20%）。
- **处理**：改用逐点 argmin（见 `field-export-and-rasterize.md` §3.2）。**验证面积口径必须用与交付脚本相同的实现。**

### H2 二值掩膜面积暴涨一倍

- **根因**：对二值掩膜用了**线性插值**（把峰值抹开）。
- **实测**：`griddata(method="linear")` 把 40.6 m² 抬到 **80.9 m²**。
- **处理**：二值掩膜**只能用最近邻**；线性只适合连续色标云图。

### H3 高密度栅格红区碎成马赛克 / 四角误标红

- **根因**：CFD 单元数远少于目标格点数。G3 呼吸层仅 **1923 单元**（平均间距 ~0.23 m）铺到 100×100，t=10 s 红区碎成 **38 个连通块**、最大块仅占 59%。
- **处理**：**NX ≥ 50 时启用 `3×3 闭运算 + 3×3 中值滤波×2`**（碎块 38→7、最大块占比 →84.8%，面积 +7%）。若必须严格对齐基准面积，退回 10×10 / 50×50。

### H4 显示时图左右/上下错位

- **根因**：cell 编号是 `k = i*NZ + j`（i=X, j=Z），`reshape(NG,NG)` 得 `[X][Z]`，**显示前没转置**。
- **处理**：`mask.reshape(NG,NG).T` 后再 imshow。

### H5 并排对比时下游图与云图"上下颠倒"

- **根因**：下游 2D 画布 Y 轴向下，post 云图 Z 轴向上，**上下镜像**。阈值/切片/数据源其实完全相同。
- **处理**：对比前翻转其一。见 `field-export-and-rasterize.md` §5.3。

### H6 危险区看起来"不对"，但数值校验是对的

- **先怀疑口径，再怀疑数据**。依次核：切片高度、阈值、cell 编号、转置、镜像。
- **最有力的自证**：写一个渲染脚本**直接 import 栅格化模块并调用同一函数**（即"与下游数据同一份代码生成"），然后逐格比对。G3 实测 13 个时刻累计差异 **0 格**。
- **视觉差异的解释**：云图 turbo 对数色标下大片红色是 10⁴~10⁶ ppm 核心，而 **100 ppm 只对应色标中低端的青绿色**，量级差 100 倍以上——所以"云图看着红一片、掩膜只有小块"是正常的。

## I. PyFluent 编程接口类故障（S2 实测）

> 完整记录见 `pyfluent-vof-sputtering.md`。本节只列速查。

### I1 仿真"能跑"但物理明显不对（液块悬空不下落、不溅开）

- **根因**：**相材料赋值静默失败**——`material` 是交互式命令，写法少了 `yes` 应答或用了空格，命令不报错但不生效，phase-2 仍是空气（密度比 1:1）。
- **判别**：查块内 `phase-2-density`，若等于空气密度即中招。
- **处理**：`/define/phases/set-domain-properties/phase-domains/phase-2/material yes slag`（斜杠路径 + `yes`）。
- **通用**：**TUI 交互式命令写错只静默失败，必须用场数据反查**，不能以"没报错"为通过标准。

### I2 patch 报 `0 cells marked`

- **根因**（三条顺序铁律之一）：
  1. register 是 solve 阶段**新建**的（PyFluent 新建不触发标记）→ 必须**预置在 setup 保存的 case 里**再复用；
  2. `reg.type` 设在了 `standard_initialize` **之后**（initialize 会清空 register 标记）；
  3. `calculate_patch` 的 `cell_zones` 传了 zone 列表（**应为 `[]` 空列表**，靠 `registers` 定位）。

### I3 6 核并行访问 `cell_registers` 报 `wta(1st) to string->symbol`

- **根因**：**"VOF 模型查询" + "粘性模型设置"的组合**在并行下破坏 register 内部状态（单独任一都不触发）。
- **处理**：把 `cell_registers` 相关操作**移到 VOF 查询与粘性模型设置之前**。

### I4 场数据"值对但位置怪"（vof 峰值位置与理论严重不符）

- **根因**：`ScalarFieldDataRequest` 的 `node_value` 默认 **True** → 返回**逐节点**值（与 `FacesCentroid` 的逐面心数量/顺序不同）→ 按索引配对**错位**。
- **判别**：比较两者长度（sym 面 9891 节点 vs 19581 面心）。
- **处理**：**一律加 `node_value=False`**（逐面心，与 `FacesCentroid` 一一对应）。
- **通用**：坐标与标量是两次独立请求，**必须保证采样位置一致**。

### I5 高密度比 VOF 求解第几步就发散（Courant 从 0.6 跳到 200+）

- **根因**：密度比过大（如 2857）使压力 Poisson/AMG 病态，**不是 CFL、也不是表面张力问题**（关表面张力、缩步长均无效甚至更糟）。
- **处理**：**降密度比**（ρ 3500 → 1200）。弹道/溅开由 Fr 数主导，降密度不改变物理图像。

### I6 隐式 VOF 下进程崩溃（无 Application Error，gRPC Connection refused）

- **根因**：隐式 VOF 用 **geo-reconstruct** 界面格式会崩（24.2 实测）。
- **处理**：回退 **compressive**；配套 `PISO + PRESTO! + 二阶迎风 + 隐式体积力`（"更稳健"的 body-force-weighted + 一阶反而崩）。

### I7 求解中途发散，没跑到设定步数

- **先判断**：发散的最后一帧是否**已越过关键物理事件**（如落地 t≈0.556 s）。
- **已越过** → **用前一帧 checkpoint 出结果**，结论有效，不必重算（S2 即用 ckpt1350 完成全部交付）。
- **未越过** → 才降 dt 重跑（如落地后 5e-4 → 2.5e-4）。

### I8 重试脚本清理进程失效 / 残留进程累积

- **根因 1**：Git Bash 下 `taskkill //F` 被当成路径 → 报"无效参数"；应用 **`/F`**。
- **根因 2**：**`/IM` 不能连用多个**（`/IM a.exe /IM b.exe` 只杀第一个）→ **必须分成多条命令**。
- **后果**：残留累积 → 内存耗尽 → 系统卡死、Fluent 启动超时。


---

## J. 密度基可压缩激波（B2/B4 实测，2026-10-08）

### J1 ★ `solver.type` 的合法值不是 `density-based`

- `session.setup.general.solver.type` 只接受三个值：
  `pressure-based` / **`density-based-implicit`** / `density-based-explicit`。
- journal 里写 `/define/models/solver/density-based` **报错且不生效**（Fluent 保持
  pressure-based），**而 journal 不会因此中断**，后续命令照跑 —— 静默。
- **B2 实测后果**：当年 journal 写的正是 `density-based`，实际全程用
  **pressure-based** 跑完 200 步（case 读回来 `solver.type = pressure-based`）。
  压力基抹平激波、峰值偏低，是其结果比解析法低 6.3 倍的原因之一。
- **判据**：必须**从 case 读回** `solver.type` 才作数，不能看 journal 写了什么。

### J2 ★ pressure-far-field 的 Mach 数不能给 0

- 报错原文：`Mach number at Pressure Far-Field boundary should not be set to zero.`
- 必须给小正数（用 **`1e-3`**，≈0.34 m/s；对 0.1 s 激波问题等同静止）。
- **连锁症状（极易误判为 MPI 故障）**：报错点在 `initialize-flow`，多核下表现为
  `mpt_accept: connection timed out after 120 seconds`
  + `BAD TERMINATION OF ONE OF YOUR APPLICATION PROCESSES`
  —— 实为某个 rank 报错退出、其余 rank 干等。
  ⇒ **这类问题先用 1 核复跑**，能拿到清晰错误信息。
- **B2 实测后果**：当年因此放弃该边界，外边界仍是 **wall** ⇒ 激波反射，
  20 m 测点在 0.09 s 出现 117 kPa 假峰（B2 交付文档已人工剔除）。

### J3 强激波算例的耗时与"发散-重试"

- B4（初压 11.657 MPa，容器整体失效）压比 **115:1** ⇒ 激波马赫数 ≈10、
  激波后理论温度 ≈5900 K（**超过 Fluent 默认 5000 K 上限**）⇒
  `temperature limited to 5.000000e+03 in <大量> cells` 属**物理性截断**，
  不是数值爆炸，但会削弱峰值。
- 症状：每步都出现
  `Divergence detected - temporarily reducing Courant number to 0.5 / 0.05 / 0.005`
  ⇒ 一步重算数遍。实测 **189 s/步（8 核）/ 215 s/步（4 核）**，
  **加核几乎无效（8 核仅快 12%）**——瓶颈是发散重试，不是并行度。
- 缓解：journal 开头显式 `/solve/set/courant-number 0.5`，别让它从 1 往下探。
- 量级参照：同日 B2（初压 3.6 MPa、pressure-based）**18.6 s/步**
  （4 核，62 min 跑完 200 步）⇒ **密度基+马赫 10 比压力基+马赫 6 贵约一个数量级**，
  排期按此留量。

### J4 PyFluent 0.42.1 的取场 API 已重构

以下在 0.42.1 **全部不存在**（旧文档里的写法会直接 AttributeError）：

- `session.fields.field_info`
- `session.fields.field_data.get_scalar_field_data(...)`（`LiveFieldData` 无此方法）
- `session.tui.report.volume_integrals.volume_average`、
  `session.tui.report.surface_integrals.vertex_average`
- `session.tui.solve.initialize.set_defaults.pressure(...)`

**替代路线（实测可行，且零 API 依赖）**：

1. **取数**：用 Fluent 自己的 **report file**
   （`/solve/report-files/add ... frequency 1 frequency-of time-step file-name "..."`）
   每时间步写一行，Python 侧只读文件 —— 中途断开也能看，不依赖 PyFluent。
2. **初始化 / patch / 建测点**：**统一走 journal 文件**
   （`session.tui.file.read_journal(path)`），格式与手工 journal 完全一致，最稳。
   实测：`/solve/patch 707` + `()` + `pressure` + 值的多行写法一次通过。

## K. 外部格式网格导入直接 SIGSEGV（2026-10-23 冒烟测试实测）

**现象**：`/file/read-case xxx.msh`（gmsh 2.2）或 `xxx.cgns` → 日志走到

```
Reading "xxx.msh"...
Buffering for file scan...

Building...
     mesh
Node 0: Process NNNN: Received signal SIGSEGV.
Fatal failure in fluent (disconnected / ended abnormally) - exiting...
```

**关键判据**：日志里**没有** `Opening library ... done.` 这一行。
没有它就别再折腾网格文件了 —— 是 reader 库栈的问题，不是你的网格坏了。
（与 CGNS 那条"假崩溃"同一个特征，见 `meshing-routes.md` 的 CGNS 段。）

**六组对照实验（全部崩在同一位置，因此与下面四项无关）**：

| 变量 | 试过的取值 | 结果 |
|---|---|---|
| 文件格式 | gmsh 2.2 四边形（2000 quad）/ 三角形（4000 tri）/ CGNS | 全崩 |
| 路径字符集 | 含中文用户目录 / 纯 ASCII 目录 + TMP/TEMP 重定向 | 全崩 |
| 并行度 | `-t2` / `-t1` | 全崩（`-t1` 表现为 `Null Domain Pointer`） |
| PATH 传递 | Git Bash 冒号式 PATH / cmd.exe 原生分号式 PATH（补齐 vki、MS-MPI、Intel MPI） | 全崩 |

同环境下**原生 `.msh.h5` 读取正常**（`read-case` + `mesh/check` 通过），
说明求解器本身没问题，**只有外部格式 reader 这条路坏了**。

**处置**：

1. **不要让外部网格进入交付路线**。用 Fluent Meshing watertight 从 CAD（`.step`/`.igs`）
   生成原生 `.msh.h5`，这是本机唯一验证可用的链路（`tests/smoke/make_mesh.py`）。
2. **不要用 STL**：watertight 明确拒绝面片格式 ——
   `Faceted formats, like '.stl', '.tgf' and 'fmd' are not yet supported.`
3. gmsh 仍然有用，但只用来**出几何**（`gmsh.write("x.step")`），不出网格。

## L. PyFluent 0.42.1 的 `session.tui.*` 调用返回 None（静默）

**现象**：`m.tui.mesh.modify_zones.list_zones()`、`m.results.report.surface_integrals.area(...)`
等调用**不报错、不抛异常，但返回 `None`**，只在日志里留一行提示：

```
The following solver settings object method could also be used to execute the above command:
<solver_session>.results.report.surface_integrals.area(surface_names = [...], write_to_file = False)
```

**后果**：任何"靠返回值做判断"的自动化都会静默拿到 `None`，然后在下游炸
（例如按面积排序认进出口 → `min() empty sequence`）。这是最像"环境坏了"的假象之一。

**处置**：

- **取数一律走文件**：`/file/export/ascii`、`/solve/report-files/add ... file-name`，
  写盘后再用 Python 解析。已有案例（G3 监测 CSV）就是这么做的。
- **要返回值就用配置式 API**：`session.settings.*` 与 `session.solution.report_definitions.*`，
  不要用 `session.results.report.*` 的即时报表接口。
- 判断"到底有没有执行"看 `.trn` 转录文件，不要看返回值。

补充（2026-10-23 冒烟测试实测，比上面的"返回 None"更严重）：

- **`m.tui.file.*` 整条路径不可用**，不是返回 None 的问题，而是直接抛
  `RuntimeError: eval: unbound variable / Error Object: file`。因为 `file` 被路由到
  设置树求值，而设置树里没有名为 `file` 的顶层对象。
  改用 **`m.settings.file.*`** —— 它下面 `read_case` / `read_journal` /
  `start_transcript` / `stop_transcript` / `write_case_data` / `export` 全都有。
- **转录是本机最稳的取数通道**：`m.settings.file.start_transcript(file_name="x.trn")`
  → 执行 TUI 报表 → `stop_transcript` → 用正则解析该文件。报告值虽不通过返回值给出，
  但**一定会打印进转录**：

  ```
                              Area                [m^2]
  -------------------------------- --------------------
  wall:1:001                                       1e-07
  ```

- 顺带确认：`report_definitions` 在 0.42.1 里**没有** `surface_area` 属性
  （`AttributeError ... The most similar names are: surface`），
  通用面报告在 `report_definitions.surface`。

---

## M. gmsh 写的 STEP 把几何缩小 1000 倍（2026-10-23 实测）

**现象**：用 gmsh 建 1.0 m × 0.1 m × 0.02 m 的管道，STEP 导入 Fluent 后**不报错**，
但端面面积是 `1e-07 m²`（应为 `2e-3`）。求解能跑，结果却整体偏掉：
Re 从 222 变成 0.2，入口段长度远大于管长，出口根本没发展，
`u_max/U_mean` 永远对不上解析解 —— 很容易被误判成"网格质量差"或"边界条件不对"。

**根因**：gmsh 的 OCC STEP 写出器**永远**声明 `SI_UNIT(.MILLI.,.METRE.)`，
但默认把模型坐标**原样**写进去。Fluent 如实按声明换算，于是 1.0 被当成 1 mm。

**实测对照**（`gmsh` 4.15.2，三种组合，看的是"Fluent 最终得到的物理尺寸"）：

| 设置 | 文件内最大坐标 | 文件声明 | Fluent 实际得到 |
|---|---|---|---|
| 默认 | 1.0 | MILLI METRE | **0.001 m** ✗ |
| `Geometry.OCCTargetUnit = "M"` | 1000.0 | MILLI METRE | **1.0 m** ✓ |
| 默认 + 自己把尺寸乘 1000 | 1000000.0 | MILLI METRE | 1000 m ✗ |

**处置**：

```python
gmsh.initialize()
gmsh.option.setString("Geometry.OCCTargetUnit", "M")   # 必须在 model.add 之前
gmsh.model.add("duct")
gmsh.model.occ.addBox(0, 0, 0, 1.0, 0.1, 0.02)
...
```

- 设成 `"M"` 后 gmsh 会把数值乘 1000 再写，**文件里仍然是 `MILLI METRE`** —— 这是对的，
  **不要**去改声明，改了反而错 1000 倍。
- 单位不能靠"我设了"来相信，要读回文件验证：解析 `SI_UNIT` 拿到声明，
  取全部 `CARTESIAN_POINT` 的最大值，两者相乘才是物理尺寸。
  `tests/smoke/make_geometry.py` 的 `step_physical_extent()` 就是干这个的，
  偏差超过 1% 直接返回非 0。

**判别捷径**：任何"几何能导入、网格能生成、但雷诺数和预期差三个数量级"的场合，
先量一下包围盒，别先怀疑网格。

---

## N. 工作目录含中文 → Meshing 报 "Error in CAD Import"（2026-10-23 实测）

**现象**：同一份 STEP，放在纯 ASCII 目录（占位符 `<WORK>`）下正常；放到含中文的路径
（例如 Windows 用户名本身就是中文，工程目录落在其下）就在 CAD 导入阶段失败：

```
RuntimeError: Exception encountered in S_ExecuteTask: Error in CAD Import
Error occurred during import.
Importing the selected file(s) could not be completed. Check to make sure that the
selected file format is supported. In addition, check to make sure the CAD Readers
are properly configured for the format using the CAD Configuration Manager utility.
```

报错文字把矛头指向"格式不支持 / CAD Reader 没配好"，**完全是误导** —— 格式没问题，
是路径里的非 ASCII 字符。中文用户名（用户目录里带中文）会直接踩上，这在国内环境里很常见。

**处置**：

- Meshing 的工作目录必须是**纯 ASCII 路径**。`tests/smoke/make_mesh.py` 里做了两件事：
  路径非 ASCII 就自动退到系统临时目录，并在 `work.isascii()` 检查失败时直接给出可读的
  报错而不是让它走到 CAD 导入再报假错。
- 判定方法：`str(path).isascii()` 为 `False` 就换路径，别去查 CAD Reader。
- 注意这和"求解器读 `.msh.h5`"是两回事：求解器对路径宽容得多，只有 **Meshing 的
  CAD 翻译器**（Workbench→FLTG 转换）这一步挑路径。

---

## O. Meshing 的网格尺寸单位是"文件声明单位"，不是米（2026-10-23 实测）

**现象**：`create_surface_mesh` 传 `min_size=0.0015`，Meshing 立刻

```
Error: Out of Memory
running ANSYS TGrid CADToTGridConverter FAILED!
(TGL_Process_Curvature_SF(..., minMeshSize = 1.5e-06, maxMeshSize = 6e-06, ...) failed.)
```

并且进程随后挂死（本机实测挂了 9 分钟没退出）。看起来像"电脑内存不够"，
实际是**尺寸被当成了毫米再换算成米**：`0.0015` → `1.5e-06 m` = 1.5 µm，
在 1 m 长的管道上就是天文数字的单元。

**根因**：尺寸解释跟着 **STEP 文件声明的长度单位**走。gmsh 写的 STEP 声明
`MILLI METRE`，Meshing 日志会打 `length unit = [mm]`（见 M 节）。
此时传进去的 `min_size` / `max_size` 按毫米理解。

`import_geometry.length_unit.set_state("m")` **不管用** —— 文件声明优先，
日志里仍然是 `[mm]`。

**处置**：

- 尺寸常量用**毫米**表达，并在变量名上写死单位（`MIN_SIZE_MM`、`MAX_SIZE_MM`），
  防止下一个人"顺手改成米"。
- 开工前先看转录里的 `length unit = [...]`，再决定数值量级。
- 判据：日志里 `minMeshSize` 应该和你想要的物理尺寸同量级。
  想 1.5 mm，日志就该是 `1.5e-03` 左右；出现 `1.5e-06` 就是差 1000 倍。
- 万一已经挂死：直接杀 `fluent.exe` / `fl_mpi2420.exe`，别等它自己退。

---

## P. 体区域默认是 solid → "Flow boundary zone found adjacent to solid zone"

**现象**：网格建好、边界条件也贴上了，一开始求解就：

```
RuntimeError: Flow boundary zone found adjacent to solid zone.
       This problem MUST be fixed before solution proceed
```

**根因**：watertight 工作流建出的体区域**类型是 `solid`**。Meshing 自己的日志就写着：

```
 39  freeparts-...-1            solid               aluminum            cell
```

`aluminum` 这种材料名是 CAD 里带过来的，容易被当成"只是缺省材料名"而忽略，
真正的关键字是第二列的 `solid`。

**处置**（求解器侧一行，对任何来源的网格都适用）：

```python
cz = m.settings.setup.cell_zone_conditions
solids = list(cz.solid.keys())
if solids:
    cz.set_zone_type(zone_list=solids, new_type="fluid")
```

**判别**：读网格后先看 `mesh/check` 或转录里的
`N polyhedra cells, zone id: nn` 前面那行 zone 列表的 type 列；
是 `solid` 就先改了再谈物理。

---

## Q. `write_mesh` 遇到同名文件静默不覆盖（最阴的一个）

**现象**：改完网格参数重跑 Meshing，脚本打印 `[ok] wrote duct.msh.h5 (29.9 MB)`，
但求解结果和上一次**逐位相同**；`ls` 一看文件时间戳还是上一次的。

**根因**：`m.tui.file.write_mesh(path)` 在目标文件已存在时会弹"是否覆盖"，
**非交互模式下它静默放弃写入**，既不抛异常也不返回错误。
于是 `os.path.exists(path)` 依然为真（那是上一次的文件），
`os.path.getsize()` 也正常 —— 所有"以为写成功了"的检查全部通过。

**这是本 skill 里最危险的一类故障**：它不报错，只是让你拿旧结果当新结果用，
而且看起来完全合理（尺寸量级、量纲、收敛曲线都正常）。

**处置**：

```python
if os.path.exists(mesh):
    os.remove(mesh)          # 先删，把"静默放弃"变成"必然失败"
t0 = time.time()
m.tui.file.write_mesh(mesh)
if not os.path.exists(mesh) or os.path.getsize(mesh) == 0:
    raise SystemExit("写网格失败")
if os.path.getmtime(mesh) < t0 - 2:
    raise SystemExit("写网格失败：mtime 没更新，拿到的是旧文件")
```

**通用教训**：判断"文件类操作成功"永远要**三查** —— 存在、非空、**mtime 真的变了**。
只查 `exists()` 等于没查。同类问题还有 `/file/export/ascii`、`/solve/report-files`。
