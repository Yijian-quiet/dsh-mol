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


@case("convert: RU-SMILES 带 * 时 InChI 失败要报错，不能静默返回空串")
def _():
    # 领域相关：聚合物 RU-SMILES 必带 * 虚原子，而 InChI 不支持 dummy atom。
    # RDKit 此时**返回空串而不抛异常** —— 静默空值是最危险的返回。
    ru = "*OCCOC(=O)c1ccc(C(=O)O*)cc1"
    for target in ("inchi", "inchikey"):
        try:
            out = cc.convert(ru, to=target)["value"]
            raise AssertionError(f"to={target} 应当抛 ValueError，实际返回 {out!r}")
        except ValueError as exc:
            msg = str(exc)
            true("InChI" in msg, f"错误信息应提到 InChI：{msg}")
            true("虚原子" in msg or "RU-SMILES" in msg,
                 f"应点明领域原因（* 虚原子 / RU-SMILES）：{msg}")


@case("convert: 不带 * 的分子 InChI 往返正常（对照组）")
def _():
    mono = "OC(=O)c1ccc(C(=O)O)cc1"
    inchi = cc.convert(mono, to="inchi")["value"]
    true(inchi.startswith("InChI="), "应生成合法 InChI")
    eq(cc.convert(inchi, to="smiles")["value"], cc.check(mono).canonical, "往返一致")


@case("convert: RU-SMILES 的 InChI 报错也支持英文")
def _():
    ru = "*CC(*)C"
    try:
        cc.convert(ru, to="inchi", src="smiles")
        raise AssertionError("应当抛 ValueError")
    except ValueError:
        pass
    # 走 i18n 全局语言
    original = cc.current_lang()
    try:
        cc.set_lang("en")
        try:
            cc.convert(ru, to="inchi")
            raise AssertionError("应当抛 ValueError")
        except ValueError as exc:
            true("Cannot generate InChI" in str(exc), f"英文文案缺失：{exc}")
    finally:
        cc.set_lang(original)


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


@case("draw: 不同渲染选项产出不同文件名（不再互相覆盖）")
def _():
    # 曾经：文件名只由 SMILES 决定 → 改图注/加原子编号重画会覆盖上一张
    with tempfile.TemporaryDirectory() as d:
        a = os.path.basename(cc.draw(ASPIRIN, out=d)["path"])
        b = os.path.basename(cc.draw(ASPIRIN, out=d, atom_indices=True)["path"])
        c = os.path.basename(cc.draw(ASPIRIN, out=d, legend="阿司匹林")["path"])
        eq(len({a, b, c}), 3, "三种不同选项应产出三个文件")
        again = os.path.basename(cc.draw(ASPIRIN, out=d)["path"])
        eq(again, a, "相同选项应幂等（同名覆盖）")


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


@case("i18n: 环境变量 MOL_LANG 生效")
def _():
    import os
    old_env = os.environ.get("MOL_LANG")
    try:
        cc.set_lang(None)                       # 先清覆盖，让环境变量说话
        os.environ["MOL_LANG"] = "en"
        eq(cc.current_lang(), "en", "env 解析")
        true("Empty input" in cc.check("").diagnostics[0].message, "env 驱动的英文")
    finally:
        os.environ.pop("MOL_LANG", None)
        if old_env is not None:
            os.environ["MOL_LANG"] = old_env
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


# ---------------------------------------------------------------- analyze / cli
@case("analyze: 阿司匹林的类药性与骨架对得上已知值")
def _():
    d = cc.druglikeness(ASPIRIN)
    eq(d["formula"], "C9H8O4", "分子式")
    eq(d["lipinski_violations"], 0, "阿司匹林不该违反 Lipinski")
    close(d["qed"], 0.55, 0.02, "QED")
    eq(d["murcko_scaffold"], "c1ccccc1", "骨架是苯环")
    true(0.0 <= d["qed"] <= 1.0, "QED 必须落在 0-1")
    # 规则明细必须齐全：4 条 Lipinski + 2 条 Veber
    eq(len(d["rules"]), 6, "规则条数")
    true(all("passed" in r and "detail" in r for r in d["rules"]), "每条规则都要有判定与明细")


