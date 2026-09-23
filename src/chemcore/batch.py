"""批量清洗：一列 SMILES 进，一份带失败清单的 CSV 出。

这个模块解决的是科研里最常见的一件脏活：手里的表格有几百上千行 SMILES，
格式不统一、有错字、有重复、有盐。**关键要求是「不许静默丢数据」**：
每一行都要有明确归属（通过 / 警告 / 失败）并写进报告。
"""

from __future__ import annotations

import csv
import io
import os
from pathlib import Path
from typing import Any, Iterable, Sequence

from .props import properties
from .validate import check

_PROPS_COLUMNS = [
    "formula", "mw", "exact_mw", "logp", "tpsa", "hbd", "hba",
    "rotatable_bonds", "heavy_atoms", "aromatic_rings", "formal_charge",
]


def read_smiles_column(path: str | os.PathLike[str], column: str | None = None) -> list[str]:
    """从 CSV/TSV/TXT 读取 SMILES 列。

    CSV 有表头时按 ``column`` 取列（缺省猜测：名字含 smiles/smiles/structure
    的列，否则第一列）。纯 TXT 则一行一个。
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8-sig", errors="replace")
    if p.suffix.lower() in (".txt", ".smi") and "," not in text.split("\n", 1)[0]:
        return [ln.strip() for ln in text.splitlines() if ln.strip()]

    dialect = "\t" if "\t" in text.split("\n", 1)[0] else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=dialect))
    if not rows:
        return []
    header = [h.strip().lower() for h in rows[0]]
    looks_like_header = any(
        h in ("smiles", "smi", "structure", "canonical_smiles", "分子", "结构") or "smiles" in h
        for h in header
    )
    if not looks_like_header:
        return [r[0].strip() for r in rows if r and r[0].strip()]

    idx = 0
    if column:
        if column.lower() not in header:
            raise ValueError(t("err_csv_column", repr(column), header))
        idx = header.index(column.lower())
    else:
        for i, h in enumerate(header):
            if "smiles" in h or h in ("smi", "structure", "分子", "结构"):
                idx = i
                break
    return [r[idx].strip() for r in rows[1:] if len(r) > idx and r[idx].strip()]


def batch_clean(
    smiles_list: Sequence[str],
    *,
    out_csv: str | os.PathLike[str] | None = None,
    with_props: bool = True,
) -> dict[str, Any]:
    """批量校验/规范化，可选计算性质，并写出报告 CSV。

    Returns:
        摘要（计数 + 失败清单 + 警告清单）与 ``csv`` 路径（若写出）。
    """
    ok_rows, warn_rows, failed = [], [], []
    for i, smi in enumerate(smiles_list):
        r = check(smi)
        if not r.ok:
            failed.append({
                "index": i, "input": smi, "error_level": r.level,
                "reason": "；".join(d.message for d in r.diagnostics),
            })
            continue
        row: dict[str, Any] = {"index": i, "input": smi, "canonical": r.canonical,
                               "formula": r.formula, "level": r.level}
        if r.level == "warn":
            row["warnings"] = "；".join(d.message for d in r.diagnostics)
            warn_rows.append(row)
        else:
            ok_rows.append(row)
        if with_props:
            try:
                p = properties(smi)
                row.update({k: p.get(k) for k in _PROPS_COLUMNS})
            except ValueError as exc:
                row["props_error"] = str(exc)

    summary: dict[str, Any] = {
        "total": len(smiles_list),
        "ok": len(ok_rows),
        "warn": len(warn_rows),
        "failed": len(failed),
        "failed_items": failed,
        "warn_items": [{"index": r["index"], "input": r["input"],
                        "warnings": r.get("warnings")} for r in warn_rows],
    }
    if out_csv:
        path = Path(out_csv)
        if path.parent and str(path.parent) not in ("", "."):
            path.parent.mkdir(parents=True, exist_ok=True)
        cols = ["index", "input", "canonical", "formula", "level", "warnings"] + \
               (_PROPS_COLUMNS if with_props else [])
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for row in ok_rows + warn_rows:
                w.writerow(row)
        summary["csv"] = str(path.resolve())
    return summary
