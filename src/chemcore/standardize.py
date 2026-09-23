"""结构标准化：去盐 / 去溶剂 / 中和 / 规范化 / 去重。

RDKit ``MolStandardize`` 的封装。每一步都记录**改了什么**，因为标准化会
悄悄改变结构 —— 如果只返回结果不返回变更，用户无法判断该不该信任它。
"""

from __future__ import annotations

from typing import Any

from rdkit import Chem

from ._rdkit import capture_log, mol_from_smiles
from .validate import check


def _smiles_of(mol) -> str:
    return Chem.MolToSmiles(mol) if mol is not None else ""


def standardize(
    smiles: str,
    *,
    strip_salts: bool = True,
    desolvate: bool = True,
    uncharge: bool = True,
    canonical_tautomer: bool = False,
    normalize: bool = True,
) -> dict[str, Any]:
    """标准化一个结构，返回结果 + 逐步变更记录。

    Args:
        strip_salts: 只保留最大片段（去盐 / 去反离子）。
        desolvate: 断开金属-有机键（去溶剂化金属）。
        uncharge: 尽量中和电荷。
        canonical_tautomer: 取规范互变异构体（**会改变结构**，默认关闭）。
        normalize: 应用 RDKit 标准规范化规则。
    """
    from rdkit.Chem.MolStandardize import rdMolStandardize

    from ._rdkit import capture_log

    r = check(smiles)
    if not r.ok:
        raise ValueError("SMILES 无法解析：" + "；".join(d.message for d in r.diagnostics))

    mol = mol_from_smiles(smiles)
    changes: list[dict[str, str]] = []

    def step(name: str, fn) -> None:
        nonlocal mol
        before = _smiles_of(mol)
        try:
            # MolStandardize 会往 stderr 刷大量过程日志（Initializing Normalizer…），
            # 那是实现细节，不该出现在工具输出里，这里吞掉。
            with capture_log():
                out = fn(mol)
        except Exception as exc:  # RDKit 各版本 API 有漂移，不让单步炸掉整个流程
            changes.append({"step": name, "error": str(exc), "before": before})
            return
        if out is not None:
            mol = out
        after = _smiles_of(mol)
        changes.append({"step": name, "before": before, "after": after,
                        "changed": str(before != after)})

    if desolvate:
        step("metal_disconnect",
             lambda m: rdMolStandardize.MetalDisconnector().Disconnect(m))
    if strip_salts:
        step("largest_fragment",
             lambda m: rdMolStandardize.LargestFragmentChooser().choose(m))
    if normalize:
        step("normalize", lambda m: rdMolStandardize.Normalizer().normalize(m))
    if uncharge:
        step("uncharge", lambda m: rdMolStandardize.Uncharger().uncharge(m))
    if canonical_tautomer:
        step("canonical_tautomer",
             lambda m: rdMolStandardize.TautomerEnumerator().Canonicalize(m))
    step("cleanup", lambda m: rdMolStandardize.Cleanup(m))

    result_smiles = _smiles_of(mol)
    return {
        "input": smiles,
        "output": result_smiles,
        "changed": result_smiles != r.canonical,
        "canonical_input": r.canonical,
        "changes": changes,
    }


def dedupe(smiles_list: list[str], *, standardize_first: bool = False) -> dict[str, Any]:
    """按规范化结构去重，保留首次出现顺序，并给出重复分组。

    标准化**默认不开启**：去重应该基于用户给的结构，而非被算法改过的结构。
    """
    seen: dict[str, int] = {}
    unique: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for i, smi in enumerate(smiles_list):
        if standardize_first:
            try:
                key = standardize(smi)["output"]
            except ValueError as exc:
                failures.append({"index": i, "smiles": smi, "error": str(exc)})
                continue
        else:
            r = check(smi)
            if not r.ok:
                failures.append({"index": i, "smiles": smi,
                                 "error": "；".join(d.message for d in r.diagnostics)})
                continue
            key = r.canonical
        if key in seen:
            duplicates.append({"index": i, "smiles": smi,
                               "duplicate_of_index": seen[key], "canonical": key})
        else:
            seen[key] = i
            unique.append({"index": i, "input": smi, "canonical": key})

    return {"total": len(smiles_list), "unique": len(unique),
            "duplicates": duplicates, "failures": failures, "items": unique}
