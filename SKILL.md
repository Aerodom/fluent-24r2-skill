---
name: fluent-24r2-case-debug
description: ANSYS Fluent 2024R2 (v242) 通用工作流：物理判型 → 网格路线 → journal/PyFluent 搭案例 → 脚本化自动跑批与长跑续算 → 离线后处理取数 → 交付可双击打开的 .wbpj 工程。适用于可压缩瞬态（爆炸/冲击波/高压泄放）、VOF 多相（泄漏/喷溅/自由液面）、组分输运（有毒可燃气体扩散）、单相流动与传热四类算例。当任务涉及编写 .jou journal、命令行直驱 fluent.exe、PyFluent 脚本、Fluent Meshing 网格路线选择、autosave 续算与看门狗、离线读 .cas.h5/.dat.h5 做后处理、生成 Workbench .wbpj 工程，或排查"气体不泄放 / 求解发散卡死 / TUI 报 invalid / 进程残留占内存 / license 或 GPGPU 报错 / autosave 无法续算 / 场数据导不出"等故障时使用。内置案例库 cases/，动手前先检索。 English translation lives in SKILL.en.md. Applies to ANSYS Fluent 2024R2 journal writing, PyFluent scripting, Fluent Meshing route selection, autosave and resume watchdogs, offline .cas.h5 / .dat.h5 post-processing, and double-clickable .wbpj Workbench deliverables.
agent_created: true
---

# ANSYS Fluent 2024R2 通用工作流（建模 → 求解 → 后处理 → 交付）

> 🌐 English version: [`SKILL.en.md`](SKILL.en.md) —— 全译版，章节编号与本文完全一致（§0–§12）。
> 两份文件可直接互换：`cp SKILL.en.md SKILL.md` 即切到英文。
> **改任何一节，请同步改另一份的同号章节**——`cases/` 与 `references/` 里所有交叉引用都按章节号走。

面向"**用 journal / PyFluent / 脚本把 Fluent 案例搭起来、跑完、把结果导成下游可用的数据、并交出用户能自己打开的工程**"的通用方法论。

两条贯穿全篇的原则：

1. **先验证，再写正式件**。Fluent 24.2 的 TUI 与官方文档大量不符，命令写错时 journal 会中途停摆且不留线索；PyFluent 的失败更多是**静默**的（不报错、不生效）。任何未验证的命令/API 都先探针。
2. **先查案例库，再自己判断**。`cases/` 里是已跑通的真实配方，命中即可少走几天弯路；未命中才靠本文件 §2 的物理判型 + `references/` 的检查单自行推导。

---

## 0 动作起点：三步定位

| 步 | 动作 | 判据/出口 |
|---|---|---|
| **0.1 判物理类型** | 用 §2 表把需求归入 A/B/C/D 四类之一 | 能一句话说清"主导机制 + 时间尺度 + 有无相界面" |
| **0.2 检索案例库** | 打开 `cases/README.md`，按 `class` + 关键词检索；命中则读对应卡片 | **命中** → 照卡片执行，只改其「§13 复用与差异」列出的项<br>**未命中** → 走 §2 + `references/case-setup-checklist.md` 自行选型 |
| **0.3 走阶段流程** | 按 §3 的 8 个阶段推进，每阶段有明确过闸判据 | 不过闸不许进下一阶段 |

> ★ **回写义务**：一个新案例跑通后，必须按 `cases/_TEMPLATE.md` 回写一张卡片到 `cases/`，并在 `cases/README.md` 索引表加一行。案例库的价值等于它被回填的次数。

---

## 1 环境事实（示例配置 —— 换机请按本机实测替换全部占位符）

| 项 | 值 |
|---|---|
| Fluent 可执行文件 | `%AWP_ROOT242%/fluent/ntbin/win64/fluent.exe` |
| ANSYS 自带 PyFluent Python | `%AWP_ROOT242%/commonfiles/CPython/3_10/winx64/Release/python/python.exe` |
| 轻量脚本 Python | `<PY38>/python.exe`（自带 PIL） |
| **科学计算 Python（栅格化/拟合/绘图/离线 h5 必用）** | `<venv>/Scripts/python.exe`（numpy 2.5 / scipy 1.18 / matplotlib 3.11 / h5py） |
| **PyFluent Python** | 同上 `<venv>`（已装 `ansys.fluent.core` 0.42.1）；也可用 ANSYS 自带 CPython |
| 许可证 | `ANSYSLMD_LICENSE_FILE=1055@localhost`；`AWP_ROOT242` 重装/重启后会丢，脚本用 `os.environ.setdefault` 兜底 |
| 启动形态 | `fluent.exe 3ddp -gu -t4 -i case.jou > case.log 2>&1` |
| **已验证版本边界** | **只保证 2024R2 / v242 + Windows x64**。其他版本按未验证处理，先跑 `tests/smoke/`；差异清单见 `references/version-compatibility.md` |

> **占位符约定**：`%AWP_ROOT242%` = ANSYS 安装根目录；`<PY38>` = 任一自带 Pillow 的 Python 3.8+；
> `<venv>` = 已装 numpy / scipy / matplotlib / h5py 的虚拟环境；`<PROJ>` / `<CASE_DIR>` / `<OUT_DIR>`
> = 工程根目录 / 算例目录 / 输出目录。**表中这些一律是占位符，不要照抄字面。**

