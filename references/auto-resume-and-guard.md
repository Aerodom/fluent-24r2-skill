# 长时求解：分段续算与看门狗部署

> 问题：以 G3 这类的组分输运算例为例，要跑 **11.31 s 物理时间 / 2262 步**，本机 `-t4` 约 **6.6 秒/步** → 单次约 4 小时。
> 而通过后台方式拉起的 `fluent.exe` **会随 agent 会话结束被一起杀掉**，长任务必然中途断。
>
> 解法：**分段续算 + 看门狗自动接力**。每次只跑 400~700 步就主动存档退出，
> 由看门狗周期性检查并接力下一段。天然容忍被杀、崩溃、掉电。

---

## 1. 核心思路

```
[autosave 每 200 步一个 checkpoint]
        ↓
看门狗（每 5 分钟触发一次）
   ├─ fluent.exe 在跑？ → 跳过，什么都不做
   ├─ 最新 step ≥ 总步数？ → 调后处理出图，收工
   └─ 否则 → 生成续算 journal → 脱离会话启动 Fluent 续 ≤600 步 → 退出
        ↓
（下一轮触发时 Fluent 可能已被杀，看门狗再接力）
```

三个设计要点：

1. **Fluent 用 DETACHED_PROCESS 启动**，独立于脚本进程；脚本退出后 Fluent 继续跑。
2. **每段主动限步退出**，让 checkpoint 落盘，避免"跑一半被杀什么都不剩"。
3. **看门狗幂等**：先查 `fluent.exe` 是否在跑，在跑就跳过——这是防"重复触发导致两实例并发、内存耗尽"的关键。

---

## 2. 长跑启动：**先问一句"启动者是谁"**（2026-10-01 重大更正）

> ★ **本节旧结论已作废，别再用。** 旧版写"DETACHED_PROCESS 让 Fluent 完全脱离当前
> 进程树，脚本退出后继续运行" —— 这只在**启动者本身是正常进程**（用户手动、计划任务）
> 时成立。若启动者是 **Agent 的工具会话**（Bash/PowerShell 工具调用），
> **四种"脱离"方式全部实测被杀**：

| 启动方式 | 同一次调用内 | 跨调用（换一次工具调用） | 结论 |
|---|---|---|---|
| `Popen(..., DETACH_PROCESS\|CREATE_NEW_PROCESS_GROUP)` | ✔ 25 s 起 8×`fl_mpi2420.exe` | ✘ 已死 | **无效** |
| 上者再加 `CREATE_BREAKAWAY_FROM_JOB`(0x01000000) | ✔ 同上 | ✘ 已死 | **无效** |
| `os.startfile(bat)`（ShellExecute，等同双击） | ✔ 日志已到"开始求解" | ✘ 死（连 `cmd.exe` 一起收走） | **无效** |
| `Popen([r"C:\Windows\explorer.exe", bat])` | ✘ 根本没起 | — | **无效** |

**机制**：工具调用结束时按**进程树**回收本次调用创建的全部进程；强杀
（`TerminateProcess`）**不 flush 输出缓冲** ⇒ 日志里只剩调用前写的行，
**看起来像"脚本没跑"，实际是"跑起来又被收走"** —— 极易误判成脚本有 bug
（本次就白查了 20 分钟）。

**判据**：启动后**必须另起一次工具调用**再查进程。
同一次调用内查永远是健康的，**不能作为存活证据**。

**正确做法（二选一）**：
1. **让用户双击 bat**（本机首选，见 §2.1）；
2. 提前注册 Windows 计划任务 —— 但**必须提前想好清理路径**：本机 `schtasks.exe`
   已被安全策略拉黑，注册完**自己删不掉**，只能留尾巴请用户手动删（惨痛教训）。
   `Start-ScheduledTask` 还可能重复触发，实例数看 `cx2420.exe` 数量。

---

## 2.1 双击 bat：本机长跑的标准启动件（2026-10-01 实测跑通）

四条要点，缺一就出"乱码 / 零输出 / 一闪而过"：

1. **bat 文件存成 GBK（cp936），不是 UTF-8。** 本机 cmd 默认 `chcp 936`，
   UTF-8 的中文行会被按 GBK 解析 ⇒ 命令行错乱 ⇒ python 起不来
   **而且 bat 自己不报错**（窗口停在 `pause`，无从判断）。
   ```python
   io.open(path, "wb").write(txt.replace("\n", "\r\n").encode("gbk"))
   ```
