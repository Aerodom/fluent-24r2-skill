# Fluent 2024R2 TUI 命令参考（实测）

标注说明：

- **[实测]** = 在本项目算例中实际跑通。
- **[废弃]** = 本版报 `invalid command`，不要用。
- **[未测]** = 未在本项目验证，使用前先探针。

---

## 1. 文件与网格

| 命令 | 状态 | 说明 |
|---|---|---|
| `/file/read-case "x.msh.h5"` | [实测] | 读网格用 read-case，**不是** read-mesh |
| `/file/read-case "x.cas.h5"` | [实测] | 读算例 |
| `/file/read-data "x.dat.h5"` | [实测] | 读数据，需先读对应 case |
| `/file/read-case-data "a.cas.h5" "b.dat.h5"` | [废弃] | 双文件语法报错 `invalid "F:`，必须拆两步 |
| `/file/write-case "x.cas.h5"` | [实测] | 已存在时提示覆盖，journal 下一行写 `ok` |
| `/mesh/check` | [实测] | 检查网格，看最小体积是否为正 |

## 2. 几何缺陷修复

```text
/define/boundary-conditions/zone-type 714 interior
```

- **[实测]** zone 名若含冒号（`air_ambient:1:707`），TUI 无法识别，**必须用整数 ID**。
- wall → interior 时若两 wall 被缝合，提示 `wall A and wall B sewn together` 属正常。
- **副作用（重要）**：该操作会**修改网格**。之后 autosave 的 data 与原始 `.msh.h5` 不再匹配，续算会报 `The mesh has been modified`。故改完必须立刻 `write-case`。

## 3. 求解器与模型

| 命令 | 交互答案 | 状态 |
|---|---|---|
| `/define/models/solver/density-based` | `no`（隐式） | [实测] |
| `/define/models/energy yes` | `no` `no` `no` `yes` | [实测] |
| `/define/materials/change-create air air yes ideal-gas` | 6 个 `no` | [实测]，会自动启用能量方程 |
| `/define/models/unsteady-2nd-order` | `yes` | [实测]，提示 Pressure-Velocity Coupling=SIMPLE |

说明：可压缩激波案例必须密度基 + 理想气体；理想气体密度按 `rho = p/(R*T)` 更新，这是高压气膨胀产生冲击波的物理核心。

### 3.1 VOF 多相流（液体泄漏 / 熔体泄漏 / 熔体喷溅 / 自由液面）

压力基 + VOF。有限液块类案例用 patch 注入（不是连续入口），连续泄漏类用质量流入口。

| 项 | 命令/取值 | 备注 |
|---|---|---|
| 求解器 | 压力基（默认，**不要**切 density-based）+ 瞬态 | VOF 走压力基 |
| 多相流模型 | Multiphase → **VOF**，**Implicit**（隐式） | 显式对高密度比不稳 |
| 相设置 | 主相 air；次相按实际（acid / slag / 熔体） | `material` 是交互式命令，**缺 `yes` 会静默失败** |
| 表面张力 | **CSF (Continuum Surface Force)**，σ 按物性；Bo ≫ 1 时建议关 | 高密度比下 CSF 会寄生流速导致发散 |
| 粘性 | 层流（首版）或 Realizable k-ε | 车间静止空气下层流合理 |
| 重力 | **按实际轴向**（如 Y = −9.81），**隐式体积力 (Implicit Body Force) 必须开启** | 密度比 2857:1 这类不开会界面压力震荡；默认轴向是 Z，极易设错 |
| 压力-速度耦合 | **PISO** | |
| 梯度 | Green-Gauss Node-Based | |
| 压力离散 | PRESTO! 或 Body Force Weighted | |
| **体积分数离散** | **Compressive 或 Modified HRIC** | ⚠️ 二次迎风会糊界面 |
| 动量离散 | 二阶迎风 | |
| 时间步 | 1e-3 ~ 2e-3 s（受 CFL + 表面张力双约束）；有限液块起步用 1e-4 斜坡 | 实测：1e-4×100 步 → 5e-4 |

> 密度比 > 1000 时若稳定性过不去：先降密度比（如 ρ=1000）把流程调通，再上真实物性。

