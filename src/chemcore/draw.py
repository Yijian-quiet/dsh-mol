"""画分子：SMILES → PNG / SVG（纯本地，Cairo 渲染）。

设计取舍
--------
工具**只负责落盘并返回路径**，不返回二进制。这样：
- DSH / 任何 MCP 客户端都能用 `present` / 附件机制显示它（已在 dsh 侧验证可行）；
- 同一次结果可被反复引用、进版本库、写进论文；
- MCP 传输层不必承载 base64。

输出目录默认 ``$MOL_OUT``，否则 ``./dsh-mol-out``。
"""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Sequence

from rdkit import Chem
from rdkit.Chem import Draw
from rdkit.Chem.Draw import rdMolDraw2D

from ._rdkit import mol_from_smiles
from .i18n import t
from .validate import check

_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")

# RDKit 自带字体不含 CJK；且系统上的中文字体多是 .ttc 字体集合，交给 RDKit
# （FreeType）会渲染成豆腐块 □□□□（本机实测）。因此中文图注一律由我们用 PIL
# 自行排版，不依赖 RDKit 的字体处理。
_CJK_FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
)


def find_cjk_font() -> str | None:
    """找一个能渲染中文的字体文件；找不到返回 None。"""
    for p in _CJK_FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def has_non_ascii(text: str | None) -> bool:
    """图注里是否含非 ASCII（即需要 CJK 字体）。"""
    return bool(text) and any(ord(ch) > 127 for ch in text)


def _pil_font(path: str, size: int):
    from PIL import ImageFont

    try:
        return ImageFont.truetype(path, size)
    except Exception:
        try:  # .ttc 是字体集合，需要指定 face 索引
            return ImageFont.truetype(path, size, index=0)
        except Exception:
            return None


def _annotate_legend(path: Path, text: str, *, size: int = 16) -> tuple[str | None, bool]:
    """给已落盘的 PNG 在底部补一行中文图注。

    Returns:
        ``(font_used_or_None, ok)``。找不到字体时返回 ``(None, False)``，
        调用方应据此**显式告警**，而不是交出缺字/豆腐块的图。
    """
    font_path = find_cjk_font()
    if not font_path:
        return None, False
    try:
        from PIL import Image, ImageDraw

        font = _pil_font(font_path, size)
        if font is None:
            return None, False
        img = Image.open(path).convert("RGB")
        draw = ImageDraw.Draw(img)
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        canvas = Image.new("RGB", (img.width, img.height + th + 14), "white")
        canvas.paste(img, (0, 0))
        d2 = ImageDraw.Draw(canvas)
        d2.text(((img.width - tw) / 2 - bbox[0], img.height + 8 - bbox[1]),
                text, fill="black", font=font)
        canvas.save(path)
        return font_path, True
    except Exception:
        return None, False


def out_dir(base: str | os.PathLike[str] | None = None) -> Path:
    """解析输出目录并确保存在。

    **未显式指定 ``base`` 时按日期再分一层**（``<MOL_OUT>/2026-09-25/``）：
    否则每分析一个分子就往同一个目录丢一个文件，很快成垃圾场
    （实测：一个下午就平铺了 4 个产物）。

    显式给了 ``base`` 就完全听调用方的 —— 上层（agent / 插件）可以用它做
    **按会话**分目录，那是比日期更细的组织粒度。
    """
    if base:
        p = Path(base)
    else:
        p = Path(os.environ.get("MOL_OUT", "dsh-mol-out")) / date.today().isoformat()
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
        raise ValueError(t("err_smarts_parse", smarts))
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