2. **bat 里设 `S1V2_TEE=<日志文件>`，让脚本 `log()` 双写**（print + 写文件）。
   前台跑时 stdout 是控制台，`init_stdio()` 那句"stdout is None 才开日志"不触发
   ⇒ 日志一片空白：**用户看得见、Agent 查不到**，出问题只能猜。
   在 `log()` 里加 `_TEE.write(msg+"\n"); _TEE.flush()` 即可，不设该变量时零影响。
3. **bat 前台跑**（`python.exe run_xxx.py ...`，**不要**在 bat 里再套一层 detach）：
   窗口 = 可见进度，关窗口 = 停止，再双击 = 从最新存档帧续算。这也正是用户要的形态。
4. 末尾 `pause`，否则窗口一闪而过看不到报错。

**Agent 侧启动后的自检三项**（下一次工具调用里做）：
`fl_mpi2420.exe` 进程数、日志 mtime 是否在推进、日志末行是否已到"开始求解"。

---

## 3. 续算 journal 的固定结构

```text
; 续算：step <latest> -> <target>
/file/read-case "<setup.cas.h5>"          ← 必须是改过 zone 后重新 write-case 的那个
/file/read-data "<latest>.dat.h5"         ← 最新 checkpoint
/file/auto-save/data-frequency 200
/file/auto-save/root-name "<前缀>"
/solve/dual-time-iterate <N> 20
/file/write-data "<target>.dat.h5"
/exit
```

四个必须记住的点：

1. **`read-case` 指向 `_setup.cas.h5`（改过 zone 之后存的）**，不是原始 `.msh.h5`。否则报 `The mesh has been modified. Previously saved data files are incompatible`。
2. **二阶瞬态从单帧 data 续算会报 `Update_Time_Level: invalid data`**（缺 N−1 时间层）。若遇到：从 write-case 的 case 配合**连续两帧** data 载入，或该段改一阶重启。
3. **`/file/auto-save/root-name` 用正斜杠绝对路径**，否则 checkpoint 会落到工作目录。
4. **路径统一正斜杠**：Fluent journal 在 Windows 下对混合斜杠敏感。

---

## 4. 看门狗脚本骨架

`scripts/auto_resume.py` 是可直接改用的版本。核心逻辑：

```python
_pat = re.compile(r"(\d+)\.dat\.h5$")

def latest_step(fix_dir):
    steps = [int(_pat.search(f).group(1))
             for f in glob.glob(os.path.join(fix_dir, "*.dat.h5"))
             if _pat.search(f)]
    return max(steps) if steps else 0

def fluent_running():
    out = subprocess.check_output('tasklist /FI "IMAGENAME eq fluent.exe" /NH', shell=True)
    return b"fluent.exe" in out

def main():
    if fluent_running():
        return                                   # ★ 幂等保护，不要删
    latest = latest_step(FIX_DIR)
    if latest >= TOTAL_STEPS:
        subprocess.call(post_script)             # 跑完 → 自动出图
        return
    run_steps = min(SEG_STEPS, TOTAL_STEPS - latest)
    ...生成 journal...
    subprocess.Popen(cmd, shell=True, cwd=WORK_DIR, creationflags=DETACH_FLAGS)
```

**checkpoint 文件名兼容**：本项目的命名曾出现过 `G3_fix-00000.dat.h5` 与 `G3_fix-2-00XXX.dat.h5` 两种，正则用 `(\d+)\.dat\.h5$` 取**最后一段数字**即可同时兼容。

---

## 5. 参数取值经验

| 参数 | 取值 | 理由 |
|---|---|---|
| `SEG_STEPS`（每段步数） | **400 ~ 700** | 约 45 ~ 80 分钟。太短则频繁重启开销大；太长则单段内被杀概率高 |
| `data-frequency` | **200** | checkpoint 粒度；13 时刻导出需要的步号是 0/200/…/2200/2262，正好对齐 |
| 看门狗周期 | **5 分钟** | 盘查开销小，接力延迟可接受 |
| 单步耗时（`-t4`，74796 单元，组分输运） | **≈ 6.6 s** | 用来估算 ETA：ETA(min) ≈ 剩余步数 × 6.6 / 60 |
| 并行进程数 | `-t4` | `-t8` 必失败（MPIDU_Init_shm_alloc） |

---

## 6. 必须预先确认的两件事

