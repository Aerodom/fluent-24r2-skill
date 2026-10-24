# fluent-24r2-skill

> [English](README.en.md) | 简体中文

**ANSYS Fluent 2024R2（v242）通用工程 Skill**：物理判型 → 网格路线 → journal / PyFluent 搭案例 → 脚本化自动跑批与长跑续算 → 离线后处理取数 → 交付可双击打开的 `.wbpj` 工程。

全部命令、参数与"坑"都来自**实际算例实测**（本机 Windows + Fluent 2024R2 + PyFluent 0.42.1），不是文档转抄。凡未实测的结论都显式标注。

## 它解决什么问题

用脚本/命令行跑 Fluent 时，真正耗时的不是建模，而是：

- **TUI 与文档不符** —— 命令废弃、交互式提示吃行、报 `invalid command` 就停；
- **静默失败** —— 相材料没赋上、register 没标记、`node_value` 索引错位、初始化把环境填成纯氮气，全都**不报错**；
- **长跑被打断** —— 会话结束杀进程树、autosave 不能续算、续算后监控 CSV 重复计；
- **交付不完整** —— 只有 `cas.h5`/`dat.h5`，用户打不开、改不了；
- **接手别人的半成品** —— 只给几何 / 只给网格 / 设了边界没算过 / 跑过但跑崩了，
  任何中间状态都可能。**先盘点再动手**，别推倒重搭，也别在原件上改。

这个 skill 把这些坑固化成**阶段化流程 + 过闸判据 + 案例库**。
其中"接手"有专门的入口：`scripts/inspect_case.py` 离线读 `.h5` 出体检报告
（不启动 Fluent、不占 license、几秒出结果），直接告诉你"从 P几 接"。

## 安装

```bash
# 用户级（对所有项目生效）
git clone https://github.com/Aerodom/fluent-24r2-skill.git "<用户级技能目录>/fluent-24r2-skill"

# 或项目级
git clone https://github.com/Aerodom/fluent-24r2-skill.git "<项目根>/<项目级技能目录>/fluent-24r2-skill"
```

目录名保持 `fluent-24r2-skill`。装载目录的位置由所用 agent 客户端决定（用户级 / 项目级各一），
装好后重启会话或重新加载技能列表即可。

装好后，涉及 journal / PyFluent / 后处理 / `.wbpj` / Fluent 故障排查的任务会自动命中本 skill。

## 语言

| 入口 | 文件 | 说明 |
|---|---|---|
| 中文总说明 | [`SKILL.md`](SKILL.md) | 当前生效的技能文件 |
| English spec | [`SKILL.en.md`](SKILL.en.md) | 全译版，章节号与中文版一一对应 |
| 案例索引 | [`cases/README.md`](cases/README.md) / [`cases/README.en.md`](cases/README.en.md) | |
| 卡片模板 | [`cases/_TEMPLATE.md`](cases/_TEMPLATE.md) / [`cases/_TEMPLATE.en.md`](cases/_TEMPLATE.en.md) | |

加载器只读 `SKILL.md`，所以并存的译文**不占任何上下文**。两份总说明可直接互换：

```bash
cp SKILL.en.md SKILL.md        # 切到英文
```

案例卡与 `references/` 专题正文目前为中文（含大量 Fluent 面板原文与实测日志，翻译反而丢信息）；英文卡片欢迎补充，模板已就位。

## 结构

```
fluent-24r2-skill/
├── SKILL.md                      # 总说明：通用方法论 + 8 阶段流程 + 硬规则
├── SKILL.en.md                   # 英文全译版（与 SKILL.md 章节号一致）
├── cases/                        # 案例库（先查这里，再动手）
│   ├── README.md / README.en.md  # 索引表 + 检索/扩充规则
│   ├── _TEMPLATE.md / .en.md     # 统一卡片模板（§1 选型 → §13 复用差异）
│   ├── assets/                   # 卡片引用的 journal / 长表格（默认空，不放二进制）
│   └── <ID>-<短名>.md            # 每个案例一张卡片
├── references/                   # 通用参考（命令表、检查单、故障表、专题、版本边界）
├── scripts/                      # 可复用脚本 + check_cases.py / audit_sensitive.py
├── tests/smoke/                  # 冒烟测试：最小算例 + 解析解判据（换版本先跑这个）
├── .github/workflows/            # CI：push / PR 自动跑两个校验脚本
├── CHANGELOG.md                  # 版本记录（SemVer）
└── requirements.txt              # 离线脚本依赖（numpy / scipy / h5py）
```

## 怎么用（三步）

1. **判物理类型**：可压缩瞬态（A）/ 高密度比多相（B）/ 组分输运（C）/ 单相传热（D）。见 `SKILL.md` §2。
2. **查案例库**：`cases/README.md` 索引表按类型 + 关键词检索。**命中** → 照卡片执行，只改其「复用与差异」列出的项；**未命中** → 按 `SKILL.md` + `references/case-setup-checklist.md` 自行选型。
3. **走 8 阶段流程**：P0 口径冻结 → P1 网格 → P2 搭案例 → P3 试跑自检 → **P4 自动化长跑** → P5 后处理 → **P6 交付（含 `.wbpj`）** → P7 回写案例卡片。