def _options_digest(*parts: Any) -> str:
    """渲染选项的短摘要（6 位十六进制），用于文件名去重。"""
    import hashlib

    payload = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:6]


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
        out: 输出目录；缺省用 ``MOL_OUT`` 或 ``./dsh-mol-out``。
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
        raise ValueError(t("err_bad_image_format", repr(fmt)))

    r = check(smiles)
    if not r.ok:
        reason = "；".join(d.message for d in r.diagnostics) or "无法解析"
        raise ValueError(t("err_smiles_parse", reason))
    mol = mol_from_smiles(smiles)

    atoms, bonds = _highlight(mol, highlight_smarts)

    # 中文图注不能交给 RDKit（会渲染成豆腐块），PNG 走"先画图、再用 PIL 补图注"
    legend_via_pil = fmt == "png" and has_non_ascii(legend)
    rdkit_legend = "" if legend_via_pil else (legend or "")

    if fmt == "png":
        d = rdMolDraw2D.MolDraw2DCairo(width, height)
    else:
        d = rdMolDraw2D.MolDraw2DSVG(width, height)
    opts = d.drawOptions()
    opts.addAtomIndices = atom_indices
    if rdkit_legend:
        opts.legendFontSize = 14
    rdMolDraw2D.PrepareAndDrawMolecule(
        d, mol, legend=rdkit_legend,
        highlightAtoms=sorted(atoms) if atoms else None,
        highlightBonds=sorted(bonds) if bonds else None,
    )
    d.FinishDrawing()
    payload = d.GetDrawingText()
    data = payload.encode("utf-8") if isinstance(payload, str) else payload

    # 文件名带上"渲染选项"的短摘要：否则同一分子用不同选项重画会**互相覆盖**
    # （踩过：改图注后重画，把上一张覆盖掉；随后按旧名清理又删掉了新的）。
    # 相同选项 → 相同文件名（幂等重画仍覆盖，符合预期）。
    tag = _options_digest(fmt, width, height, atom_indices, highlight_smarts, legend)
    path = out_dir(out) / f"{_safe_name(smiles)}-{tag}.{fmt}"
    path.write_bytes(data)

    result: dict[str, Any] = {
        "path": str(path.resolve()),
        "format": fmt,
        "bytes": len(data),
        "smiles": smiles,
        "canonical": r.canonical,
        "highlighted": bool(atoms),
        "level": r.level,
    }
    if legend_via_pil:
        font_used, ok = _annotate_legend(path, legend or "")
        result["bytes"] = path.stat().st_size
        if ok:
            result["legend_font"] = font_used
        else:
            result["warnings"] = [
                "图注含中文，但系统找不到可用的中文字体 → PNG 里没有写上图注。"
                "请安装中文字体（如 fonts-noto-cjk），或改用 ASCII 图注。"]
    return result


def _compose_grid_pil(
    mols: list,
    legends: list[str],
    mols_per_row: int,
    sub_img_size: tuple[int, int],
):
    """自己拼网格：为了中文图注（RDKit 的字体处理会出豆腐块）。"""
    import io as _io
    from math import ceil

    from PIL import Image, ImageDraw

    cols = max(1, min(mols_per_row, len(mols)))
    rows = ceil(len(mols) / cols)
    cw, ch = sub_img_size
    pad = 28 if legends else 0
    font_path = find_cjk_font()
    font = _pil_font(font_path, 16) if (legends and font_path) else None

    canvas = Image.new("RGB", (cols * cw, rows * (ch + pad)), "white")
    draw = ImageDraw.Draw(canvas)
    for i, mol in enumerate(mols):
        d = rdMolDraw2D.MolDraw2DCairo(cw, ch)
        rdMolDraw2D.PrepareAndDrawMolecule(d, mol)
        d.FinishDrawing()
        cell = Image.open(_io.BytesIO(d.GetDrawingText())).convert("RGB")
        row, col = divmod(i, cols)
        x, y = col * cw, row * (ch + pad)
        canvas.paste(cell, (x, y))
        text = legends[i] if i < len(legends) else ""
        if text and font:
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
            draw.text((x + (cw - tw) / 2 - bbox[0], y + ch + 6 - bbox[1]),
                      text, fill="black", font=font)
    return canvas


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
    「静默丢数据」比报错更危险。图注支持中文（自行排版，不依赖 RDKit 字体）。
    """
    legends_list = list(legends) if legends is not None else []
    mols, kept_legends, skipped = [], [], []
    for i, smi in enumerate(smiles_list):
        r = check(smi)
        if not r.ok:
            skipped.append({"index": i, "smiles": smi,
                            "reason": "；".join(d.message for d in r.diagnostics)})
            continue
        mols.append(mol_from_smiles(smi))
        if legends is not None:
            kept_legends.append(legends_list[i] if i < len(legends_list) else "")
    if not mols:
        raise ValueError(t("err_no_drawable"))

    warnings: list[str] = []
    path = out_dir(out) / filename

    if kept_legends and any(has_non_ascii(t) for t in kept_legends):
        if find_cjk_font() is None:
            warnings.append(t("warn_no_cjk_font"))
            kept_legends = []
        img = _compose_grid_pil(mols, kept_legends, mols_per_row, sub_img_size)
        img.save(path)
    else:
        img = Draw.MolsToGridImage(
            mols, molsPerRow=mols_per_row, subImgSize=sub_img_size,
            legends=kept_legends or None,
        )
        if hasattr(img, "save"):
            img.save(path)
        else:  # 某些后端返回 SVG 字符串
            path.write_text(img)

    result = {
        "path": str(path.resolve()),
        "count": len(mols),
        "skipped": skipped,
        "bytes": path.stat().st_size,
    }
    if warnings:
        result["warnings"] = warnings
    return result
