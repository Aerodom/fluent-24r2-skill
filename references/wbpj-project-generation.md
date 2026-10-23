# 用 Workbench 批处理生成「双击即可打开看结果」的 .wbpj 工程

> 全部结论来自 2026-09-21 在本机（ANSYS 2024R2 / v242）的实测。

> ⚠️ **路径与脚本说明（移植时先读）**
> 文中出现的 `<PROJ>/...` 是**占位符**，代表示例工程的根目录；§5 的参考产物清单与
> §7 的静态体检判据靠它锚定"产物长什么样"。
> 移植到你自己的工程时：把路径换成本项目的输出目录，`make_wbpj.py` 一类驱动脚本需按
> **§3 的最小可运行配方**自行实现——本 skill 不附带该脚本，因为它与你项目的目录约定强绑定
> （帧怎么命名、每帧时刻从哪张 CSV 取）。**核心配方与判据全部在本文，脚本只是壳。**

## 0 适用场景

算例是脚本流水线（PyFluent / fluent.exe 直驱）跑出来的，磁盘上只有
`*.cas.h5` / `*.dat.h5`，用户**无法像 G3/B2/v4 那样双击工程文件看结果**。
本配方把「建 Fluent 系统 → 挂 case → 挂 data → 命名 → 存盘」全自动化，**无头**运行。

## 1 ★★ 五个必踩的坑（按危害排序）

### 坑 1：模板名必须是 `"Fluid Flow with Fluent Meshing"`
```python
tpl = GetTemplate(TemplateName="Fluid Flow with Fluent Meshing")   # ✅ 唯一可用
```
写成下面这些一律报 `项目中未找到模板XXX`：
- `"Fluent"`
- `"Fluid Flow (Fluent)"`
- `"Fluent (with Fluent Meshing)"`   ← 只差几个字，最容易输错

默认系统名是 `FFF`，中文显示名是「流体流动（带有Fluent网格划分功能的Fluent）」。
G3 / v4 工程里的系统目录 `dp0/FLTG/Fluent/` 就是这个模板建的
（`FLTG` = Fluent 工作流系统；目录里有 `Workflow/`、`*.1_workflow_files/` 是它的特征）。

### 坑 2：★ 改系统显示名只能用 `DisplayText`，用 `DisplayName` 会让 journal 静默崩溃
```python
s.DisplayText = "PL_L1"     # ✅ 实测可用
s.DisplayName = "PL_L1"     # ❌ 整个 journal 立刻中止（rc=2）
```
**`DisplayName` 崩溃的表现极具误导性**：rc=2、**该语句之后的全部语句都不执行**、
**且不报任何错**（连 try/except 都不进）。本次为此绕了近 10 轮：
一度误判成「journal 不支持 `for` / 嵌套 `try`」，其实 `for`、`try/except`、
自定义函数、列表推导**全都正常**——真凶只是这一句。

**定位手法**：把日志写成扁平的一行一个标记（`w("01 ...")` / `w("02 ...")`），
哪个标记之后断掉，崩溃点就在哪条语句。别用「整段 try 包住一大片」的写法去排错。

### 坑 3：`Setup.Import` / `Solution.ImportInitialData` 的准确用法
```python
s = tpl.CreateSystem()
c  = s.GetContainer(ComponentName="Setup")
c.Import(FilePath=r"<PROJ>\...\xxx.cas.h5", FileType="Case")        # 案例
c2 = s.GetContainer(ComponentName="Solution")
c2.ImportInitialData(FilePath=r"<PROJ>\...\xxx.dat.h5")             # 数据
```
登记结果（用 `c.GetFiles()` 回读）：
- case → `ContainerAssociations: ["Setup"]`
- data → `ContainerAssociations: ["Solution"]`

**`Setup.Import` 的 `Location` 写绝对还是相对，取决于"源文件在哪"**（★ 2026-09-22 修正）：