@case("analyze: 结构警报能命中（阿司匹林的酚酯）")
def _():
    d = cc.druglikeness(ASPIRIN, catalogs=("BRENK",))
    true(any("phenol_ester" in a["description"] for a in d["structural_alerts"]),
         f"应命中 phenol_ester，实际 {d['structural_alerts']}")
    eq(d["catalogs_checked"], ["BRENK"], "查了哪些目录要如实回报")
    # 干净的分子不该无端报警
    eq(cc.druglikeness("CCO")["structural_alerts"], [], "乙醇不该有结构警报")


@case("analyze: 综合分析与 properties 的分子式一致（不许两套口径）")
def _():
    a = cc.analyze(ASPIRIN)
    p = cc.properties(ASPIRIN)
    eq(a["formula"], p["formula"], "分子式")
    eq(a["canonical"], p["canonical"], "规范化 SMILES")
    eq(a["properties"]["mw"], p["mw"], "分子量")
    true("lipinski_violations" in a["druglikeness"], "综合分析要带类药性")


@case("analyze: 坏结构抛人话 ValueError，不是 RDKit 英文日志")
def _():
    try:
        cc.analyze("C1CC")
        raise AssertionError("应当抛 ValueError")
    except ValueError as exc:
        true("环闭合" in str(exc) or "配对" in str(exc), f"应是人话诊断：{exc}")


def _cli(payload):
    """按 CLI 协议调一次：JSON 进 len(stdout) 一行 JSON 出。"""
    import json as _json
    import subprocess
    src = os.path.join(os.path.dirname(__file__), "..", "src")
    proc = subprocess.run(
        [sys.executable, "-m", "chemcore.cli"],
        input=payload if isinstance(payload, str) else _json.dumps(payload),
        capture_output=True, text=True, timeout=90,
        env={**os.environ, "PYTHONPATH": src},
    )
    return proc, _json.loads(proc.stdout)


@case("cli: 成功响应形如 {ok, op, result}")
def _():
    proc, out = _cli({"op": "properties", "smiles": "CCO"})
    eq(proc.returncode, 0, "退出码")
    eq(out["ok"], True, "ok")
    eq(out["op"], "properties", "op 回显")
    eq(out["result"]["formula"], "C2H6O", "分子式")
    eq(proc.stderr.strip(), "", "成功时 stderr 不该有噪音（否则上层会以为是故障）")


@case("cli: 领域错误也是结构化响应，且退出码为 0")
def _():
    proc, out = _cli({"op": "properties", "smiles": "C1CC"})
    eq(proc.returncode, 0, "领域错误属于业务答案，不该用非零退出码")
    eq(out["ok"], False, "ok")
    eq(out["code"], "domain_error", "code")
    true("环闭合" in out["message"] or "配对" in out["message"], f"人话原因：{out['message']}")


@case("cli: 未知 op / 坏 JSON / 缺字段都给人话，不崩")
def _():
    _, out = _cli({"op": "no_such_op"})
    eq(out["code"], "unknown_op", "未知 op")
    true("可用的 op" in out["message"], "应列出可用 op")
    _, out = _cli("这不是 JSON")
    eq(out["code"], "invalid_json", "坏 JSON")
    _, out = _cli({"smiles": "CCO"})
    eq(out["code"], "invalid_request", "缺 op")
    _, out = _cli({"op": "properties"})
    eq(out["code"], "invalid_request", "缺参数应报调用错误")


