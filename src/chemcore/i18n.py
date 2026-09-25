"""消息国际化（zh / en）。

为什么单独一层
--------------
诊断文本是这个项目**最主要的对外输出**（模型和人都靠它理解错在哪）。
中文写死会让英文使用者拿到读不懂的报错——对一个要开源的库这是硬伤。

设计
----
- ``code`` 永远与语言无关（`unclosed_ring` 之类），**文本**才随语言变。
  调用方与测试断言 code，不要断言文案。
- 语言解析顺序：显式参数 > ``MOL_LANG`` 环境变量 > 默认 ``zh``。
  默认保持 zh（现有行为不变、可预测）；英文使用者设一个环境变量即可。
- 缺翻译时**回退**到默认语言并保留 key 可见（``[missing:xxx]``），
  绝不抛异常 —— 报错信息本身不该再报错。
"""

from __future__ import annotations

import os
from typing import Any

DEFAULT_LANG = "zh"
SUPPORTED = ("zh", "en")

_override: str | None = None


def _normalize(lang: str | None) -> str | None:
    if not lang:
        return None
    low = lang.strip().lower().replace("_", "-")
    if low.startswith("zh"):
        return "zh"
    if low.startswith("en"):
        return "en"
    return None


def current_lang() -> str:
    """当前生效语言。"""
    if _override:
        return _override
    return _normalize(os.environ.get("MOL_LANG")) or DEFAULT_LANG


def set_lang(lang: str | None) -> None:
    """设置进程级语言；传 ``None`` 清除覆盖，回到环境变量/默认。"""
    global _override
    _override = _normalize(lang)


def t(key: str, *args: Any, lang: str | None = None) -> str:
    """取一条本地化文本并格式化。

    Args:
        key: 消息 key（与语言无关）。
        *args: 位置参数，按 ``{}`` 顺序代入。
        lang: 临时指定语言；缺省用 :func:`current_lang`。
    """
    resolved = _normalize(lang) or current_lang()
    table = MESSAGES.get(resolved) or MESSAGES[DEFAULT_LANG]
    template = table.get(key)
    if template is None:
        template = MESSAGES[DEFAULT_LANG].get(key)
    if template is None:
        return f"[missing:{key}]"
    if not args:
        return template
    try:
        return template.format(*args)
    except (IndexError, KeyError):
        return template