| 源 case/data 的位置 | `Location` 写成 | 工程可搬移？ |
|---|---|---|
| 在**工程目录之外**（如 `<PROJ>/PL/v2/results/...`） | `r"<PROJ>/PL\...\x.cas.h5"` 绝对 | ❌ 断链 |
| **先拷进 `<stem>_files\dp0\FLTG\Fluent\`，再 `Import` 这个副本** | `r"$(ProjectName)_files\dp0\FLTG\Fluent\x.cas.h5"` 相对 | ✅ 可搬移 |

⇒ **要交付"拷到别的机器上点开就能算"的工程，正解是先把文件拷进工程内的
`<stem>_files\dp0\FLTG\Fluent\` 再 Import** —— Workbench 自己就会写相对路径，
**不需要事后改 XML**。这与 Workbench 自己建的 G3/v4 完全同形态。
（只挂绝对路径的旧配方省 GB 级磁盘，适用于"本机看结果"。）

另：`Solution` 容器**没有** `Import` 方法 —— 它返回的是 `DataContainerReference`，
只能 `ImportInitialData(FilePath=...)`（挂 data）。挂 case 只走 `Setup`。

### 坑 4：不要用 `s.Duplicate()` 复制系统
`Duplicate()` 能成功（`W.b2` 探针测过），但复制出的系统组件名会变成
`Setup 1` / `Solution 1`，之后 `GetContainer(ComponentName="Setup")` **直接抛错**。
⇒ **每个算例各自 `tpl.CreateSystem()` 一次**（模板可重复 `CreateSystem`）。

### 坑 5：Workbench 侧日志是**控制台代码页（GBK）**，不是 UTF-8
`open(LOG,"a")` 从 journal 里写出来的中文读到会乱码（`Ä£°å` = 模板）。
⇒ journal 里**只写 ASCII 标记**；Python 端读取时 `encoding="gbk", errors="replace"`。
另：journal 里 `open()` **不能带 `encoding=` 参数**（Workbench 内嵌解释器不支持），
异常会被 try 吞掉、日志一个字都不出——这是早期"日志为空"的真因之一。

## 2 可直接复用的系统 / 容器 API（v242 实测 `dir()` 结果）

**System（`tpl.CreateSystem()` 的返回值）关键成员**：
```
AnalysisType  Copy  Delete  DisplayText  Duplicate  GetComponent  GetContainer
Name  Notes  Physics  Refresh  RecreateDeletedComponents  Solver  Type  Update
```
（注意：有 `DisplayText`，**没有** `DisplayName`。）

**各组件容器的方法**：
| 组件 | 关键方法 |
|---|---|
| `Setup` | `Import` `SendCommand` `Edit` `Exit` `GetFiles` `GetFluentLauncherSettings` `GetTGridMeshImportOptions` `CopyLauncherSettings` |
| `Solution` | `ImportInitialData` `SendCommand` `Edit` `Exit` `Continue` `GetFiles` `GetFluentSolutionProperties` `GetSolutionSettings` `MarkUpToDate` `MarkUpdateRequired` |
| `Results` | `Edit` `Exit` `SendCommand` `GetCFDResults` `GetFiles` |
| `Mesh` | 只有 `GetAllParameters` `GetFiles` `Name` `ToString` `Type`（**没有任何 task chain API**） |

⇒ 再次印证 B2 的结论：**Fluent Meshing 的 task chain 无法在 batch 里动态搭**，
必须在 GUI 里预先建好。但**"挂 case/data 看结果"这条路完全不需要 task chain**。

## 3 最小可运行配方

```python
# journal（.wbjn），RunWB2.exe -B -R <journal>
def w(s):
    try:
        f = open(LOG, "a"); f.write(str(s) + "\n"); f.close()
    except Exception:
        pass

def main():
    tpl = GetTemplate(TemplateName="Fluid Flow with Fluent Meshing")
    for disp, case, data in SPECS:                 # 每个算例一套
        s = tpl.CreateSystem()
        s.DisplayText = disp                       # ★ 不是 DisplayName
        s.GetContainer(ComponentName="Setup").Import(FilePath=case, FileType="Case")
        s.GetContainer(ComponentName="Solution").ImportInitialData(FilePath=data)
    Save(FilePath=WBPJ, Overwrite=True)

main()
```
运行：
```bash
export AWP_ROOT242="<ANSYS_INSTALL>"
"/d/Program Files/ANSYS Inc/v242/Framework/bin/Win64/RunWB2.exe" -B -R "<journal>"
```

## 4 交付前必做的回读校核

工程**必须能重新打开**才算成立。用同一套批处理回读：
```python
Open(FilePath=WBPJ)
for s in GetAllSystems():
    w(str(s.DisplayText))
    for c in ["Setup", "Solution", "Results"]:
        w(str(s.GetContainer(ComponentName=c).GetFiles()))
