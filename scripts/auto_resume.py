#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
长时求解的分段续算 journal 生成器 + 看门狗（脱离会话启动 Fluent）
================================================================
为什么需要它：
  * 通过后台方式拉起的 fluent.exe 会随 agent 会话结束被一起杀掉；
  * 数小时的长任务必然中途断（被杀 / 崩溃 / 掉电）；
  * Windows 10+ 上 `schtasks /create` 常报"拒绝访问"（需管理员）。

解法：**分段限步续算 + 看门狗幂等接力**。每段只跑 SEG_STEPS 步就主动存档退出，
下次触发时从最新 checkpoint 接着跑，直到总步数。见 references/auto-resume-and-guard.md。

用法：
    # 1) 只生成 journal 并打印启动命令（推荐先看一眼）
    python auto_resume.py

    # 2) 直接把命令贴到终端后台跑，或让脚本自己脱离会话启动
    python auto_resume.py --launch

    # 3) 看门狗模式（每 5 分钟被触发一次；fluent 在跑就跳过）
    python auto_resume.py --guard

    # 4) 只查状态，什么都不做
    python auto_resume.py --status

必须按本场景改的常量：CASE_FILE / FIX_DIR / WORK_DIR / TOTAL_STEPS / DT / SEG_STEPS
"""
import argparse
import glob
import os
import re
import subprocess
import sys
import time

# ============================ 按场景修改 ============================
CASE_FILE = "<CASE_DIR>/G3_files/dp0/FLTG/Fluent/FLTG-1.cas.h5"   # setup case（改过 zone 后 write-case 的那个）
FIX_DIR = "<CASE_DIR>/fix"          # checkpoint 目录（autosave 落盘处）
WORK_DIR = "<CASE_DIR>/work"        # journal / 日志目录
TOTAL_STEPS = 2262                  # 总步数（物理时长 / dt）
DT = 0.005                          # 每步物理时间（s），用于打印 t
SEG_STEPS = 600                     # 每段最多续多少步（400~700，约 45~80 分钟）
SAVE_FREQ = 200                     # autosave 频率
POST_SCRIPT = ""                    # 跑到总步数后要调用的后处理脚本（可空）

FLUENT_EXE = "%AWP_ROOT242%/fluent/ntbin/win64/fluent.exe"
PYTHON_EXE = sys.executable
LOG = os.path.join(WORK_DIR, "guard.log")

# DETACHED_PROCESS(0x8) | CREATE_NEW_PROCESS_GROUP(0x200) | CREATE_NO_WINDOW(0x08000000)
DETACH_FLAGS = 0x00000008 | 0x00000200 | 0x08000000
# ==================================================================

# 兼容 G3_fix-00000.dat.h5 与 G3_fix-2-00XXX.dat.h5 两种命名：取文件名最后一段数字
_PAT = re.compile(r"(\d+)\.dat\.h5$")


def p(*parts):
    """拼接路径并统一正斜杠（Fluent journal 对混合斜杠敏感）。"""
    return os.path.join(*parts).replace("\\", "/")


def log(msg):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    os.makedirs(WORK_DIR, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    print(line)


def latest_step():
    steps = []
    for f in glob.glob(os.path.join(FIX_DIR, "*.dat.h5")):
        m = _PAT.search(f)
        if m:
            steps.append(int(m.group(1)))
    return max(steps) if steps else 0


def find_data(step):
    for f in glob.glob(os.path.join(FIX_DIR, "*.dat.h5")):
        m = _PAT.search(f)
        if m and int(m.group(1)) == step:
            return p(f)
    return None


def fluent_running():
    """看门狗幂等判据：★ 不要删。防重复触发导致两实例并发、内存耗尽。"""
    try:
        out = subprocess.check_output(
            'tasklist /FI "IMAGENAME eq fluent.exe" /NH', shell=True)
        return b"fluent.exe" in out
    except Exception:
        return False


def build_journal(latest, target, run_steps):
    src = find_data(latest)
    if not src:
        return None, None, None, None
    jou = p(WORK_DIR, "resume_%05d.jou" % target)
    logf = p(WORK_DIR, "resume_%05d.log" % target)
    dst = p(FIX_DIR, "resume-%05d.dat.h5" % target)
    text = (
        "; 续算：step %d -> %d（auto_resume.py 生成）\n"
        '/file/read-case "%s"\n'
        '/file/read-data "%s"\n'
        "/file/auto-save/data-frequency %d\n"
        '/file/auto-save/root-name "%s"\n'
        "/solve/dual-time-iterate %d 20\n"
        '/file/write-data "%s"\n'
        "/exit\n"
    ) % (latest, target, p(CASE_FILE), src, SAVE_FREQ,
         p(FIX_DIR, "resume"), run_steps, dst)
    return jou, logf, text, dst


def cmd_of(jou, logf):
    return '"%s" 3ddp -gu -i "%s" -t4 > "%s" 2>&1' % (FLUENT_EXE, jou, logf)


def do_guard():
    log("===== guard 触发 =====")
    if fluent_running():
        log("fluent.exe 在跑，本次跳过。")
        return
    latest = latest_step()
    log("最新 checkpoint: step %d (t=%.3fs)" % (latest, latest * DT))
    if latest >= TOTAL_STEPS:
        log("已迭代到 %d 步。" % TOTAL_STEPS)
        if POST_SCRIPT and os.path.isfile(POST_SCRIPT):
            log("调用后处理：%s" % POST_SCRIPT)
            subprocess.call('"%s" "%s"' % (PYTHON_EXE, POST_SCRIPT),
                            shell=True, cwd=WORK_DIR)
        return
    run_steps = min(SEG_STEPS, TOTAL_STEPS - latest)
    jou, logf, text, _ = build_journal(latest, latest + run_steps, run_steps)
    if not jou:
        log("[错误] 找不到 step %d 的 data，中止。" % latest)
        return
    with open(jou, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    log("启动续算: step %d -> %d (%d 步, 约 %.0f 分钟)"
        % (latest, latest + run_steps, run_steps, run_steps * 6.6 / 60))
    subprocess.Popen(cmd_of(jou, logf), shell=True, cwd=WORK_DIR,
                     creationflags=DETACH_FLAGS)
    log("[已启动] 已脱离会话，脚本退出后 Fluent 继续跑。")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--launch", action="store_true", help="脚本自身脱离会话启动 Fluent")
    ap.add_argument("--guard", action="store_true", help="看门狗模式（幂等 + 自动接力）")
    ap.add_argument("--status", action="store_true", help="只查状态")
    ap.add_argument("--steps", type=int, default=None, help="本次续算步数上限，默认 SEG_STEPS")
    args = ap.parse_args()

    if not os.path.isfile(CASE_FILE):
        sys.exit("[错误] CASE_FILE 不存在：%s\n"
                 "（应是改过 zone 后 write-case 出的 setup case，否则续算会报 mesh modified）"
                 % CASE_FILE)

    if args.guard:
        do_guard()
        return

    latest = latest_step()
    remaining = TOTAL_STEPS - latest
    print("case        : %s" % p(CASE_FILE))
    print("checkpoint  : %s" % FIX_DIR)
    print("最新步号    : %d  (t = %.3f s)" % (latest, latest * DT))
    print("剩余步数    : %d  (约 %.1f 小时)" % (remaining, remaining * 6.6 / 3600))
    print("fluent 在跑 : %s" % fluent_running())

    if args.status:
        return
    if remaining <= 0:
        print("[完成] 已迭代到 %d 步，无需续算。" % TOTAL_STEPS)
        return

    seg = args.steps or SEG_STEPS
    run_steps = min(remaining, seg)
    target = latest + run_steps
    jou, logf, text, dst = build_journal(latest, target, run_steps)
    if not jou:
        sys.exit("[错误] 找不到 step %d 的 data 文件。" % latest)

    with open(jou, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("\n续算: step %d -> %d  (共 %d 步, 约 %.0f 分钟)"
          % (latest, target, run_steps, run_steps * 6.6 / 60))
    print("journal : %s" % jou)
    print("日志    : %s" % logf)
    print("目标    : %s" % dst)
    print("\n启动命令:\n  %s" % cmd_of(jou, logf))

    if args.launch:
        subprocess.Popen(cmd_of(jou, logf), shell=True, cwd=WORK_DIR,
                         creationflags=DETACH_FLAGS)
        print("\n[已启动] 已脱离会话，本脚本退出后 Fluent 继续跑。")
    else:
        print("\n[仅生成] 用上面命令启动，或加 --launch。")
        print("看门狗模式（每 5 分钟触发一次）：python auto_resume.py --guard")
    print("\n提示：启动前确认内存与磁盘；若有崩溃残留先清 cx2420/fl2420/fl_mpi2420。")


if __name__ == "__main__":
    main()
