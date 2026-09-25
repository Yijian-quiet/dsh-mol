"""格式互转：SMILES ↔ InChI ↔ InChIKey ↔ MOL block ↔ SDF。

只做**本地**转换，不查任何网络服务。名称→结构（OPSIN 等）与图像→结构
（OCSR）属于重依赖能力，不在本模块范围内。
"""

from __future__ import annotations

from typing import Any

from rdkit import Chem
from rdkit.Chem import rdMolDescriptors

from ._rdkit import capture_log, mol_from_smiles
from .i18n import t
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
            raise ValueError(t("err_smiles_parse", "；".join(d.message for d in r.diagnostics)))
        return mol_from_smiles(value)
    if src == "inchi":
        mol = Chem.MolFromInchi(value.strip())
        if mol is None:
            raise ValueError(t("err_inchi_parse"))
        return mol
    if src in ("mol", "sdf"):
        block = value
        if "$$$$" in block:          # 多记录 SDF：只取第一条
            block = block.split("$$$$")[0]
        mol = _mol_from_block(block)
        if mol is None:
            raise ValueError(t("err_molblock_parse"))
        return mol
    if src == "inchikey":
        raise ValueError(t("err_inchikey_readonly"))
    raise ValueError(t("err_bad_src_format", src))


def convert(value: str, *, to: str, src: str | None = None) -> dict[str, Any]:
    """转换单个结构。``src`` 缺省时自动嗅探。"""
    to = to.lower()
    if to not in FORMATS:
        raise ValueError(t("err_bad_dst_format", FORMATS, repr(to)))
    src = (src or sniff(value)).lower()

    # InChIKey 是只读派生：直接从分子算，不需要先转成别的
    mol = _to_mol(value, src)

    if to == "smiles":
        out = Chem.MolToSmiles(mol)
    elif to == "inchi":
        # RDKit 生成 InChI 失败时**返回空串而不抛异常**（例如含 * 虚原子的
        # 聚合物 RU-SMILES —— 领域里最常见的输入）。静默返回 '' 是错答案，
        # 必须显式报错，否则调用方会把它当成"成功的空值"。
        # 同时捕获日志：InChI 失败会往 stderr 打 "Unsupported ... element '*'"
        # 这类噪声，不该出现在工具输出里。
        with capture_log():
            out = Chem.MolToInchi(mol)
        if not out:
            raise ValueError(t("err_inchi_unsupported"))
    elif to == "inchikey":
        with capture_log():
            out = Chem.MolToInchiKey(mol)
        if not out:
            raise ValueError(t("err_inchikey_unsupported"))
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