```
判据：
- `Open` 不抛错；
- 每个系统的 `DisplayText` = 预期算例名；
- `Setup.GetFiles()` 非空、`Solution.GetFiles()` 非空，数量 = 算例数（各 1 条）。

`Results.GetFiles()` 为空是**正常的**——Results(CFD-Post) 单元格运行时
从上游 Solution 取 case+data，自身不持有文件。

## 5 本机参考产物（2026-09-21）

| 工程 | 系统（DisplayText） | 说明 |
|---|---|---|
| `<PROJ>/PL/PL.wbpj` | PL_L1 / PL_L2 / PL_L3 | 各挂 `_final.cas.h5` + `_final.dat.h5` |
| `<PROJ>/PG/PG.wbpj`   | PG_G1 / PG_G2 | 同上 |
| `<PROJ>/S1/S1.wbpj`     | S1_v1_t0p02 / S1_v1_final / S1_expC_t0_fixed | ⚠️ 内容是**已判定废弃的 v1**：t=0.02 s 帧（注入缺陷可见）、终态、`expC_union`（修法验证 t=0）。v2 网格跑完后**必须重建** |
| `<PROJ>/S2/S2.wbpj`     | S2_vof_fine_t1250 / t1300 / t1350 | 已验证 VOF 运行的三个存档帧，可做时序对照 |
| `<PROJ>/g3/G3.wbpj`     | FLTG（+Geom） | 历史工程，可直接对照 XML 结构 |
| `<PROJ>/v4/v4.wbpj`     | FLTG（+FFF） | 同上，结构最干净 |
| `<PROJ>/b4/B4.wbpj` | B4_t0p00000s … B4_t0p02005s（7 个系统） | 爆炸模块 2：7 帧时序，见 §9 |
| `<PROJ>/b3/B3.wbpj` | B3_t0p00000s … B3_t0p03005s（10 个系统） | 同上，见 §9 |
| `<PROJ>/b1/B1.wbpj` | B1_t0p00000s … B1_t0p03005s（10 个系统） | 同上，见 §9 |

**多帧写法**：同一个算例想把多个时刻都做成可查看的系统，就**每帧一条 `--sys`**
（帧 N 的 case 必须配**同一帧**的 dat，否则网格/设置不匹配）。这样每个系统的
`Solution` 都有数据，用户点 Results **不会触发"更新"（即不会误启动求解）**。
⚠️ **不要建"只挂 case、不挂 data"的系统**：它的 Solution 单元格是未完成状态，
用户双击 Results 时 Workbench 会提示更新 → 可能拉起 Fluent 真去算。

生成的工程结构：
```
<工程名>.wbpj            # XML，含 FileContainer 文件登记 + Schematic 系统定义
<工程名>_files/
├── dp0/act.dat  dp0/designPoint.wbdp
├── session_files/journalN.wbjn     # Workbench 自动录制的本次操作
└── dpall/  user_files/
```
`.wbpj` 里 `Location` 用 `$(ProjectName)_files\dp0\...` 的内置文件会随工程改名自动跟随，
但**手工 `Import` 进来的 case/data 是绝对路径、不跟随**。

## 6 与本项目其它入口的关系

- **`.flprj`（Fluent 独立工程，`settings.file.parametric_project.new()` 生成）**：
  双击直接进 Fluent，**不依赖 Workbench**。PG 的 `PG_G1.flprj` /
  `PG_G2.flprj` 已与其同目录的 `PG_G?_final.*` 自洽。两条入口可并存，
  `.flprj` 作为 Workbench 不可用时的兜底。
- **`.wbpj`**：用户要的形态（与 G3/B2/v4 一致），也是能出 CFD-Post 的入口。

## 7 批量核验 + 工程 XML 静态体检（2026-09-21 补）

### 7.1 一次核验全部工程
`<PROJ>/tools/wb_verify_all.wbjn` —— 把所有 `.wbpj` 列在 `PROJECTS` 里，
`Open` → `GetAllSystems` → 逐系统打印 `DisplayText` + `Setup/Solution/Results.GetFiles()`，
结果写 `<PROJ>/tools/wb_verify_all.log`。跑法同 §3。
**判据**：`OPEN OK` 且每个系统的 Setup / Solution 都非空。
「全部 6 个工程一次通过」的实测输出可作为后续回归基线。

### 7.2 ★ 解析 `.wbpj` 时**不要用 `json.loads`**
`member-data` 里是**近似 JSON 但不是合法 JSON**：
```json
{"DisplayText": "x.cas.h5", "FileType": $$979eecc4-d82e-4774-9a83-f4f7e2bf3a47, ...}
```
`FileType` 的值是裸的 `$$<guid>`，`json.loads` 必抛 → 若把异常吞掉，
结果就是「FileReference 数 = 0」，**会伪装成"工程里没有引用任何文件"**。
⇒ 用正则取字段：`"Location":\s*r?"(.*?)"` / `"DisplayText":\s*"([^"]*)"`。
另：文件是 **UTF-8 with BOM**；`<FileReference:F1>` 只出现在
`<Object Name="/FileContainer/FileReference:F1">` 的**属性**里，不是 XML 标签。