1. **磁盘余量**：单帧 data 可达 **268 MB**（126 MB 网格 + 约 25 个场）。40 帧约 **10 GB**。
   `.xyz` 导出额外占用（74796 单元 × 13 时刻 ≈ 数十 MB）。
2. **空闲内存**：`"第 1 步卡死数小时不出 Flow time"` 已**两次被证实是内存不足**，不是发散。
   本项目一次真实根因是当时仅剩 2.95 GB 空闲；内存充足（7.8 GB）时同一 journal 第 1 步正常完成。
   **先查内存，再怀疑发散。**

---

## 7. 崩溃残留清理

崩溃会留下 `cx2420.exe` / `fl2420.exe` / `fl_mpi2420.exe`，合计约 **2.7 GB**。
`taskkill fluent.exe` **杀不掉它们**。

```powershell
taskkill /F /IM cx2420.exe; taskkill /F /IM fl2420.exe; taskkill /F /IM fl_mpi2420.exe
```

清理后再启动续算，否则新实例会因为内存不足在第 1 步卡死。

---

## 8. 部署清单

| # | 步骤 | 检查 |
|---|---|---|
| 1 | 求解 journal 里已设 `data-frequency` + `root-name` | 能产出 checkpoint |
| 2 | 改过 zone 之后已 `write-case` 出 `_setup.cas.h5` | 续算不会报 mesh modified |
| 3 | `auto_resume.py` 的 `FIX_DIR/工作目录/case 路径/总步数` 已改成本场景值 | — |
| 4 | 手动跑一次 `python auto_resume.py` | 生成 journal、打印启动命令 |
| 5 | 加 `--launch` 或手动后台启动，确认 Fluent 真的脱离了会话 | 关掉终端后进程仍在 |
| 6 | 注册看门狗（任务计划或外部触发器，每 5 分钟） | `guard.log` 有触发记录 |
| 7 | 跑到总步数 | 自动调用后处理出图 |

---

## 9. 本机实测（2026-09-19）：任务计划方案可用，但有两个必改项

PL V2 的三场景长跑（600 步 × 3，约 17 h）实测记录，用来替代上面 §2 的"schtasks 常报拒绝访问"结论。

### 9.1 `schtasks` 免提权可创建成功

```python
# 关键：本机用户目录含非 ASCII 字符（中文用户名），Git Bash 传参到 schtasks.exe 会经 ANSI 转换，
# 中文路径可能被破坏。**用 Python subprocess 调 schtasks**（走 CreateProcessW，宽字符安全）。
TR = '"%s" "%s"' % (PYEXE, SCRIPT)          # 两个路径各自加引号
subprocess.run(["schtasks", "/create", "/tn", TN, "/tr", TR,
                "/sc", "minute", "/mo", "15", "/f"])
subprocess.run(["schtasks", "/run", "/tn", TN])   # 立刻触发一次
```

未提权即返回 `成功: 成功创建计划任务`。

### 9.2 ⚠️ 必须改掉"电池条件"（笔记本上会直接不触发）

`schtasks` 建的默认任务带：

```
电源管理: 在电池模式停止, 不用电池启动        ← 一旦切到电池，任务再也不触发
```

而 **`schtasks` CLI 没有开关这个条件的参数**，只能用 PowerShell 的 `ScheduledTasks` 模块：

```python
PS_EXE = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"  # 精简 PATH 下必须全路径
ps = ("$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries "
      "-DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Days 3);"
      "Set-ScheduledTask -TaskName 'X' -Settings $s")
subprocess.run([PS_EXE, "-NoProfile", "-NonInteractive", "-Command", ps])
```

改完 `schtasks /query /v` 里"电源管理"一栏应为空。顺带把 `ExecutionTimeLimit` 设到 3 天（默认 72 h，长跑够用但别更小）。

### 9.3 幂等用 **PID 锁**，比 `tasklist` 扫进程名可靠

`tasklist` 扫 `fl_mpi2420` 有个窄缝：chunk 之间的落盘间隙求解进程可能短暂不在，会误判成"没人跑"而双开。
改用 PID 锁更稳：

```python
def pid_alive(pid):                    # 不依赖 psutil
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
    if not h: return False
    code = ctypes.c_ulong()
    ok = k.GetExitCodeProcess(h, ctypes.byref(code))
    k.CloseHandle(h)
    return ok and code.value == 259                # STILL_ACTIVE
```

看门狗每次触发：① 全部完成？→ 退出；② `logs/run.pid` 里的 pid 还活着？→ 跳过；
③ 否则接管（清陈旧锁）并拉起调度器。**看门狗自己阻塞等待调度器**，所以它的 pid 就是锁。
另用 `tasklist` 扫进程名做**第二道**兜底。

