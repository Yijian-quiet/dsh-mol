"""dsh-mol MCP server —— 把 chemcore 的本地能力暴露给 DSH / 任何 MCP 客户端。

传输：**stdio**，即完全本地的进程间通信，**不需要网络、不需要 API key**。
（容易混淆的一点：只有"远端 MCP"才走网络；stdio MCP 是纯本地。）

用法
----
stdio（DSH / Claude Code / Codex 等 MCP 客户端）：
    python3 -m dsh_mol_mcp.server

自测（不经过任何客户端）：
    python3 -m dsh_mol_mcp.server --selftest

环境变量：
    MOL_OUT   图片与报表的输出目录（默认 ./dsh-mol-out）
"""

from __future__ import annotations

import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

try:
    from mcp.server.fastmcp import FastMCP  # noqa: E402
except ModuleNotFoundError as _exc:  # pragma: no cover - 依赖版本不符时的友好出路
    # MCP Python SDK 2.x 把 FastMCP 改名为 MCPServer，API 有破坏性变更。
    # 如果只写 pyproject 的版本约束，用户拿到的是一条难懂的 traceback；
    # 这里明确告诉他怎么办（同一个原则：失败要说人话）。
    if "fastmcp" in str(_exc):
        raise SystemExit(
            "本插件需要 MCP Python SDK **1.x**（FastMCP）。\n"
            "检测到你装的是 2.x：2.x 把 FastMCP 改名为 MCPServer，且 API 有破坏性变更。\n"
            "修复：pip install 'mcp>=1.0,<2'\n"
            f"（原始错误：{_exc}）"
        ) from _exc
    raise

import chemcore as cc  # noqa: E402

# ---------------------------------------------------------------------------
# 工具语义注解（MCP 规范里的 ToolAnnotations）
#
# 为什么值得写：宿主（Claude Code / Codex / Cursor…）靠这四个 hint 决定
# "能不能自动放行"和"要不要先警告用户"。不声明时规范默认 destructiveHint=true ——
# 也就是说**不写等于暗示我们可能破坏东西**，宿主只能每次都来问人。
#
# 我们两类工具，语义都是明确的：
#   READ_ONLY  纯计算，不碰文件系统
#   WRITES_FILE 会落盘（画图 / 写 CSV），但只新增、不删除不覆盖别人的东西 → destructive=false
# 全部零网络 → openWorldHint=false；同样的参数重复调用结果一致 → idempotent=true。
# ---------------------------------------------------------------------------

from mcp.types import ToolAnnotations  # noqa: E402

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
WRITES_FILE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

def _with_image(result: dict[str, Any]):
    """把产物图**作为图片内容块**一起返回，让客户端直接渲染（DSH 有 image-card），
    同时保留原有的路径元数据 —— 模型能读路径，人能看到图，两边都不缺。

    SVG 不在此列：MCP 图片内容块只认 png/jpeg/webp/gif。
    """
    from mcp.server.fastmcp import Image

    path = result.get("path")
    if path and str(path).lower().endswith(".png") and os.path.exists(path):
        # 明确告诉模型下一步该做什么：DSH 的内联图卡**只对 read_image 生效**
        # （源码里 `if (call?.name !== "read_image") return null`），
        # 只返回路径的话，用户看到的是一行文字而不是图。
        result = {
            **result,
            "next_step": "请调用 read_image 把这张图内联展示给用户（或 present 作为交付物），不要只给路径",
        }
        return [Image(path=path), result]
    return result


mcp = FastMCP(
    "dsh-mol",
    log_level="WARNING",          # stdio 下 stdout 是协议通道，日志越安静越好
    instructions=(
        "本地化学基础工具（纯 RDKit，无网络）。"
        "优先用 chem_check_smiles 校验用户给的 SMILES —— 它会把人话级的错误原因和"
        "字符位置一起返回；不要自己肉眼判断 SMILES 是否合法。"
        "需要展示结构时用 chem_draw_molecule，它返回图片路径。"
    ),
)

# FastMCP 没有 version 参数，默认会把 MCP SDK 的版本当成服务版本报出去
# （客户端看到的是 1.28.1 而不是本工具的版本）。这里改回自己的版本。
try:
    mcp._mcp_server.version = cc.__version__  # noqa: SLF001
except Exception:  # pragma: no cover - SDK 内部结构变化时不影响功能
    pass


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------
@mcp.tool(title="Validate SMILES", annotations=READ_ONLY)
def chem_check_smiles(smiles: str) -> dict[str, Any]:
    """Validate and canonicalise a SMILES string.

    Returns a three-level result: ok (clean), warn (parses but suspicious, e.g. an
    odd formal charge), or error (parse failure). Failures carry a human-readable
    reason (unclosed ring, unbalanced parentheses, valence exceeded, ...) and, when it
    can be located, the character position. This is the validation entry point for
    SMILES input.

    校验并规范化一个 SMILES。返回三级结果：ok（干净）/ warn（能解析但可疑，如电荷异常）
    / error（解析失败）。失败时给出人话原因（环未闭合、括号不匹配、价键超限…）和可定位的
    字符位置。"""
    return cc.check(smiles).as_dict()


