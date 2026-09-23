"""RDKit 初始化与日志捕获。

为什么需要这个模块
------------------
RDKit 的 SMILES 解析失败时**不抛异常**，只返回 ``None``，而失败原因写到
C++ 层的 stderr。天真地用 ``MolFromSmiles`` 包一层，模型只会拿到一个空洞的
``None``，不知道错在哪。

``rdBase.LogToPythonStderr()`` 把 RDKit 日志改道到 Python 的 ``sys.stderr``，
之后就能用 ``contextlib.redirect_stderr`` 捕获到文本，从而翻译成人话。

另有两个必须处理的坑（实测 2023.09.6）：

1. ``MolFromSmiles('')`` 返回的不是 ``None``，而是一个 **0 原子的空分子**。
   天真写法会把空输入判成"合法"。
2. ``'   '``（纯空白）却 *会* 返回 ``None`` 并报语法错误 —— 与空串行为不一致。

线程安全：``redirect_stderr`` 是进程级的，本模块的捕获不是线程安全的。
MCP server 单请求串行执行工具，故可接受。
"""

from __future__ import annotations

import contextlib
import io
import threading
from typing import Iterator

from rdkit import rdBase

_lock = threading.Lock()
_initialized = False


def ensure_py_logging() -> None:
    """把 RDKit 的 C++ 日志改道到 Python stderr（幂等）。"""
    global _initialized
    if not _initialized:
        rdBase.LogToPythonStderr()
        _initialized = True


@contextlib.contextmanager
def capture_log() -> Iterator[io.StringIO]:
    """捕获这段代码里 RDKit 写出的日志文本。

    同时禁止 RDKit 日志继续污染真实 stderr（用户不该看到原始堆栈）。
    """
    ensure_py_logging()
    buf = io.StringIO()
    with _lock:
        with contextlib.redirect_stderr(buf):
            yield buf


def parse(smiles: str):
    """解析 SMILES，返回 ``(mol_or_None, rdkit_log_text)``。

    调用方负责判断 ``mol`` 是否为 ``None``、以及是否为 0 原子空分子。
    """
    from rdkit import Chem

    with capture_log() as buf:
        mol = Chem.MolFromSmiles(smiles)
    return mol, buf.getvalue()


def parse_sanitized(smiles: str, *, sanitize: bool = True):
    """解析但可选关闭 sanitize（用于先拿到结构、再单独报告 sanitize 问题）。"""
    from rdkit import Chem

    with capture_log() as buf:
        mol = Chem.MolFromSmiles(smiles, sanitize=sanitize)
    return mol, buf.getvalue()


def mol_from_smiles(smiles: str):
    """在日志捕获下解析 SMILES，返回 mol 或 ``None``。

    **所有**内部解析都应走这里，而不是直接 ``Chem.MolFromSmiles`` ——
    否则 RDKit 的告警（如 "Unusual charge on atom 0"）会漏到真实 stderr，
    污染工具输出，用户和模型都会看到莫名其妙的英文噪声。
    """
    mol, _ = parse(smiles)
    return mol
