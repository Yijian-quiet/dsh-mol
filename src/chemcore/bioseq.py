"""生物大分子（肽 / 核酸）的序列与 HELM 解析 —— 先定类型，再谈结构。

为什么单独一层
--------------
Ketcher 的大分子编辑器画出来的肽/核酸**没有 SMILES**，只有序列或 HELM。要把它们
接进现有工具链（properties / analyze / draw 都吃 SMILES），必须在这里把序列变成分子。

这个模块存在的**唯一理由**是：序列里的字母天生有歧义，而 RDKit 不会告诉你。

歧义在哪（实测 RDKit 2023.09.6）
--------------------------------
- ``A`` / ``T`` / ``G`` / ``C`` 既是氨基酸字母（Ala / Thr / Gly / Cys），
  也是碱基字母（腺嘌呤 / 胸腺嘧啶 / 鸟嘌呤 / 胞嘧啶）。
- ``Chem.MolFromSequence("ATGC", flavor=0)`` **不报错**，它按肽算出 ``C12H22N4O6S``
  （MW 350.4）。同一个串按 RNA 算是 ``C39H50N15O26P3``（MW 1237.8）、按 DNA 算是
  ``C39H50N15O22P3``（MW 1173.8）。三个完全不同的分子，RDKit 只会静默给你第一个。
  所以在**只有裸序列、没有类型**时，本模块的策略是**拒绝解析并要求显式指定 kind**，
  而不是替调用方选一个默认值 —— 选错是"化学上完全错误且没有任何迹象"，比报错危险得多。
- HELM 是例外：``PEPTIDE1{…}`` / ``RNA1{…}`` / ``DNA1{…}`` 前缀**自带类型**，
  这是确定的声明，不是猜，所以 ``kind="auto"`` 可以直接解析它。

两个必须记下来的 RDKit 坑（都实测过）
-------------------------------------
1. **flavor 编号与直觉不符**。``MolFromSequence`` 的 flavor 很细：
   ``0`` 肽(L) / ``1`` 肽(D) / ``2`` RNA 无帽 / ``3`` RNA 5' 帽 / ``4`` RNA 3' 帽 /
   ``5`` RNA 双帽 / ``6`` DNA 无帽 / ``7`` DNA 5' 帽 / ``8`` DNA 3' 帽 / ``9`` DNA 双帽。
   也就是说 **DNA 是 6 不是 3**；``flavor=3`` 其实是"给 RNA 加 5' 磷酸帽"
   （``ATGC`` 在 flavor=3 下得到 ``C39H51N15O29P4``，比 RNA 还多一个磷酸 —— 是错的）。
   本模块只用 0 / 2 / 6 这三个**无帽**口径，并在返回值里写明用了哪个 flavor。
2. **3 字母氨基酸码根本没被支持**。文档说"only supports peptides"，实测它把整串
   按**大小写不敏感的单字母**读：``MolFromSequence("Gly")`` 得到的是
   Gly-Leu-Tyr（G+L+Y）而不是甘氨酸；``"Gly-Ala-Val"`` 得到的是 9 肽
   ``C43H71N9O11``（MW 890.1），不是三肽。这也是"静默给错分子"。
   因此 ``kind="peptide3"`` 由本模块自己把 3 字母码翻成 1 字母码再交给 RDKit，
   而不是把 3 字母串原样丢给 RDKit。
3. **序列里的空白会被 RDKit 当成"多接两个氢"**。``"GA VL"`` 与 ``"GAVL"`` 分子式
   不同（前者多 2 个 H），却都不报错。所以本模块在调用 RDKit 前先把空白与 ``-``
   （纯分隔符）去掉，并把"改了什么"记进 ``warnings``，不静默改分子。

口径
----
- ``smiles`` 是 RDKit 生成的**规范 SMILES**，可直接喂给 ``check`` / ``properties`` /
  ``analyze`` / ``draw`` —— 这是"接得上现有工具链"的关键。
- ``mw`` 是平均分子量（含同位素丰度加权），``exact_mw`` 是单同位素精确质量。
- ``atom_count`` 是**重原子数**（RDKit ``GetNumAtoms`` 口径，不含隐式氢），
  与 ``properties()["heavy_atoms"]`` 同口径。
- 失败一律抛 ``ValueError``，原因走 ``i18n``（``code`` 与语言无关这一约定同样适用；
  这里没有分级 warn/error，因为"分子到底是不是你要的那个"不该由本模块裁决）。
"""

