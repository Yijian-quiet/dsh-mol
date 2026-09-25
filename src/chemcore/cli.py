"""``python3 -m chemcore.cli`` —— 一行 JSON 进，一行 JSON 出。

为什么要有它：工作台（`dsh-ui`）的宿主半边是 Node，它需要在**用户点按钮的当下**
就把 RDKit 的结果显示出来，而不是绕一圈去问模型。Node 调 Python 最省事的接口就是
"喂一个 JSON 到 stdin，读一个 JSON 从 stdout"，不用装 HTTP 框架、不用管端口、
天然进程隔离（崩了也只是这一次调用失败）。

约定（改这里请同步改 `dsh-ui/lib/index.js`）：

    请求   {"op": "properties", "smiles": "CCO"}
    成功   {"ok": true,  "op": "properties", "result": {...}}
    失败   {"ok": false, "op": "properties", "code": "invalid_request", "message": "…"}

``code`` 是给程序看的，``message`` 是给人看的人话（中文，可定位）。
**stdout 只能有那一个 JSON**，任何日志/警告都走 stderr —— 否则上层解析会碎。
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable

from .analyze import DEFAULT_CATALOGS, analyze, druglikeness
from .batch import batch_clean
from .convert import convert
from .draw import draw, draw_grid
from .props import descriptors_available, properties
from .search import similarity, substructure_match
from .standardize import dedupe, standardize
from .validate import check


def _op_check(smiles: str, **kw: Any) -> Any:
    result = check(smiles, include_inchi_key=bool(kw.get("include_inchi_key", False)))
    return result.as_dict()


def _op_standardize(smiles: str, **kw: Any) -> Any:
    return standardize(
        smiles,
        strip_salts=bool(kw.get("strip_salts", True)),
        uncharge=bool(kw.get("uncharge", True)),
        desolvate=bool(kw.get("desolvate", True)),
        canonical_tautomer=bool(kw.get("canonical_tautomer", False)),
    )


def _op_dedupe(smiles_list: list[str], **kw: Any) -> Any:
    return dedupe(smiles_list, standardize_first=bool(kw.get("standardize_first", False)))


def _op_similarity(a: str, b: str, **kw: Any) -> Any:
    return similarity(a, b, kind=str(kw.get("kind", "morgan")))


def _op_substructure(smiles: str, smarts: str, **kw: Any) -> Any:
    return substructure_match(smiles, smarts, max_matches=int(kw.get("max_matches", 50)))


def _op_convert(value: str, **kw: Any) -> Any:
    return convert(value, to=str(kw.get("to", "smiles")), src=kw.get("src") or None)


def _op_batch_clean(smiles_list: list[str], **kw: Any) -> Any:
    # 工作台里贴进来的清单一般不落盘，所以 out_csv 留空 = 只回摘要
    return batch_clean(
        smiles_list,
        out_csv=kw.get("out_csv") or None,
        with_props=bool(kw.get("with_props", True)),
    )


def _op_druglikeness(smiles: str, **kw: Any) -> Any:
    catalogs = kw.get("catalogs") or DEFAULT_CATALOGS
    return druglikeness(smiles, catalogs=tuple(catalogs))


def _op_draw(smiles: str, **kw: Any) -> Any:
    return draw(
        smiles,
        fmt=str(kw.get("fmt", "png")),
        out=kw.get("out") or None,
        legend=kw.get("legend") or None,
    )


def _op_draw_grid(smiles_list: list[str], **kw: Any) -> Any:
    return draw_grid(
        smiles_list,
        out=kw.get("out") or None,
        mols_per_row=int(kw.get("mols_per_row", 4)),
    )


#: op 名 → 实现。新增工具时**只加这里**，宿主半边不用改。
OPS: dict[str, Callable[..., Any]] = {
    "check": _op_check,
    "canonicalize": lambda smiles, **_: {"canonical": check(smiles).canonical},
    "properties": lambda smiles, **_: properties(smiles),
    "druglikeness": _op_druglikeness,
    "analyze": lambda smiles, **_: analyze(smiles),
    "substructure": _op_substructure,
    "similarity": _op_similarity,
    "standardize": _op_standardize,
    "dedupe": _op_dedupe,
    "convert": _op_convert,
    "batch_clean": _op_batch_clean,
    "draw": _op_draw,
    "draw_grid": _op_draw_grid,
    "descriptors": lambda **_: descriptors_available(),
}


def run(request: dict[str, Any]) -> dict[str, Any]:
    """执行一个请求，**永远返回可 JSON 化的 dict**（不抛异常给上层）。"""
    op = request.get("op")
    if not isinstance(op, str) or not op:
        return {
            "ok": False, "op": op, "code": "invalid_request",
            "message": f"请求里缺少 op 字段。可用的 op：{', '.join(sorted(OPS))}",
        }
    handler = OPS.get(op)
    if handler is None:
        return {
            "ok": False, "op": op, "code": "unknown_op",
            "message": f"没有名为 {op!r} 的操作。可用的 op：{', '.join(sorted(OPS))}",
        }

    kwargs = {k: v for k, v in request.items() if k != "op"}
    try:
        return {"ok": True, "op": op, "result": handler(**kwargs)}
    except TypeError as error:
        # 参数不对（少传/多传）—— 这类错误必须说清是调用方的问题
        return {
            "ok": False, "op": op, "code": "invalid_request",
            "message": f"调用参数不对：{error}",
        }
    except ValueError as error:
        # 领域错误：chemcore 抛的 ValueError 都是给人看的人话
        return {"ok": False, "op": op, "code": "domain_error", "message": str(error)}
    except Exception as error:  # pragma: no cover - 兜底
        return {
            "ok": False, "op": op, "code": "internal_error",
            "message": f"{type(error).__name__}: {error}",
        }


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    raw = sys.stdin.read()
    if not raw.strip():
        # 允许把请求直接写在命令行里，方便手工试：python3 -m chemcore.cli '{"op":"properties",...}'
        raw = argv[0] if argv else ""
    try:
        request = json.loads(raw)
    except json.JSONDecodeError as error:
        json.dump(
            {"ok": False, "op": None, "code": "invalid_json",
             "message": f"请求不是合法 JSON：{error}"},
            sys.stdout, ensure_ascii=False,
        )
        return 0
    if not isinstance(request, dict):
        json.dump(
            {"ok": False, "op": None, "code": "invalid_request",
             "message": "请求必须是一个 JSON 对象"},
            sys.stdout, ensure_ascii=False,
        )
        return 0

    json.dump(run(request), sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