启动参数：

- `3ddp` = 3D 双精度。**高压比案例（如 36 倍压比）必须双精度**。
- `-gu` = 无图形界面，journal 直驱。`-i <journal>` = 执行 journal。
- `-t<N>`：**命令行用 `-t4`，不要 `-t8`** —— `-t8` 报 `MPIDU_Init_shm_alloc: unable to allocate shared memory`（Windows MPI 共享内存段限制，与物理内存无关）。
- **PyFluent 形态（`processor_count=N`）不受 MPI 该限制**，但受**物理内存**限制：632k 单元 / 双精度 / 16 GB 机器 `processor_count=6` 可稳定长跑（峰值 ~5.8 GB）；878k 单元用 6 核会 OOM **静默崩溃**（无弹窗）。
- ⚠️ `-meshing` 在批处理下无效，首提示符仍是 Solver Mode。网格路线见 `references/meshing-routes.md`。

---

## 2 物理判型 → 求解路线（先定这条，再动 journal）

| 类 | 判据 | 求解器/模型 | 时间尺度 | 典型时间步 |
|---|---|---|---|---|
| **A 可压缩瞬态** | 压力梯度/惯性主导，马赫数 ≳ 0.3，毫秒级（爆炸、冲击波、高压泄放） | **密度基（隐式）+ 理想气体 + 二阶瞬态**，**不开重力** | ms | 1e-4 ~ 5e-4 s |
| **B 高密度比多相** | 存在相界面，Fr/We 数主导，秒级（液体泄漏、熔体喷溅、自由液面） | **压力基 + VOF（隐式）+ Implicit Body Force**，PISO | s | 1e-4 ~ 5e-3 s |
| **C 组分输运/扩散** | 无相界面，要的是浓度场（有毒/可燃气体、烟气） | **压力基 + Species Transport + Realizable k-ε** | 十秒~分钟 | 5e-3 ~ 1e-2 s |
| **D 单相流动/传热** | 无界面、无组分，稳态或慢瞬态（风场、换热、阻力） | 压力基 SIMPLE / Coupled；按需能量与辐射 | 稳态或长瞬态 | 按 CFL |

> ⚠️ **覆盖声明 —— 别把"分类齐了"当成"案例齐了"**
>
> 上表四类是**判型框架**，不是案例库覆盖率。案例库的 `class` 目前只有三种取值
> （`vof-free-surface` / `compressible-shock` / `species-dispersion`），
> **D 类（单相流动/传热）一张实测卡片都没有**。
>
> 判型落到 D 类时：
> 1. **不要硬套 B 类的 VOF 配方**（多相与单相的网格/格式要求完全不同）；
> 2. 直接走 §2 + `references/case-setup-checklist.md` 自行选型；
> 3. P0 口径优先用**解析解**兜底（管道/通道层流 `u_max = 1.5 U_mean`、平板 Blasius、圆管 `f = 64/Re`），
>    这样即使没有同族卡片也能验证对错；
> 4. 跑通后**请回写第一张 D 类卡片** —— 这是当前案例库最大的缺口。

### 四条选型铁律

1. **毫秒级激波 → 密度基 + 理想气体**。压力基无法正确捕捉激波/膨胀波。**且不启用重力**：0.1 s 内重力速度增量约 1 m/s，不足激波速度的 0.3%。
2. **秒级高密度比多相 → 压力基 + VOF + 隐式体积力**。密度比 > 1000 不开隐式体积力，界面压力会震荡；界面格式用 **Compressive / Modified HRIC**，**不要用二次迎风**（会糊）。
   - 密度比过大仍会病态发散（实测 ρ=3500、密度比 2857：第 8~9 步 Courant 由 0.6 跳到 210，**关表面张力、缩步长都无效**）。此时**降密度比**（3500 → 1200）有效，弹道/溅开由 Fr 数主导、物理图像不变——但必须在交付文档标明这是**数值妥协**。
   - **隐式 VOF 下不要用 `geo-reconstruct`**（24.2 实测会崩进程）；固定组合 `PISO + compressive + PRESTO! + 二阶迎风 + 隐式体积力`。
   - **表面张力默认关**，判据用 `Bo = ρgL²/σ`；Bo ≫ 1 时物理上可忽略，且高密度比下 CSF 会产生寄生流速导致发散。
3. **秒级气体扩散 → 压力基 + 组分输运**，比 VOF 简单（无相界面），输出直接是浓度场（`molef-<组分>`）。**重气必须开重力**（下沉是主导机制），与 A 类相反。
4. **网格必须匹配物理形态**。换物理模型 = 换网格要求，原网格通常不可复用（DPM 的 0.15 m 网格算 Ø150 mm 液块会糊死）。开工前 30 秒先算"网格能否分辨特征尺度"：
   ```python
   R_min = 5 * h            # 取 10 格直径
   V_min = 4/3*pi*R_min**3  # 设计注入体积 << V_min ⇒ 该网格算不了这个案例
   ```

---

## 3 标准工作流（8 阶段，逐阶段过闸）

> 全流程的"闸"都在表里。**闸不过不前进**——这比事后解释结果便宜得多。

