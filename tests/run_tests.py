#!/usr/bin/env python3
"""chemcore 测试 —— 零依赖（不需要 pytest）。

运行：
    PYTHONPATH=src python3 tests/run_tests.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import chemcore as cc  # noqa: E402

PASS, FAIL = [], []


def case(name):
    def deco(fn):
        try:
            fn()
        except AssertionError as exc:
            FAIL.append((name, str(exc) or "断言失败"))
        except Exception:
            FAIL.append((name, "异常: " + traceback.format_exc(limit=2).strip().splitlines()[-1]))
        else:
            PASS.append(name)
        return fn
    return deco


def eq(actual, expected, label=""):
    assert actual == expected, f"{label} 期望 {expected!r}，实际 {actual!r}"


def true(cond, label=""):
    assert cond, f"{label} 应为真"


def close(actual, expected, tol, label=""):
    assert abs(actual - expected) <= tol, f"{label} 期望 {expected}±{tol}，实际 {actual}"


ASPIRIN = "CC(=O)Oc1ccccc1C(=O)O"

# ---------------------------------------------------------------- validate
@case("validate: 正常分子通过且规范化")
def _():
    r = cc.check(ASPIRIN)
    eq(r.level, "ok", "level")
    eq(r.formula, "C9H8O4", "formula")
    eq(r.num_atoms, 13, "原子数")
    true(r.canonical and cc.check(r.canonical).level == "ok", "规范化结果应可再解析")


@case("validate: 规范化是幂等的")
def _():
    c1 = cc.check(ASPIRIN).canonical
    c2 = cc.check(c1).canonical
    eq(c2, c1, "二次规范化")


@case("validate: 空串被拦（RDKit 会当合法，这是坑）")
def _():
    r = cc.check("")
    eq(r.level, "error", "level")
    eq(r.diagnostics[0].code, "empty", "code")


@case("validate: 环未闭合指出是哪个编号、在哪")
def _():
    r = cc.check("C1CC")
    eq(r.level, "error", "level")
    eq(r.position, 1, "position")        # C0 1→1 C2 C3
    precise = [d for d in r.diagnostics if d.code == "unclosed_ring_position"]
    true(precise, f"应给出精确的成环编号诊断：{[d.code for d in r.diagnostics]}")
    true("成环编号 1" in precise[0].message, f"信息应指出编号：{precise[0].message}")


@case("validate: 成环数字成对时不误报")
def _():
    for good in ("C1CC1", "c1ccccc1", "C1CCCCC1", "C%10CC%10"):
        eq(cc.check(good).level, "ok", f"{good} 不应报错")


@case("validate: 方括号内的数字不算成环标记")
def _():
    r = cc.check("[13CH4]")
    eq(r.level, "ok", "[13CH4] 应通过（13 是同位素，不是成环编号）")


@case("validate: 两位成环编号 %10 也能定位")
def _():
    r = cc.check("C%10CC")
    eq(r.level, "error", "level")
    true(any(d.code == "unclosed_ring_position" and "10" in d.message
             for d in r.diagnostics), f"应指出编号 10：{[d.message for d in r.diagnostics]}")


@case("validate: 纯空白也失败")
def _():
    eq(cc.check("   ").level, "error", "level")


@case("validate: 环未闭合 → 人话原因")
def _():
    r = cc.check("C1CC")
    eq(r.level, "error", "level")
    true(any(d.code == "unclosed_ring" for d in r.diagnostics), "应有 unclosed_ring")
    true("环闭合" in r.diagnostics[0].message, "信息应是中文人话")


@case("validate: 非法元素/语法错误")
def _():
    r = cc.check("c1ccccc1X")
    eq(r.level, "error", "level")
    true(len(r.diagnostics) >= 1, "应有诊断")


@case("validate: 价键超限给出原子序号")
def _():
    r = cc.check("C(C)(C)(C)(C)C")
    eq(r.level, "error", "level")
    true(any(d.code == "valence" for d in r.diagnostics), "应有 valence")
    true("价键" in r.diagnostics[0].message, "应说明价键超限")


@case("validate: 多余右括号能定位到字符位置")
def _():
    r = cc.check("CC(=O)O)")
    eq(r.level, "error", "level")
    eq(r.position, 7, "position")   # C0 C1 (2 =3 O4 )5 O6 )7
    true(any(d.code == "extra_paren" for d in r.diagnostics), "应有 extra_paren")


@case("validate: 未闭合括号能定位")
def _():
    r = cc.check("CC(=O")
    eq(r.level, "error", "level")
    eq(r.position, 2, "position")
    true(any(d.code == "missing_paren" for d in r.diagnostics), "应有 missing_paren")


@case("validate: 异常电荷 → warn 而非 error（分级）")
def _():
    r = cc.check("[Fe+9]")
    eq(r.level, "warn", "level")
    true(r.ok, "warn 仍应视为可用")
    true(any(d.code == "unusual_charge" for d in r.diagnostics), "应有 unusual_charge")


@case("canonicalize: 失败返回 None 而不是抛异常")
def _():
    eq(cc.canonicalize("C1CC"), None, "坏输入")
    eq(cc.canonicalize(ASPIRIN), cc.check(ASPIRIN).canonical, "好输入")


# ---------------------------------------------------------------- props
@case("props: 阿司匹林数值正确")
def _():
    p = cc.properties(ASPIRIN)
    close(p["mw"], 180.16, 0.05, "mw")
    eq(p["formula"], "C9H8O4", "formula")
    eq(p["hbd"], 1, "hbd")
    eq(p["hba"], 3, "hba")
    eq(p["aromatic_rings"], 1, "芳香环")
    eq(p["formal_charge"], 0, "电荷")
    true("Crippen" in p["_notes"]["logp"], "应标注 logP 是估算值")


@case("props: 坏输入抛 ValueError 且带人话")
def _():
    try:
        cc.properties("C1CC")
        raise AssertionError("应当抛 ValueError")
    except ValueError as exc:
        true("环闭合" in str(exc), f"错误信息应是人话，实际：{exc}")


# ---------------------------------------------------------------- convert
@case("convert: SMILES→InChI→SMILES 往返一致")
def _():
    inchi = cc.convert(ASPIRIN, to="inchi")["value"]
    true(inchi.startswith("InChI="), "InChI 前缀")
    back = cc.convert(inchi, to="smiles")["value"]
    eq(back, cc.check(ASPIRIN).canonical, "往返")


@case("convert: InChIKey 与 MOL/SDF")
def _():
    key = cc.convert(ASPIRIN, to="inchikey")["value"]
    eq(len(key), 27, "InChIKey 长度")
    mol = cc.convert(ASPIRIN, to="mol")["value"]
    true("V2000" in mol or "M  END" in mol, "MOL block 结构")
    sdf = cc.convert(ASPIRIN, to="sdf")["value"]
    true(sdf.strip().endswith("$$$$"), "SDF 结束符")
    eq(cc.convert(mol, to="smiles")["value"], cc.check(ASPIRIN).canonical, "MOL 回转")


@case("convert: 格式嗅探")
def _():
    eq(cc.sniff(ASPIRIN), "smiles", "smiles")
    eq(cc.sniff("InChI=1S/C9H8O4/c1-6(10)13-8-5-3-2-4-7(8)9(11)12/h2-5H,1H3,(H,11,12)"), "inchi", "inchi")


@case("convert: InChIKey 不可反推（明确报错而不是瞎猜）")
def _():
    try:
        cc.convert("BSYNRYMUTXBXSQ-UHFFFAOYSA-N", to="smiles", src="inchikey")
        raise AssertionError("应当抛 ValueError")
    except ValueError as exc:
        true("单向" in str(exc) or "反推" in str(exc), "应说明不可反推")


# ---------------------------------------------------------------- draw
@case("draw: 生成 PNG / SVG，落盘且非空")
def _():
    with tempfile.TemporaryDirectory() as d:
        png = cc.draw(ASPIRIN, out=d, fmt="png")
        true(os.path.getsize(png["path"]) > 1000, "PNG 应有内容")
        svg = cc.draw(ASPIRIN, out=d, fmt="svg")
        true("<svg" in open(svg["path"], encoding="utf-8").read(), "SVG 应为矢量文本")


@case("draw: 原子编号与子结构高亮")
def _():
    with tempfile.TemporaryDirectory() as d:
        r = cc.draw(ASPIRIN, out=d, atom_indices=True, highlight_smarts="c1ccccc1")
        true(r["highlighted"], "应命中苯环并高亮")


@case("draw: 坏 SMILES 抛人话错误")
def _():
    with tempfile.TemporaryDirectory() as d:
        try:
            cc.draw("C1CC", out=d)
            raise AssertionError("应当抛 ValueError")
        except ValueError as exc:
            true("环闭合" in str(exc), f"实际：{exc}")


@case("draw_grid: 跳过坏条目但逐条记录（不静默丢）")
def _():
    with tempfile.TemporaryDirectory() as d:
        r = cc.draw_grid([ASPIRIN, "C1CC", "CCO"], out=d)
        eq(r["count"], 2, "画出 2 个")
        eq(len(r["skipped"]), 1, "跳过 1 个")
        eq(r["skipped"][0]["index"], 1, "跳过的是第 1 个")
        true("环闭合" in r["skipped"][0]["reason"], "跳过原因应是人话")


# ---------------------------------------------------------------- standardize
@case("standardize: 去盐 + 中和，并记录变更")
def _():
    r = cc.standardize("CC(=O)[O-].[Na+]")
    eq(r["output"], "CC(=O)O", "应去掉钠并中和")
    true(r["changed"], "changed 应为真")
    steps = {c["step"] for c in r["changes"]}
    true("largest_fragment" in steps and "uncharge" in steps, f"应有步骤记录，实际 {steps}")


@case("standardize: 默认不做互变异构（避免悄悄改结构）")
def _():
    r = cc.standardize("CC(=O)C")
    eq(r["output"], "CC(C)=O", "规范化后仍是酮式")


@case("dedupe: 识别重复并保留首次出现")
def _():
    r = cc.dedupe([ASPIRIN, "CCO", "OC(=O)c1ccccc1OC(C)=O", "C1CC"])
    eq(r["total"], 4, "总数")
    eq(r["unique"], 2, "唯一数")
    eq(len(r["duplicates"]), 1, "重复数")
    eq(r["duplicates"][0]["duplicate_of_index"], 0, "重复源")
    eq(len(r["failures"]), 1, "失败数")


# ---------------------------------------------------------------- batch
@case("dedupe: 字段名一致（duplicates 与 items 都用 canonical，不混用 key）")
def _():
    r = cc.dedupe([ASPIRIN, "OC(=O)c1ccccc1OC(C)=O"])
    eq(len(r["duplicates"]), 1, "重复数")
    d = r["duplicates"][0]
    true("canonical" in d, f"duplicates 条目应有 canonical 字段：{list(d)}")
    true("key" not in d, f"不应混用 key 这个别名：{list(d)}")
    true("canonical" in r["items"][0], "items 条目也应有 canonical")


@case("batch_clean: 混合输入计数正确并写出 CSV")
def _():
    with tempfile.TemporaryDirectory() as d:
        csv_path = os.path.join(d, "report.csv")
        r = cc.batch_clean([ASPIRIN, "C1CC", "[Fe+9]", "CCO"], out_csv=csv_path)
        eq(r["total"], 4, "总数")
        eq(r["ok"], 2, "ok 数")
        eq(r["warn"], 1, "warn 数")
        eq(r["failed"], 1, "failed 数")
        true(os.path.exists(csv_path), "CSV 应写出")
        header = open(csv_path, encoding="utf-8").readline()
        true("canonical" in header and "mw" in header, "CSV 表头应含规范化与性质列")


@case("read_smiles_column: 读 CSV 与 TXT")
def _():
    with tempfile.TemporaryDirectory() as d:
        p1 = os.path.join(d, "a.csv")
        open(p1, "w", encoding="utf-8").write("name,SMILES\nx,%s\ny,CCO\n" % ASPIRIN)
        eq(cc.read_smiles_column(p1), [ASPIRIN, "CCO"], "CSV 按表头取列")
        p2 = os.path.join(d, "b.smi")
        open(p2, "w", encoding="utf-8").write("CCO\n%s\n" % ASPIRIN)
        eq(cc.read_smiles_column(p2), ["CCO", ASPIRIN], "TXT 一行一个")


@case("draw: 中文图注不出现豆腐块（有字体则渲染，无字体则显式告警）")
def _():
    with tempfile.TemporaryDirectory() as d:
        r = cc.draw(ASPIRIN, out=d, legend="阿司匹林 aspirin")
        has_font = "legend_font" in r
        has_warn = any("字体" in w for w in r.get("warnings", []))
        true(has_font or has_warn,
             f"要么写上图注并报告字体，要么明确告警；实际 {r}")
        if has_font:
            true(os.path.getsize(r["path"]) > 1000, "带中文图注的 PNG 应有内容")


@case("draw_grid: 中文图注走自绘路径")
def _():
    with tempfile.TemporaryDirectory() as d:
        r = cc.draw_grid([ASPIRIN, "CCO"], out=d, legends=["阿司匹林", "乙醇"],
                         filename="cjk.png")
        eq(r["count"], 2, "画出 2 个")
        true(os.path.getsize(r["path"]) > 1000, "文件非空")


@case("draw: 缺中文字体时不留豆腐块（返回 warnings 字段）")
def _():
    # 注意：``chemcore.draw`` 既是子模块名、也是本包导出的函数名，
    # ``import chemcore.draw as D`` 拿到的是函数。要拿模块必须走 importlib。
    import importlib
    D = importlib.import_module("chemcore.draw")
    real = D.find_cjk_font
    D.find_cjk_font = lambda: None          # 模拟无中文字体环境
    try:
        with tempfile.TemporaryDirectory() as d:
            r = D.draw_grid([ASPIRIN], out=d, legends=["阿司匹林"], filename="x.png")
            true(any("字体" in w for w in r.get("warnings", [])),
                 f"应显式告警而不是默默产出豆腐块：{r}")
    finally:
        D.find_cjk_font = real


# ---------------------------------------------------------------- i18n
@case("i18n: 英文诊断可读，且不再出现中文")
def _():
    r = cc.check("C1CC", lang="en")
    eq(r.level, "error", "level")
    msgs = " ".join(d.message for d in r.diagnostics)
    true("Ring-closure digit" in msgs, f"英文文案缺失：{msgs[:80]}")
    true(not any("\u4e00" <= ch <= "\u9fff" for ch in msgs), f"英文模式下不应有中文：{msgs[:80]}")


@case("i18n: code 与语言无关（契约是 code，不是文案）")
def _():
    zh = cc.check("C1CC")
    en = cc.check("C1CC", lang="en")
    eq([d.code for d in en.diagnostics], [d.code for d in zh.diagnostics], "诊断 code 序列")
    eq(en.position, zh.position, "position")
    eq(en.canonical, zh.canonical, "canonical")
    # 等级也必须一致，否则行为会随语言漂移
    eq(en.level, zh.level, "level")


@case("i18n: 空输入 / 括号 / 价键 都有英文")
def _():
    cases = [("", "Empty input"), ("CC(=O)O)", "parenthes"),
             ("C(C)(C)(C)(C)C", "Valence exceeded"), ("[Fe+9]", "Unusual charge")]
    for smi, needle in cases:
        msgs = " ".join(d.message for d in cc.check(smi, lang="en").diagnostics)
        true(needle.lower() in msgs.lower(), f"{smi!r} 的英文诊断应含 {needle!r}，实际：{msgs[:70]}")


@case("i18n: set_lang 全局生效，且可复位")
def _():
    original = cc.current_lang()
    try:
        cc.set_lang("en")
        eq(cc.current_lang(), "en", "set_lang")
        true("Empty input" in cc.check("").diagnostics[0].message, "全局英文应生效")
        cc.set_lang(None)      # 清除覆盖
        eq(cc.current_lang(), cc.DEFAULT_LANG, "复位到默认")
    finally:
        cc.set_lang(original)


@case("i18n: 环境变量 CHEMWORKBENCH_LANG 生效")
def _():
    import os
    old_env = os.environ.get("CHEMWORKBENCH_LANG")
    try:
        cc.set_lang(None)                       # 先清覆盖，让环境变量说话
        os.environ["CHEMWORKBENCH_LANG"] = "en"
        eq(cc.current_lang(), "en", "env 解析")
        true("Empty input" in cc.check("").diagnostics[0].message, "env 驱动的英文")
    finally:
        os.environ.pop("CHEMWORKBENCH_LANG", None)
        if old_env is not None:
            os.environ["CHEMWORKBENCH_LANG"] = old_env
        cc.set_lang(None)


@case("i18n: 异常消息也走 i18n（ValueError 英文）")
def _():
    try:
        cc.properties("C1CC", )
    except ValueError:
        pass
    # properties 没有 lang 形参，走全局设置
    original = cc.current_lang()
    try:
        cc.set_lang("en")
        try:
            cc.standardize("C1CC")
            raise AssertionError("应当抛 ValueError")
        except ValueError as exc:
            true("Cannot parse SMILES" in str(exc), f"英文异常缺失：{exc}")
    finally:
        cc.set_lang(original)


# ---------------------------------------------------------------- 汇总
if __name__ == "__main__":
    total = len(PASS) + len(FAIL)
    print(f"\n通过 {len(PASS)}/{total}")
    for name, why in FAIL:
        print(f"  ✗ {name}\n      {why}")
    if FAIL:
        print("\n有失败用例。")
        sys.exit(1)
    print("全部通过 ✅")
