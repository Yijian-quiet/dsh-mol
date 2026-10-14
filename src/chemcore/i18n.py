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
        # —— 生物大分子（肽 / 核酸）——
        # 核心一条是 bioseq_ambiguous：裸序列有歧义时**拒绝解析并要求显式指定 kind**，
        # 因为 RDKit 会静默按肽解析出一个分子式完全不同的分子（见 bioseq 模块 docstring）。
        "bioseq_empty": "输入为空：没有可解析的序列或 HELM 内容",
        "bioseq_bad_kind": (
            "kind 只能是 {0} 之一，收到 {1}。裸序列本身不带类型信息，必须由你显式指定。"
        ),
        "bioseq_ambiguous": (
            "无法判断「{0}」是肽还是核酸，已拒绝解析：A/T/G/C 这几个字母既是氨基酸"
            "（Ala/Thr/Gly/Cys）也是碱基（腺嘌呤/胸腺嘧啶/鸟嘌呤/胞嘧啶），而 RDKit 的 "
            "MolFromSequence 默认只按肽解析、**不会报错** —— 同一个串按肽 / RNA / DNA 算出来是"
            "分子式完全不同的三个分子，选错了没有任何迹象。请显式指定 kind：peptide"
            "（1 字母氨基酸）/ peptide3（3 字母氨基酸）/ rna / dna；HELM 字符串"
            "（以 PEPTIDE1 / RNA1 / DNA1 前缀开头）自带类型，也可以直接传。"
        ),
        "bioseq_rdkit_unsupported": (
            "当前 RDKit（{0}）没有 {1} 接口，无法解析生物大分子序列。"
            "MolFromSequence / MolFromHELM 需要 RDKit ≥ 2022.09；请升级：pip install -U rdkit"
        ),
        "bioseq_idt_modifier": (
            "这是 IDT 记法，且带末端/骨架修饰「{0}」：RDKit 的序列解析器表达不了它，"
            "已拒绝解析。硬转成纯序列会**静默少掉这个修饰**（例如 /3Phos/ 是一个 3′ 磷酸，"
            "分子量少约 79.97，却看不出任何异常）。请给不含修饰的纯序列（ACGU / ACGT），"
            "或改用自带修饰信息的 HELM（以 RNA1 / DNA1 前缀开头）。"
        ),
        "bioseq_idt_unparsed": (
            "IDT 记法无法解析：位置「{0}」不符合 IDT 语法（残基形如 rA / dC / A，"
            "修饰形如 /3Phos/）。原始输入：{1}"
        ),
        "bioseq_idt_backbone": (
            "IDT 记法里有硫代磷酸骨架「*」：RDKit 的序列解析器表达不了它，已拒绝解析"
            "（硬转会静默丢掉这个硫）。原始输入：{0}"
        ),
        "bioseq_idt_sugar_unsupported": (
            "IDT 记法里有 RDKit 序列解析器表达不了的糖型：{0}。"
            "已拒绝解析 —— 硬转会得到一个化学上不相符、却看不出错的分子。原始输入：{1}"
        ),
        "bioseq_idt_mixed_sugar": (
            "IDT 记法里混用了不同糖型（{0}）：RDKit 的 MolFromSequence 一次只能表达"
            "一种糖型（全核糖或全脱氧），混用会算错。已拒绝解析。原始输入：{1}"
        ),
        "bioseq_idt_kind_mismatch": (
            "IDT 记法本身声明这是 {0}，但调用方给的 kind 是 {1} —— 两边不一致，已拒绝解析"
            "（这个记法的糖型前缀是**声明**，不是猜出来的：r=核糖、d=脱氧）。原始输入：{2}"
        ),
        "bioseq_idt_normalized": (
            "IDT 记法 → {0} 序列「{1}」：逐残基糖型一致，属于无损转换"
            "（已实测：flavor=2 下的 T 给的是核糖胸苷，带 2′-OH）"
        ),
        "bioseq_normalized": (
            "输入里的空白/连字符按分隔符移除了：{0} → {1}"
            "（RDKit 不把空格当分隔符，而会把它变成额外的氢）"
        ),
        "bioseq_bad_letters": (
            "{0} 序列里出现非法字母「{1}」：{0} 只接受 {2}。"
            "如果这串其实属于另一类生物大分子，请改 kind（同一串字母在肽与核酸里含义不同）。"
        ),
        "bioseq_seq_unparsable": (
            "{0} 序列无法解析：{1}（RDKit 只返回 None、不给原因；该类型的合法字母是 {2}）"
        ),
        "bioseq_rna_has_t": (
            "rna 序列里出现了 DNA 碱基 T：RDKit 会照它算出核糖核苷酸，"
            "请确认不是把 DNA 写成了 RNA"
        ),
        "bioseq_dna_has_u": (
            "dna 序列里出现了 RNA 碱基 U：RDKit 会照它算出脱氧核苷酸，"
            "请确认不是把 RNA 写成了 DNA"
        ),
        "bioseq_peptide3_unknown": (
            "3 字母氨基酸码无法识别：「{0}」。标准氨基酸码只有这 20 个：{1}。"
            "如果你手上其实是 1 字母序列（如 GAVL），请改用 kind='peptide'"
        ),
        "bioseq_peptide3_malformed": (
            "3 字母氨基酸序列无法切分：{0}。去掉分隔符后长度应是 3 的整数倍，"
            "例如 Gly-Ala-Val 或 GlyAlaVal"
        ),
        "bioseq_helm_unterminated": (
            "HELM 字符串缺少结束标记 $$$$（连接层结束符）：{0}。"
            "RDKit 对这种缺失很宽容、会照常解析，但那说明文本可能已被截断 —— "
            "截断后它仍可能给出一个更短的分子且毫无提示，所以我们主动拦住。请补全 $$$$。"
        ),
        "bioseq_helm_unparsable": (
            "HELM 字符串无法解析：{0}。RDKit 没有给出原因（只返回 None）。"
            "常见原因：单体名拼写错误、分隔符（. / | / 括号）不配对，"
            "或用了当前 RDKit 不支持的 HELM 单体（实测 2023.09.6 解析不了 DNA1 与 CHEM1）。"
        ),
        "bioseq_helm_kind_mismatch": (
            "输入是 HELM 字符串、它自己声明为 {0}，但你指定了 kind={1}。"
            "HELM 的类型由前缀确定（PEPTIDE1 / RNA1 / DNA1 / CHEM1），本工具不去猜；"
            "请改用 kind='helm'（或 kind='auto'），或改成与声明一致的 kind。"
        ),
        "bioseq_not_helm": (
            "kind='helm' 要求输入以 PEPTIDE1 / RNA1 / DNA1 / CHEM1 前缀开头，收到：{0}"
        ),
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
        # —— biomolecules (peptides / nucleic acids) ——
        "bioseq_empty": "Empty input: no sequence or HELM content to parse",
        "bioseq_bad_kind": (
            "kind must be one of {0}, got {1}. A bare sequence carries no type information, "
            "so the type has to be given explicitly."
        ),
        "bioseq_ambiguous": (
            "Cannot tell whether \"{0}\" is a peptide or a nucleic acid, so parsing was refused: "
            "A/T/G/C are valid both as amino acids (Ala/Thr/Gly/Cys) and as bases "
            "(adenine/thymine/guanine/cytosine), and RDKit's MolFromSequence defaults to reading "
            "the string as a peptide **without raising any error** — the same string yields three "
            "different molecular formulas as peptide / RNA / DNA, and a wrong choice leaves no "
            "trace. Pass an explicit kind: peptide (1-letter amino acids) / peptide3 (3-letter "
            "amino acids) / rna / dna. A HELM string (starting with the PEPTIDE1 / RNA1 / DNA1 "
            "prefix) declares its own type and may be passed directly."
        ),
        "bioseq_rdkit_unsupported": (
            "This RDKit ({0}) has no {1} entry point, so biological sequences cannot be parsed. "
            "MolFromSequence / MolFromHELM require RDKit >= 2022.09; upgrade with: pip install -U rdkit"
        ),
        "bioseq_idt_modifier": (
            "This is IDT notation with a terminal/backbone modification \"{0}\": RDKit's "
            "sequence parser cannot express it, so parsing was refused. Forcing a plain "
            "sequence would **silently drop the modification** (e.g. /3Phos/ is a 3' phosphate, "
            "about 79.97 Da, and nothing would look wrong). Pass an unmodified sequence "
            "(ACGU / ACGT) or use HELM (RNA1 / DNA1 prefix), which carries modifications."
        ),
        "bioseq_idt_unparsed": (
            "Cannot parse IDT notation: \"{0}\" does not fit the IDT grammar (residues look like "
            "rA / dC / A, modifications like /3Phos/). Original input: {1}"
        ),
        "bioseq_idt_backbone": (
            "IDT notation contains a phosphorothioate backbone \"*\", which RDKit's sequence "
            "parser cannot express; parsing was refused (forcing it would silently drop the "
            "sulfur). Original input: {0}"
        ),
        "bioseq_idt_sugar_unsupported": (
            "IDT notation uses sugar chemistry RDKit's sequence parser cannot express: {0}. "
            "Parsing was refused -- forcing it would produce a chemically different molecule "
            "with nothing looking wrong. Original input: {1}"
        ),
        "bioseq_idt_mixed_sugar": (
            "IDT notation mixes sugar types ({0}): RDKit's MolFromSequence can express only one "
            "sugar type at a time (all-ribose or all-deoxy), so mixing would compute the wrong "
            "molecule. Parsing was refused. Original input: {1}"
        ),
        "bioseq_idt_kind_mismatch": (
            "The IDT notation itself declares {0}, but kind was given as {1} -- they disagree, so "
            "parsing was refused (the sugar prefix is a **declaration**, not a guess: "
            "r=ribose, d=deoxy). Original input: {2}"
        ),
        "bioseq_idt_normalized": (
            "IDT notation -> {0} sequence \"{1}\": sugar type is uniform per residue, so this is "
            "a lossless conversion (verified: T under flavor=2 is ribothymidine with a 2'-OH)"
        ),
        "bioseq_normalized": (
            "Whitespace/hyphens in the input were removed as separators: {0} -> {1} "
            "(RDKit does not treat a space as a separator; it turns it into extra hydrogens)"
        ),
        "bioseq_bad_letters": (
            "Illegal letter(s) \"{1}\" in a {0} sequence: {0} accepts only {2}. "
            "If the string actually belongs to the other kind of biomolecule, change kind "
            "(the same letters mean different things in peptides and nucleic acids)."
        ),
        "bioseq_seq_unparsable": (
            "Cannot parse the {0} sequence {1} (RDKit returns None without a reason; the legal "
            "letters for this type are {2})"
        ),
        "bioseq_rna_has_t": (
            "The rna sequence contains the DNA base T: RDKit will build a ribonucleotide from it "
            "— confirm this is not DNA written as RNA"
        ),
        "bioseq_dna_has_u": (
            "The dna sequence contains the RNA base U: RDKit will build a deoxyribonucleotide "
            "from it — confirm this is not RNA written as DNA"
        ),
        "bioseq_peptide3_unknown": (
            "Unknown 3-letter amino-acid code: \"{0}\". Only these 20 standard codes exist: {1}. "
            "If you actually have a 1-letter sequence (e.g. GAVL), use kind='peptide'"
        ),
        "bioseq_peptide3_malformed": (
            "Cannot split this 3-letter amino-acid sequence: {0}. After removing separators the "
            "length must be a multiple of 3, e.g. Gly-Ala-Val or GlyAlaVal"
        ),
        "bioseq_helm_unterminated": (
            "The HELM string is missing its terminator $$$$ (end of the connection layer): {0}. "
            "RDKit happily parses such a string, but a missing terminator means the text may be "
            "truncated — and a truncated string can still yield a shorter molecule with no "
            "warning — so we block it here. Please append the full $$$$."
        ),
        "bioseq_helm_unparsable": (
            "Cannot parse this HELM string: {0}. RDKit gives no reason (it only returns None). "
            "Common causes: a misspelled monomer name, unbalanced separators (. / | / brackets), "
            "or a monomer this RDKit does not support (as measured, 2023.09.6 cannot parse DNA1 "
            "or CHEM1)."
        ),
        "bioseq_helm_kind_mismatch": (
            "The input is a HELM string that declares itself as {0}, but you passed kind={1}. "
            "A HELM type comes from its prefix (PEPTIDE1 / RNA1 / DNA1 / CHEM1) and is never "
            "guessed; use kind='helm' (or kind='auto'), or pass a kind that matches the declaration."
        ),
        "bioseq_not_helm": (
            "kind='helm' requires the input to start with the PEPTIDE1 / RNA1 / DNA1 / CHEM1 "
            "prefix, got: {0}"
        ),
        "warn_no_cjk_font": (
            "Legends contain CJK characters but no CJK font was found → the image will have no "
            "legends. Install a CJK font (e.g. fonts-noto-cjk) or use ASCII legends."
        ),
    },
}