| 阶段 | 做什么 | 产出 | **过闸判据** |
|---|---|---|---|
| **P0 口径冻结** | 定验收量、阈值来源、起算基准、切片高度、时间窗；从案例库取基线量级 | 一页"验收口径"（写进 README） | 每个交付数字都能回答"单位 / 从哪儿起算 / 阈值谁定的 / 哪个时间窗" |
| **P1 网格** | 按 `references/meshing-routes.md` 选路线；关键区加密 | `.msh.h5` 或 `.cgns` | `/mesh/check` 最小体积 > 0；网格能分辨特征尺度（铁律 4） |
| **P2 搭案例** | 探针 journal 逐条验证 → 正式 journal / PyFluent 脚本 → **改完 zone 立刻 write-case** | `*_setup.cas.h5` | 日志出现 `N cell zone, M face zones`；zone 清单（ID/类型）已记录 |
| **P3 试跑自检** | 跑 10~50 步；核 t=0 初始场；量级比对基线 | 试跑日志 + 判据表 | ① 初始场核验通过（注入量/patch 量对得上）② 第 1 步有 `Flow time` 输出 ③ 量级与基线同阶 |
| **P4 自动化长跑** | 脚本化批量驱动 + autosave + 分段续算 + 看门狗（§4） | 无人值守跑完的 dat 帧 | `.trn` 里 `time step` 持续推进；auto_save 已落盘至少一帧 |
| **P5 后处理** | **优先离线读 `.h5`**，必要才起 Fluent（§7） | CSV / 云图 / 场数据 / 轮廓 | 与 Fluent 自报量**逐位对齐**；口径写入元数据 |
| **P6 交付** | 数据 + 云图 + **`.wbpj` 工程**（§8）+ 口径说明 | 交付包 | 两道判据：静态体检 + 无头回读（§8 第 4 条） |
| **P7 回写案例** | 按 `cases/_TEMPLATE.md` 写卡片 + 更新 `cases/README.md` 索引 | 新案例卡片 | 卡片能被下一个人**照做复现**（含差异指引与坑）；`scripts/check_cases.py` 零 error |

**贯穿全程的三条**：

- **P2 的顺序不可颠倒**：`read-case → check → 修 zone 类型 → 写 case`。改过 zone 类型的网格已与原始网格不同，不存 case 会导致后续所有 autosave 都无法续算。
- **P3 的 t=0 核验是最便宜的把关**。实测代价：patch 注入只有设计值 24%（多 register 逐个调用不累积），长跑 4.3 h 白跑；若在 t=0 存一帧离线核验 `ΣαV`，5 分钟就能发现。
- **P6 之前不要宣布"跑完了"**。脚本产出的 `*.cas.h5` / `*.dat.h5` 不算交付完成——用户打不开、改不了。

---

## 4 自动化：让脚本把活干完（P4 展开）

### 4.1 三种驱动形态，按需要选

| 形态 | 适用 | 入口 |
|---|---|---|
| **journal 直驱** | 命令链固定、无需读中间结果决策 | `scripts/run_fluent_journal.py` |
| **PyFluent 脚本** | 需要条件分支（读回值判断、循环 patch、失败重试、网格导入） | `pyfluent.launch_fluent(...)`，见 `references/pyfluent-vof-sputtering.md` |
| **外层调度器** | 多案例批量、串行排队、内存守卫、自动后处理 | 项目内 `run_serial_*.py` 一类脚本 |

**关键判断**：**CGNS 网格导入一律走 PyFluent + 重试，不要走 `fluent.exe -i journal`**。实测同一份 CGNS 用 journal 路径必崩在 `Importing` 之后（无栈、无 `Opening library` 行），换 PyFluent 首次即成——当年据此得出的"文件本身有问题"结论是**错的**。

### 4.2 长跑：分段续算 + 看门狗

1. 求解时开 autosave：`/file/auto-save/data-frequency 200` + `/file/auto-save/root-name "<前缀>"`（**只写纯文件名，不带目录**）。
2. 脚本扫描目录里最新 `*.dat.h5` 编号作 checkpoint（**取最后一串数字**，别取第一段——扩展名 `.h5` 里的 `5` 会把 600 步判成 5 步）。
3. 续算 = `read-case(setup)` → `read-data(最新 checkpoint)` → `dual-time-iterate N 20` → `write-data`。**绝不调 `standard_initialize`**（流场来自 data，初始化会清零）。
4. 每次只续 400~700 步（约 45~80 min）主动退出存档 ⇒ **可反复触发、天然容忍被杀/崩溃**。
5. 外部周期拉起（Windows 任务计划）做看门狗：检测到求解进程在跑就跳过，否则续下一段；到总步数调后处理。

> ⚠️ **会话结束会杀掉整棵子进程树**。`DETACHED_PROCESS` / `BREAKAWAY` / `ShellExecute` 在 Agent 会话里**全部实测被杀**。**本机标准做法：写好 bat，请用户双击**。判活必须**换一次工具调用**再看（同一次调用内看到的"在跑"不算证据）。
> 细节与全部坑（`IgnoreNew` 阻塞、Ctrl+C 带走进程树、`python.exe` 每 15 min 闪黑窗、半成品存档）见 `references/auto-resume-and-guard.md`。

### 4.3 判"到底在不在算"：只看三种证据