### 7.3 ⚠️ G3.wbpj 在批处理下打不开（未解决，非缺文件）
`RunWB2 -B -R` 里 `Open(FilePath="<PROJ>/g3/G3.wbpj")` 抛错，且
`traceback.format_exc()` 返回**空串**（C++ 层抛的，没有 Python 帧）。
- 已排除缺文件：静态体检显示 G3 的 **28 个 `Location` 全部存在**。
- 同批 `v4.wbpj`（同样含 `FLTG` Fluent Meshing 系统）**能正常打开** ⇒
  不是"带 Meshing 系统就打不开"，疑似 G3 需要 GUI / 插件上下文。
- ⇒ `-B` 下打不开**不等于** GUI 里打不开；结论待 GUI 双击确认。
  排查时别急着改 G3。

### 7.4 常见误报
参数写错时的表现（易误判成工具坏了）：
```
case 不存在: S1_ckpt_0010.cas.h5      # ← 我误写成相对路径；--sys 必须给绝对路径
```
`make_wbpj.py` 会**在跑 Workbench 之前**就校验 case/data 是否存在并报 `rc=1`，
所以看到这条说明是命令行参数问题，不需要怀疑 Workbench。

## 8. ★★ 交付"可搬移工程"：配方 + 决定性验证（2026-09-22 实测，S1 v2）

场景变了：不再是"本机看结果"，而是**把工程拷到大内存机器上、GUI 里点运行计算**。
脚本：`<PROJ>/s1/work/make_wbpj_s1v2.py`（`gen` / `verify` 两个子命令）。

### 8.1 ★★ 四步法则（顺序不能错，2026-09-30 复现确认）

> **两个最大的坑**：
> ① `dp0/` 下**只有与「系统节点名」同名的子目录才是该系统的家**；
> ② **建工程那一次 `Save()` 会把 `dp0/<系统节点名>/` 下的文件当外来物静默删掉**
>    —— 目录名写对了也照删。

1. **预置**：把 case/data 拷到 `<stem>_files/dp0/<系统节点名>/Fluent/`
   —— 必须先拷，因为 `Setup.Import` 要求文件**存在**（不拷 ⇒ journal 停在 `STEP04` 不动）；
2. **建工程**：journal 里 `CreateSystem` → `Setup.Import(case)` → `Solution.ImportInitialData(dat)`
   → `Save()`。**这一步会把第 1 步拷进去的 case/data 删掉**（正常现象，不是 bug）；
3. **再植入**：`Save()` 之后把 case/data **重新拷回**同一目录；
4. **固化**：再跑一次 `Open()` + `Save()`（模拟用户"打开工程"这一步），确认素材**仍在**。
   实测：建工程之后的 `Open`+`Save` **不会**再清理已登记的素材。

**系统节点名怎么查**：wbpj 里搜 `/Schematic/System:<名>`。
本模板（`Fluid Flow with Fluent Meshing`）用 API 建出来的系统，节点名是 **`FFF`**
（**不是**模板名缩写 `FLTG`）。`v4.wbpj` 这种纯 GUI 工程里同时存在 `FFF` 与 `FLTG`
两个节点，各有自己的 `dp0/<名>/Fluent/`，不要看混。

⚠️ **写错目录名的后果**：素材在 Save 时被删，而 wbpj 里的相对路径照样写得漂漂亮亮
——**最坏的一类失败**（工程看着对、文件没了）。所以第 4 步的"素材存活校验"绝不能省。