@case("cli: 注册表里的每个 op 都能真跑通（防止文档吹了没实现的）")
def _():
    import importlib
    cli = importlib.import_module("chemcore.cli")
    samples = {
        "check": {"smiles": "CCO"},
        "canonicalize": {"smiles": "OCC"},
        "properties": {"smiles": "CCO"},
        "druglikeness": {"smiles": "CCO"},
        "analyze": {"smiles": "CCO"},
        "substructure": {"smiles": "c1ccccc1", "smarts": "c1ccccc1"},
        "similarity": {"a": "CCO", "b": "CCCO"},
        "standardize": {"smiles": "[Na+].CC(=O)[O-]"},
        "dedupe": {"smiles_list": ["CCO", "OCC"]},
        "convert": {"value": "CCO", "to": "inchikey"},
        "bioseq": {"value": "GAVL", "kind": "peptide"},
        "batch_clean": {"smiles_list": ["CCO", "C1CC"]},
        "draw": {"smiles": "CCO"},
        "draw_grid": {"smiles_list": ["CCO", "CCC"]},
        "descriptors": {},
    }
    eq(sorted(samples), sorted(cli.OPS), "每个 op 都要有测试样本（新增 op 请补一条）")
    for op, params in samples.items():
        with tempfile.TemporaryDirectory() as d:
            if op in ("draw", "draw_grid"):
                params = {**params, "out": d}
            out = cli.run({"op": op, **params})
            eq(out["ok"], True, f"{op} 应成功：{out.get('message')}")


# ---------------------------------------------------------------- bioseq
# 大分子（肽 / 核酸）：Ketcher 里画的这些东西没有 SMILES，只有序列或 HELM。
# 这里的回归重点是两条 —— (1) 四种类型都算得对；(2) **绝不猜类型**。
@case("bioseq: 肽 1 字母 GAVL 对得上实测分子量与分子式")
def _():
    r = cc.parse_bioseq("GAVL", kind="peptide")
    eq(r["kind"], "peptide", "kind")
    eq(r["format"], "sequence", "format")
    eq(r["formula"], "C16H30N4O5", "分子式")
    close(r["mw"], 358.4, 0.05, "mw")
    eq(r["residues"], 4, "残基数")
    eq(r["rdkit_flavor"], 0, "flavor")


@case("bioseq: 肽 3 字母按 3 字母翻译（RDKit 其实不支持，不能给出 9 肽）")
def _():
    r = cc.parse_bioseq("Gly-Ala-Val", kind="peptide3")
    eq(r["formula"], "C10H19N3O4", "三肽分子式")
    close(r["mw"], 245.28, 0.05, "三肽分子量")
    eq(r["residues"], 3, "残基数")
    # 反例：RDKit 原生把 3 字母串当**大小写不敏感的单字母**读 —— "Gly-Ala-Val" 会变成
    # G,L,Y,A,L,A,V,A,L 的 9 肽（C43H71N9O11 / MW 890.1）且不报错。我们必须给化学上
    # 正确的三肽，绝不能把那个值当成"3 字母解析成功"。
    true(abs(r["mw"] - 890.1) > 1.0, "不能把 3 字母串当 1 字母读出 9 肽")


@case("bioseq: RNA 对得上实测值（flavor=2，无帽）")
def _():
    r = cc.parse_bioseq("AUGC", kind="rna")
    eq(r["formula"], "C38H48N15O26P3", "分子式")
    close(r["mw"], 1223.8, 0.05, "mw")
    eq(r["rdkit_flavor"], 2, "flavor")


@case("bioseq: DNA 用 flavor=6（不是 3 —— 3 是 RNA 5' 帽）")
def _():
    r = cc.parse_bioseq("ATGC", kind="dna")
    eq(r["formula"], "C39H50N15O22P3", "分子式")
    close(r["mw"], 1173.8, 0.05, "mw")
    eq(r["rdkit_flavor"], 6, "DNA 的 flavor 必须是 6")
    # 同一串 "ATGC" 在三个 kind 下必须是三个不同的分子 —— 这正是"不能猜"的硬理由
    pep = cc.parse_bioseq("ATGC", kind="peptide")
    rna = cc.parse_bioseq("ATGC", kind="rna")
    eq(len({pep["smiles"], rna["smiles"], r["smiles"]}), 3, "三种类型应是三个不同分子")