| 判据 | 刷新节奏 | 用途 |
|---|---|---|
| **`work/fluent-<时间戳>-<pid>.trn`** | 实时（Fluent 自己写） | ★ 首选。读 `Flow time = X, time step = N` 得真实步数 |
| 调度脚本的 stdout 日志 | Python 8 KB 块缓冲，实测可达 3 min 不刷盘 | **只看它会把"健康推进"误判成"卡住"** |
| `*_auto-*-NNNNNN.dat.h5` | 每 N 步 | 存档/续跑依据，粒度太粗 |

- **别数迭代行推步数**：残差表每 10 个迭代打一行 ⇒ `iter_lines ≈ 步数 × 25 / 10`，实测差 2.5 倍。
- **solve 日志是混合编码**（Fluent 侧 OEM + 脚本侧 UTF-8），中文 pattern 搜不到且会静默返回 0 行。**一律用 ASCII 锚点**（`grep -a '>> '`、`grep -a '\[OK\]'`），并加 `-a`。
- **别用 `tasklist | grep` 判进程**（中文 locale 编码乱，实测返回空）。用 Python `subprocess` 调 `tasklist /FO CSV` + `csv.reader`；或干脆用文件 mtime。
- **Bash 里不要调 PowerShell**（被安全策略拦），而 PowerShell 工具在本机**不回显 stdout** ⇒ 取进程/内存信息走 Python `subprocess` 调原生 exe。

### 4.4 脚本清单（本 skill 自带）

| 脚本 | 用途 |
|---|---|
| `scripts/run_fluent_journal.py` | 跑 journal、落盘日志、回显关键行与退出码 |
| `scripts/make_render_journal.py` | 多帧串行渲染云图 journal（内置 re-render、固定色标） |
| `scripts/export_field_journal.py` | 多帧多变量场数据（`.xyz`）批量导出 journal |
| `scripts/rasterize_field_to_grid.py` | 场数据 → 栅格掩膜宽表/长表（含去噪、最近邻口径） |
| `scripts/monitor_to_csv.py` | 监控文本 → 时序 CSV（首峰/到达时间，可剔除反射峰） |
| `scripts/auto_resume.py` | 分段续算 journal 生成 + 启动 |
| `scripts/check_cases.py` | 案例库一致性校验：front matter / 受控词 / 索引双向一致 / 链接 / assets |
| `scripts/audit_sensitive.py` | **对外发布前**体检：本机绝对路径 / 用户目录 / 邮箱 / IP / 组织名；支持 `scripts/audit_terms.local.txt` 自定义词表 |

---

## 5 已验证 TUI 命令

完整清单、交互式答案序列、废弃命令对照见 `references/tui-commands.md`。下面是一条**可压缩瞬态**的完整骨架：

```text
/file/read-case "path/case.msh.h5"
/mesh/check
/define/boundary-conditions/zone-type 714 interior
/define/models/solver/density-based
no
/define/models/energy yes
no
no
no
yes
/define/materials/change-create air air yes ideal-gas
no
no
no
no
no
no
/define/models/unsteady-2nd-order
yes
/solve/set/time-step 0.0005
/solve/initialize/set-defaults/pressure 101325
/solve/initialize/set-defaults/temperature 298
/solve/initialize/initialize-flow
/solve/patch
707
()
pressure
3600000
/solve/dual-time-iterate 200 20
/file/write-case "path/final.cas.h5"
ok
/exit
yes
```

要点：

- **命令名用连字符**（`unsteady-2nd-order`、`plane-point-n-normal`），不是下划线。
- **zone 名含冒号时（`air_ambient:1:707`）TUI 无法识别**，一律用数字 ID。
- `/solve/set/time-step` 必须在切到瞬态**之后**执行才生效。
- `/solve/patch` 是交互式：先输 zone ID，再输 `()` 结束列表，再输变量名和值。
- 覆盖已存在文件会提示 `OK to overwrite?`，journal 里要补一行 `ok`，否则**后续行会被当答案吃掉**。
- `read-case-data` 不接受两个路径，必须拆成 `read-case` + `read-data`。
- VOF / 组分输运的模型启用链路见 `references/tui-commands.md` §3。

---

## 6 监控与云图

### 6.1 测点采样（求解时自动记录）

`/report/surface-integrals/vertex-avg` 及其变体在 24.2 build 中**全部报 invalid command**。唯一可靠的是 datamodel 驱动的 report-definitions + report-files：

```text
/surface/point-surface p5 6.75 0 0
/solve/report-definitions/add mon_p5 surface-vertexavg field pressure surface-names (p5) q q q
/solve/report-files/add mon_file report-defs (mon_p5) frequency 1 frequency-of time-step file-name "path/mon.txt" q q
```

三条铁律：

1. **`point-surface` 绝不出现在求解 journal 里**——求解阶段存在 point-surface 会触发 `Update_Boundary_Velocity → porous_interface_mom_source → SIGSEGV`。只在**后处理**阶段创建。
2. `report-files` 目标文件已存在时，覆盖提示会吃掉后续 journal 行，实际文件名变成 `<name>_1_1.txt`。**每次运行前删旧文件或用带序号的新名**。
3. 记录的是**绝对压力**（Pa）；超压 = 值 − 操作压力（通常 101325 Pa）。

### 6.2 云图与多帧渲染