> 另一个必须注意的：Git Bash 里 `taskkill /PID` 的 `/PID` 会被 MSYS 当路径转换
> （`//PID` 也不行，会报 `无效参数/选项 - '//PID'`）。**杀进程一律用 Python 调 taskkill**。

### 9.4 编码陷阱：会让长跑"一启动就静默死"

**现象**：某场景 `exit=1`，日志最后是

```
UnicodeEncodeError: 'gbk' codec can't encode character '\u1e41' in position 11
```

**根因**：中文 Windows 的控制台/重定向文件默认 **GBK(CP936)**，而日志里有 `ṁ`(U+1E41)、
`²`、`₂`、`⇒` 这类 GBK 编不出的字符，`print` 直接抛异常终止整个场景。

**最阴的地方**：**同一脚本在不同启动方式下表现不同**。
Git Bash 拉起时（locale 令 Python 进 UTF-8 模式）一切正常，跑了 5.5 小时；
换成任务计划拉起，同一个文件立刻炸。**"昨天能跑"完全不能作为判据。**

**两层修复**（缺一不可）：

```python
# ① 每个长跑入口模块，保命 —— 任何不可编码字符降级成 '?'
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(errors="replace")
    except Exception: pass

# ② 看门狗给整条链路注入，避免真丢字符
env["PYTHONIOENCODING"] = "utf-8"
# 注意：**不要**设 PYTHONUTF8=1 —— 会切换 Fluent 内嵌 Python 的默认编码，影响面过大
```

排查建议：一条命令扫全项目，别等跑到那行才发现。

```python
# 找出所有 GBK 编不出的字符（docstring 里的无害，重点看 print 行）
for i, ch in enumerate(src):
    try: ch.encode("gbk")
    except UnicodeEncodeError: print(base, line_no, "U+%04X" % ord(ch))
```

### 9.5 日志编码别再靠猜

`run_serial_PL.py` 用 `open(logf, "w", encoding="utf-8")` 打开子进程日志并把它当 stdout 传下去，
而子进程写进去的字节编码取决于**子进程自己的 locale**。
⇒ **同一个日志文件里可能前半段 GBK、后半段 UTF-8**（实测就撞上了，读起来像乱码）。
读日志要按"先 utf-8、再 gbk"逐个试；长期看应统一注入 `PYTHONIOENCODING=utf-8` 固定下来。

### 9.6 ⚠️ 长驻进程：**改磁盘源码不会影响它写出的后续行**

这是最容易漏掉的一条。长跑进程（`run_scenario.py`）把代码载入内存后就一直用那份代码，
此后你把磁盘上的 `.py` 改了 —— **正在跑的那个进程完全不知道**。

实测代价：修正了 `film_resolved` 的判据并写回源码，但 L1 的行已经/仍由旧代码写出，
三个场景的 CSV 口径立刻不一致。

**规则**：

1. 长跑期间**可以**改源码，但要清楚它只对**下次启动**的进程生效；
2. 因此口径类改动**必须配一个"跑完之后的归一化步骤"**，对已写出的 CSV 重算：
   例如 `normalize_monitors.py`（补 `h_mean_m`、统一 `film_resolved` 标签、
   原文件备份为 `.orig`、幂等可重跑）；
3. 把它作为后处理链的**第 1 步**，先归一化再出图/合并，顺序不能反。

```python
# 归一化骨架：从已有列派生出新列，不依赖跑批进程
h = mv / sa                       # 液深 = 体积 / 报告面积
label = ("亚网格(h<Δ)" if h < D else ("h~Δ" if h < 2*D else "深池(h≥2Δ)"))
```

同理：**改了判据口径后，别只看新跑的数**。旧行会"看起来正常"地留在表里。

### 9.7 后处理链要"单步失败不中断 + 单步超时"

三个场景跑完后通常要连做出一串交付物（出图 → 阈值面积 → 辐射半径 → 数据接口）。
把它们串成一条链挂在看门狗上是合适的，但要注意：

- **单步失败不要 `break`**：后续步骤（辐射、CSV 合并）往往与它独立，让它们照跑，
  最后统一汇报哪几步失败；
- **每步加超时**（`subprocess.run(..., timeout=N)`）：某步挂死会把看门狗永久占住，
  也会让 `MultipleInstancesPolicy=IgnoreNew` 的后续触发全部被吞掉；