不要用字符串替换去"事后改绝对路径"——**先拷进工程目录再 Import 就能自动拿到相对路径**，
比改 XML 稳得多（改 XML 只在别处已有绝对路径工程时才作为兜底）。

### 8.2 journal 里真正存在的 API 面（`RunWB2 -B` 的批处理解释器）

用 `globals().keys()` 一次性打出来过（约 900 个名字）。**没有** `GetProject` / `GetSystems`。
已验证可用的：

```python
Open(FilePath=...)                 # 打开工程
GetProjectDirectory()               # -> '<OUT_DIR>\_port_test\S1'
GetAllSystems()                     # -> ['/Schematic/System:FFF']
GetAllFiles()                       # ★ 全部已登记文件的**解析后绝对路径**列表
GetMessages()                       # -> []  工程消息（缺文件会在这里冒出来）
CheckProjectConsistency()           # -> None
GetTemplate(TemplateName=...)  CreateSystem()  Save()  Archive  Unarchive
GetSystemForComponent / GetContainerForComponent / GetFilesForContainer ...
```

### 8.3 ⚠️ 批处理解释器会**静默吞掉某些调用**

同一段 journal 里，`GetSystem(Name=...)`、`GetProjectFiles()`、`IsFileRelative(...)`、
`Archive(FileName=...)` 的日志行**凭空消失**（后续语句照常执行、`V99 done` 照常打印）。
⇒ 排查时**每条调用前后各写一条日志并带序号**（`w('>> 03 xxx')` / `w('<< 03 ...')`），
靠**序号缺口**判断哪条被吞了。只写"结果行"会误以为代码没跑到。

### 8.4 ★ 可搬移性的**决定性**判据（比"能打开"强得多）

`Open()` 不抛错 ≠ 文件引用解析成功。真正的判据是：

```
① 把 <stem>.wbpj + <stem>_files/ 拷到一个**不同的绝对路径**（如 <OUT_DIR>/_port_test/S1/）
② 无头 Open 该副本
③ GetAllFiles() 返回的路径必须落在**新位置**下（说明 $(ProjectName) 按新工程目录展开了）
④ GetMessages() == []
```

实测输出（S1 v2）：
```
01 GetProjectDirectory OK -> <OUT_DIR>\_port_test\S1
04 GetAllFiles OK -> ['<OUT_DIR>\\_port_test\\S1\\S1_files\\dp0\\FFF\\Fluent\\S1v2_t0.cas.h5',
                      '<OUT_DIR>\\_port_test\\S1\\S1_files\\dp0\\FFF\\Fluent\\S1v2_t0.dat.h5',
                      '<OUT_DIR>\\_port_test\\S1\\S1.wbpj', ...]
09 GetMessages OK -> []
```
注意 `Error` 这一条也存在于 `_wb_verify.out` 的 stdout 里，属正常。

### 8.6 ★ 交付前必须全绿的**静态判据**（纯离线，秒级，不开 Workbench）

光看"`Location` 是相对路径"不够——**要同时钉死"挂在哪个容器上"**。
把下面这组做成机器可判的清单（`make_wbpj_s1v2.py::static_check`），任一条 FAIL 就不许交付：

| # | 判据 | 用正则/字符串从 wbpj 里取 |
|---|---|---|
| 1 | 相对路径 ≥ 2 处、**绝对路径 = 0 处** | `t.count("$(ProjectName)_files")` / 正则 `[A-Za-z]:[\\/]` 命中数 = 0 |
| 2 | **case 挂在 `Setup`** | `"S1v2_t0.cas.h5".*?ContainerAssociations":\s*\["Setup"\]` |
| 3 | **dat 挂在 `Solution`** ★ 最关键 | `"S1v2_t0.dat.h5".*?ContainerAssociations":\s*\["Solution"\]` |
| 4 | 系统显示名 = 你要的 | `"DisplayText": "<SYSNAME>"` |
| 5 | 系统类型正确 | `Fluent with Fluent Meshing` |
| 6 | 系统目录名与 `dp0/<名>/` 一致 | `"UniqueSystemDirectoryName": "FFF"` |
| 7 | ★ **`"Start from available data": "True"`** | 决定点运行时**会不会用现成的 dat 当初值** |
| 8 | 素材实体在位且体积合理 | `os.path.getsize(dp0/FFF/Fluent/*.h5)` |