- 切面：`/display/surface/plane-point-n-normal <name> <px> <py> <pz> <nx> <ny> <nz>`（点 + 法向）。**竖直/水平剖面靠法向区分**：水平面 `0 1 0`，竖直面 `0 0 1`。
- **每帧 `read-data` 后重建切面，切面名逐帧唯一**；整段只建一次不可靠。
- 变量与色标范围走**交互式** `/display/contour`（先变量名，再 min、max）。多帧对比**必须固定 min/max**，否则颜色不可比。
- **每帧保存前必须 `/display/re-render`**，否则从第二帧起 `save-picture` 抓到的是上一帧（表现为"只有网格没有云图"）。
- **不要写** `/display/set/contours/filled-contours yes` / `node-values yes` —— 不接受行内参数，默认本就 yes，删掉后图像逐字节不变。
- `save-picture` 前用 `/display/set/picture/x-resolution`、`y-resolution`（这两条行内传参有效）。
- **一次会话内串行读多帧渲染**（2 帧约 1 min，8 帧约 2 min），不要每帧重启 Fluent。

---

## 7 后处理与交付数据（P5 展开）

### 7.1 ⭐ 优先离线直读 `.h5`，别起 Fluent 会话

`.cas.h5` / `.dat.h5` 本身就是标准 HDF5。凡"取数 + 算指标"型后处理（面积、通量、极值、阈值半径、时序曲线、给下游出 CSV），一律 `h5py` 离线算：

- 时间从 **~30 min / 3 个算例** 降到 **~20 s**；
- 不占 license、不吃提交内存，**长跑进行中即可对已完成帧增量出产物**；
- 不依赖 CFF / iso-clip / `report_definitions` 等少实测接口，**没有静默失败**；
- 逐位可复现，改一行脚本就能重算全部历史帧。

**必查的三个坑**（详见 `references/offline-h5-postprocessing.md`、`references/offline-cells-and-species.md`）：

1. **2024R2 的网格在 `.cas.h5`、场在 `.dat.h5`** —— 拿 dat 当网格读必 `KeyError: 'meshes'`，必须**成对读**。
2. **面场下标口径按字段而异**：同一个 `.dat.h5` 里 `SV_VOF` 是全局 face id（长度 = 总面数），`SV_T` 是边界面口径（长度 = 边界面数）。统一换算会**静默错位**（实测 `∮αdA` 算成 0.46025，真值 0.421395）⇒ **按数组长度判别**，且**必须与 `monitors_<S>.csv` 里 Fluent 自报的同名量逐位对齐**。
3. **`zoneTopology/name` 是一条分号拼接字符串**（`shape=(1,)`），不是字符串数组 ⇒ 先 `decode().split(";")`。

仍须起 Fluent 的情形：需要 Fluent 做插值/重采样、抽取等值面几何、定义并求值自定义场函数。可混合，别为统一而全塞回 Fluent。

需要 3D 体素/切片但 `dat.h5` 里没有单元形心与体积时：由 `c0`/`c1` 反算（恒等式 `nface + nint = 4×ncell` 判是否纯四面体），实测体积加权均值与 Fluent 自报偏差 **7.9e-09**。

### 7.2 四种交付形态（按验收量选，不要硬套）

| 形态 | 内容 | 典型验收量 | 生成方式 |
|---|---|---|---|
| **A 时序标量** | `time_s, 指标` 两列 CSV | 液池体积、覆盖面积、泄漏总量 | 监控文本 → `monitor_to_csv.py` |
| **B 半径 + 到达时刻** | 阈值半径表、波前到达时间 | 爆炸伤害边界、喷溅扇形半径 | 首峰拟合 + 阈值反解 |
| **C 栅格掩膜长表** | `time, cell, red, yellow` | 二维危险区扩散动画 | `.xyz` → 栅格化 → 汇总 |
| **D 多边形顶点** | 每行一顶点 `x_m, y_m` | 不规则覆盖区轮廓 | 等值线提取 + 闭合 + 重采样 |

**跨工具一致性靠三件事**：单位与起算基准写进文件名或同目录 README；CSV 全英文路径；索引定义（如 `k = i*NZ + j`）在**栅格化脚本、长表转换、下游解析**三处必须同一个，改一处必须改三处。

### 7.3 栅格化四个口径约定（都踩过坑）

1. **切片带厚度必须写明**（如呼吸高度 `y ∈ [1.5−0.1, 1.5+0.1] m`），漏写无法复现。
2. **验证面积用"逐点 argmin 最近邻"，不要用 `scipy.interpolate.griddata(method="nearest")`** —— griddata 基于 Delaunay 凸包，实测比正确值小 20%（32.27 vs 40.57 m²）。
3. **二值掩膜禁用线性插值** —— 会把峰值抹开，实测面积从 40.6 暴涨到 80.9 m²。线性只适合连续色标云图。
4. **高密度栅格必须去噪** —— CFD 单元远少于目标格点时最近邻产生马赛克（实测红区碎成 38 个连通块、最大块占 59%）。`NX ≥ 50` 时启用 `3×3 闭运算 + 3×3 中值滤波×2`：碎块 38→7、最大块占比 59%→84.8%，代价面积 +7%。

### 7.4 阈值判据与拟合