- **成功标记用文件**（`post_done.flag`），失败则下一轮整链重试，并设**重试上限**
  （否则每 15 分钟无限重跑一个必然失败的步骤）；
- 后处理同样要**独占重算资源**：进链前查 PID 锁 + 求解进程，避免与长跑/上一轮并发；
- 长跑刚结束时 Fluent 可能还在退出，**推迟到下一轮**再做，别抢内存。

### 9.8 ⚠️ `IgnoreNew` 的双刃剑：看门狗**阻塞**着等长跑，会导致全程无法触发

**实测（2026-09-20，PL V2）**：看门狗用 `subprocess.call(...)` 拉起长跑并在原地等它结束
（原意是"任务实例存活 = 防双开"）。结果计划任务在此后 **20 h 内被拒绝了约 28 次**：

```
schtasks /query /tn <任务名> /fo LIST /v     # 关键字段
模式:        正在运行
上次结果:     -2147020576      # = 0x800710E0，SCHED_E_...  "请求被拒绝（实例已在运行）"
```

两个后果：

1. **挂在看门狗上的"增量后处理"永远不会执行。** 本机现象：L2 于 06:19 跑完，
   到 07:41 仍无 `post_inc_L2.done`；`watchdog.log` 最后一条停在 00:40:57 ——
   而那几条其实还是**手动实跑**留下的，不是计划任务触发的。
   ⇒ 想"边跑边出已完成场景的产物"，就必须让看门狗自己在等待期间做，不能指望下一轮触发。
2. **若长跑"挂死"（不是崩溃）而占着锁**，要一直耗到任务的执行时间上限
   （本机设 72 h）才会被系统强制结束。

**正解：把"原地阻塞等"换成"阻塞式监护循环"**——既不放弃防双开，又补上自愈：

```python
child = subprocess.Popen([...run_serial...], cwd=WORK, env=env,
                         stdout=fh, stderr=subprocess.STDOUT)
while True:
    rc = child.poll()
    if rc is not None:
        break
    time.sleep(POLL_S)                       # 默认 60 s
    if time.time() - last_post >= INC_EVERY_S:   # 默认 900 s
        run_incremental_post(env)                 # 纯读 h5，长跑中安全
        last_post = time.time()
    age = heartbeat_age_s()                  # 进度文件"无声"时长
    if age is not None and age > STALL_LIMIT_S:  # 默认 1800 s
        kill_tree(child.pid)                 # taskkill /T /F
        break                                # 退出 → 交回计划任务下一轮接管
```

- **心跳判据用"进度文件 mtime"**，不要用 CPU 时间（挂死与满负荷算难分）：
  `logs/run_*.log`、`logs/run_*.fluent`（Fluent 持续写）+ `results/*/monitors_*.csv`。
  正常每步（几十秒）刷一次，30 min 无声必然是异常。
- **不要改成"Popen 完就返回"**：任务实例一结束，Task Scheduler 可能连带结束
  整棵进程树，长跑反而会被杀。**验证这一点之前，别动阻塞语义。**
- **别为了"加载新代码"去杀正在监护的看门狗**：杀了它 = 任务实例结束，
  同样有连带结束进程树的风险。改源码只会对**下一次接管**生效，接受这一点。
- 监护循环的可注入设计便于自检：把心跳函数与后处理函数做成参数，就能用
  **替身进程**（`python -c "import time; time.sleep(N)"`）演练三条路径 ——
  ① 正常退出原样返回 rc；② 心跳超限必须 `taskkill` 并返回哨兵值；
  ③ 到达间隔真的调用了后处理。自检日志写到**独立文件**，别污染运维日志。

**回归测试要点**（本机已过）：`python watchdog_resume.py --selftest`。

### 9.9 ⚠️ 长跑进行中读存档：必须按 mtime 过滤"半成品"

边算边写时，最新的 `step<N>.dat.h5` 可能只写了一半。做增量后处理时若直接读它，
轻则抛异常（无害），重则读到自洽但不完整的数据（**有害，静默**）。

```python
MIN_AGE_S = 120        # 只看 mtime 早于 2 min 的存档
def _old_enough(p):
    return (time.time() - os.path.getmtime(p)) >= MIN_AGE_S
```

离线复算历史帧时可用 `--min-age-s 0` 关掉。**同时要给"跳过"打日志**，
否则"少算了一帧"看起来像没算完。