from __future__ import annotations

import re
from typing import Any

from rdkit import Chem
from rdkit.Chem import Descriptors, rdMolDescriptors

from ._rdkit import capture_log
from .i18n import t

# --------------------------------------------------------------------------
# 常量与类型口径
# --------------------------------------------------------------------------

#: 允许的 ``kind``：``auto`` 只在能确定时推断（HELM 前缀），否则报错要求显式指定。
KINDS = ("auto", "peptide", "peptide3", "rna", "dna", "helm", "idt")

#: 序列类 kind（不含 auto / helm）。
SEQUENCE_KINDS = ("peptide", "peptide3", "rna", "dna")

#: kind → RDKit ``MolFromSequence`` 的 flavor。
#: 注意 DNA 是 **6**；3 是 RNA 5' 帽（会多接一个磷酸），不是 DNA（见模块开头）。
_FLAVOR: dict[str, int] = {"peptide": 0, "rna": 2, "dna": 6}
_FLAVOR_REFERENCE = {
    0: "protein, L amino acids",
    1: "protein, D amino acids",
    2: "RNA, no cap",
    3: "RNA, 5' cap（不是 DNA！）",
    4: "RNA, 3' cap",
    5: "RNA, both caps",
    6: "DNA, no cap",
    7: "DNA, 5' cap",
    8: "DNA, 3' cap",
    9: "DNA, both caps",
}

#: 标准 20 种氨基酸的 1 字母码（RDKit 的肽字母表就是这 20 个）。
PEPTIDE_ALPHABET = "ACDEFGHIKLMNPQRSTVWY"

#: RDKit 的核酸字母表实测是 ACGTU（T 与 U 在 RNA / DNA flavor 下都被接受）。
NUCLEIC_ALPHABET = "ACGTU"

#: 3 字母氨基酸码 → 1 字母码。只收标准 20 种：RDKit 的 1 字母表也只认这 20 个，
#: 收进来的扩展码（Sec/Pyl/Xaa…）在下一步必然失败，不如在这里给出更准的报错。
AA3: dict[str, str] = {
    "Ala": "A", "Arg": "R", "Asn": "N", "Asp": "D", "Cys": "C",
    "Gln": "Q", "Glu": "E", "Gly": "G", "His": "H", "Ile": "I",
    "Leu": "L", "Lys": "K", "Met": "M", "Phe": "F", "Pro": "P",
    "Ser": "S", "Thr": "T", "Trp": "W", "Tyr": "Y", "Val": "V",
}

#: HELM 的类型前缀。命中即"输入自带类型"，可以确定地推断（不是猜）。
_HELM_RE = re.compile(r"^(PEPTIDE|RNA|DNA|CHEM)\d*\{", re.IGNORECASE)
_HELM_REQUIRED_SUFFIX = "$$$$"

#: HELM 前缀 → 与 SEQUENCE_KINDS 对应的"声明类型"，用于和调用方给的 kind 对账。
_HELM_CLASS_TO_KIND = {"PEPTIDE": "peptide", "RNA": "rna", "DNA": "dna"}
_KIND_TO_HELM_CLASS = {"peptide": "PEPTIDE", "peptide3": "PEPTIDE", "rna": "RNA", "dna": "DNA"}

#: 序列里允许作为分隔符去掉的字符：空白 + 连字符。
#: 只去这两个 —— 实测 RDKit 自己忽略 ``-``，但**不**忽略空格（空格会改变分子式），
#: 而 ``.`` 之类的字符在 RDKit 眼里是有效但不同的东西，绝不能当分隔符吞掉。
_SEQ_SEPARATORS = re.compile(r"[\s\-]+")