- **取"入射首峰"而非全程峰值**。外边界为 wall 时激波反射会叠出更高假峰（实测 20 m 点全程峰 117.1 kPa @0.090 s 是反射峰，真实入射首峰 52.6 kPa @0.0475 s）。用"前 60% 时间窗找峰"剔除（`monitor_to_csv.py --window 0.6`）。
- **峰值-距离衰减拟合** `P(r) = a·r^b`，双对数最小二乘；`b ≈ −1` 与球面强激波 `P ∝ 1/r` 一致，可作量级校核。
- **伤害阈值是外部判据，不是 CFD 产物**。评审若指定标准或剂量-时间曲线，半径必须重算——**报告里必须显式标注阈值来源**。
- **反解**：`r = exp((ln 阈值 − ln a) / b)`。**起算基准必须对齐**（测点从部件侧壁量、下游圆以轴线为心，差半个部件尺寸）。
- 正解是把外边界改 `pressure-far-field`（表压 0、Mach 0、T 298 K）重算，物理上模拟无限大环境。

---

## 8 交付物：`.wbpj` 工程（P6 展开，硬要求）

**每个算例交付必须带 Workbench 工程入口。** 流水线跑出来的 `*.cas.h5` / `*.dat.h5` **不算交付完成**——那是只有你会用的中间产物。用户要能**双击 `.wbpj`**，在 Fluent / CFD-Post 里看设置、看结果、并自己改。

配方与全部坑见 `references/wbpj-project-generation.md`。五条底线：

1. **多帧就每帧一个系统**，且**帧 N 的 case 必须配同一帧的 dat**。**绝不能只挂 case 不挂 data**（Solution 处于未完成态，用户双击 Results 可能被提示更新、误启动求解）。
2. **可搬移工程**（拷到别机可用）：先把 case/dat 拷进工程 `_files` 再 `Import`；`dat` 必须挂 `ContainerAssociations: ["Solution"]` + 系统属性 `"Start from available data": "True"`，否则用户点运行时用不上初始场。
3. **`-B` 批处理下 `Edit()` 必失败**，批处理只能**登记引用**、不能真读 case；系统显示名只能用 `DisplayText`（用 `DisplayName` 会让 journal 静默崩溃）。
4. **交付前两道判据都要过**：
   - 离线静态体检（Location 存在性 / 挂载容器 / 系统显示名 / 交付清单声明→glob→真实落盘）；
   - 无头回读（`RunWB2 -B -R`：`Open` → `GetAllSystems` → 逐系统 `Setup/Solution.GetFiles()` 非空 → `GetMessages()==[]`）。
5. **告诉用户从哪个入口进**：交付说明里明确写"更新 / 双击 `Solution`"，并在 Fluent 控制台确认**既读了 case、也读了 dat**。让用户走 `Setup` 会看到冷态初值，从而误判"没配好"。

---

## 9 进程、内存、磁盘

- **判断实例数看 `cx2420.exe` 数量**（每实例 1 个），不要看 `fluent.exe`（启动器有多个）。
- **清理残留**：崩溃留下 `cx2420.exe` / `fl2420.exe` / `fl_mpi2420.exe`（合计约 2.7 GB）。`taskkill fluent.exe` 杀不掉它们，必须三个一起杀。
- **内存判据看"提交（commit）"，不看物理可用**：崩溃信息 `ST_Create_Store: out of memory` 是**提交分配失败**。实测一次 `ullAvailPhys` 3.33 GB（看着不够）而 `ullAvailPageFile` **19.97 GB**，按提交判据放行后全速运行、零换页。
  - 守卫条件：`提交可用 ≥ 单作业提交 × 1.5`，物理可用只作软门槛（≥2.5 GB）。
  - 单作业提交量参考：404k 单元 + DO 16 向 + 隐式 VOF + 凝固、`-t4` ≈ **6.1 GB**；632k 普通瞬态 `-t6` 峰值 ≈ 5.8 GB。16 GB 机器上这类作业**只能串行跑一个**。
- **"第 1 步卡死数小时不出 Flow time"已两次被证实是内存不足**，不是发散。
- **磁盘预估**：`auto_save` 的 `case_frequency` 默认 `if-case-is-modified` ⇒ case 只在求解前改过时写一次（覆盖，~43 MB），data 每帧累积（~275 MB）⇒ 12 帧约 **3.35 GB**，别把 case 按帧数乘。
- 成本量级必须实测：普通瞬态约 6.6 s/步（632k、`-t4`）；404k + DO + 隐式 VOF + 凝固实测 **36~40 s/步**；1.63M + 隐式 VOF + 能量实测 **64~69 s/步**。**ETA 用最近一个完整块的均值**，不要用前几步外推（会偏高 30%）。
- 回流噪声：`Reversed flow on N faces of pressure-outlet X` 是**正常警告**，不是发散证据。

---

## 10 故障速查（最高频）

完整表（含 autosave / 续算 / 内存 / 进程 / 多相 / 栅格化六类）见 `references/troubleshooting.md`。

