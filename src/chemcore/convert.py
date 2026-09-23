"""格式互转：SMILES ↔ InChI ↔ InChIKey ↔ MOL block ↔ SDF。

只做**本地**转换，不查任何网络服务。名称→结构（OPSIN 等）与图像→结构
（OCSR）属于重依赖能力，不在本模块范围内。
"""

from __future__ import annotations

from typing import Any

from rdkit import Chem
from rdkit.Chem import rdMolDescriptors

from ._rdkit import mol_from_smiles
from .validate import check

FORMATS = ("smiles", "inchi", "inchikey", "mol", "sdf", "formula")


def sniff(text: str) -> str:
    """猜输入格式（够用即可，不求完备）。"""
    t = text.strip()
    if t.startswith("InChI="):
        return "inchi"
    if "V2000" in t or "V3000" in t or "M  END" in t or t.startswith("$$$$"):
        return "sdf" if "$$$$" in t else "mol"
    if "-" in t.split("\n", 1)[0] and len(t) == 27 and t.count("-") == 2:
        return "inchikey"
    return "smiles"


def _mol_from_block(block: str):
    """解析 MOL/SDF 结构块。

    坑：RDKit 生成的 molblock 第一行是**空行**（分子名占位）。如果调用方
    或聊天界面把首行空白吃掉，整体会上移一行、解析必失败。所以这里两种
    排布都试一次，而不是假设输入是干净的。
    """
    from ._rdkit import capture_log

    for candidate in (block, "\n" + block.lstrip("\n")):
        with capture_log():
            mol = Chem.MolFromMolBlock(candidate, sanitize=True)
        if mol is not None:
            return mol
    return None


def _to_mol(value: str, src: str):
    src = src.lower()
    if src == "smiles":
        r = check(value)
        if not r.ok:
            raise ValueError("SMILES 无法解析：" + "；".join(d.message for d in r.diagnostics))
        return mol_from_smiles(value)
    if src == "inchi":
        mol = Chem.MolFromInchi(value.strip())
        if mol is None:
            raise ValueError("InChI 无法解析（检查前缀 InChI= 与校验位）")
        return mol
    if src in ("mol", "sdf"):
        block = value
        if "$$$$" in block:          # 多记录 SDF：只取第一条
            block = block.split("$$$$")[0]
        mol = _mol_from_block(block)
        if mol is None:
            raise ValueError("MOL/SDF 结构块无法解析（检查是否缺少标题行或原子块被截断）")
        return mol
    if src == "inchikey":
        raise ValueError("InChIKey 是单向摘要，无法反推结构")
    raise ValueError(f"不支持的源格式：{src}")


def convert(value: str, *, to: str, src: str | None = None) -> dict[str, Any]:
    """转换单个结构。``src`` 缺省时自动嗅探。"""
    to = to.lower()
    if to not in FORMATS:
        raise ValueError(f"目标格式须是 {FORMATS} 之一，收到 {to!r}")
    src = (src or sniff(value)).lower()

    # InChIKey 是只读派生：直接从分子算，不需要先转成别的
    mol = _to_mol(value, src)

    if to == "smiles":
        out = Chem.MolToSmiles(mol)
    elif to == "inchi":
        out = Chem.MolToInchi(mol)
    elif to == "inchikey":
        out = Chem.MolToInchiKey(mol)
    elif to == "mol":
        out = Chem.MolToMolBlock(mol)
    elif to == "sdf":
        out = Chem.MolToMolBlock(mol) + "\n$$$$\n"
    elif to == "formula":
        out = rdMolDescriptors.CalcMolFormula(mol)
    else:  # pragma: no cover - 上面已校验
        raise ValueError(to)

    return {"from": src, "to": to, "value": out}


def convert_many(values: list[str], *, to: str, src: str | None = None) -> dict[str, Any]:
    """批量转换，逐条报告失败而不是整体失败。"""
    results, failures = [], []
    for i, v in enumerate(values):
        try:
            results.append({"index": i, **convert(v, to=to, src=src)})
        except ValueError as exc:
            failures.append({"index": i, "value": v, "error": str(exc)})
    return {"to": to, "ok": len(results), "failed": len(failures),
            "results": results, "failures": failures}