**第 3 与第 7 条是"点一下就能算"的命门**：
少了任何一条，用户点运行就从**冷态**（初始场全 0）开始算——白跑十几小时才发现。
判据 7 来自系统 XML 的 `Attributes`：

```json
"Attributes": { "PhysicsTypeDisplayString": "流体",
                "Start from available data": "True",
                "SolverTypeDisplayString": "FLUENT", "IsCreated": "True" },
"SystemType": "Fluid Flow (Fluent with Fluent Meshing)",
"DisplayText": "S1_v2_FoamSlag",
"UniqueSystemDirectoryName": "FFF"
```

**同一条 `static_check()` 要在两个目录各跑一遍**：交付目录 + **拷贝后的副本目录**
（后者才能证明判据跟着工程走，而不是我这边环境碰巧满足）。

### 8.7 交付包里要不要带 `session_files/journal*.wbjn`

`<stem>_files/session_files/journal*.wbjn` 是 Workbench 自动写的**操作记录**
（原生 GUI 工程 v4 里也有 5 个）。它们**不是**加载工程所必需，
内容却是本机的绝对路径 journal。交付"拷到别机运行"的包时**建议排除**：
一是无意义，二是容易被用户误当成"要我跑的脚本"。
实测：排掉之后工程照样能打开、引用解析正常、`GetMessages() == []`。

### 8.5 其它实测结论

- **`Open()` 在 `-B` 批处理下是能成功的**（S1 v2 副本可以）。
  所以 §7.3 里 G3 批处理打不开**不是**"带 Fluent Meshing 系统就打不开"，
  是 G3 这个工程自身的个别问题，别拿它当通则。
- **系统节点 key 显示成 `FFF` 是正常的**：那是该模板的默认系统名
  （见 §1 坑 1）。`v4.wbpj` 这种纯 GUI 工程里同样有 `/Schematic/System:FFF`。
  GUI 里显示的是 `DisplayText`，所以设了 `s.DisplayText = "S1_v2_FoamSlag"` 就够。
- **工程目录改名要注意**：`$(ProjectName)` 展开成 **`.wbpj` 的文件名（不含扩展名）**，
  所以要连 `<stem>_files/` 一起改；**`S1.wbpj` 不要单独改名**，否则找不到 `S1_files`。
  顶层目录名随便改（`_files` 是它内部固定的子目录名）。
- 交付前清掉 `S1_files/.lock`（残留锁会让 GUI 报"工程已被占用"）。

## 9. ★ 三个爆炸算例的落地 + 四条新实测（2026-10-10）

B4 / B3 / B1 此前只有 `*.cas.h5` / `*.dat.h5`，没有工程入口（用户明确要求补）。
用本配方一次补齐，**全流程无头、不开 GUI、不复制 GB 级数据**。

### 9.1 工具链（已落盘，可直接复用）

| 文件 | 作用 |
|---|---|
| `<PROJ>/tools/make_wbpj.py` | 主力：journal 生成 + 无头 RunWB2 + `STEP09 done` 判据 |
| `<PROJ>/tools/make_wbpj_b134.py` | **批量驱动**：从监控 CSV 自动取每帧精确时刻 → 拼 `--sys` → 逐个调 `make_wbpj.py` |
| `<PROJ>/tools/wb_static_check_b134.py` | **纯离线静态体检**（秒级，不启 WB）：Location 存在性 / 挂载容器 / 系统名 |
| `<PROJ>/tools/wb_verify_b134.wbjn` | **无头回读核验**：`Open` → `GetAllSystems` → 逐系统 `Setup/Solution.GetFiles()` |

**帧命名约定**（沿用 S1 的 `t0p02` 风格）：`<场景>_t0p<5位秒>s`，如 `B4_t0p01285s` = t = 0.01285 s。
**步 → 时刻**：`results/<S>_monitor_clean.csv` **首列就是 `time_s`**，
**行 i 对应 step i+1** ⇒ `t = times[step-1]`。**不要手算 dt 斜坡**（斜坡切换点不在整数步上，
手算 B4 的 step80 会得到 0.005 而真值 0.00485）。

### 9.2 实测结果（全部核验通过）