### 9.10 ⚠️ 交互式控制台的 Ctrl+C 会把长跑整棵树带走（"脱离会话"≠"免疫 Ctrl+C"）

**实证（2026-09-20 07:57）**：由计划任务拉起的看门狗 + run_serial + Fluent 全部消失，
求解日志断在半句。取证：

```
schtasks /query /tn <任务名> /fo LIST /v
  → 上次运行时间 07:55:01
  → 上次结果 −1073741510          # = 0xC000013A = STATUS_CONTROL_C_EXIT，即 CTRL+C
```

原因链：任务登录状态是 **"只使用交互方式"**（`Run only when user is logged on`），
进程仍挂在用户交互会话的控制台上。在 IDE/终端里对**另一个**会话按"中断/Ctrl+C"，
`CTRL_C_EVENT` 会顺着控制台送到本进程；看门狗一死，Task Scheduler 收尾时
**连带结束整个任务作业对象**，孩子（run_serial → Fluent）一起陪葬。
⇒ **"改成计划任务"只解决了"会话没了长跑还在"，没解决"控制台被 Ctrl+C"。**

**两层修法（缺一不可）**：

```python
# ① 看门狗自己无视控制台信号（真实长跑路径；--selftest 不要装，否则测不了）
for _sig in ("SIGINT", "SIGBREAK"):
    try:
        signal.signal(getattr(signal, _sig), signal.SIG_IGN)
    except Exception:
        pass

# ② 孩子放进独立进程组：CTRL_C_EVENT 只发给前台进程组，新组收不到
CHILD_FLAGS = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
child = subprocess.Popen([...], creationflags=CHILD_FLAGS, ...)
```

副作用：**以后要真停长跑必须显式 `taskkill /T /F`**（或封装成 `--stop` 动作），
不能再指望 Ctrl+C。这条要写进运维说明。

**"长跑是否还活着"的正确判据**（只看日志时间戳会被缓冲骗到，看起来只是"慢"）：

| 顺序 | 检查 | 说明 |
|---|---|---|
| 1 | `tasklist` 找 `fl_mpi2420.exe` / `fluent.exe` | **没有它 = 已经死了**，不用再看别的 |
| 2 | `logs/run.pid` 里的 pid 是否真活 | ⚠️ 锁里存的是**看门狗自己的 pid**，不是 run_serial 的 |
| 3 | `run_<S>.log` 是否只写了 `场景 <S> 开始` 而无 `结束` | 中断的典型指纹 |
| 4 | `schtasks /query ... /v` 的上次结果码 | `0xC000013A` = Ctrl+C；`0x800710E0` = IgnoreNew 被拒 |

**恢复是幂等的**：陈旧锁会被判"pid 已不存在"自动接管，`run_serial` 自己取最大可用存档续跑。
代价只是自上次存档之后的步数 —— **每 100 步存一次档 ⇒ 典型损失 ≤ 30~60 min**。
本次实测：L3 死在 step 151，从 step100（t=0.5 s）续跑，只赔了 50 步。

---

### 9.11 ⚠️ 计划任务每 15 分钟"闪一下黑窗" —— 必须用 `pythonw.exe`（2026-09-21 实撞）

**症状**（用户原话："电脑时不时弹出个 CMD 弹窗然后瞬间消失，是不是你之前设置了什么定时检查？"）：
`schtasks /create ... /tr "python.exe watchdog.py"` 且登录状态为
**"只使用交互方式"**（XML 里 `<LogonType>InteractiveToken</LogonType>`）
⇒ 每触发一次就在**用户桌面上真实创建一个控制台窗口**，python 秒级退出＝黑窗一闪。
本项目两个看门狗错开 3 分钟触发（:07/:22/:37/:52 与 :10/:25/:40/:55），
**平均每 7.5 分钟闪一次** —— 极易被当成"电脑中招"。

**根因（PE 头硬证据）**：`python.exe` 的 `Subsystem = 3 (WINDOWS_CUI)`，
控制台子系统程序被**无控制台的父进程**（任务计划服务）拉起时**必须分配新控制台**；
`pythonw.exe` 是 `Subsystem = 2 (WINDOWS_GUI)`，**不分配控制台**。