每个阶段都有过闸判据，**闸不过不前进**。

## 案例库现状

| 类型 | 案例 | 状态 |
|---|---|---|
| VOF 自由液面 | 熔体泄漏 ×3、酸碱泄漏 | 实测 / 部分实测 |
| 可压缩激波 | 高压釜压力爆炸 | ★ 实测跑通（含反射峰剔除与幂律拟合） |
| VOF 有限液块 | 放出口喷溅、泡沫渣喷溅 | ★ 实测（喷溅落点误差 3%；泡沫渣暴露网格分辨极限） |
| 组分输运 | 有毒气体泄漏 | ★ 实测（含 `last_species` 初始化陷阱） |

未实测的场景（熔体入水爆炸、反应失控、材料失效、烟气持续源）也各有一张卡片，**只写路线、前置数据需求与不能照抄的地方**，不给结果数字。

## 扩充案例

案例库**不预设数量**，随时可以加。完整流程（判要不要建卡 → 填 §1~§13 → 更新索引 → 校验）见
[`cases/README.md` §四](cases/README.md#四怎么填一张卡完整流程)，这里只留三条底线：

1. 先看 §四 第 0 步——**同构案例不要重复建卡**，用 `reuse_of` 指过去，正文只写差异；
2. 未实测的项写"待实测"，**不要编数字**；
3. 加完跑 `python scripts/check_cases.py`，零 error 才算完。

## 对外发布前

仓库里的示例一律用占位符（`<PROJ>`、`<CASE_DIR>`、`<OUT_DIR>`、`<venv>`、`%AWP_ROOT242%`），
不留本机绝对路径。往这个仓库里加东西、或把仓库推到公开地址之前，跑一次体检：

```bash
python scripts/audit_sensitive.py            # ERROR 必须为 0
python scripts/audit_sensitive.py --strict   # 连 WARN 一起当失败
```

它查本机绝对路径、用户目录、邮箱、IPv4、组织名。想额外核对客户名、项目号等本项目的敏感词，
把它们写进 `scripts/audit_terms.local.txt`（每行一个，已被 `.gitignore` 排除，**不要提交**）。

## 版本与兼容

| 项 | 值 |
|---|---|
| 当前版本 | **0.1.0**（变更见 [CHANGELOG.md](CHANGELOG.md)） |
| **已验证** | ANSYS Fluent **2024R2 / v242**，Windows x64；PyFluent 0.42.1 |
| **未验证** | 其他任何版本。能跑通是运气，不是契约 |

换版本（2025R1/R2 等）时：**先跑 `tests/smoke/`**，它用 2D 通道层流在几分钟内验证
"网格读取 / journal 命令 / 求解 / 离线读数"四层；最易变的六处与探针判据见
[`references/version-compatibility.md`](references/version-compatibility.md)。

> 案例卡片只在**实测过的版本**上标 `verified`。在别的版本上跑通，请在卡片里新增一行
> `verified_on:`，**不要改旧数字** —— 改了就等于伪造实测。

## 仓库治理

| 机制 | 位置 | 作用 |
|---|---|---|
| CI | `.github/workflows/validate.yml` | 每次 push / PR 跑下面两个脚本，任一失败即标红 |
| 案例库校验 | `scripts/check_cases.py` | front matter、受控词、**索引 ↔ 文件 ↔ 状态三向对账**、登记闭环、链接、素材引用 |
| 发布前体检 | `scripts/audit_sensitive.py` | 绝对路径、用户目录、邮箱、IP、组织名（`--strict` 让 warning 也失败） |
| 版本记录 | `CHANGELOG.md` | 每次改卡片或改流程记一行 |

提交前本地自检（两条都过才算完）：

```bash
python scripts/check_cases.py
python scripts/audit_sensitive.py --strict
```

## 说明

- `SKILL.md` §1 的环境表全部是**占位符**（`%AWP_ROOT242%`、`<venv>`、`<PY38>` 等）。首次使用请按本机实际
  把占位符换掉，**不要照抄字面**；核数与内存限制也需按你的机器重新确定。
- 案例里的几何尺寸、物性、阈值均来自具体工程算例，仅作**配方参考**；用于新工程时请以设计资料替换。
- `references/` 里出现的 `PL` / `PG` 是**示例工程代号**（液体泄漏项目 / 气体泄漏项目），只为叙述"两个案例来自不同工程"方便，**不对应任何真实项目或客户**。

## 许可证

[MIT](LICENSE) © 2026 Aero

可以自由使用、修改、商用、闭源分发，只需保留版权声明。

## 免责声明

- **与 Ansys 公司无关**。ANSYS 与 Fluent 是 Ansys, Inc. 的商标。本仓库是独立的实践笔记与脚本集合，**未获 Ansys, Inc. 认可、赞助或与其存在关联**。
- **本仓库内容不构成任何工程依据**。案例中的几何尺寸、物性、验收阈值与结果数字来自具体工程项目，**仅作配方参考**。用于新工程时请替换为自有设计资料并独立验证，**不得**直接用于设计定型、安全评估或监管报批。
- 按 **"AS IS"（现状）** 提供，不附带任何明示或默示担保，详见 [LICENSE](LICENSE)。

