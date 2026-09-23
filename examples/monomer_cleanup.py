#!/usr/bin/env python3
"""实例：一列"脏"单体 SMILES → 清洗报告 + 去重 + 结构图。

模拟真实科研场景：手头的表格来自不同来源，格式不统一、有重复（同一个分子
写成不同形式）、有盐、有错字。目标不是"跑通"，而是**一个数据都不能悄悄丢**。

运行：
    PYTHONPATH=src python3 examples/monomer_cleanup.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import chemcore as cc  # noqa: E402

# 聚酯/聚酰胺常见单体，故意混入各种"脏"：
#   - 同一个分子两种写法（乳酸：带/不带立体化学）
#   - 盐形式（己二酸单钠盐）
#   - 重复项（对苯二甲酸写了两遍，一个不规范）
#   - 错字（环未闭合、元素大小写错）
MESSY = [
    ("CC(O)C(=O)O", "乳酸"),            # 乳酸，无立体标记
    ("C[C@H](O)C(=O)O", "L-乳酸"),      # 同一个分子的立体异构写法
    ("OCC(O)CO", "甘油"),
    ("OC(=O)c1ccccc1C(=O)O", "邻苯二甲酸"),
    ("OC(=O)c1ccc(cc1)C(=O)O", "对苯二甲酸"),
    ("O=C(O)c1ccc(C(=O)O)cc1", "对苯二甲酸(另一写法，重复)"),
    ("OCCO", "乙二醇"),
    ("NCCCCCCN", "己二胺"),
    ("OC(=O)CCCCC(=O)[O-].[Na+]", "己二酸单钠盐(含盐)"),
    ("OC(=O)CCCCC(=O)O", "己二酸"),
    ("C1CC", "环未闭合(错字)"),
    ("c1ccccc1Cl", "氯苯"),
    ("C(C)(C)(C)(C)C", "价键超限(错字)"),
    ("[Fe+9]", "电荷异常(可疑)"),
]


def main() -> int:
    out = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "out"))
    os.makedirs(out, exist_ok=True)

    smiles = [s for s, _ in MESSY]
    names = [n for _, n in MESSY]

    print(f"输入 {len(smiles)} 条 —— 来自一张手工维护的单体表\n")

    csv_path = os.path.join(out, "monomer-report.csv")
    report = cc.batch_clean(smiles, out_csv=csv_path)

    print("【1】批量清洗")
    print(f"  通过 {report['ok']} · 警告 {report['warn']} · 失败 {report['failed']}")
    for item in report["failed_items"]:
        print(f"    ✗ 第{item['index']:>2}行 {item['input']:<28} {item['reason']}")
    for item in report["warn_items"]:
        print(f"    ⚠ 第{item['index']:>2}行 {item['input']:<28} {item['warnings']}")
    print(f"  报告 → {csv_path}")

    print("\n【2】结构去重（同一分子不同写法会被合并）")
    dedup = cc.dedupe(smiles)
    print(f"  {dedup['total']} 条 → 唯一 {dedup['unique']} · 重复 {len(dedup['duplicates'])}"
          f" · 失败 {len(dedup['failures'])}")
    for d in dedup["duplicates"]:
        print(f"    = 第{d['index']}行 与 第{d['duplicate_of_index']}行 是同一物：{d['canonical']}")

    print("\n【3】盐形式标准化")
    salt = "OC(=O)CCCCC(=O)[O-].[Na+]"
    std = cc.standardize(salt)
    print(f"  {salt}\n    → {std['output']}")
    for step in std["changes"]:
        if step.get("changed") == "True":
            print(f"    · {step['step']}: {step['before']} → {step['after']}")

    print("\n【4】画结构图（整列原样交给工具，坏的由它跳过并逐条记录）")
    grid = cc.draw_grid(smiles, legends=names, out=out, mols_per_row=4,
                        filename="monomers.png")
    print(f"  画出 {grid['count']} 个 → {grid['path']}")
    print(f"  跳过 {len(grid['skipped'])} 个（原因逐条记录，没有静默丢弃）：")
    for s in grid["skipped"]:
        print(f"    ✗ 第{s['index']:>2}行 {s['smiles']:<20} {s['reason'][:52]}")

    print("\n【5】性质速查（前 3 个）")
    for s, n in [(s, n) for s, n in MESSY if cc.check(s).ok][:3]:
        p = cc.properties(s)
        print(f"  {n:<12} {p['formula']:<10} MW={p['mw']:<8} logP={p['logp']:<7} "
              f"HBD={p['hbd']} HBA={p['hba']}")

    print("\n完成。所有产物都在", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
