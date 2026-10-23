---
id: L3
name: 渣线烧损致高温熔体泄漏
class: vof-free-surface
status: partial           # verified | partial | untested
last_run: 2026-09
keywords: [VOF, 熔体泄漏, 渣线, 续算, 监控CSV去重, 复用L1]
reuse_of: L1
---

# L3 · 渣线烧损致高温熔体泄漏

> **一句话画像**：渣线部位耐火材料烧损 → 熔体从**渣线高度**的开口泄出 → 贴壁下落铺展。与 L1 同构，差别在泄漏口标高偏低、射流更贴壁。
> **状态**：与 L1/L2 同批跑过（实测落点 **x = 4.56 m**），中途被杀后**从 step100 续跑**，因此监控 CSV 有重复行——本卡片的独特价值就是**续算与监控归一化的实测记录**。

## 1 选型卡

**沿用 [L1](L1-molten-shell-leak.md) §1**。追加：

| 项 | L3 取值 |
|---|---|
| 续算 | 有（被外部终止 → `read-data(checkpoint)` 续跑） |
| 监控归一化 | **必需**（同一步会被重算并再写一行） |

## 2 几何与计算域

同 L1（474.256 m³）。泄漏口 `breach_l3` 位于**渣线标高**，贴壁泄出。
实测落点 **x = 4.56 m**（三场景中最远，与出口 `outlet_xmax` 距离 0.44 m ⇒ 最先/最多流出）。

## 3 网格

同 L1（~404k）。贴壁射流对近壁首层网格更敏感，若贴壁薄层失真，先查近壁加密。

## 4 材料与相

同 L1。

## 5 模型与求解设置

同 L1 §5。

## 6 边界条件

同 L1 **修正版**（侧面 0~3 m wall + 屋顶开口）。本场景正是暴露"地面标高开 pressure-outlet"危害的那一个：落点距壁仅 0.44 m，薄层以 6.8 m/s 出域。

## 7 初始化与 patch

同 L1。**续算时绝不调 `standard_initialize`**（流场来自 data，初始化会清零）。

## 8 推进策略

- 分段续算：每段 400~700 步主动退出存档，可反复触发。
- 续算 journal：`read-case(setup)` → `read-data(最新 checkpoint)` → `dual-time-iterate N 20` → `write-data`。
- **续算成功的硬证据**：transcript 打出 `Flow time = 1.005s, time step = 201`（从 1.000 s/step200 续上）。若打出 `Flow time = 0.005s, time step = 1`，说明 data 没读进去或误调了初始化。
- 帧号解析：`auto_save` 文件名可能是 `<root>-1-000050.dat.h5`，root 名里本身可能带数字 ⇒ **取最后一串数字**，不要 `re.search(r"(\d+)")`。

## 9 监控与验收判据

| 判据 | 标准 | 说明 |
|---|---|---|
| 续算连续性 | `Flow time` / `time step` 精确接上 | 见 §8 |
| 监控时间轴单调 | 去重后 `t_s` 严格升序 | 见 §11 |
| 质量闭合 | L1 三步闭合 | L1 §11 |

## 10 后处理与交付

- 取数前先跑**归一化**：同 `t` 保留最后一次 + 按 `t_s` 升序（本项目 `normalize_monitors.py`）。
- 其余同 L1。

## 11 已知坑（本案例专属）

| 现象 | 根因 | 处理 |
|---|---|---|
| `monitors_<S>.csv` 行数比理论值多、时间戳不单调（27 行应为 25 行，`t=0.625/0.750` 各出现两遍） | 监视器文件是 **append 模式**；"从 stepN 存档续跑"会把 N 之后那几步**重算并再写一行** | 归一化：**去重（同 t 保留最后一次）+ 按 `t_s` 升序**；否则下游曲线/动画**双计** |
| 续跑后墙钟时间从 0 重新开始 | 墙钟列没做累计偏移 | 读旧 CSV 末行做偏移 |
| 续算报 `Uninitialized flow field` / `phase-2-vof data not available` | 只读了 case、没读 data（case 不存流场） | 必须 case + data 成对读 |
| 续算报 `Update_Time_Level: invalid data` | 二阶瞬态缺 N−1 时间层 | 从 write-case 的 case + **对应帧** data 续算 |

## 12 复现入口

```text
续算段：scripts/auto_resume.py（生成 journal）
归一化：normalize_monitors.py（项目内）
```

## 13 复用与差异

- **可以直接照抄的**：L1 全部配方 + 本卡片的续算/归一化配方。
- **必须改的**：泄漏口标高与位置、落点校验。
- **不能照抄的**：L1 的落点与面积数字。
