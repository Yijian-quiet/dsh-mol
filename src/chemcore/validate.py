"""SMILES 校验与规范化 —— 给人看，也给模型看。

与"包一层 RDKit"的差别，在于**失败要说人话、并且分级**：

- ``error``：解析不了，附人话原因 + 可能的位置
- ``warn``：能解析，但结构可疑（如电荷异常、不是中性分子）
- ``ok``：干净通过

RDKit 原始的失败信息是英文 C++ 日志、且**不抛异常**（见 ``_rdkit``），
这里负责翻译与补位。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any

from rdkit import Chem

from ._rdkit import parse

# --------------------------------------------------------------------------
# RDKit 原始信息 → 人话
# 顺序重要：先具体后笼统
# --------------------------------------------------------------------------
_RULES: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"unclosed ring", re.I), "unclosed_ring",
     "环闭合标记没有配对：SMILES 里的成环数字（如 C1...C1）出现次数必须是偶数"),
    (re.compile(r"extra close parentheses", re.I), "extra_paren",
     "多余的右括号：) 比 ( 多"),
    (re.compile(r"unmatched open parentheses", re.I), "missing_paren",
     "括号没有闭合：( 比 ) 多"),
    (re.compile(r"Explicit valence for atom #\s*(\d+)\s*([A-Za-z]{1,3}),\s*(\d+),\s*is greater than permitted", re.I),
     "valence",
     "原子价键数超限：第 {0} 号原子（{1}）的连接数是 {2}，超过该元素允许的最大值"),
    (re.compile(r"Unusual charge on atom\s*(\d+)", re.I), "unusual_charge",
     "电荷异常：第 {0} 号原子的形式电荷在常见化学里很少见，请确认不是笔误"),
    (re.compile(r"[Cc]an'?t kekulize|kekulize", re.I), "kekulize",
     "芳香环无法 Kekulé 化：芳香性写法或环上取代基有问题"),
    (re.compile(r"[Ee]lement '([^']+)' not found|Invalid element", re.I), "bad_element",
     "元素符号无法识别（{0}）：注意大小写，如 Cl 不是 CL、c 是芳香碳而 C 是脂肪碳"),
    (re.compile(r"non-ring atom\s*(\d+)\s*marked aromatic", re.I), "aromatic_nonring",
     "非环原子被标成芳香（第 {0} 号）：芳香小写字母只能用在环上"),
    (re.compile(r"SMILES Parse Error: syntax error while parsing", re.I), "syntax",
     "SMILES 语法错误：在这附近有非法字符或不完整片段"),
    (re.compile(r"SMILES Parse Error", re.I), "parse_error",
     "SMILES 解析失败"),
    (re.compile(r"Ring closure bond type specified", re.I), "ring_bond_redundant",
     "环闭合时重复指定了键型（如 C=1CCCC=1 之类）"),
]

_LEVEL_BY_CODE = {
    "unusual_charge": "warn",
    "ring_bond_redundant": "warn",
    "aromatic_nonring": "warn",
}


@dataclass
class Diagnostic:
    level: str          # "error" | "warning"
    code: str
    message: str        # 人话
    raw: str = ""       # RDKit 原文（保留证据，便于排错）

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CheckResult:
    level: str                              # "ok" | "warn" | "error"
    input: str
    canonical: str | None = None
    formula: str | None = None
    num_atoms: int | None = None
    diagnostics: list[Diagnostic] = field(default_factory=list)
    position: int | None = None             # 0 基字符偏移，能定位时给出

    @property
    def ok(self) -> bool:
        return self.level != "error"

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "ok": self.ok,
            "input": self.input,
            "canonical": self.canonical,
            "formula": self.formula,
            "num_atoms": self.num_atoms,
            "position": self.position,
            "diagnostics": [d.as_dict() for d in self.diagnostics],
        }


# --------------------------------------------------------------------------
# 轻量预扫描：RDKit 不报位置，这里补上括号/方括号的错位位置
# --------------------------------------------------------------------------
def _scan_brackets(text: str) -> tuple[str, int] | None:
    """返回 (code, position) 或 None。只处理可靠的情形。"""
    stack: list[tuple[str, int]] = []
    pairs = {")": "(", "]": "["}
    for i, ch in enumerate(text):
        if ch in "([":
            stack.append((ch, i))
        elif ch in ")]":
            if not stack:
                return ("extra_paren" if ch == ")" else "extra_bracket", i)
            open_ch, _ = stack.pop()
            if open_ch != pairs[ch]:
                return ("mismatched_bracket", i)
    if stack:
        open_ch, pos = stack[-1]
        return ("missing_paren" if open_ch == "(" else "missing_bracket", pos)
    return None


def _translate(raw_log: str) -> list[Diagnostic]:
    """把 RDKit 日志翻成一或多条人话诊断。"""
    out: list[Diagnostic] = []
    seen: set[str] = set()
    for line in raw_log.splitlines():
        line = re.sub(r"^\[\d{2}:\d{2}:\d{2}\]\s*", "", line).strip()
        if not line:
            continue
        for pattern, code, template in _RULES:
            m = pattern.search(line)
            if not m:
                continue
            if code in seen:
                break
            seen.add(code)
            groups = [g for g in (m.groups() or ()) if g]
            try:
                message = template.format(*groups) if groups else template
            except (IndexError, KeyError):
                message = template
            level = "warning" if _LEVEL_BY_CODE.get(code) == "warn" else "error"
            out.append(Diagnostic(level=level, code=code, message=message, raw=line))
            break
    return out


def check(smiles: str, *, include_inchi_key: bool = False) -> CheckResult:
    """校验并规范化一个 SMILES。

    Args:
        smiles: 待校验的 SMILES 字符串。
        include_inchi_key: 预留参数（当前不产出 InChIKey，见 convert 模块）。

    Returns:
        CheckResult，``level`` 为 ``ok`` / ``warn`` / ``error``。
    """
    # 坑 1：空串会被 RDKit 解析成 0 原子空分子，必须在这里拦
    if smiles is None or not smiles.strip():
        return CheckResult(
            level="error",
            input=smiles if isinstance(smiles, str) else "",
            diagnostics=[Diagnostic(
                level="error", code="empty",
                message="输入为空：没有可解析的 SMILES 内容", raw="")],
        )

    mol, raw_log = parse(smiles)
    diags = _translate(raw_log)

    # 坑 2：0 原子空分子也算失败（防御性，正常路径已被上面的空串分支拦住）
    if mol is not None and mol.GetNumAtoms() == 0:
        return CheckResult(
            level="error", input=smiles, num_atoms=0,
            diagnostics=[Diagnostic(
                level="error", code="no_atoms",
                message="没有解析出任何原子：输入可能只含空白或无效片段",
                raw=raw_log.strip())],
        )

    position = None
    if mol is None:
        scanned = _scan_brackets(smiles)
        if scanned:
            code, pos = scanned
            position = pos
            if not any(d.code in (code, "extra_paren", "missing_paren") for d in diags):
                msg = {
                    "extra_paren": f"多余的右括号：第 {pos} 个字符处",
                    "missing_paren": f"括号没有闭合：第 {pos} 个字符处的 ( 未配对",
                    "extra_bracket": f"多余的右方括号：第 {pos} 个字符处",
                    "missing_bracket": f"方括号没有闭合：第 {pos} 个字符处的 [ 未配对",
                    "mismatched_bracket": f"括号类型不匹配：第 {pos} 个字符处应为 ]",
                }[code]
                diags.append(Diagnostic(level="error", code=code, message=msg))
        if not diags:
            diags.append(Diagnostic(
                level="error", code="parse_failed",
                message="RDKit 无法解析该 SMILES，且未给出具体原因", raw=""))
        return CheckResult(level="error", input=smiles, diagnostics=diags,
                           position=position)

    # 解析成功：区分干净 / 有警告
    from rdkit.Chem import rdMolDescriptors

    canonical = Chem.MolToSmiles(mol)
    formula = rdMolDescriptors.CalcMolFormula(mol)
    warnings = [d for d in diags if d.level == "warning"]
    # RDKit 只写日志但没匹配到规则时，也降级为 warning 而不是默默吞掉
    if not warnings and raw_log.strip():
        for line in raw_log.splitlines():
            line = re.sub(r"^\[\d{2}:\d{2}:\d{2}\]\s*", "", line).strip()
            if line:
                warnings.append(Diagnostic(level="warning", code="rdkit_warning",
                                           message=f"RDKit 提示：{line}", raw=line))
    return CheckResult(
        level="warn" if warnings else "ok",
        input=smiles,
        canonical=canonical,
        formula=formula,
        num_atoms=mol.GetNumAtoms(),
        diagnostics=warnings,
    )


def canonicalize(smiles: str) -> str | None:
    """只要规范化结果，失败返回 None。批量场景的便捷入口。"""
    r = check(smiles)
    return r.canonical if r.ok else None