| 现象 | 根因 | 处理 |
|---|---|---|
| 启动即报 `License is not available` / `GPGPU computing disabled` / `floating point exception` | Launcher 里 Solver GPGPUs per Machine 填了非 0 | 该值填 **0** |
| 气体不膨胀、压力场无变化 | 高压气区被自家 wall 完全封闭 | 把该 wall 改 `interior`，**改完立刻 write-case** |
| 第 1 步 CPU 满负荷却长时间不出 `Flow time` | 空闲内存不足；或求解 journal 里有 point-surface | 清残留进程 / 确认提交内存；去掉 point-surface |
| journal 报 `invalid command "xxx"` 后停止 | 命令在 24.2 废弃或需交互 | 查废弃对照表，改探针验证 |
| 后续 journal 行被"吃掉" | 覆盖确认提示吃掉了行 | 补 `ok`；**不要**关覆盖确认（关掉后同样的参数会变成致命错误） |
| 续算报 `The mesh has been modified / data incompatible` | 改 zone 类型改了网格，而 autosave 只存场 | 改完 zone 立刻 write-case，从该 case 续算 |
| 续算报 `Update_Time_Level: invalid data` | 二阶瞬态缺 N−1 时间层 | 从 write-case 的 case + 对应 data 续算 |
| 超压曲线出现多余假峰 | 外边界是 wall，激波反射 | 外边界改 `pressure-far-field`；或只取首峰并写明剔除 |
| 峰值整体偏一个大气压 | patch 误用 gauge / absolute | 统一口径：patch 填表压，超压 = 绝对 − 操作压力 |
| VOF 界面震荡/糊化 | 未开隐式体积力 / 界面格式用二次迎风 / 网格太粗 | 开 Implicit Body Force，改 Compressive 或 Modified HRIC，加密界面 |
| **仿真能跑但液块悬空不下落** | **相材料赋值静默失败**（`material` 是交互式命令，缺 `yes` 不报错但不生效）⇒ phase-2 仍是空气 | 用 `.../phase-domains/phase-2/material yes slag`；**用场数据反查 `phase-2-density` 确认** |
| **patch 报 `0 cells marked`** | register 新建 / `reg.type` 在 `standard_initialize` 之后 / `cell_zones` 未传 `[]` | 三条顺序铁律；register 必须**烘焙进 case** |
| **多个 register 逐个 patch，只有少数生效** | 逐个 `calculate_patch` **不累积**（实测 12 团只生效 3 团，注入量 24%） | **全部 register 放进一次调用**；并加"牺牲位"补末位涂抹：`cases/S1-foam-slag-splashing.md` |
| **场数据"值对但位置怪"** | `ScalarFieldDataRequest` 的 `node_value` 默认 True（逐节点值，与面心错位） | 加 **`node_value=False`** |
| **离线算出的面积/极值"差不多但就是不对"** | 面场下标口径按字段而异（见 §7.1） | 按数组长度判别 + 与 Fluent 自报值逐位对齐 |
| **交付指标整列恒为 0** | 该量依赖 Dirichlet 定温边界，不是算错 | **任何恒为 0 的交付指标，先回去查它依赖的 BC 类型** |
| 长跑跑到一半静默消失 | 进程随会话结束/机器重启被整棵杀掉 | 长跑必须由**外部周期拉起**（任务计划 + PID 锁幂等） |
| 电脑每 15 min 闪一次黑窗 | 计划任务用 `python.exe`（Subsystem=3）+ `InteractiveToken` ⇒ 每次在桌面建控制台 | 换 **`pythonw.exe`** + 入口做 stdout 兜底（`pythonw` 下 `print()` 是**静默丢弃**，不是崩溃）；跑完删任务 |
| 计划任务"上次结果"= `0x800710E0` | 看门狗阻塞着等长跑，`IgnoreNew` 拒了后续触发 ⇒ 挂在其上的增量后处理永不执行 | 改**阻塞式监护循环**：等待期间自己做增量后处理 + 用进度文件 mtime 判停滞并 `taskkill /T /F` |
| `.dat.h5` 报 `KeyError: 'meshes'` | 网格在 `.cas.h5`，dat 顶层只有 `results/settings` | 后处理**必须成对读** |
| 组分算例"环境大气"变纯氮气 | `standard_initialize()` 把差减组分 `last_species` 填 1 | 混合物用 `{so2, air}`，`air` 作差减组分；别再 `copy_by_name('air')`（得 `air-1`） |
| 后处理某步 rc=2 且整链无限重试 | 脚本位置参数 `nargs="?"` 只收单案例却被传多个 | 改 `nargs="*"` + 逐案例 `try/except`；接链后**真跑一次**看 rc |
| `OSError: [Errno 22]` 出在 `PIL/Image.py` | 目标 PNG 被别的进程（图片预览面板）占着写句柄 | 重试 + 改存 `<name>.busy.png`，绝不抛异常 |
| 算例一启动 `exit=1`，日志末尾 `UnicodeEncodeError: 'gbk'` | 日志含 GBK 编不出的字符（`ṁ`/`²`/`⇒`），中文 Windows 下 `print` 直接终止进程 | 入口 `sys.stdout.reconfigure(errors="replace")` + 链路注入 `PYTHONIOENCODING=utf-8` |

---

## 11 硬规则

