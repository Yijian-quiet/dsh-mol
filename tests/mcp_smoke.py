#!/usr/bin/env python3
"""MCP 协议级冒烟测试：用真的 MCP 客户端（stdio）启动 server，列工具、调工具。

这比"直接调函数"强的地方：证明**协议层**是通的 —— 工具注册、schema、
参数传递、结构化返回、错误传播，全都真跑一遍。

运行：
    PYTHONPATH=src python3 tests/mcp_smoke.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")

EXPECTED_TOOLS = {
    "chem_check_smiles", "chem_properties", "chem_draw_molecule", "chem_draw_grid",
    "chem_convert", "chem_standardize", "chem_dedupe", "chem_substructure_match",
    "chem_similarity", "chem_batch_clean",
}


def _payload(result) -> dict:
    """从 CallToolResult 里取出结构化内容（FastMCP 把 dict 放进 text JSON）。"""
    if getattr(result, "structuredContent", None):
        return result.structuredContent
    for item in result.content or []:
        if getattr(item, "type", None) == "text":
            try:
                return json.loads(item.text)
            except json.JSONDecodeError:
                return {"_text": item.text}
    return {}


async def main() -> int:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "chemworkbench_mcp.server"],
        env={**os.environ, "PYTHONPATH": SRC, "CHEMWORKBENCH_OUT": "/tmp/chemwb-mcp-out"},
    )
    failures: list[str] = []
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            info = await session.initialize()
            print(f"已连接：{info.serverInfo.name} v{info.serverInfo.version}")

            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            print(f"注册工具 {len(names)} 个：{', '.join(sorted(names))}")
            missing = EXPECTED_TOOLS - names
            if missing:
                failures.append(f"缺少工具：{sorted(missing)}")

            for t in tools.tools:
                if not (t.description or "").strip():
                    failures.append(f"工具 {t.name} 没有描述（模型会不知道怎么用）")

            # 1) 正常校验
            r = _payload(await session.call_tool("chem_check_smiles",
                                                 {"smiles": "CC(=O)Oc1ccccc1C(=O)O"}))
            print(f"  check(阿司匹林) -> level={r.get('level')} formula={r.get('formula')}")
            if r.get("level") != "ok" or r.get("formula") != "C9H8O4":
                failures.append(f"正常校验结果异常：{r}")

            # 2) 错误路径：坏 SMILES 应返回人话，而不是协议错误
            r = _payload(await session.call_tool("chem_check_smiles", {"smiles": "C1CC"}))
            msg = (r.get("diagnostics") or [{}])[0].get("message", "")
            print(f"  check(C1CC) -> level={r.get('level')} message={msg[:40]}")
            if r.get("level") != "error" or "环闭合" not in msg:
                failures.append(f"错误路径没给人话原因：{r}")

            # 3) 画图：应返回可用的文件路径
            r = _payload(await session.call_tool("chem_draw_molecule",
                                                 {"smiles": "CCO", "atom_indices": True}))
            path = r.get("path", "")
            ok = bool(path) and os.path.exists(path) and os.path.getsize(path) > 1000
            print(f"  draw(CCO) -> {path} ({r.get('bytes')} bytes)")
            if not ok:
                failures.append(f"画图未产出有效文件：{r}")

            # 4) 非法参数应作为工具错误返回（不崩服务）
            try:
                res = await session.call_tool("chem_properties", {"smiles": "C1CC"})
                text = json.dumps(_payload(res), ensure_ascii=False)
                print(f"  非法输入 -> isError={res.isError} 内容={text[:80]}")
                if not res.isError:
                    failures.append("非法输入没有被标记为工具错误")
            except Exception as exc:  # noqa: BLE001
                print(f"  非法输入 -> 客户端收到异常：{type(exc).__name__}: {exc}")
                failures.append(f"非法输入导致协议级异常（应为工具错误）：{exc}")

    if failures:
        print("\n失败：")
        for f in failures:
            print("  ✗", f)
        return 1
    print("\nMCP 冒烟测试全部通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
