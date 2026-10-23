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
