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
from .i18n import t

# --------------------------------------------------------------------------
# RDKit 原始信息 → 人话
# 顺序重要：先具体后笼统
# --------------------------------------------------------------------------
# 第三条是 **i18n key**（不是文案）：文案取自 chemcore.i18n，随语言变，
# 而 code 与 key 永远与语言无关 —— 调用方/测试断言 code，不要断言文案。
_RULES: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"unclosed ring", re.I), "unclosed_ring", "unclosed_ring"),
    (re.compile(r"extra close parentheses", re.I), "extra_paren", "extra_paren"),
    (re.compile(r"unmatched open parentheses", re.I), "missing_paren", "missing_paren"),
    (re.compile(r"Explicit valence for atom #\s*(\d+)\s*([A-Za-z]{1,3}),\s*(\d+),\s*is greater than permitted", re.I),
     "valence", "valence"),
    (re.compile(r"Unusual charge on atom\s*(\d+)", re.I), "unusual_charge", "unusual_charge"),
    (re.compile(r"[Cc]an'?t kekulize|kekulize", re.I), "kekulize", "kekulize"),
    (re.compile(r"[Ee]lement '([^']+)' not found|Invalid element", re.I), "bad_element", "bad_element"),
    (re.compile(r"non-ring atom\s*(\d+)\s*marked aromatic", re.I), "aromatic_nonring", "aromatic_nonring"),
    (re.compile(r"SMILES Parse Error: syntax error while parsing", re.I), "syntax", "syntax"),
    (re.compile(r"SMILES Parse Error", re.I), "parse_error", "parse_error"),
    (re.compile(r"Ring closure bond type specified", re.I), "ring_bond_redundant", "ring_bond_redundant"),
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


def _scan_ring_closures(text: str) -> list[tuple[str, list[int]]]:
    """扫描成环数字（方括号外的），返回 ``[(编号, 位置列表)]``。

    SMILES 里成环数字必须**成对出现**（`C1CC1`）。RDKit 只说"环未闭合"，
    不告诉你是哪个数字、在哪 —— 这里补上。

    注意：方括号内的数字不是成环标记（`[13C]`、`[C@H]`、原子映射 `[CH3:1]`），
    两位成环编号写作 `%10`。
    """
    found: dict[str, list[int]] = {}
    depth = 0
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth = max(0, depth - 1)
        elif depth == 0:
            if ch == "%" and i + 2 < n and text[i + 1].isdigit() and text[i + 2].isdigit():
                tok = text[i + 1:i + 3]
                found.setdefault(tok, []).append(i)
                i += 3
                continue
            if ch.isdigit():
                found.setdefault(ch, []).append(i)
        i += 1
    return list(found.items())


def _translate(raw_log: str, lang: str | None = None) -> list[Diagnostic]:
    """把 RDKit 日志翻成一或多条人话诊断（按 ``lang`` 取文案）。"""
    out: list[Diagnostic] = []
    seen: set[str] = set()
    for line in raw_log.splitlines():
        line = re.sub(r"^\[\d{2}:\d{2}:\d{2}\]\s*", "", line).strip()
        if not line:
            continue
        for pattern, code, msg_key in _RULES:
            m = pattern.search(line)
            if not m:
                continue
            if code in seen:
                break
            seen.add(code)
            groups = [g for g in (m.groups() or ()) if g]
            message = t(msg_key, *groups, lang=lang)
            level = "warning" if _LEVEL_BY_CODE.get(code) == "warn" else "error"
            out.append(Diagnostic(level=level, code=code, message=message, raw=line))
            break
    return out


def check(smiles: str, *, include_inchi_key: bool = False,
          lang: str | None = None) -> CheckResult:
    """校验并规范化一个 SMILES。

    Args:
        smiles: 待校验的 SMILES 字符串。
        include_inchi_key: 预留参数（当前不产出 InChIKey，见 convert 模块）。
        lang: 诊断文案语言（``zh`` / ``en``）；缺省取 ``MOL_LANG`` 或 ``zh``。
              ``code`` 与语言无关，断言请用 code。

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
                message=t("empty", lang=lang), raw="")],
        )

    mol, raw_log = parse(smiles)
    diags = _translate(raw_log, lang)

    # 坑 2：0 原子空分子也算失败（防御性，正常路径已被上面的空串分支拦住）
    if mol is not None and mol.GetNumAtoms() == 0:
        return CheckResult(
            level="error", input=smiles, num_atoms=0,
            diagnostics=[Diagnostic(
                level="error", code="no_atoms",
                message=t("no_atoms", lang=lang),
                raw=raw_log.strip())],
        )

    position = None
    if mol is None:
        scanned = _scan_brackets(smiles)
        if scanned:
            code, pos = scanned
            position = pos
            if not any(d.code in (code, "extra_paren", "missing_paren") for d in diags):
                # code 与 i18n key 同名（*_at 带位置），避免再维护一张映射表
                diags.append(Diagnostic(level="error", code=code,
                                        message=t(f"{code}_at", pos, lang=lang)))

        # 成环数字：RDKit 只说"环未闭合"，这里指出是哪个编号、在哪
        odd = [(digit, positions) for digit, positions in _scan_ring_closures(smiles)
               if len(positions) % 2 == 1]
        for digit, positions in odd:
            pos = positions[-1]
            if position is None:
                position = pos
            diags.append(Diagnostic(
                level="error", code="unclosed_ring_position",
                message=t("unclosed_ring_position", digit, len(positions), pos, lang=lang),
                raw=""))

        if not diags:
            diags.append(Diagnostic(
                level="error", code="parse_failed",
                message=t("parse_failed", lang=lang), raw=""))
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
                                           message=t("rdkit_warning", line, lang=lang),
                                           raw=line))
    return CheckResult(
        level="warn" if warnings else "ok",
        input=smiles,
        canonical=canonical,
        formula=formula,
        num_atoms=mol.GetNumAtoms(),
        diagnostics=warnings,
    )


def canonicalize(smiles: str, lang: str | None = None) -> str | None:
    """只要规范化结果，失败返回 None。批量场景的便捷入口。"""
    r = check(smiles, lang=lang)
    return r.canonical if r.ok else None