#: IDT（Integrated DNA Technologies）记法。
#:
#: 为什么单拎出来：Ketcher 大分子编辑器导出核酸时给的**就是 IDT 记法**
#: （实测用户画 RNA 得到 ``rArCrGrTrU/3Phos/``），而它不是纯序列 ——
#: 残基带糖型前缀（``r``=核糖、``d``=脱氧、``m``=2'-O-甲基、``+``=LNA），
#: 还有 ``/3Phos/`` 这类末端修饰。RDKit 的 ``MolFromSequence`` 只认纯字母序列，
#: 所以必须**先翻译、再对账**，不能直接喂给它（否则会被当成非法字母，报出
#: 一串毫无意义的字符）。
#:
#: 支持的判据（保守）：出现 ``/xxx/`` 修饰，或出现带糖型前缀的残基。
_IDT_MODIFIER_RE = re.compile(r"/[A-Za-z0-9]+/")
_IDT_RESIDUE_RE = re.compile(r"(\+|r|d|m)?([ACGTU])(\*?)")
#: IDT 糖型前缀 → 说明（用于报错时说清"这串里有什么 RDKit 表达不了的东西"）
_IDT_SUGAR_ZH = {"r": "核糖 r", "d": "脱氧 d", "m": "2'-O-甲基 m", "+": "LNA +"}



# --------------------------------------------------------------------------
# 能力检测
# --------------------------------------------------------------------------
def bioseq_capabilities() -> dict[str, Any]:
    """报告当前 RDKit 是否具备生物大分子解析能力（供上层做功能开关 / 排错）。

    ``MolFromSequence`` / ``MolFromHELM`` 并非所有 RDKit 版本都有；老版本上直接调用
    会得到 ``AttributeError``。本模块内部走 :func:`_require` 把它们变成可操作的人话错误，
    这个函数则让调用方**提前**问清楚，而不是撞上去。
    """
    import rdkit

    return {
        "rdkit_version": rdkit.__version__,
        "mol_from_sequence": hasattr(Chem, "MolFromSequence"),
        "mol_from_helm": hasattr(Chem, "MolFromHELM"),
        "kinds": list(KINDS),
        "sequence_flavors": dict(_FLAVOR),
        "sequence_flavor_reference": dict(_FLAVOR_REFERENCE),
        "_notes": {
            "flavor": (
                "本模块只用无帽口径：肽=0、RNA=2、DNA=6。"
                "特别注意 DNA 是 6；flavor=3 是 RNA 5' 帽，不是 DNA"
            ),
            "peptide3": "3 字母码由本模块自行翻成 1 字母码，RDKit 2023.09.6 并不真正支持 3 字母码",
        },
    }


def _require(api: str):
    """取 RDKit 的某个接口；缺失时给人话错误而不是 ``AttributeError``。"""
    fn = getattr(Chem, api, None)
    if fn is None:
        import rdkit

        raise ValueError(t("bioseq_rdkit_unsupported", rdkit.__version__, api))
    return fn


# --------------------------------------------------------------------------
# 文本预处理
# --------------------------------------------------------------------------
def _clip(text: str, limit: int = 60) -> str:
    """把长输入截断成可放进报错的短串（保留证据，但别把一整条 HELM 糊到人脸上）。"""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit] + "…"


def _clean_sequence(text: str) -> tuple[str, str | None]:
    """去掉序列里的分隔符并转大写，返回 ``(规范化序列, 是否发生过改动的说明)``。

    空白必须去：RDKit 不把空格当分隔符，而是让它变成额外的氢（实测 ``"GA VL"``
    比 ``"GAVL"`` 多 2 个 H、且不报错）。我们不静默改分子，但也不把这种输入直接
    判死 —— 去掉分隔符并把这次改动记进 ``warnings`` 是更诚实的做法。
    """
    stripped = text.strip()
    cleaned = _SEQ_SEPARATORS.sub("", stripped)
    note = None
    if cleaned != stripped:
        note = t("bioseq_normalized", _clip(stripped, 40), cleaned)
    return cleaned.upper(), note


def _peptide3_to_letters(text: str) -> str:
    """把 3 字母氨基酸码序列翻成 1 字母序列。

    支持的写法：``Gly-Ala-Val``、``GlyAlaVal``、``Gly Ala Val``、``Gly.Ala.Val``。
    失败时抛 ``ValueError``（未知码 / 无法按 3 字切分），绝不猜。
    """
    raw = text.strip()
    tokens = [tok for tok in re.split(r"[\s\-_.,;:/|]+", raw) if tok]
    if not tokens:
        raise ValueError(t("bioseq_empty"))

    codes: list[str] = []
    for token in tokens:
        if len(token) % 3 != 0:
            raise ValueError(t("bioseq_peptide3_malformed", _clip(raw)))
        codes.extend(token[i:i + 3] for i in range(0, len(token), 3))

    letters: list[str] = []
    known = ", ".join(sorted(AA3))
    for code in codes:
        one = AA3.get(code.capitalize())
        if one is None:
            raise ValueError(t("bioseq_peptide3_unknown", code, known))
        letters.append(one)
    return "".join(letters)


