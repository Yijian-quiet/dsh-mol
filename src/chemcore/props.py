"""分子性质计算（纯本地，无网络）。

数值口径以 RDKit 默认为准：
- ``mw`` / ``exact_mw`` 单位 Da
- ``logp`` 为 Crippen 贡献法估算值（**不是实验值**，工具输出里会标注）
- ``tpsa`` 单位 Å²
"""

from __future__ import annotations

from typing import Any

from rdkit import Chem
from rdkit.Chem import Crippen, Descriptors, rdMolDescriptors

from ._rdkit import mol_from_smiles
from .i18n import t
from .validate import check


def _mol_or_raise(smiles: str):
    r = check(smiles)
    if not r.ok:
        reason = "；".join(d.message for d in r.diagnostics) or "无法解析"
        raise ValueError(t("err_smiles_parse", reason))
    return mol_from_smiles(smiles), r


def properties(smiles: str) -> dict[str, Any]:
    """计算常用分子性质。失败时抛 ``ValueError``（附人话原因）。"""
    mol, checked = _mol_or_raise(smiles)

    ri = mol.GetRingInfo()
    chiral = Chem.FindMolChiralCenters(mol, includeUnassigned=True,
                                       useLegacyImplementation=False)
    unassigned = [idx for idx, tag in chiral if tag == "?"]

    result: dict[str, Any] = {
        "input": smiles,
        "canonical": checked.canonical,
        "formula": checked.formula,
        "mw": round(Descriptors.MolWt(mol), 4),
        "exact_mw": round(Descriptors.ExactMolWt(mol), 6),
        "logp": round(Crippen.MolLogP(mol), 4),
        "tpsa": round(rdMolDescriptors.CalcTPSA(mol), 4),
        "hbd": rdMolDescriptors.CalcNumHBD(mol),
        "hba": rdMolDescriptors.CalcNumHBA(mol),
        "rotatable_bonds": rdMolDescriptors.CalcNumRotatableBonds(mol),
        "heavy_atoms": mol.GetNumHeavyAtoms(),
        "rings": ri.NumRings(),
        "aromatic_rings": rdMolDescriptors.CalcNumAromaticRings(mol),
        "aliphatic_rings": rdMolDescriptors.CalcNumAliphaticRings(mol),
        "saturated_rings": rdMolDescriptors.CalcNumSaturatedRings(mol),
        "heteroatoms": rdMolDescriptors.CalcNumHeteroatoms(mol),
        "formal_charge": Chem.GetFormalCharge(mol),
        "fraction_csp3": round(rdMolDescriptors.CalcFractionCSP3(mol), 4),
        "stereocenters": len(chiral),
        "stereocenters_unassigned": len(unassigned),
        # 口径声明：让模型/人别把估算值当实验值
        "_notes": {
            "logp": "Crippen 估算值，非实验值",
            "mw": "平均分子量（含同位素丰度加权）",
            "exact_mw": "单同位素精确质量",
        },
    }
    return result


def descriptors_available() -> list[str]:
    """列出可用的 RDKit 描述符名（供后续扩展 / 调试）。"""
    return sorted(Descriptors._descList and [n for n, _ in Descriptors._descList] or [])