@mcp.tool(title="Molecular properties", annotations=READ_ONLY)
def chem_properties(smiles: str) -> dict[str, Any]:
    """Compute common molecular properties: formula, molecular weight, exact mass,
    logP, TPSA, hydrogen-bond donors and acceptors, rotatable bonds, ring counts,
    stereocentres and more. logP is a Crippen estimate, not an experimental value.

    计算分子性质：分子式、分子量、精确质量、logP、TPSA、氢键供受体、可旋转键、环数、
    手性中心等。注意 logP 是 Crippen 估算值，不是实验值。"""
    return cc.properties(smiles)


@mcp.tool(title="Analyse molecule", annotations=READ_ONLY)
def chem_analyze(smiles: str) -> dict[str, Any]:
    """Properties, drug-likeness, structural alerts and the Murcko scaffold in one call.

    Every rule is returned with its own passed flag and threshold detail. It
    deliberately returns no overall "drug-like or not" verdict: that is not a boolean
    AND of thresholds and is better left to the reader. QED measures closeness to the
    property distribution of known drugs (Bickerton 2012); it is not an activity
    prediction.

    分子"深看一层"：基础性质 + 类药性 + 结构警报 + Murcko 骨架，一次给全。每条规则都带
    passed 与阈值明细，不给"能否成药"的总评。QED 是接近已知药物性质分布的程度
    （Bickerton 2012 口径），不是活性预测。"""
    return cc.analyze(smiles)


@mcp.tool(title="Drug-likeness and alerts", annotations=READ_ONLY)
def chem_druglikeness(smiles: str, catalogs: list[str] | None = None) -> dict[str, Any]:
    """Drug-likeness and structural alerts only (Lipinski / Veber / QED / PAINS / BRENK /
    Murcko scaffold). `catalogs` chooses which alert catalogues to check and defaults
    to PAINS + BRENK; NIH and ZINC are also available but noisier.

    只要类药性与结构警报（Lipinski / Veber / QED / PAINS / BRENK / 骨架）。catalogs 可指定
    警报目录，默认 PAINS + BRENK；也可传 NIH / ZINC（误报更多，需要时再开）。"""
    return cc.druglikeness(smiles, catalogs=tuple(catalogs) if catalogs else cc.DEFAULT_ALERT_CATALOGS)


@mcp.tool(title="Draw molecule", annotations=WRITES_FILE)
def chem_draw_molecule(
    smiles: str,
    fmt: str = "png",
    width: int = 640,
    height: int = 480,
    atom_indices: bool = False,
    highlight_smarts: str = "",
    legend: str = "",
    out: str = "",
):
    """Render one molecule to an image file (png or svg) and return its path.

    Parameters:
      atom_indices: label atom indices (useful when discussing specific atoms)
      highlight_smarts: highlight a substructure by SMARTS, e.g. "c1ccccc1" for benzene
      out: output directory; defaults to MOL_OUT or ./dsh-mol-out

    The return value carries no image bytes, only the written path and size
    information; displaying the image is up to the caller's host.

    把分子画成结构图，返回图片文件路径（png 或 svg）。返回值里不含图片二进制，只有落盘路径
    与尺寸信息；图片本身需要由调用方按自己宿主的能力展示。"""
    return _with_image(cc.draw(
        smiles, out=out or None, fmt=fmt, width=width, height=height,
        atom_indices=atom_indices, highlight_smarts=highlight_smarts or None,
        legend=legend or None,
    ))


@mcp.tool(title="Draw molecule grid", annotations=WRITES_FILE)
def chem_draw_grid(
    smiles_list: list[str],
    mols_per_row: int = 4,
    filename: str = "grid.png",
    out: str = "",
):
    """Render several molecules into one grid image and return its path. Entries that cannot
    be parsed are skipped, each with its reason recorded in `skipped` - nothing is
    dropped silently. The return value carries no image bytes, only the written path.

    把多个分子拼成一张网格图，返回图片路径。无法解析的条目会被跳过，但会在 skipped 里逐条
    给出原因，不会静默丢数据；返回值里不含图片二进制，只有落盘路径。"""
    return _with_image(cc.draw_grid(smiles_list, out=out or None, mols_per_row=mols_per_row,
                                    filename=filename))


@mcp.tool(title="Convert structure format", annotations=READ_ONLY)
def chem_convert(value: str, to: str, src: str = "") -> dict[str, Any]:
    """Convert between structure formats: smiles / inchi / inchikey / mol / sdf / formula.
    `src` is auto-detected when left empty. An InChIKey is a one-way hash and cannot be
    converted back into a structure.

    结构格式互转：smiles / inchi / inchikey / mol / sdf / formula。src 留空则自动嗅探。
    注意 InChIKey 是单向摘要，不能反推结构。"""
    return cc.convert(value, to=to, src=src or None)


