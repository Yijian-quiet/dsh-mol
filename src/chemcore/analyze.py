"""分子"深看一层"的分析：类药性规则、结构警报、骨架。

为什么单独一个模块：``props.properties`` 只回答"这个分子多大多重多油"，
而药物化学的人接着会问"像不像药""有没有毒理警戒结构""骨架是什么"。
这三类问题的口径（阈值来自文献）和计算方式都不一样，混进 properties 会让
那个函数的返回值越来越像杂物抽屉。所以这里独立成模块，各自说清口径。

阈值出处（都在函数里标注，避免被当成 RDKit 默认值）：
- Lipinski 五规则：Lipinski et al., Adv. Drug Deliv. Rev. 1997/2001
- Veber 规则：Veber et al., J. Med. Chem. 2002
- QED：Bickerton et al., Nat. Chem. 2012
- PAINS / BRENK / NIH 结构警报：RDKit 内置 FilterCatalog
"""

from __future__ import annotations

from typing import Any, Iterable

from rdkit import Chem
from rdkit.Chem import QED, Descriptors
from rdkit.Chem.FilterCatalog import FilterCatalog, FilterCatalogParams
from rdkit.Chem.Scaffolds import MurckoScaffold

from ._rdkit import mol_from_smiles
from .props import properties, _mol_or_raise

#: 结构警报目录名 → RDKit 枚举成员。默认查这两个：
#: PAINS（泛筛选干扰化合物，Baell & Holloway 2010）和 BRENK（不良骨架/官能团）。
#: NIH / ZINC 也可以查，但误报更多，默认不开，需要时用 catalogs= 显式传。
DEFAULT_CATALOGS = ("PAINS", "BRENK")
KNOWN_CATALOGS = ("PAINS", "PAINS_A", "PAINS_B", "PAINS_C", "BRENK", "NIH", "ZINC")


def _catalog(name: str) -> FilterCatalog:
    params = FilterCatalogParams()
    try:
        params.AddCatalog(getattr(FilterCatalogParams.FilterCatalogs, name))
    except AttributeError as error:  # pragma: no cover - 取决于 RDKit 版本
        raise ValueError(
            f"这个 RDKit 构建里没有结构警报目录 {name!r}；可用：{', '.join(KNOWN_CATALOGS)}"
        ) from error
    return FilterCatalog(params)


def druglikeness(smiles: str, *, catalogs: Iterable[str] = DEFAULT_CATALOGS,
                 max_alerts: int = 20) -> dict[str, Any]:
    """类药性 + 结构警报。

    返回的 ``rules`` 每一项都是 ``{rule, passed, detail}`` —— **不返回一个总评**，
    因为"是否成药"不是这些阈值的与运算，交给人/模型看细节更好。
    """
    mol, checked = _mol_or_raise(smiles)

    mw = Descriptors.MolWt(mol)
    logp = Descriptors.MolLogP(mol)
    hbd = Descriptors.NumHDonors(mol)
    hba = Descriptors.NumHAcceptors(mol)
    tpsa = Descriptors.TPSA(mol)
    rot = Descriptors.NumRotatableBonds(mol)

    # Lipinski：MW/捐氢/受氢/logP 四项，违反 ≥2 项通常意味着口服吸收堪忧。
    # 注意 HBD/HBA 这里用 RDKit 的 NumHDonors/NumHAcceptors（Lipinski 原始定义口径），
    # 与 properties 里的 CalcNumHBD/CalcNumHBA（更严格的 SMARTS 口径）**可能差 1**，
    # 这是两个口径并存，不是 bug。
    lipinski_checks = [
        ("MW ≤ 500", mw <= 500, f"{mw:.1f}"),
        ("logP ≤ 5", logp <= 5, f"{logp:.2f}"),
        ("氢键给体 ≤ 5", hbd <= 5, str(hbd)),
        ("氢键受体 ≤ 10", hba <= 10, str(hba)),
    ]
    lipinski_failures = [name for name, ok, _ in lipinski_checks if not ok]

    rules: list[dict[str, Any]] = [
        {"rule": name, "passed": ok, "detail": detail}
        for name, ok, detail in lipinski_checks
    ]
    rules += [
        # Veber：可旋转键 ≤10 且 TPSA ≤140 Å² → 口服生物利用度通常够
        {"rule": "可旋转键 ≤ 10", "passed": rot <= 10, "detail": str(rot)},
        {"rule": "TPSA ≤ 140 Å²", "passed": tpsa <= 140, "detail": f"{tpsa:.1f}"},
    ]

    alerts: list[dict[str, str]] = []
    for name in catalogs:
        catalog = _catalog(name)
        for entry in catalog.GetMatches(mol):
            alerts.append({"catalog": name, "description": entry.GetDescription()})
    truncated = len(alerts) > max_alerts
    alerts = alerts[:max_alerts]

    scaffold = MurckoScaffold.MurckoScaffoldSmiles(mol=mol) or ""
    generic = ""
    if scaffold:
        core = Chem.MolFromSmiles(scaffold)
        if core is not None:
            generic = Chem.MolToSmiles(MurckoScaffold.MakeScaffoldGeneric(core))

    return {
        "input": smiles,
        "canonical": checked.canonical,
        "formula": checked.formula,
        "qed": round(QED.qed(mol), 4),
        "qed_note": "QED 0-1，越大越接近已知药物的性质分布（Bickerton 2012 口径，不是活性预测）",
        "molar_refractivity": round(Descriptors.MolMR(mol), 3),
        "lipinski_violations": len(lipinski_failures),
        "lipinski_failed_rules": lipinski_failures,
        "rules": rules,
        "structural_alerts": alerts,
        "structural_alerts_truncated": truncated,
        "catalogs_checked": list(catalogs),
        "murcko_scaffold": scaffold,
        "murcko_scaffold_generic": generic,
        "scaffold_note": "Murcko 骨架：去掉侧链只留环系与连接子；generic 版把所有原子类型抹平",
    }


def analyze(smiles: str) -> dict[str, Any]:
    """一次给全：基础性质 + 类药性 + 骨架。工作台"分析"页签用的就是这个。"""
    base = properties(smiles)
    deep = druglikeness(smiles)
    return {
        "input": smiles,
        "canonical": base["canonical"],
        "formula": base["formula"],
        # 基础性质直接摊平，前端不用再钻一层
        "properties": base,
        "druglikeness": deep,
    }
