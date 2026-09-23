"""chemworkbench MCP server —— 把 chemcore 的本地能力暴露给 DSH / 任何 MCP 客户端。

传输：**stdio**，即完全本地的进程间通信，**不需要网络、不需要 API key**。
（容易混淆的一点：只有"远端 MCP"才走网络；stdio MCP 是纯本地。）

用法
----
stdio（DSH / Claude Code / Codex 等 MCP 客户端）：
    python3 -m chemworkbench_mcp.server

自测（不经过任何客户端）：
    python3 -m chemworkbench_mcp.server --selftest

环境变量：
    CHEMWORKBENCH_OUT   图片与报表的输出目录（默认 ./chemworkbench-out）
"""

from __future__ import annotations

import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from mcp.server.fastmcp import FastMCP  # noqa: E402

import chemcore as cc  # noqa: E402

mcp = FastMCP(
    "chemworkbench",
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
@mcp.tool()
def chem_check_smiles(smiles: str) -> dict[str, Any]:
    """校验并规范化一个 SMILES。

    返回三级结果：ok（干净）/ warn（能解析但可疑，如电荷异常）/ error（解析失败）。
    失败时给出**人话原因**（环未闭合、括号不匹配、价键超限…）和可定位的字符位置。
    校验 SMILES 请一律用这个工具，不要凭眼睛判断。
    """
    return cc.check(smiles).as_dict()


@mcp.tool()
def chem_properties(smiles: str) -> dict[str, Any]:
    """计算分子性质：分子式、分子量、精确质量、logP、TPSA、氢键供受体、
    可旋转键、环数、手性中心等。

    注意 logP 是 Crippen 估算值，不是实验值。"""
    return cc.properties(smiles)


@mcp.tool()
def chem_draw_molecule(
    smiles: str,
    fmt: str = "png",
    width: int = 640,
    height: int = 480,
    atom_indices: bool = False,
    highlight_smarts: str = "",
    legend: str = "",
    out: str = "",
) -> dict[str, Any]:
    """把分子画成结构图，返回图片**文件路径**（png 或 svg）。

    参数：
      atom_indices: 标注原子编号（讨论具体原子时很有用）
      highlight_smarts: 用 SMARTS 高亮子结构，如 "c1ccccc1" 高亮苯环
      out: 输出目录，默认 CHEMWORKBENCH_OUT 或 ./chemworkbench-out

    画完若要让用户看到图，**请再用 `present` 工具把这个路径声明为交付物**
    （在 dsh web 等挂载了 standard 预设的环境里可用；headless 一次性任务没有该工具）。
    """
    return cc.draw(
        smiles, out=out or None, fmt=fmt, width=width, height=height,
        atom_indices=atom_indices, highlight_smarts=highlight_smarts or None,
        legend=legend or None,
    )


@mcp.tool()
def chem_draw_grid(
    smiles_list: list[str],
    mols_per_row: int = 4,
    filename: str = "grid.png",
    out: str = "",
) -> dict[str, Any]:
    """把多个分子拼成一张网格图，返回图片路径。

    无法解析的条目会被跳过，但会在 skipped 里**逐条给出原因**——不会静默丢数据。
    画完若要让用户看到图，请再用 `present` 工具把这个路径声明为交付物。"""
    return cc.draw_grid(smiles_list, out=out or None, mols_per_row=mols_per_row,
                        filename=filename)


@mcp.tool()
def chem_convert(value: str, to: str, src: str = "") -> dict[str, Any]:
    """结构格式互转：smiles / inchi / inchikey / mol / sdf / formula。

    src 留空则自动嗅探。注意 InChIKey 是单向摘要，不能反推结构。"""
    return cc.convert(value, to=to, src=src or None)


@mcp.tool()
def chem_standardize(
    smiles: str,
    strip_salts: bool = True,
    desolvate: bool = True,
    uncharge: bool = True,
    canonical_tautomer: bool = False,
) -> dict[str, Any]:
    """结构标准化：去盐、去金属、中和电荷、规范化。

    会逐步记录**改了什么**（changes），便于判断该不该信任结果。
    canonical_tautomer 默认关闭，因为它会悄悄改变结构（酮式/烯醇式之类）。"""
    return cc.standardize(
        smiles, strip_salts=strip_salts, desolvate=desolvate,
        uncharge=uncharge, canonical_tautomer=canonical_tautomer,
    )


@mcp.tool()
def chem_dedupe(smiles_list: list[str], standardize_first: bool = False) -> dict[str, Any]:
    """按规范化结构去重，保留首次出现顺序，返回重复分组与失败条目。"""
    return cc.dedupe(smiles_list, standardize_first=standardize_first)


@mcp.tool()
def chem_substructure_match(smiles: str, smarts: str) -> dict[str, Any]:
    """用 SMARTS 在分子里查子结构，返回匹配的原子索引列表。"""
    return cc.substructure_match(smiles, smarts)


@mcp.tool()
def chem_similarity(a: str, b: str, kind: str = "morgan") -> dict[str, Any]:
    """两个分子的指纹相似度（默认 Morgan/Tanimoto）。kind 可选 morgan / rdkit / maccs。"""
    return cc.similarity(a, b, kind=kind)


@mcp.tool()
def chem_batch_clean(smiles_list: list[str], out_csv: str = "") -> dict[str, Any]:
    """批量清洗：一列 SMILES 进，返回计数摘要 + 失败清单（可选写出 CSV 报表）。

    每一行都会有明确归属（ok / warn / failed），不会静默丢弃坏数据。"""
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