@case("bioseq: HELM 两种（PEPTIDE1 / RNA1）能解析且类型自证")
def _():
    p = cc.parse_bioseq("PEPTIDE1{G.A.V.L}$$$$")
    eq(p["format"], "helm", "format")
    eq(p["kind"], "helm", "kind")
    eq(p["helm_class"], "PEPTIDE", "声明类型")
    close(p["mw"], 358.4, 0.05, "肽 HELM")
    r = cc.parse_bioseq("RNA1{R(A)P.R(U)P.R(G)}$$$$")
    eq(r["helm_class"], "RNA", "声明类型")
    close(r["mw"], 918.6, 0.05, "RNA HELM")
    # auto 对 HELM 是**确定推断**（前缀自带类型），不是猜
    eq(cc.parse_bioseq("PEPTIDE1{G.A.V.L}$$$$")["formula"], p["formula"], "auto 应走 HELM")


@case("bioseq: 歧义保护 —— 裸序列 auto 必须报错，绝不默认当肽")
def _():
    for text in ("ATGC", "GAVL", "AUGC"):
        try:
            got = cc.parse_bioseq(text)
            raise AssertionError(f"parse_bioseq({text!r}) 应当抛 ValueError，实际 kind={got.get('kind')}")
        except ValueError as exc:
            msg = str(exc)
            true("无法判断" in msg, f"应说明无法判断类型：{msg[:60]}")
            true("显式指定" in msg, f"应要求显式指定 kind：{msg[:60]}")


@case("bioseq: 空串 / 非法字母 / 坏 kind 给人话错误")
def _():
    for bad in ("", "   "):
        try:
            cc.parse_bioseq(bad, kind="peptide")
            raise AssertionError(f"{bad!r} 应当抛 ValueError")
        except ValueError as exc:
            true("输入为空" in str(exc), f"{bad!r}: {exc}")
    try:
        cc.parse_bioseq("GAVL", kind="protein")
        raise AssertionError("坏 kind 应当抛 ValueError")
    except ValueError as exc:
        true("kind" in str(exc) and "protein" in str(exc), f"应说明 kind 非法：{exc}")
    try:
        cc.parse_bioseq("GAVL", kind="rna")
        raise AssertionError("非法字母应当抛 ValueError")
    except ValueError as exc:
        true("非法字母" in str(exc), f"应指出非法字母：{exc}")


@case("bioseq: HELM 缺 $$$$ / 语法坏 / 类型冲突都明确报错")
def _():
    try:
        cc.parse_bioseq("PEPTIDE1{G.A.V.L}", kind="helm")
        raise AssertionError("缺 $$$$ 应当抛 ValueError")
    except ValueError as exc:
        true("$$$$" in str(exc), f"应说明缺结束标记：{exc}")
    try:
        cc.parse_bioseq("PEPTIDE1{}}$$$$")
        raise AssertionError("坏 HELM 应当抛 ValueError")
    except ValueError as exc:
        true("HELM" in str(exc), f"应说明 HELM 无法解析：{exc}")
    try:
        cc.parse_bioseq("RNA1{R(A)P}$$$$", kind="peptide")
        raise AssertionError("HELM 声明与 kind 冲突应当抛 ValueError")
    except ValueError as exc:
        true("声明" in str(exc), f"应说明类型冲突：{exc}")


@case("bioseq: 3 字母码非法/无法切分要报错，且不静默换读法")
def _():
    try:
        cc.parse_bioseq("Gly-Xyz-Val", kind="peptide3")
        raise AssertionError("未知 3 字母码应当抛 ValueError")
    except ValueError as exc:
        true("Xyz" in str(exc), f"应指出未知码：{exc}")
    try:
        cc.parse_bioseq("GAVL", kind="peptide3")
        raise AssertionError("1 字母串按 peptide3 应当抛 ValueError")
    except ValueError as exc:
        true("3 的整数倍" in str(exc), f"应说明按 3 字切分失败：{exc}")
    try:
        cc.parse_bioseq("GAV", kind="peptide3")
        raise AssertionError("把 1 字母串的 3 个字母当码应当抛 ValueError")
    except ValueError as exc:
        true("kind='peptide'" in str(exc), f"应提示改用 peptide：{exc}")
    eq(cc.parse_bioseq("GlyAlaVal", kind="peptide3")["formula"],
       cc.parse_bioseq("Gly-Ala-Val", kind="peptide3")["formula"], "两种写法应一致")