def _helm_class(text: str) -> str:
    """取 HELM 字符串声明的类型前缀（``PEPTIDE`` / ``RNA`` / ``DNA`` / ``CHEM``）。"""
    m = _HELM_RE.match(text)
    return m.group(1).upper() if m else ""


def _looks_like_helm(text: str) -> bool:
    return bool(_HELM_RE.match(text.strip()))


# --------------------------------------------------------------------------
# 两条解析路径
# --------------------------------------------------------------------------
def _finish(mol, *, kind: str, requested_kind: str, fmt: str, api: str,
            flavor: int | None, sequence: str | None, helm_class: str | None,
            warnings: list[str]) -> dict[str, Any]:
    """把 RDKit 的分子整理成统一返回结构（含口径声明）。"""
    smiles = Chem.MolToSmiles(mol)
    if not smiles:
        # MolToSmiles 理论上只对空分子返回空串；这里兜底，避免把""当成功值传下去
        raise ValueError(t("bioseq_seq_unparsable", kind, "", ""))

    heavy = mol.GetNumAtoms()
    return {
        "input": None,                      # 占位，由 parse_bioseq 填回原始输入
        "kind": kind,
        "requested_kind": requested_kind,
        "format": fmt,                      # "sequence" | "helm"
        "rdkit_api": api,                   # MolFromSequence | MolFromHELM
        "rdkit_flavor": flavor,             # 序列口径；HELM 为 None
        "helm_class": helm_class,           # HELM 声明类型；序列为 None
        "sequence": sequence,               # 规范化的 1 字母序列；HELM 为 None
        "residues": len(sequence) if sequence is not None else None,
        "smiles": smiles,
        "formula": rdMolDescriptors.CalcMolFormula(mol),
        "mw": round(Descriptors.MolWt(mol), 4),
        "exact_mw": round(Descriptors.ExactMolWt(mol), 6),
        "atom_count": heavy,                # 重原子数（RDKit GetNumAtoms 口径）
        "heavy_atoms": heavy,               # 与 properties() 同名字段，方便对照
        "warnings": warnings,
        "_notes": {
            "smiles": (
                "RDKit 生成的规范 SMILES，可直接喂给本项目其它工具"
                "（check / properties / analyze / draw）"
            ),
            "kind": (
                "类型一律由调用方显式指定：同一串字母在肽和核酸里都合法，"
                "RDKit 只会按默认 flavor 解析且不报错"
            ),
            "mw": "平均分子量（含同位素丰度加权）",
            "exact_mw": "单同位素精确质量",
            "atom_count": "重原子数（不含隐式氢），与 properties()['heavy_atoms'] 同口径",
            "rdkit_flavor": (
                "0=肽(L) / 2=RNA 无帽 / 6=DNA 无帽；注意 3 是 RNA 5' 帽而不是 DNA"
            ),
        },
    }


def _looks_like_idt(text: str) -> bool:
    """是不是 IDT 记法。

    判据保守：**必须**有 ``/…/`` 修饰，或者有带糖型前缀的残基（``rA``/``dC``/``mA``/``+G``）。
    纯 ``ACGU`` 不算 —— 那是普通序列，有它自己的路径。
    """
    s = text.strip()
    if _IDT_MODIFIER_RE.search(s):
        return True
    return any(res.group(1) for res in _IDT_RESIDUE_RE.finditer(s))