| 工程 | 系统数 | 帧（step → t / s） | 无头回读 |
|---|---|---|---|
| `<PROJ>/b4/B4.wbpj` | 7 | 0→0 / 40→0.00100 / 80→0.00485 / 120→0.00885 / 160→0.01285 / 200→0.01685 / 232→0.02005 | OPEN OK；7/7 全 `Setup=1 Solution=1`；`GetMessages=[]` |
| `<PROJ>/b3/B3.wbpj` | 10 | 0 / 40 / 80 / 120 / 160 / 200 / 240 / 280 / 320 / 332→0.03005 | 同上（10/10） |
| `<PROJ>/b1/B1.wbpj` | 10 | 步号同 B3 | 同上（10/10） |

### 9.3 ★ 新坑 A：`case` 引用被**按路径去重**，静态判据别写"case 数 = 系统数"

B4 有 7 个系统，但 wbpj 里 **case 引用只有 4 条** —— 因为 `B4_auto-3.cas.h5`
（autosave 的 case，**不带步数、覆盖写**）被 4 帧共用，Workbench 只登记一条 `FileReference`。

⇒ 判据落在 **`data`（每帧一份、不去重）**：`data 引用数 == 系统数`；
`case 引用数` 只要求 `≥1` 且**无重复登记**。
按"case 数 = 系统数"写会**误报 FAIL**（本次先踩了一次）。

### 9.4 ★ 新坑 B：`-B` 批处理下**不能真让 Fluent 读 case**（`Edit()` 必失败）

想省掉"用户手动 File→Read Case"，试过 batch 里 `setup1.Edit()` +
`SendCommand('/file/read-case "…"')`，**两种系统都失败**：

| 系统 | `Edit()` 结果 |
|---|---|
| 全新建、不 Import | `Exception('在保存时，FLUENT中发生错误')`（18.6 s） |
| 先 `Import` case 再 Edit | `Exception('保存模型信息时，FLUENT中发生错误')`（53.3 s） |

⇒ **不是 Import 引起的**，是 batch 模式本身没有 Fluent 的图形/消息通道
（launcher 默认 `ShowLauncher=True`、`EmbedGraphicsWindows=True`）。
**结论：批处理只负责"建系统 + 登记引用"；要真读一遍 case 必须走 GUI。**
别在 batch 里绕这一步。（顺带：`Edit()` 会真的拉一堆 `fluent.exe`/`cx2420.exe`/`fl_mpi2420.exe`
残留，失败后必须按 §10 铁律用 `subprocess.run(["taskkill","/F",…])` 清干净再干别的。）

### 9.5 另一组可用模板名（2024R2 实测 `GetTemplate`）

| 模板名 | 得到 | 组件 |
|---|---|---|
| `Fluid Flow with Fluent Meshing` | `/Schematic/Template:FLTG`，系统节点 `FFF` | Setup / Solution / Results |
| `FLUENT` | `/Schematic/Template:FLUENT`，`/Schematic/System:FLU` | **只有 Setup / Solution** |
| `Fluid Flow` / `Geometry` / `Mesh` | 存在 | — |
| `FLU` / `Fluent` / `FluentMeshing` / `Meshing` / `Fluid Flow (Fluent)` | **不存在**（报"项目中未找到模板X"） | — |

`GetFileType(Name=…)` 已注册的名字：`CFFCase` `CFFData` `CFFMesh` `FLUENTCase` `FLUENTData`
`FLUENTMesh` `FLUENTBc` `ACTDatabase` `project`。
`Setup.Import` 的 `FileType` 参数：**`"Case"`（本配方）与 `"CFFCase"` 都能过**；
`"FluentCase"`（大小写不对）报 `不能将值…从String转换为FileType`；
传 `GetFileType(...)` 返回的 DataReference 报同样的错 ⇒ **这个参数要字符串**。

### 9.6 无头跑 RunWB2 的日志可能是空的

`RunWB2.exe -B -R x.wbjn > x.log 2>&1` 得到的 `x.log` **可能 0 字节**
（输出走了 WB 自己的通道）。判活/判错只能靠 **journal 里自己写文件打序号标记**
（`open(TR,"a")`）；失败时 **rc=2，且标记在崩溃语句处断掉** —— 靠"标记缺口"定位，
不要靠 rc（有几条调用会被静默吞掉，见 §8.3）。
另：WB 侧日志按 **GBK** 落盘，读取要 `encoding="gbk", errors="replace"`。