### 3.2 组分输运（有毒/可燃气体、烟气扩散）

压力基 + Species Transport + 湍流。比 VOF 简单（无相界面），输出直接是 `molef-<组分>`。

| 项 | 命令/取值 | 备注 |
|---|---|---|
| 求解器 | 压力基 + 瞬态 | |
| 组分模型 | **Species Transport**，开 volumetric reactions = no（纯扩散） | |
| 混合物材料 | mixture-template；**差减组分用 `air`**（`{so2, air}`） | ⚠️ last_species 会被填 1，写错则全域初始化成纯氮气 |
| 湍流 | **Realizable k-ε**（或 SST k-ω） | 远场浓度对模型不敏感 |
| 重力 | 视需要（重气扩散必须开，Y = −9.81） | SO₂ 密度大于空气 → 下沉 |
| 标量变量名 | `molef-so2`（导出与云图都用这个名） | 大小写敏感 |
| 时间步 | 5e-3 s | 十秒级过程（实测 2262 步 = 11.31 s） |

## 4. 初始化与 patch

```text
/solve/initialize/set-defaults/pressure 101325
/solve/initialize/set-defaults/temperature 298
/solve/initialize/set-defaults/x-velocity 0
/solve/initialize/set-defaults/y-velocity 0
/solve/initialize/set-defaults/z-velocity 0
/solve/initialize/initialize-flow
```

patch（**交互式，逐行输入**）：

```text
/solve/patch
707          <- zone ID
()           <- 空括号结束 zone 列表
pressure     <- 变量名
3600000      <- 值
```

同一方式再 patch 一次 `temperature` → `493`。

- **[实测]** 本项目用的是 `/solve/initialize/set-defaults/*` + `initialize-flow` 组合，而非 GUI 的 "Compute from"。
- **gauge/absolute 口径**：`pressure` 字段为**表压**（相对 Operating Pressure，默认 101325 Pa）。釜内如需绝对 3.6 MPa，填 **3600000** 为表压口径下对应 3.7 MPa 绝对——务必与所用案例口径统一，填错会导致超压曲线整体偏移一个大气压。
- 若 patch 后出现 `absolute pressure limited to 1.0 in N cells`，说明该区被限压，需核实环境区初值是否被误覆盖。

## 5. 求解

| 命令 | 说明 |
|---|---|
| `/solve/set/time-step 0.0005` | [实测]，**必须在切到瞬态之后**执行 |
| `/solve/dual-time-iterate 200 20` | [实测]，200 时间步 × 每步最多 20 内迭代 |
| `/file/auto-save/data-frequency 200` | **[实测]** 每 N 步存一个 data |
| `/file/auto-save/root-name "<正斜杠绝对前缀>"` | **[实测]** 保存前缀；不设会落到工作目录 |
| `/file/write-data "<path>.dat.h5"` | **[实测]** 主动存一个 checkpoint |

autosave 文件命名：`<root>-<caseid>-<step>.dat.h5`，如 `b2_trans-1-00005.dat.h5`。单文件可达 268 MB（126 MB 网格 + 约 25 个场），40 帧约 10 GB，注意磁盘余量。

**分段续算的固定组合**（G3 实测跑通 2262 步）：

```text
/file/read-case "<setup.cas.h5>"       ← 改过 zone 后重新 write-case 的那个
/file/read-data "<latest>.dat.h5"      ← 最新 checkpoint
/file/auto-save/data-frequency 200
/file/auto-save/root-name "<前缀>"
/solve/dual-time-iterate <N> 20
/file/write-data "<target>.dat.h5"
/exit
```

细节与看门狗部署见 `auto-resume-and-guard.md`。

## 6. 测点采样

### 6.1 废弃命令（不要用）

| 命令 | 结果 |
|---|---|
| `/report/surface-integrals/vertex-avg` | [废弃] invalid command |
| `/report/surface-integrals/facet-avg` | [废弃] |
| `/report/surface-integrals/area-weighted-average` | [废弃] |
| `/report/surface-integrals/vertex_avg` | [废弃] |
| `/report/surface-integrals/area` | 有效，但需交互式输入，journal 单行传参不可靠 |

官方 v242 文档列出的这些子命令与本机 build 10192 实际不符。