def _parse_idt(text: str, requested_kind: str) -> dict[str, Any]:
    """IDT 记法 → 纯序列 → 分子。

    **只在无损时才转换**，否则报错说明原因：

    - 末端/骨架修饰（``/3Phos/``、``/5Phos/``、``*`` 硫代磷酸…）→ 拒绝。
      RDKit 的序列解析器表达不了它们；硬转会**静默少掉一个磷酸（≈79.97 Da）**，
      得到一个分子量对不上、却看不出错的分子。
    - 糖型不统一（``rA`` 混 ``dC``）或非标准糖（``m``/``+``）→ 拒绝，同上。
    - 全是 ``r`` → RNA；全是 ``d`` 或无前缀 → DNA。这两种 RDKit 能**无损**表达
      （已实测：flavor=2 里的 ``T`` 给的是核糖胸苷，带 2'-OH，不是脱氧）。
    """
    s = text.strip()
    modifiers = _IDT_MODIFIER_RE.findall(s)
    if modifiers:
        raise ValueError(t("bioseq_idt_modifier", " ".join(modifiers), _clip(text)))

    body = _IDT_MODIFIER_RE.sub("", s)
    residues = []
    pos = 0
    for m in _IDT_RESIDUE_RE.finditer(body):
        if m.start() != pos:
            raise ValueError(t("bioseq_idt_unparsed", _clip(body[pos:], 20), _clip(text)))
        sugar, base, star = m.group(1) or "", m.group(2), m.group(3)
        if star:
            raise ValueError(t("bioseq_idt_backbone", _clip(text)))
        residues.append((sugar, base))
        pos = m.end()
    if pos != len(body) or not residues:
        raise ValueError(t("bioseq_idt_unparsed", _clip(body[pos:], 20), _clip(text)))

    sugars = {sugar for sugar, _ in residues}
    unsupported = sorted(sugars & {"m", "+"})
    if unsupported:
        names = "、".join(_IDT_SUGAR_ZH.get(x, x) for x in unsupported)
        raise ValueError(t("bioseq_idt_sugar_unsupported", names, _clip(text)))
    if len(sugars) > 1:
        raise ValueError(t("bioseq_idt_mixed_sugar",
                           "、".join(_IDT_SUGAR_ZH.get(x, "无前缀") for x in sorted(sugars)),
                           _clip(text)))

    sugar = next(iter(sugars)) if sugars else ""
    deduced = "rna" if sugar == "r" else "dna"

    # 调用方显式给了 kind 就与推断对账（rNA 的 IDT 不能被当成肽）
    if requested_kind in SEQUENCE_KINDS and requested_kind != deduced:
        raise ValueError(t("bioseq_idt_kind_mismatch", deduced, requested_kind, _clip(text)))

    sequence = "".join(base for _, base in residues)
    result = _from_sequence(sequence, deduced)
    result["format"] = "idt"
    result["idt_sugars"] = {"r": "ribose", "": "deoxyribose", "d": "deoxyribose"}[sugar]
    result["warnings"] = list(result.get("warnings") or []) + [
        t("bioseq_idt_normalized", deduced, sequence)]
    return result


def _from_sequence(text: str, kind: str) -> dict[str, Any]:
    """裸序列路径：先定字母表，再按 kind 对应的 flavor 调用 RDKit。"""
    warnings: list[str] = []

    if kind == "peptide3":
        letters = _peptide3_to_letters(text)
        flavor = _FLAVOR["peptide"]
        alphabet = PEPTIDE_ALPHABET
    else:
        letters, note = _clean_sequence(text)
        if note:
            warnings.append(note)
        flavor = _FLAVOR[kind]
        alphabet = PEPTIDE_ALPHABET if kind == "peptide" else NUCLEIC_ALPHABET

    if not letters:
        raise ValueError(t("bioseq_empty"))

    # 保序去重（原来用 sorted(set(...))，报出来是 "/3HOPRS" 这种看起来像乱码的东西；
    # 现在按出现顺序、空格分隔，人能一眼看出是哪些字符）
    bad = list(dict.fromkeys(ch for ch in letters if ch not in set(alphabet)))
    if bad:
        raise ValueError(t("bioseq_bad_letters", kind, " ".join(bad), alphabet, _clip(text)))

    # 字母表内的可疑组合：不拦，但要如实说出来（选了 rna/dna 就尊重选择）
    if kind == "rna" and "T" in letters:
        warnings.append(t("bioseq_rna_has_t"))
    if kind == "dna" and "U" in letters:
        warnings.append(t("bioseq_dna_has_u"))

    fn = _require("MolFromSequence")
    with capture_log():
        mol = fn(letters, sanitize=True, flavor=flavor)

    # 坑：``MolFromSequence("")`` 不返回 None，而是一个 0 原子的"空分子"（与
    # ``MolFromSmiles("")`` 同类）；空分子绝不能算成功。
    if mol is None or mol.GetNumAtoms() == 0:
        raise ValueError(t("bioseq_seq_unparsable", kind, _clip(text), alphabet))

    result = _finish(
        mol, kind=kind, requested_kind=kind, fmt="sequence",
        api="MolFromSequence", flavor=flavor, sequence=letters,
        helm_class=None, warnings=warnings,
    )
    return result


