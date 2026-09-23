"""子结构匹配与相似度（纯本地）。

用途：查一批分子里谁含某个骨架、两个分子有多像、找重复/近似重复。
指纹一律本地计算，不依赖任何模型文件。
"""

from __future__ import annotations

from typing import Any

from rdkit import Chem, DataStructs
from rdkit.Chem import rdFingerprintGenerator

from ._rdkit import mol_from_smiles
from .i18n import t
from .validate import check

_FP_KINDS = ("morgan", "rdkit", "maccs")


def _fp(mol, kind: str = "morgan", radius: int = 2, n_bits: int = 2048):
    kind = kind.lower()
    if kind == "morgan":
        gen = rdFingerprintGenerator.GetMorganGenerator(radius=radius, fpSize=n_bits)
        return gen.GetFingerprint(mol)
    if kind == "rdkit":
        gen = rdFingerprintGenerator.GetRDKitFPGenerator(fpSize=n_bits)
        return gen.GetFingerprint(mol)
    if kind == "maccs":
        from rdkit.Chem import MACCSkeys
        return MACCSkeys.GenMACCSKeys(mol)
    raise ValueError(t("err_bad_fp", _FP_KINDS, repr(kind)))


def substructure_match(smiles: str, smarts: str, *, max_matches: int = 50) -> dict[str, Any]:
    """在分子里找 SMARTS 子结构，返回匹配的原子索引。

    典型用途：确认某个官能团在不在、定位要高亮的原子。
    """
    r = check(smiles)
    if not r.ok:
        raise ValueError(t("err_smiles_parse", "；".join(d.message for d in r.diagnostics)))
    patt = Chem.MolFromSmarts(smarts)
    if patt is None:
        raise ValueError(t("err_smarts_parse", repr(smarts)))
    mol = mol_from_smiles(smiles)
    if mol is None:
        raise ValueError(t("err_smiles_parse", ""))
    if not mol.HasSubstructMatch(patt):
        return {"matched": False, "count": 0, "matches": [], "canonical": r.canonical}
    all_matches = mol.GetSubstructMatches(patt, uniquify=True, maxMatches=max_matches)
    return {
        "matched": True,
        "count": len(all_matches),
        "matches": [list(m) for m in all_matches],
        "canonical": r.canonical,
    }


def similarity(a: str, b: str, *, kind: str = "morgan", metric: str = "tanimoto") -> dict[str, Any]:
    """两个分子的指纹相似度。"""
    ma, mb = mol_from_smiles(a), mol_from_smiles(b)
    for label, m, s in (("a", ma, a), ("b", mb, b)):
        if m is None:
            raise ValueError(t("err_mol_parse_labeled", label, repr(s)))
    fa, fb = _fp(ma, kind), _fp(mb, kind)
    if metric.lower() == "tanimoto":
        score = DataStructs.TanimotoSimilarity(fa, fb)
    elif metric.lower() in ("dice", "diceSimilarity".lower()):
        score = DataStructs.DiceSimilarity(fa, fb)
    else:
        raise ValueError(t("err_bad_metric"))
    return {"a": a, "b": b, "fingerprint": kind.lower(), "metric": metric.lower(),
            "score": round(float(score), 4)}


def find_similar(
    query: str,
    pool: list[str],
    *,
    threshold: float = 0.5,
    kind: str = "morgan",
    top_k: int = 20,
) -> dict[str, Any]:
    """在一批分子中按相似度排序，返回超过阈值的前 ``top_k`` 个。"""
    mq = mol_from_smiles(query)
    if mq is None:
        raise ValueError(t("err_query_parse", repr(query)))
    fq = _fp(mq, kind)
    hits, failures = [], []
    for i, smi in enumerate(pool):
        m = mol_from_smiles(smi)
        if m is None:
            failures.append({"index": i, "smiles": smi, "error": "无法解析"})
            continue
        score = float(DataStructs.TanimotoSimilarity(fq, _fp(m, kind)))
        if score >= threshold:
            hits.append({"index": i, "smiles": smi, "score": round(score, 4)})
    hits.sort(key=lambda h: -h["score"])
    return {"query": query, "fingerprint": kind.lower(), "threshold": threshold,
            "hits": hits[:top_k], "failures": failures}