### 6.2 可用方案（datamodel 驱动）

```text
/surface/point-surface p5 6.75 0 0
/solve/report-definitions/add mon_p5 surface-vertexavg field pressure surface-names (p5) q q q
/solve/report-files/add mon_file report-defs (mon_p5 mon_p10 mon_p20) frequency 1 frequency-of time-step file-name "path/monitor_p_1_1.txt" q q
```

- 末尾的 `q q q` / `q q` 是逐层退出交互提示，不可省。
- **只在后处理阶段创建 point-surface**。求解 journal 里出现 point-surface 会触发段错误：

```text
Update_Boundary_Velocity -> porous_interface_mom_source -> SIGSEGV
```

- 输出为绝对压力 Pa，超压 = 值 − 101325。

### 6.3 监控文件的实际格式（实测）

```text
"mon_file"
"Time Step" "mon_p5 etc.."
("Time Step" "mon_p5" "mon_p10" "mon_p20" "flow-time")
0 101325.015625 101324.9375 101325.015625 0
1 101325.015625 101324.9375 101325.015625 0.0005
2 101325.015625 101324.9375 101325.015625 0.001
```

注意 **`flow-time` 在最后一列**，压力列在中间。**不要按位置猜列**——第三行的带引号表头才是权威。
`scripts/monitor_to_csv.py` 已按此实现（读表头定列），并顺带给出"全程峰值 / 前 60% 窗口首峰 / 到达时间"三个量。

### 6.4 场数据批量导出（`/file/export/ascii`，**实测**）

导出**单元中心**场值（`molef-so2` / `pressure` / 相体积分数），是栅格化数据接口的源头。

```text
/file/read-case "case.cas.h5"

/file/read-data "frame_00000.dat.h5"
/file/export/ascii "<CASE_DIR>/export/so2_00000.xyz"
()
no
molef-so2
()
yes

/file/read-data "frame_00200.dat.h5"
/file/export/ascii "<CASE_DIR>/export/so2_00200.xyz"
()
no
molef-so2
()
yes

/exit
```

**交互提示原文**（必须逐行给答案）：

```text
> /file/export/ascii "<PROJ>/g3/export/so2_00000.xyz"
Surfaces(1) [()] ()                        <- 空 = 全部
Delimiter/Comma?, if comma not chosen,
space is assumed to be the delimiter [no] no
ASCII scalar(1)> molef-so2
ASCII scalar(2)> ()                        <- 空 = 结束变量列表
Location/Cell-Centered?,
-if Cell-Centered not chosen, node values of scalars are reported [no] yes
```

要点：

- **`Location/Cell-Centered?` 必须回答 `yes`**。选 no 会输出**节点插值值**，节点数 ≠ 单元数，栅格化对不上。
- `Delimiter/Comma?` 回答 `no`（空格分隔）。
- 一次可导出多个变量：在 `ASCII scalar(1)`、`(2)`… 依次输入，最后用 `()` 结束。列序与输入顺序一致。
- 输出表头固定为 `cellnumber x-coordinate y-coordinate z-coordinate <变量名>`。
- **数据行数 = 网格单元数**（G3 实测 74796）——用这一条做数据溯源自检。
- **read-case 一次、read-data 逐帧**，全在一个会话内串行完成最快。13 帧耗时分钟级。
- 批量生成用 `scripts/export_field_journal.py`。

## 7. 云图渲染

### 7.1 最小可用命令链（已端到端跑通，产出正确填色云图）

```text
/file/read-case "case.cas.h5"
/display/set/picture/x-resolution 1600
/display/set/picture/y-resolution 900

/file/read-data "frame_00020.dat.h5"
/display/surface/plane-point-n-normal pl_00020 0 0 0 0 1 0
/display/set/contours/surfaces (pl_00020)
/display/contour
pressure
0
600000
/display/re-render
/display/save-picture "<OUT_DIR>/pic_00020.png"

...（下一帧重复 read-data 之后的部分）...
/exit
yes
```

三条结构性的结论，都是实测得来：