@case("bioseq: 序列里的空白被规范化并记进 warnings（RDKit 会静默改分子）")
def _():
    r = cc.parse_bioseq("G A V L", kind="peptide")
    eq(r["sequence"], "GAVL", "规范化序列")
    eq(r["formula"], "C16H30N4O5", "去掉空白后分子式应正确")
    true(any("空白" in w for w in r["warnings"]), f"应记录规范化动作：{r['warnings']}")
    # 对照：RDKit 原生不把空格当分隔符，而会把它变成额外的氢（分子式就变了且不报错）


@case("bioseq: 返回的 smiles 能被 properties / analyze 直接吃下（接得上工具链）")
def _():
    for value, kind in [("GAVL", "peptide"), ("AUGC", "rna"), ("ATGC", "dna"),
                        ("PEPTIDE1{G.A.V.L}$$$$", "helm")]:
        r = cc.parse_bioseq(value, kind=kind)
        p = cc.properties(r["smiles"])
        eq(p["formula"], r["formula"], f"{value} properties 分子式")
        close(p["mw"], r["mw"], 0.01, f"{value} properties mw")
        a = cc.analyze(r["smiles"])
        eq(a["formula"], r["formula"], f"{value} analyze 分子式")
        eq(a["canonical"], p["canonical"], f"{value} canonical 一致")


@case("bioseq: 能力检测如实报告 RDKit 接口与 flavor 口径")
def _():
    caps = cc.bioseq_capabilities()
    eq(caps["mol_from_sequence"], True, "MolFromSequence 可用")
    eq(caps["mol_from_helm"], True, "MolFromHELM 可用")
    eq(caps["sequence_flavors"], {"peptide": 0, "rna": 2, "dna": 6}, "flavor 口径")


@case("bioseq: 英文报错可读且不出现中文")
def _():
    original = cc.current_lang()
    try:
        cc.set_lang("en")
        try:
            cc.parse_bioseq("ATGC")
            raise AssertionError("应当抛 ValueError")
        except ValueError as exc:
            msg = str(exc)
            true("Cannot tell" in msg, f"英文文案缺失：{msg[:80]}")
            true(not any("\u4e00" <= ch <= "\u9fff" for ch in msg),
                 f"英文模式下不应有中文：{msg[:80]}")
    finally:
        cc.set_lang(original)


# ---------------------------------------------------------------- 汇总
# 语言无关的机器可读标记。每个 README*.md（含翻译版）都必须带这两行，
# 位置固定在文件末尾（许可章节之后），一行一个数字：
#     <!-- dsh-mol:test-count 65 -->
#     <!-- dsh-mol:tool-count 13 -->
README_TEST_MARKER = "dsh-mol:test-count"
README_TOOL_MARKER = "dsh-mol:tool-count"


def _actual_tool_count():
    """实际注册的 MCP 工具数 —— 从适配层源码里数 @mcp.tool 装饰器，不在这里写死。

    返回 None 表示数不出来（源码缺失、或注册方式改了）：调用方会跳过工具数校验，
    而不是拿一个假数字去误报六个 README。
    """
    import pathlib, re
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "src" / "dsh_mol_mcp" / "server.py")
    if not src.exists():
        return None
    n = len(re.findall(r"^@mcp\.tool\(", src.read_text(encoding="utf-8"), re.M))
    return n or None


README_UI_MARKER = "dsh-mol:ui-assertions"