def _from_helm(text: str, helm_class: str, requested_kind: str) -> dict[str, Any]:
    """HELM 路径：前缀自带类型，只需要完整性检查 + RDKit 解析。"""
    stripped = text.strip()
    if not stripped.endswith(_HELM_REQUIRED_SUFFIX):
        # RDKit 对缺失 $$$$ 很宽容（``PEPTIDE1{G.A.V.L}`` 照样解析），但那意味着文本
        # 可能被截断；截断后仍可能解析出一个"看起来成功"的更短分子。所以主动拦住。
        raise ValueError(t("bioseq_helm_unterminated", _clip(stripped)))

    fn = _require("MolFromHELM")
    with capture_log():
        mol = fn(stripped)

    if mol is None or mol.GetNumAtoms() == 0:
        raise ValueError(t("bioseq_helm_unparsable", _clip(stripped)))

    return _finish(
        mol, kind="helm", requested_kind=requested_kind, fmt="helm",
        api="MolFromHELM", flavor=None, sequence=None,
        helm_class=helm_class, warnings=[],
    )


# --------------------------------------------------------------------------
# 对外入口
# --------------------------------------------------------------------------
def parse_bioseq(value: str, kind: str = "auto") -> dict[str, Any]:
    """把肽/核酸的序列或 HELM 解析成分子（并给出可直接续用的规范 SMILES）。

    Args:
        value: 序列（``GAVL`` / ``Gly-Ala-Val`` / ``AUGC`` …）或 HELM
            （``PEPTIDE1{G.A.V.L}$$$$``）。
        kind: ``auto`` / ``peptide`` / ``peptide3`` / ``rna`` / ``dna`` / ``helm``。
            **裸序列必须显式给类型**：``auto`` 只对 HELM 这种"自带类型前缀"的输入做推断；
            遇到裸序列一律报错，因为 ``A/T/G/C`` 既是氨基酸字母也是碱基字母，
            RDKit 会静默按肽算出一个分子式完全不同的分子（详见模块 docstring）。

    Returns:
        含 ``input`` / ``kind`` / ``format`` / ``smiles`` / ``formula`` / ``mw`` /
        ``atom_count`` 等的 dict，口径写在 ``_notes`` 里。

    Raises:
        ValueError: 输入为空、kind 非法、类型有歧义、字母非法、HELM 不完整或无法解析，
            或当前 RDKit 缺少所需接口。原因均为中/英人话（随 ``MOL_LANG``）。
    """
    if not isinstance(value, str):
        raise ValueError(t("bioseq_empty"))
    if not isinstance(kind, str):
        raise ValueError(t("bioseq_bad_kind", " / ".join(KINDS), repr(kind)))

    key = kind.strip().lower()
    if key not in KINDS:
        raise ValueError(t("bioseq_bad_kind", " / ".join(KINDS), repr(kind)))

    text = value.strip()
    if not text:
        raise ValueError(t("bioseq_empty"))

    if _looks_like_helm(text):
        declared = _helm_class(text)
        # 调用方给了序列类 kind 时，和 HELM 自己声明的类型对账：
        # 一致就照解析，冲突就报错 —— 两边都不猜。
        if key in _KIND_TO_HELM_CLASS and declared != _KIND_TO_HELM_CLASS[key]:
            raise ValueError(t("bioseq_helm_kind_mismatch", declared, key))
        result = _from_helm(text, declared, key)
        result["input"] = value
        return result

    if key == "helm":
        raise ValueError(t("bioseq_not_helm", _clip(text)))

    if key == "idt" or _looks_like_idt(text):
        # IDT 是**自带糖型**的记法（``rA``/``dC``），不算"猜"；但它的子集有限，
        # 表达不了的部分由 _parse_idt 明确拒绝（见那里的注释）。
        result = _parse_idt(text, key)
        result["input"] = value
        return result

    if key == "auto":
        # 这条是本模块的核心策略：没有类型信息就**不解析**，而不是选个默认值。
        raise ValueError(t("bioseq_ambiguous", _clip(text)))

    result = _from_sequence(text, key)
    result["input"] = value
    return result
