"""画分子：SMILES → PNG / SVG（纯本地，Cairo 渲染）。

设计取舍
--------
工具**只负责落盘并返回路径**，不返回二进制。这样：
- DSH / 任何 MCP 客户端都能用 `present` / 附件机制显示它（已在 dsh 侧验证可行）；
- 同一次结果可被反复引用、进版本库、写进论文；
- MCP 传输层不必承载 base64。

输出目录默认 ``$CHEMWORKBENCH_OUT``，否则 ``./chemworkbench-out``。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Iterable, Sequence

from rdkit import Chem
from rdkit.Chem import Draw
from rdkit.Chem.Draw import rdMolDraw2D

from ._rdkit import mol_from_smiles
from .validate import check

_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def out_dir(base: str | os.PathLike[str] | None = None) -> Path:
    """解析输出目录并确保存在。"""
    p = Path(base or os.environ.get("CHEMWORKBENCH_OUT", "chemworkbench-out"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe_name(smiles: str, fallback: str = "mol") -> str:
    s = _SAFE.sub("_", smiles)[:48].strip("_")
    return s or fallback


def _highlight(mol, smarts: str | None):
    if not smarts:
        return None, None
    patt = Chem.MolFromSmarts(smarts)
    if patt is None:
        raise ValueError(f"SMARTS 无法解析：{smarts}")
    match = mol.GetSubstructMatch(patt)
    if not match:
        return None, None
    atoms = set(match)
    bonds: set[int] = set()
    for a in atoms:
        for b in mol.GetAtomWithIdx(a).GetBonds():
            if b.GetOtherAtomIdx(a) in atoms:
                bonds.add(b.GetIdx())
    return atoms, bonds


def draw(
    smiles: str,
    *,
    out: str | os.PathLike[str] | None = None,
    fmt: str = "png",
    width: int = 640,
    height: int = 480,
    atom_indices: bool = False,
    highlight_smarts: str | None = None,
    legend: str | None = None,
) -> dict[str, Any]:
    """把单个分子画成图片。

    Args:
        smiles: 输入 SMILES。
        out: 输出目录；缺省用 ``CHEMWORKBENCH_OUT`` 或 ``./chemworkbench-out``。
        fmt: ``png`` 或 ``svg``。
        width/height: 像素尺寸。
        atom_indices: 是否标注原子编号。
        highlight_smarts: 用 SMARTS 指定要高亮的子结构。
        legend: 图注（仅 PNG 的 PNG 元数据之外，SVG 会作为文本写入）。

    Returns:
        ``{"path": ..., "format": ..., "bytes": ..., "smiles": ..., "canonical": ...}``
    """
    fmt = fmt.lower().lstrip(".")
    if fmt not in ("png", "svg"):
        raise ValueError(f"只支持 png / svg，收到 {fmt!r}")

    r = check(smiles)
    if not r.ok:
        reason = "；".join(d.message for d in r.diagnostics) or "无法解析"
        raise ValueError(f"SMILES 无法解析：{reason}")
    mol = mol_from_smiles(smiles)

    atoms, bonds = _highlight(mol, highlight_smarts)

    if fmt == "png":
        d = rdMolDraw2D.MolDraw2DCairo(width, height)
    else:
        d = rdMolDraw2D.MolDraw2DSVG(width, height)
    opts = d.drawOptions()
    opts.addAtomIndices = atom_indices
    if legend:
        opts.legendFontSize = 14
    rdMolDraw2D.PrepareAndDrawMolecule(
        d, mol, legend=legend or "",
        highlightAtoms=sorted(atoms) if atoms else None,
        highlightBonds=sorted(bonds) if bonds else None,
    )
    d.FinishDrawing()
    payload = d.GetDrawingText()
    data = payload.encode("utf-8") if isinstance(payload, str) else payload

    path = out_dir(out) / f"{_safe_name(smiles)}.{fmt}"
    path.write_bytes(data)
    return {
        "path": str(path.resolve()),
        "format": fmt,
        "bytes": len(data),
        "smiles": smiles,
        "canonical": r.canonical,
        "highlighted": bool(atoms),
        "level": r.level,
    }


def draw_grid(
    smiles_list: Sequence[str],
    *,
    out: str | os.PathLike[str] | None = None,
    legends: Iterable[str] | None = None,
    mols_per_row: int = 4,
    sub_img_size: tuple[int, int] = (300, 240),
    filename: str = "grid.png",
) -> dict[str, Any]:
    """把多个分子拼成一张网格图（适合做批量汇报 / 论文附图）。

    无法解析的条目会被跳过，并在 ``skipped`` 里逐条给出原因 —— 批量场景下
    「静默丢数据」比报错更危险。
    """
    mols, kept_legends, skipped = [], [], []
    for i, smi in enumerate(smiles_list):
        r = check(smi)
        if not r.ok:
            skipped.append({"index": i, "smiles": smi,
                            "reason": "；".join(d.message for d in r.diagnostics)})
            continue
        mols.append(mol_from_smiles(smi))
        if legends is not None:
            legends_list = list(legends)
            kept_legends.append(legends_list[i] if i < len(legends_list) else "")
    if not mols:
        raise ValueError("没有任何可画的分子（全部解析失败）")

    img = Draw.MolsToGridImage(
        mols, molsPerRow=mols_per_row, subImgSize=sub_img_size,
        legends=kept_legends or None,
    )
    path = out_dir(out) / filename
    if hasattr(img, "save"):
        img.save(path)
    else:  # 某些后端返回 SVG 字符串
        path.write_text(img)
    return {
        "path": str(path.resolve()),
        "count": len(mols),
        "skipped": skipped,
        "bytes": path.stat().st_size,
    }