# --------------------------------------------------------------------------
# 词条表
# --------------------------------------------------------------------------
MESSAGES: dict[str, dict[str, str]] = {
    "zh": {
        # —— 输入层 ——
        "empty": "输入为空：没有可解析的 SMILES 内容",
        "no_atoms": "没有解析出任何原子：输入可能只含空白或无效片段",
        # —— RDKit 日志翻译 ——
        "unclosed_ring": "环闭合标记没有配对：SMILES 里的成环数字（如 C1...C1）出现次数必须是偶数",
        "extra_paren": "多余的右括号：) 比 ( 多",
        "missing_paren": "括号没有闭合：( 比 ) 多",
        "valence": "原子价键数超限：第 {0} 号原子（{1}）的连接数是 {2}，超过该元素允许的最大值",
        "unusual_charge": "电荷异常：第 {0} 号原子的形式电荷在常见化学里很少见，请确认不是笔误",
        "kekulize": "芳香环无法 Kekulé 化：芳香性写法或环上取代基有问题",
        "bad_element": "元素符号无法识别（{0}）：注意大小写，如 Cl 不是 CL、c 是芳香碳而 C 是脂肪碳",
        "aromatic_nonring": "非环原子被标成芳香（第 {0} 号）：芳香小写字母只能用在环上",
        "syntax": "SMILES 语法错误：在这附近有非法字符或不完整片段",
        "parse_error": "SMILES 解析失败",
        "parse_failed": "RDKit 无法解析该 SMILES，且未给出具体原因",
        "ring_bond_redundant": "环闭合时重复指定了键型（如 C=1CCCC=1 之类）",
        "rdkit_warning": "RDKit 提示：{0}",
        # —— 我们自己补的字符定位 ——
        "unclosed_ring_position": (
            "成环编号 {0} 只出现了 {1} 次（最后一次在第 {2} 个字符）："
            "成环数字必须成对出现，如 C1CC1 而不是 C1CC"
        ),
        "extra_paren_at": "多余的右括号：第 {0} 个字符处",
        "missing_paren_at": "括号没有闭合：第 {0} 个字符处的 ( 未配对",
        "extra_bracket_at": "多余的右方括号：第 {0} 个字符处",
        "missing_bracket_at": "方括号没有闭合：第 {0} 个字符处的 [ 未配对",
        "mismatched_bracket_at": "括号类型不匹配：第 {0} 个字符处应为 ]",
        # —— 各模块抛出的错误 ——
        "err_smiles_parse": "SMILES 无法解析：{0}",
        "err_smarts_parse": "SMARTS 无法解析：{0}",
        "err_inchi_parse": "InChI 无法解析（检查前缀 InChI= 与校验位）",
        "err_molblock_parse": "MOL/SDF 结构块无法解析（检查是否缺少标题行或原子块被截断）",
        "err_inchikey_readonly": "InChIKey 是单向摘要，无法反推结构",
        "err_inchi_unsupported": (
            "无法生成 InChI：分子含 InChI 不支持的元素 —— 最常见的是聚合物 RU-SMILES 里的"
            " * 虚原子（InChI 规范不支持 dummy atom）。若要唯一标识，请改用 canonical SMILES。"
        ),
        "err_inchikey_unsupported": (
            "无法生成 InChIKey：分子含 InChI 不支持的元素（最常见是 RU-SMILES 里的 * 虚原子）。"
            "请改用 canonical SMILES 做唯一标识。"
        ),
        "err_bad_src_format": "不支持的源格式：{0}",
        "err_bad_dst_format": "目标格式须是 {0} 之一，收到 {1}",
        "err_bad_image_format": "只支持 png / svg，收到 {0}",
        "err_no_drawable": "没有任何可画的分子（全部解析失败）",
        "err_bad_fp": "指纹类型须是 {0} 之一，收到 {1}",
        "err_bad_metric": "metric 只支持 tanimoto / dice",
        "err_mol_parse_labeled": "分子 {0} 的 SMILES 无法解析：{1}",
        "err_query_parse": "查询 SMILES 无法解析：{0}",
        "err_csv_column": "CSV 里没有列 {0}；现有列：{1}",
        "warn_no_cjk_font": (
            "图注含中文，但系统找不到可用的中文字体 → 图里将没有图注。"
            "请安装中文字体（如 fonts-noto-cjk），或改用 ASCII 图注。"
        ),
    },
    "en": {
        "empty": "Empty input: nothing to parse as SMILES",
        "no_atoms": "No atoms were parsed: the input may be blank or contain only invalid fragments",
        "unclosed_ring": (
            "Unpaired ring-closure digit: ring numbers in SMILES (e.g. C1...C1) "
            "must appear an even number of times"
        ),
        "extra_paren": "Too many closing parentheses: more ) than (",
        "missing_paren": "Unclosed parenthesis: more ( than )",
        "valence": (
            "Valence exceeded: atom #{0} ({1}) has {2} connections, "
            "above the maximum allowed for that element"
        ),
        "unusual_charge": (
            "Unusual charge: the formal charge on atom #{0} is very rare in real chemistry — "
            "please check for a typo"
        ),
        "kekulize": "Aromatic ring cannot be kekulized: check the aromatic notation or ring substituents",
        "bad_element": (
            "Unrecognized element symbol ({0}): mind the case — Cl not CL, "
            "lowercase c is aromatic carbon while uppercase C is aliphatic"
        ),
        "aromatic_nonring": (
            "Atom #{0} is marked aromatic but is not in a ring: "
            "lowercase aromatic atoms may only appear in rings"
        ),
        "syntax": "SMILES syntax error: an illegal character or incomplete fragment near here",
        "parse_error": "SMILES parsing failed",
        "parse_failed": "RDKit could not parse this SMILES and gave no specific reason",
        "ring_bond_redundant": "A ring-closure bond type was specified twice (e.g. C=1CCCC=1)",
        "rdkit_warning": "RDKit note: {0}",
        "unclosed_ring_position": (
            "Ring-closure digit {0} appears {1} time(s) (last at character {2}): "
            "ring numbers must come in pairs, e.g. C1CC1 rather than C1CC"
        ),
        "extra_paren_at": "Extra closing parenthesis at character {0}",
        "missing_paren_at": "Unclosed parenthesis: the ( at character {0} has no partner",
        "extra_bracket_at": "Extra closing bracket at character {0}",
        "missing_bracket_at": "Unclosed bracket: the [ at character {0} has no partner",
        "mismatched_bracket_at": "Mismatched bracket: expected ] at character {0}",
        "err_smiles_parse": "Cannot parse SMILES: {0}",
        "err_smarts_parse": "Cannot parse SMARTS: {0}",
        "err_inchi_parse": "Cannot parse InChI (check the InChI= prefix and the check digit)",
        "err_molblock_parse": (
            "Cannot parse the MOL/SDF block (check for a missing title line or a truncated atom block)"
        ),
        "err_inchikey_readonly": "InChIKey is a one-way digest and cannot be converted back to a structure",
        "err_inchi_unsupported": (
            "Cannot generate InChI: the molecule contains an element InChI does not support — most"
            " commonly the `*` dummy atom in polymer RU-SMILES (InChI has no dummy-atom support)."
            " Use canonical SMILES as the identifier instead."
        ),
        "err_inchikey_unsupported": (
            "Cannot generate InChIKey: the molecule contains an element InChI does not support"
            " (most commonly the `*` dummy atom in RU-SMILES). Use canonical SMILES instead."
        ),
        "err_bad_src_format": "Unsupported source format: {0}",
        "err_bad_dst_format": "Target format must be one of {0}, got {1}",
        "err_bad_image_format": "Only png / svg are supported, got {0}",
        "err_no_drawable": "No drawable molecules (every entry failed to parse)",
        "err_bad_fp": "Fingerprint kind must be one of {0}, got {1}",
        "err_bad_metric": "metric supports only tanimoto / dice",
        "err_mol_parse_labeled": "Cannot parse SMILES of molecule {0}: {1}",
        "err_query_parse": "Cannot parse the query SMILES: {0}",
        "err_csv_column": "CSV has no column {0}; available columns: {1}",
        "warn_no_cjk_font": (
            "Legends contain CJK characters but no CJK font was found → the image will have no "
            "legends. Install a CJK font (e.g. fonts-noto-cjk) or use ASCII legends."
        ),
    },
}