def _actual_ui_assertions():
    """界面验收的**断言总数**，从 `dsh-ui/tests/ui-assertions.json` 读。

    这个数字只能由跑过 Playwright 的那次运行写入（`verify-ui.cjs` 结尾自己记），
    Python 侧算不出来 —— 所以设计成"跑过就有记录、没跑过就不校验"，而不是猜一个数。
    文件不存在时返回 None（CI 只跑 Python 测试，不跑浏览器，不该因此报错）。
    """
    import json
    import pathlib
    f = pathlib.Path(__file__).resolve().parent.parent / "dsh-ui" / "tests" / "ui-assertions.json"
    if not f.exists():
        return None
    try:
        return int(json.loads(f.read_text(encoding="utf-8"))["total"])
    except (ValueError, KeyError, TypeError):
        return None


def check_readme_count():
    """README 里写的数字必须与实际一致 —— 文档数字最容易悄悄过期。

    两道机制并用：

    1. **语言无关的标记**（新增）：扫仓库根下所有 `README*.md`，每份都必须带
       `<!-- dsh-mol:test-count N -->`（以及工具数 `<!-- dsh-mol:tool-count N -->`），
       且 N 等于实际值。翻译版没有中文/英文正则可用，靠的就是这个标记 ——
       缺标记要报错，数字不符也要报错，翻译版不会悄悄过期。
    标记制还覆盖**界面断言数**（`dsh-mol:ui-assertions`）：那个数只能由跑过 Playwright 的
    `verify-ui.cjs` 写进 `dsh-ui/tests/ui-assertions.json`，所以"没跑过就不校验"，
    不会让只跑 Python 的 CI 误报。

    2. **中文/英文原文正则**（保留）：`(\\d+)\\s*个核心用例` / `(\\d+)\\s*core cases`，
       对 `README.md` / `README.en.md` 仍然有意义，所以不删。
    """
    import pathlib, re
    total = len(PASS) + len(FAIL)
    tools = _actual_tool_count()
    ui = _actual_ui_assertions()
    root = pathlib.Path(__file__).resolve().parent.parent
    problems = []

    readmes = sorted(root.glob("README*.md"))
    if not readmes:
        problems.append("仓库根下没找到任何 README*.md")
    for p in readmes:
        text = p.read_text(encoding="utf-8")
        checks = [("用例数", README_TEST_MARKER, total)]
        if tools is not None:
            checks.append(("工具数", README_TOOL_MARKER, tools))
        if ui is not None:
            checks.append(("界面断言数", README_UI_MARKER, ui))
        for label, marker, actual in checks:
            m = re.search(rf"<!--\s*{re.escape(marker)}\s+(\d+)\s*-->", text)
            if not m:
                problems.append(
                    f"{p.name}: 缺少语言无关标记 <!-- {marker} {actual} -->（{label}）")
            elif int(m.group(1)) != actual:
                problems.append(
                    f"{p.name}: {label}标记写的是 {m.group(1)}，实际 {actual}")

    # 旧机制：中文/英文原文里的用例数声明（保留，向后兼容）
    for f, pat in (("README.md", r"(\d+)\s*个核心用例"),
                   ("README.en.md", r"(\d+)\s*core cases")):
        p = root / f
        if not p.exists():
            continue
        m = re.search(pat, p.read_text(encoding="utf-8"))
        if not m:
            problems.append(f"{f}: 找不到用例数声明")
        elif int(m.group(1)) != total:
            problems.append(f"{f}: 写的是 {m.group(1)}，实际 {total}")
    return problems


if __name__ == "__main__":
    total = len(PASS) + len(FAIL)
    print(f"\n通过 {len(PASS)}/{total}")
    for prob in check_readme_count():
        FAIL.append(("README 文档数字与实际不一致", prob))
        print(f"  ✗ {prob}")
    for name, why in FAIL:
        print(f"  ✗ {name}\n      {why}")
    if FAIL:
        print("\n有失败用例。")
        sys.exit(1)
    print("全部通过 ✅")