```python
# 判子系统：读 PE 头 Optional Header 的 Subsystem（opt 起点 = 0x18，字段偏移 +68）
import struct
d = open(r"...\Scripts\python.exe", "rb").read(0x400)
o = struct.unpack_from("<I", d, 0x3C)[0]          # e_lfanew
f = open(r"...\Scripts\python.exe", "rb"); f.seek(o)
h = f.read(0x100)                                  # PE sig(4)+COFF(20)+可选头
print(struct.unpack_from("<H", h, 0x18 + 68)[0])   # 3=控制台会闪窗, 2=GUI不闪
```

**修法（两步，缺一不可）**

① 注册任务时把解释器换成 `pythonw.exe`（**不要**去改 `LogonType`，
S4U/服务会话下 Fluent 可能跑不起来，风险更大）：

```python
PYEXE = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
if not os.path.isfile(PYEXE):
    PYEXE = sys.executable
```

② 看门狗入口做 **stdout 兜底**（原因见下条纠错）。

**⚠️ 纠错：`pythonw` 下 `print()` 不会崩，是"静默丢弃"**
"pythonw 下 `sys.stdout` 为 None ⇒ 裸 `print()` 抛 `AttributeError` 把脚本弄死"
这个说法**实测不成立**（2026-09-21）：CPython 的 `print()` 在 `file is None` 时
**直接返回**，实测 `rc=0`、零输出。所以真实症状是**日志一条不留**，
排查时表现成"任务跑了但什么都没发生"，而**不是**崩溃。
真正会抛 `AttributeError` 的只有显式 `sys.stdout.write()/.flush()`。

```python
# 放在 LOGDIR 定义之后
_WD_FH = None
if sys.stdout is None or sys.stderr is None:
    try:
        _WD_FH = open(os.path.join(LOGDIR, "watchdog_stdout.log"),
                      "a", encoding="utf-8", errors="replace")
        if sys.stdout is None:
            sys.stdout = _WD_FH
        if sys.stderr is None:
            sys.stderr = _WD_FH
    except Exception:
        pass
```

> ⚠️ §9.4 那段 `sys.stdout.reconfigure(errors="replace")`（GBK 保命）在
> `stdout is None` 时会抛 `AttributeError` —— 必须包 `try/except`（PG 已包，
> PL 无此段），或放到本兜底**之后**执行。

**怎么验证（关键：方法要对，否则测不出来）**

❌ **别用 `EnumWindows` 数 `ConsoleWindowClass` 窗口**：本机实测**无区分度**
（基线 0 个，python.exe / pythonw.exe 两组都报 0）—— 枚举进程与任务
大概率不在同一 window station / desktop。
✅ **用进程内自证**：让被测进程自己读 `GetConsoleWindow()`。
但必须复现"无控制台父进程"的处境 —— 从有控制台的 shell 直接起子进程会**继承**句柄，
连 pythonw 的 `sys.stdio` 都不是 None，测不出差异：

```python
# 中间启动器（DETACHED_PROCESS ⇒ 自身无控制台 = 任务计划服务的处境）
DETACHED_PROCESS = 0x00000008
p = subprocess.Popen([python_exe, LAUNCHER, target_exe, probe_py],
                     creationflags=DETACHED_PROCESS, stdin=subprocess.DEVNULL)
```

实测结果（探针在**进程内部**读并写文件）：

| 被测 | `GetConsoleWindow()` | `sys.stdout is None` | 结论 |
|---|---|---|---|
| `python.exe` | **461096** | False | 有控制台窗口 → 闪窗 |
| `pythonw.exe` | **0** | **True** | 无控制台 → 不闪窗 |

端到端复核：改造后 `setup_watchdog_task_*.py create` 出来的任务
`<Command>` 已是 `pythonw.exe`，手动 `/run` 一次 `rc=0`、看门狗日志正常追加。

**清场**：长跑跑完后**把任务删掉**，别留着空转（本项目两个看门狗在全部场景完成后
仍每 15 min 触发，只打两行日志就退出，纯属白闪+白耗）。
先 `schtasks /query /tn X /xml ONE > 备份.xml` 存到 `_scheduled_task_backup_<日期>/`，再
`schtasks /delete /tn X /f`。判"任务是否还在触发"看 `/query /v` 的上次运行时间/结果码，
**别**看看门狗日志（手动实跑也写同一文件）。