1. **每帧 read-data 之后重建切面，且切面名逐帧唯一**（`pl_00020`、`pl_00080` …）。整段只建一次切面的写法不可靠。
2. **`/display/re-render` 每帧必加**，否则多帧循环时第二帧起 `save-picture` 抓到的是上一帧画面。
3. **不要写 `/display/set/contours/filled-contours yes` 和 `/display/set/contours/node-values yes`**。这两个菜单项**不接受行内参数**，参数会被当成独立命令报错；而它们的默认值本来就是 yes（填色 + 节点平滑），删掉这两行后输出图像完全不变——实测删前删后 PNG 字节数、色彩分布完全一致。详见 7.4。

### 7.2 命令状态表

| 命令 | 状态 | 说明 |
|---|---|---|
| `/display/surface/plane-point-n-normal` | [实测] | 点 + 法向；**连字符**，下划线写法报错 |
| `/display/surface/plane-points` | [未测] | 三点定面（备选） |
| `/display/surface/list-surfaces` | [实测] | 确认切面已创建（会报点/面片数） |
| `/display/set/contours/field` | [废弃] | 此层级在 24.2 不存在 |
| `/display/set/contours/range/option` + `min`/`max` | [废弃] | 旧路径已废 |
| `/display/set/contours/surfaces` | [实测] | 参数为括号列表 `(pl_01)`，**行内传参有效** |
| `/display/set/contours/filled-contours` | 不接受参数 | 行内写 `yes`/`no` 均无效且报错；默认即填色，通常无需设置 |
| `/display/set/contours/node-values` | 不接受参数 | 同上；默认即开启 |
| `/display/set/picture/x-resolution` / `y-resolution` | [实测] | **行内传参有效** |
| `/display/contour` | [实测] | **交互式**：变量名 → min → max |
| `/display/re-render` | [实测] | **每帧必加**，否则多帧循环只抓到上一帧 |
| `/display/save-picture "x.png"` | [实测] | 路径用正斜杠 |

### 7.3 交互式提示（转录原文）

```text
> /display/contour

contours of> pressure
minimum value (in [Pa]) [11178.40308531618] 0
maximum value (in [Pa]) [328370.6327069692] 600000
```

- 变量名在 `contours of>` 处输入。
- min/max 提示里方括号内是**当前自动范围**。直接回车接受自动范围；输入数值则固定色标。**做多帧对比时必须固定 min/max**，否则每帧自动缩放会让不同时刻的颜色不可比。

### 7.4 行内参数被忽略：`Overwrite confirmations` 告警

现象：日志出现

```text
Overwrite confirmations (/file/set-batch-options ...)
are on -- will therefore ignore the following journal
Error: invalid command: yes
```

含义：该行命令之后的多余参数被 Fluent 当作**另一条命令**，因此忽略并报错。

`/file/set-batch-options` 的三个提示（实测）：

```text
> /file/set-batch-options
Do you want to confirm overwrite? [yes]
Do you want to exit on error? [no]
Do you want to hide questions? [no]
```

**结论：不要为了消除这条告警去关闭覆盖确认。** 实测对比：

| 覆盖确认 | 遇到行内多余参数时 | 后果 |
|---|---|---|
| 开启（默认） | 输出 `will therefore ignore the following journal` 告警 | journal **继续执行**，图像正常产出 |
| 关闭 | 输出 `Error: invalid command` + `An error or interrupt occurred while reading the journal file` | journal **直接中断**，后续命令不再执行 |

正确做法是从源头避免给不接受参数的菜单项写行内参数。

多帧渲染的 pitfall 汇总：

1. 缺 `re-render` → 第二帧起 save-picture 抓到的是旧画面（常见表现为"只有网格没有云图"，因为首次渲染的是网状图）。
2. 每帧重启 Fluent → 极慢。8 帧单会话串行约 2 分钟。
3. 图片内容校验：用 PIL 统计饱和彩色像素占比（>3% 基本可确认是填色云图），比肉眼更可靠：

```python
from PIL import Image
im = Image.open(p).convert('RGB').resize((160, 90))
px = list(im.getdata())
sat = sum(1 for r, g, b in px if max(r, g, b) - min(r, g, b) > 60)
print(round(100 * sat / len(px), 1), '%')
```

## 8. 退出

```text
/exit
yes
```