@mcp.tool(title="Standardise structure", annotations=READ_ONLY)
def chem_standardize(
    smiles: str,
    strip_salts: bool = True,
    desolvate: bool = True,
    uncharge: bool = True,
    canonical_tautomer: bool = False,
) -> dict[str, Any]:
    """Standardise a structure: strip salts, disconnect metals, neutralise charges and
    apply RDKit normalisation. Returns a per-step change log so the caller can judge
    whether to trust the result. canonical_tautomer is off by default because it
    silently changes the structure (keto/enol and similar).

    结构标准化：去盐、去金属、中和电荷、规范化。会逐步记录改了什么（changes），便于判断
    该不该信任结果。canonical_tautomer 默认关闭，因为它会悄悄改变结构（酮式/烯醇式之类）。"""
    return cc.standardize(
        smiles, strip_salts=strip_salts, desolvate=desolvate,
        uncharge=uncharge, canonical_tautomer=canonical_tautomer,
    )


@mcp.tool(title="Deduplicate structures", annotations=READ_ONLY)
def chem_dedupe(smiles_list: list[str], standardize_first: bool = False) -> dict[str, Any]:
    """Deduplicate a list by canonical structure, keeping first-seen order. Returns the
    duplicate groups and any per-item failures.

    按规范化结构去重，保留首次出现顺序，返回重复分组与失败条目。"""
    return cc.dedupe(smiles_list, standardize_first=standardize_first)


@mcp.tool(title="Substructure match", annotations=READ_ONLY)
def chem_substructure_match(smiles: str, smarts: str) -> dict[str, Any]:
    """Find a SMARTS substructure inside a molecule; returns the matching atom indices.

    用 SMARTS 在分子里查子结构，返回匹配的原子索引列表。"""
    return cc.substructure_match(smiles, smarts)


@mcp.tool(title="Fingerprint similarity", annotations=READ_ONLY)
def chem_similarity(a: str, b: str, kind: str = "morgan") -> dict[str, Any]:
    """Fingerprint similarity between two molecules (Morgan/Tanimoto by default). `kind`
    may be morgan, rdkit or maccs.

    两个分子的指纹相似度（默认 Morgan/Tanimoto）。kind 可选 morgan / rdkit / maccs。"""
    return cc.similarity(a, b, kind=kind)


@mcp.tool(title="Clean SMILES batch", annotations=WRITES_FILE)
def chem_batch_clean(smiles_list: list[str], out_csv: str = "") -> dict[str, Any]:
    """Clean a list of SMILES: returns counts plus the failure list and, optionally,
    writes a CSV report. Every input row is accounted for (ok / warn / failed);
    malformed rows are never dropped silently.

    批量清洗：一列 SMILES 进，返回计数摘要 + 失败清单（可选写出 CSV 报表）。每一行都会有
    明确归属（ok / warn / failed），不会静默丢弃坏数据。"""
    return cc.batch_clean(smiles_list, out_csv=out_csv or None)


# --------------------------------------------------------------------------
# 自测：不依赖任何 MCP 客户端，直接调用底层函数
# --------------------------------------------------------------------------
def _selftest() -> int:
    aspirin = "CC(=O)Oc1ccccc1C(=O)O"
    checks = [
        ("校验正常分子", lambda: cc.check(aspirin).level == "ok"),
        ("拦住空串", lambda: cc.check("").level == "error"),
        ("环未闭合给人话", lambda: "环闭合" in cc.check("C1CC").diagnostics[0].message),
        ("异常电荷降级为 warn", lambda: cc.check("[Fe+9]").level == "warn"),
        ("性质计算", lambda: abs(cc.properties(aspirin)["mw"] - 180.16) < 0.05),
        ("InChIKey", lambda: len(cc.convert(aspirin, to="inchikey")["value"]) == 27),
        ("画图落盘", lambda: os.path.getsize(cc.draw(aspirin, out="/tmp/chemwb-selftest")["path"]) > 1000),
        ("去盐", lambda: cc.standardize("CC(=O)[O-].[Na+]")["output"] == "CC(=O)O"),
        ("子结构", lambda: cc.substructure_match(aspirin, "c1ccccc1")["matched"]),
        ("相似度自比=1", lambda: cc.similarity(aspirin, aspirin)["score"] == 1.0),
        ("批量清洗", lambda: cc.batch_clean([aspirin, "C1CC"])["failed"] == 1),
    ]
    bad = 0
    for name, fn in checks:
        try:
            ok = bool(fn())
        except Exception as exc:  # noqa: BLE001
            ok, name = False, f"{name} (异常: {exc})"
        print(f"  {'✓' if ok else '✗'} {name}")
        bad += 0 if ok else 1
    print(f"\n自测：{len(checks) - bad}/{len(checks)} 通过")
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    """入口：无参数则启动 stdio MCP server；``--selftest`` 只跑本地自测。"""
    args = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in args:
        return _selftest()
    mcp.run()  # 默认 stdio
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