1. **未验证的 TUI 命令一律先探针**。只含该命令的 journal 单独跑一次，看日志。批量猜命令的代价是整个 journal 中途停摆。
2. **改过网格相关设置（zone 类型）后必须立刻 write-case**，否则本次求解的所有 autosave 都无法续算。
3. **不要给不接受参数的菜单项写行内 `yes`/`no`**。日志出现 `Overwrite confirmations ... will ignore the following journal` 就是这个毛病；**更不要通过关闭覆盖确认来消除它**。
4. **交付数据必须写清口径**：单位、起算基准、阈值来源、切片高度、时间窗。无法复现的数据等于没有数据。
5. **新写的"胶水代码"先自证，再上长跑**。skill 管得住已知的、会重复的坑；管不住这次现写、只跑第一遍的解析/开关/启动代码。三道 1 分钟门槛：
   - **解析函数拿真实文件名自测**（`re.findall(r"\d+", "X_auto-1-00050.dat.h5")` 最后一串是扩展名里的 `5`，600 步被当成 5 步）；
   - **开关先证伪语义**（`RESUME=1` 实际置了 `force_restart=True`，从 t=0 重跑）；
   - **长跑启动件跨调用验活**（同一次工具调用内查到的"在跑"不算证据）。
6. **每个算例交付必须带 `.wbpj` 工程入口**（§8）。脚本跑出 `cas.h5`/`dat.h5` 不算交付完成。
7. **数值妥协必须标明**。降密度比、关表面张力、等效雾团、亚网格口径——都是可接受的手段，但**交付文档里必须写"这是工程假设"**，不能包装成物理结论。
8. **量级先对基线**。结果与既有基线量级不符就报"不符"，**不要替它编一个物理解释把它合理化**。
9. **扩充必须登记**。新增 `references/*.md` 或 `scripts/*.py`，必须在 §12 资源地图 / §4.4 脚本清单里加一行；新增案例卡必须跑 `scripts/check_cases.py` 且零 error。**没被登记的文件，下一个人等于不存在。**

---

## 12 资源地图

**通用参考 `references/`**

| 文件 | 内容 |
|---|---|
| `tui-commands.md` | 全部已验证命令、交互式答案序列、废弃命令对照、VOF/组分启用链路、云图与导出链路 |
| `case-setup-checklist.md` | 逐面板检查单（三分支：可压缩瞬态 / VOF / 组分输运），每项带"为什么" |
| `meshing-routes.md` | 网格路线决策树：Fluent Meshing GUI / gmsh 脚本化 / 复用既有网格；CGNS 导入的三个假崩溃；重导网格后 zone ID 重排陷阱 |
| `troubleshooting.md` | 故障 → 根因 → 处理（A 启动 / B 物理 / C 发散 / D 段错误 / E journal / F 进程 / G 网格 / H 栅格化 / I PyFluent 接口 / J 密度基激波 / K 外部网格 SIGSEGV / L 报表返回 None / M 几何单位缩 1000 倍 / N 非 ASCII 路径 / O 网格尺寸单位 / P 体区域是 solid / Q 写文件静默不覆盖） |
| `auto-resume-and-guard.md` | 长跑启动件、分段续算、看门狗部署、编码陷阱、计划任务闪窗与阻塞式监护 |
| `offline-h5-postprocessing.md` | ⭐ 离线读 `.h5`：结构路径、CSR 展开、面场口径、`SV_VOF` 语义、退化指标识别、足迹渲染 |
| `offline-cells-and-species.md` | ⭐ 离线后处理（组分）：网格/场分离、由 `c0/c1` 反算形心体积、质量→摩尔分数、初始化陷阱、`NaN ≠ 0` |
| `field-export-and-rasterize.md` | 场数据导出 → 切片 → 最近邻 → 阈值 → 去噪 → 宽表/长表 → 逐格校验 |
| `footprint-contours.md` | 轮廓时序提取：面量→节点量、自由边界沿弧闭合（方向写反会静默自交）、双门槛滤波、shoelace 独立校核、固定顶点重采样 |
| `pyfluent-vof-sputtering.md` | PyFluent 编程接口层故障：相材料静默失败、register+patch 顺序、6 核 `wta` 崩溃、`node_value` 错位、内存预算 |
| `s1-foam-slag-vof.md` | 泡沫渣喷溅的完整设置记录：VOF + 能量 + **关表面张力**、多球 register 注入的原始配方、网格分辨不了液块时的取舍 |
| `version-compatibility.md` | 版本边界：什么算"已验证"、换版本最易变的六处及 10 分钟探针判据、版本策略 |
| `wbpj-project-generation.md` | ★ 生成"双击即可看结果"的 `.wbpj`：模板名、`DisplayText`、`Import` 用法、可搬移四步法则、两道判据 |

**案例库 `cases/`** —— 见 `cases/README.md` 索引与 `cases/_TEMPLATE.md` 模板；扩充流程见其 §四；加完跑 `python scripts/check_cases.py` 校验。

**冒烟测试 `tests/smoke/`** —— 换版本 / 换机器时先跑它：3D 矩形管道层流 + 解析解判据，
几分钟内验证"几何→网格→改流体域→拆 zone→认进出口→设边界→求解→取数"整条链路。
两条判据：**连续性 ≤2%**（对网格不敏感，专抓设置错误）+ **峰值比 ±10%**（对网格敏感）。
当前状态与实测数字写在 `tests/smoke/README.md`。

跑之前记住三件事，否则会撞上伪装成"格式坏了"的假故障：
**工作目录必须是纯 ASCII 路径**（中文用户名会让 Meshing 的 CAD 导入器报
"Error in CAD Import"，措辞完全误导）；**网格尺寸用 STEP 声明单位（毫米）**；
**体区域建出来是 `solid`，要先改 `fluid`**。

**脚本 `scripts/`** —— 见 §4.4。