**顺带一个"生成脚本"的坑（我就是被它连坑三轮）**：在 Git Bash heredoc 里用 Python
**生成**另一个 Python 文件时，被写文件的换行**不要用 `\n` 字面量** —— 本机实测会被
MSYS/包装层转成 `/n`，生成出
`with open(...) as f:` 后面接一个被转成 `/n` 的假换行、再跟 `f.write(...)` 的脚本，
而报错只在**子进程**里（父进程完全看不到，只看到"没写出文件"），
于是被误读成"实验没复现"。
✅ 用 `NL = chr(10)` 拼行 + **每行一个独立字符串** + `NL.join(lines)`；
生成后**立刻 `py_compile` 一遍**再交给子进程，别让它静默跑。
同一坑还有：`chr(10)` 若被拼进**被写脚本的字符串字面量内部**，
会把那个字面量自己裂成两行 ⇒ `unterminated string literal`。

---

## 10. 后处理链自身的三个"静默 / 连锁"失败（2026-09-20 实战）

链的写法是 `POST_STEPS = [(标签, [脚本, 参数...]), ...]`，**框架不做参数展开**，
判成功只看 rc。下面三件事必须做，否则失败方式都是"看起来在跑、其实白跑"。

### ① 位置参数接口要对得上 —— 否则整链每 15 min 白跑一次

现象：某步 `rc=2`，日志里是 argparse 的 `error: unrecognized arguments: L2 L3`。
含义：该脚本的 scenario 是 `nargs="?"`（**单场景**），不能一次传多个。

**代价不是"一步失败"**：链的规矩是"全部成功才写 `post_done.flag`"，所以
失败 → 15 min 后整链重试 → 又失败 ⇒ **`post_done.flag` 永远写不出来、无限重试**，
而长跑其实早已结束。本次就是这样：L3 14:52 就完成了，15:25 还在整链重试。

- 脚本改 `nargs="*"`，`main()` 里 `for scen in (args.scenarios or ["L1"]):` 逐场景跑；
- **每个场景各自 `try/except`**：一个场景的异常不该吞掉其余场景
  （本次 L1 出图失败，导致 L2/L3 一个都没算 —— 因为异常在场景循环里没被隔离）；
- 接链后**必须真跑一次** `python <脚本> L1 L2 L3` 看 rc，别只看"参数顺序像对的"。
  同类前科：`setup_BC.py` / `verify_BC.py` 也是单场景脚本。

### ② 目标文件被"看图的人"占用 ⇒ `Errno 22`，不是路径错

现象：`OSError: [Errno 22] Invalid argument`，出处是
`PIL/Image.py:2708  fp = builtins.open(filename, "w+b")`。

**先做这个 30 秒判别**（能省掉几小时乱查）：

```python
open(r"...\某图.png", "w+b")   # → Errno 22
open(r"...\某图.png", "rb")    # → OK
```

只读正常、写失败 ⇒ **有别的进程握着写句柄**（本次实测是 IDE 的**图片预览面板**，
正显示着那张图）。**不是**路径非法、不是文件名坏字符、不是编码、不是磁盘。

特征（认这个模式就够了）：
* **同一个脚本**，增量跑失败、完整链跑成功 —— 差别只是"那一刻面板在看哪张图"；
* 每次失败的**文件各不相同**，且都出现在成功写出前几张之后。

修法（`<work>/figsave.py`，四个出图脚本各加两行）：

```python
import figsave
figsave.patch_savefig()      # 包住 Figure.savefig：重试 6×1.5 s → 改存 .busy.png，不抛异常
```

⚠️ 实现要点：补丁里**必须持住"打补丁之前"的原始 `Figure.savefig`** 并在重试时调用它。
直接把 `fig.savefig` 当"原函数"用会回调自己 ⇒ `RecursionError`
（本次第一版就这样翻车：`EXPORT_RC=1`、三个场景的图全废，但**数据 CSV 都已写出** ——
所以"图没出来"仍可能是"这轮其实成功了"的假象）。自检：`python figsave.py`。

### ③ 续跑会让监视器 CSV 出现重复行 ⇒ 时间序列双计

Fluent 的监视器文件是 **append** 模式，而"从 stepN 存档续跑"会把 N 之后那几步
**重算并再写一行**。实测 L3（被杀后从 step100 续跑）：
`t=0.625` / `t=0.750` 各两遍、**27 行（应 25 行）**、`t_s` **不单调**，
且已污染下游合并表（`grid_ALL.csv` 里 L3 那两行重复）。
L1/L2 未中途续跑，所以只有 L3 中招 —— **"续跑过的场景要专门查一遍"**。

修法：在归一化步骤里加**去重 + 按 `t_s` 升序**，同一时刻**保留最后一次**
（续跑那次才是权威值）。本项目落在 `normalize_monitors.py`，是链上第 2 步。
