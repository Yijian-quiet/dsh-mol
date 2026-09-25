#!/usr/bin/env python3
"""dsh-mol 验收脚本 —— 10 个工具逐个跑一遍，给结论、耗时和产物路径。

用法：
    cd ~/dsh-plugins/dsh-mol
    PYTHONPATH=src python3 examples/acceptance.py

它不评判"对不对"（那要你自己看），只保证：**每个工具都被真实调用、产物真的落盘、
判定项给出行/不行**。最后一节是留给你手改的输入，改完重跑即可。

输出目录默认 ~/dsh-mol-out（可用 MOL_OUT 覆盖）。
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import chemcore as cc  # noqa: E402

OUT = os.environ.get("MOL_OUT", os.path.expanduser("~/dsh-mol-out"))
os.makedirs(OUT, exist_ok=True)

PASS, FAIL = [], []


def step(title: str, fn):
    t0 = time.perf_counter()
    try:
        detail = fn()
        dt = (time.perf_counter() - t0) * 1000
        PASS.append(title)
        print(f"  ✓ {title}   ({dt:.0f} ms)")
        if detail:
            for line in str(detail).splitlines():
                print(f"      {line}")
    except Exception as exc:  # noqa: BLE001
        dt = (time.perf_counter() - t0) * 1000
        FAIL.append((title, str(exc)))
        print(f"  ✗ {title}   ({dt:.0f} ms)\n      {type(exc).__name__}: {exc}")


# 高分子领域的真实样本：PET 重复单元、常见单体、一个含盐的去污剂中间体
PET_RU = "*OCCOC(=O)c1ccc(C(=O)O*)cc1"
MONOMERS = [
    ("OC(=O)c1ccc(C(=O)O)cc1", "对苯二甲酸"),
    ("OCCO", "乙二醇"),
    ("CC(O)C(=O)O", "乳酸"),
    ("OC(=O)CCCCC(=O)O", "己二酸"),
    ("NCCCCCCN", "己二胺"),
    ("OCC(O)CO", "甘油"),
]

print(f"dsh-mol 验收 ｜ 输出目录 {OUT}\n")

print("【1】SMILES 校验（三级结果 + 人话原因）")
step("正常分子 → ok", lambda: f"level={cc.check(PET_RU).level} formula={cc.check(PET_RU).formula}")
step("坏分子 → error + 人话", lambda: cc.check("C1CC").diagnostics[-1].message)
step("可疑分子 → warn（不拒绝）", lambda: f"[Fe+9] → level={cc.check('[Fe+9]').level}；"
                                       f"{cc.check('[Fe+9]').diagnostics[0].message[:40]}…")
step("空输入被拦（RDKit 会当合法）", lambda: f"'' → level={cc.check('').level}（{cc.check('').diagnostics[0].code}）")

print("\n【2】性质计算")
step("PET 重复单元", lambda: (lambda p: f"{p['formula']}  MW={p['mw']}  logP={p['logp']}  "
                                          f"HBD={p['hbd']} HBA={p['hba']}  环={p['rings']}")(cc.properties(PET_RU)))
step("logP 标注了口径", lambda: cc.properties("CCO")["_notes"]["logp"])

print("\n【3】画分子（返回文件路径；在 dsh web 里可再用 present 展示）")
step("单分子 + 原子编号 + 高亮苯环",
     lambda: cc.draw(PET_RU, out=OUT, atom_indices=True, highlight_smarts="c1ccccc1",
                     legend="PET 重复单元")["path"])
step("批量拼图（中文图注）",
     lambda: cc.draw_grid([s for s, _ in MONOMERS], legends=[n for _, n in MONOMERS],
                          out=OUT, mols_per_row=3, filename="acceptance-grid.png")["path"])

def _expect_error(fn):
    """断言 fn 会抛 ValueError，并返回那句人话（用于演示'错误也是产品'）。"""
    try:
        fn()
    except ValueError as exc:
        return f"按预期报错：{exc}"
    raise AssertionError("本应报错但没有")


print("\n【4】格式互转")
def _roundtrip():
    mono = "OC(=O)c1ccc(C(=O)O)cc1"          # 不带 * 的普通分子
    inchi = cc.convert(mono, to="inchi")["value"]
    back = cc.convert(inchi, to="smiles")["value"]
    return f"InChI 往返一致：{back == cc.check(mono).canonical}"
step("SMILES ↔ InChI 往返（普通分子）", _roundtrip)
step("InChIKey（单向摘要）", lambda: cc.convert("OC(=O)c1ccc(C(=O)O)cc1", to="inchikey")["value"])
step("拒绝反推 InChIKey（明确报错，不瞎猜）",
     lambda: _expect_error(
         lambda: cc.convert("BSYNRYMUTXBXSQ-UHFFFAOYSA-N", to="smiles", src="inchikey")))
step("RU-SMILES 带 * 转 InChI：应明确报错而不是静默返回空串",
     lambda: _expect_error(lambda: cc.convert(PET_RU, to="inchi")))

print("\n【5】结构标准化（逐步记录改了什么）")
def _std():
    r = cc.standardize("OC(=O)CCCCC(=O)[O-].[Na+]")
    changes = [f"{c['step']}: {c.get('before')} → {c.get('after')}"
               for c in r["changes"] if str(c.get("changed")) == "True"]
    return f"{r['output']}\n" + "\n".join(changes)
step("己二酸单钠盐 → 中和去盐", _std)

print("\n【6】去重与子结构")
step("同一分子两种写法被合并",
     lambda: f"重复 {len(cc.dedupe(['OC(=O)c1ccc(C(=O)O)cc1', 'O=C(O)c1ccc(C(=O)O)cc1'])['duplicates'])} 组")
step("找酯键（SMARTS）", lambda: f"命中 {cc.substructure_match(PET_RU, 'C(=O)O')['count']} 处")
step("相似度自比 = 1.0", lambda: cc.similarity(PET_RU, PET_RU)["score"])

print("\n【7】批量清洗（脏数据不能让任何一行悄悄消失）")
MESSY = [s for s, _ in MONOMERS] + ["C1CC", "C(C)(C)(C)(C)C", "[Fe+9]", "OC(=O)c1ccc(C(=O)O)cc1"]
def _batch():
    csv = os.path.join(OUT, "acceptance-report.csv")
    r = cc.batch_clean(MESSY, out_csv=csv)
    lines = [f"共 {r['total']} 行 → 通过 {r['ok']} · 警告 {r['warn']} · 失败 {r['failed']}",
             f"报告 CSV：{r['csv']}"]
    for it in r["failed_items"]:
        lines.append(f"  第{it['index']}行 {it['input']}: {it['reason'][:44]}…")
    return "\n".join(lines)
step("批量清洗 + 失败清单", _batch)

print("\n【8】诊断语言可切换（英文使用者）")
step("同一坏输入的中英文", lambda:
     "zh: " + cc.check("C1CC").diagnostics[-1].message[:34] + "…\n"
     "en: " + cc.check("C1CC", lang="en").diagnostics[-1].message[:34] + "…")

print(f"\n{'='*52}\n通过 {len(PASS)} 项")
for t, why in FAIL:
    print(f"  ✗ {t}: {why}")
if not FAIL:
    print("全部通过 ✅")
print(f"\n产物都在 {OUT} —— 用文件管理器打开就能看结构图。")
sys.exit(1 if FAIL else 0)
