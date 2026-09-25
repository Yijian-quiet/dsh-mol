#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""retro_star_bridge.py 的**协议自检** —— 零依赖（只用标准库），不碰 Retro* 数据。

跑法：
    python3 dsh-ui/retro/selfcheck.py
    # 也可以指定解释器（比如 retro 环境里的那个）
    /path/to/retro/env/bin/python3 dsh-ui/retro/selfcheck.py

它在干两件事：
  A. **端到端**：真的把 retro_star_bridge.py 当子进程拉起来，喂 JSON 到 stdin、
     读 stdout，检查协议本身 ——
       * 数据缺失时必须回 retro_not_configured 且**退出码 0**（上层要能优雅展示）
       * 坏 JSON / 缺 smiles / 类型错 / 空 SMILES 必须回结构化 bad_request，
         不能是崩溃或半个栈
       * **stdout 必须是干干净净的一个 JSON**（日志、traceback 一律不许混进来）
       * retro_home 的解析优先级：环境变量 > 请求字段 > 内置默认
       * 数据检查必须发生在 import torch 之前（看响应里的 heavy_imports_skipped
         标记，以及本进程 import 桥接模块后 sys.modules 里没有 torch）
  B. **单元**：直接 import 桥接模块，测路线串 → 树的还原（这层不能依赖任何
     化学库，否则数据没装就没法测）。

为什么需要它：桥接脚本最容易坏的地方不是化学，是**协议**和**没装数据时的表现**。
这两样恰好可以在没有任何 Retro* 数据的机器上完整验证 —— 所以这份自检永远能跑。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.join(HERE, "retro_star_bridge.py")
PROJECT_ROOT = os.path.dirname(os.path.dirname(HERE))

FAILURES = []
PASSES = []


def check(name, condition, detail=""):
    if condition:
        PASSES.append(name)
        print("  [ok]   %s" % name)
    else:
        FAILURES.append((name, detail))
        print("  [FAIL] %s%s" % (name, ("  ← " + detail) if detail else ""))


def run_bridge(stdin_text, env_home=None, drop_env_home=False, argv=None, timeout=120,
               extra_env=None):
    """拉起桥接脚本，返回 (exit_code, stdout_str, stderr_str)。"""
    env = dict(os.environ)
    if drop_env_home:
        env.pop("RETRO_STAR_HOME", None)
    if env_home is not None:
        env["RETRO_STAR_HOME"] = env_home
    if env_home is None and not drop_env_home:
        env.setdefault("RETRO_STAR_HOME", "/nonexistent-retro-home-for-selfcheck")
    if extra_env:
        env.update(extra_env)

    cmd = [sys.executable, BRIDGE] + list(argv or [])
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
    )
    try:
        out, err = proc.communicate(
            stdin_text.encode("utf-8") if stdin_text is not None else b"", timeout=timeout
        )
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        return None, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
    return proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def parse_only_json(name, code, out):
    """stdout 必须是一个、且只有一个 JSON —— 这是整个协议的地基。"""
    stripped = out.strip()
    if not stripped:
        check(name + " · stdout 非空", False, "stdout 是空的")
        return None
    try:
        payload = json.loads(stripped)
    except ValueError as exc:
        check(name + " · stdout 是干净 JSON", False, "%s；stdout 前 200 字：%r" % (exc, stripped[:200]))
        return None
    check(name + " · stdout 是干净 JSON", True)
    check(name + " · stdout 无 traceback",
          "Traceback" not in out and "File \"" not in out,
          "stdout 里混进了栈")
    return payload


# ---------------------------------------------------------------------------
# A. 端到端
# ---------------------------------------------------------------------------

def e2e_cases(tmp):
    empty_home = os.path.join(tmp, "empty-retro-home")
    os.makedirs(empty_home)
    other_home = os.path.join(tmp, "other-retro-home")
    os.makedirs(other_home)
    gone_home = os.path.join(tmp, "does-not-exist-at-all")

    print("\n[1] 数据缺失 → retro_not_configured，退出码必须是 0")
    code, out, _ = run_bridge('{"smiles": "CCOC(=O)c1ccccc1"}', env_home=empty_home)
    payload = parse_only_json("not_configured", code, out)
    if payload:
        check("not_configured · 退出码 0（上层要能优雅展示，不是崩溃）", code == 0, "实际退出码 %r" % code)
        check("not_configured · code == retro_not_configured",
              payload.get("code") == "retro_not_configured", repr(payload.get("code")))
        check("not_configured · ok 是 false", payload.get("ok") is False)
        check("not_configured · backend 是 retro_star", payload.get("backend") == "retro_star")
        check("not_configured · retro_home 回显的是环境变量给的那个",
              payload.get("retro_home") == empty_home, repr(payload.get("retro_home")))
        missing = payload.get("missing") or []
        for rel in ("retro_star/dataset/origin_dict.csv",
                    "retro_star/one_step_model/template_rules_1.dat",
                    "retro_star/one_step_model/saved_rollout_state_1_2048.ckpt",
                    "retro_star/saved_models/best_epoch_final_4.pt"):
            check("not_configured · missing 含 %s" % rel, rel in missing, repr(missing))
        check("not_configured · setup 是给人看的一步步命令",
              isinstance(payload.get("setup"), str) and "pip install -e" in payload["setup"]
              and "dropbox" in payload["setup"].lower())
        check("not_configured · message 是中文人话且提到缺文件",
              isinstance(payload.get("message"), str) and "还没装好" in payload["message"])
        check("not_configured · heavy_imports_skipped == true（数据检查在 import torch 之前）",
              payload.get("heavy_imports_skipped") is True)

    print("\n[2] use_value_fn=false → 价值网络权重降级为可选")
    code, out, _ = run_bridge('{"smiles": "CCOC(=O)c1ccccc1", "use_value_fn": false}', env_home=empty_home)
    payload = parse_only_json("no_value_fn", code, out)
    if payload:
        check("no_value_fn · 退出码 0", code == 0, "实际 %r" % code)
        check("no_value_fn · missing 里没有价值网络",
              "retro_star/saved_models/best_epoch_final_4.pt" not in (payload.get("missing") or []))
        check("no_value_fn · 价值网络进了 missing_optional",
              "retro_star/saved_models/best_epoch_final_4.pt" in (payload.get("missing_optional") or []))

    print("\n[3] retro_home 解析优先级：环境变量 > 请求字段")
    code, out, _ = run_bridge(
        json.dumps({"smiles": "CCO", "retro_home": other_home}), env_home=empty_home)
    payload = parse_only_json("home_priority_env", code, out)
    if payload:
        check("home_priority · 环境变量赢过请求字段",
              payload.get("retro_home") == empty_home, repr(payload.get("retro_home")))
        check("home_priority · retro_home_source 说明来源是环境变量",
              payload.get("retro_home_source") == "env:RETRO_STAR_HOME",
              repr(payload.get("retro_home_source")))

    print("\n[4] 没有环境变量时，用请求里的 retro_home")
    code, out, _ = run_bridge(
        json.dumps({"smiles": "CCO", "retro_home": other_home}), drop_env_home=True)
    payload = parse_only_json("home_from_request", code, out)
    if payload:
        check("home_from_request · retro_home 用请求字段",
              payload.get("retro_home") == other_home, repr(payload.get("retro_home")))
        check("home_from_request · retro_home_source == request:retro_home",
              payload.get("retro_home_source") == "request:retro_home",
              repr(payload.get("retro_home_source")))

    print("\n[5] 路径压根不存在 → 仍然结构化、退出码 0，并提示源码要先 git clone")
    code, out, _ = run_bridge('{"smiles": "CCO"}', env_home=gone_home)
    payload = parse_only_json("home_missing", code, out)
    if payload:
        check("home_missing · 退出码 0", code == 0, "实际 %r" % code)
        check("home_missing · 缺 retro_star/api.py",
              "retro_star/api.py" in (payload.get("missing") or []))
        check("home_missing · setup 提示 git clone 源码",
              "git clone" in (payload.get("setup") or ""))

    print("\n[6] 非法输入 → 结构化 bad_request，不是崩溃")
    bad_inputs = [
        ("坏 JSON", "{not json", 2, "<stdin>"),
        ("空 stdin", "", 2, "<stdin>"),
        ("顶层不是对象", "[1,2,3]", 2, "<root>"),
        ("缺 smiles", '{"iterations": 10}', 2, "smiles"),
        ("smiles 是数字", '{"smiles": 123}', 2, "smiles"),
        ("smiles 是空白", '{"smiles": "   "}', 2, "smiles"),
        ("iterations 是字符串", '{"smiles": "CCO", "iterations": "many"}', 2, "iterations"),
        ("timeout_s 是 0", '{"smiles": "CCO", "timeout_s": 0}', 2, "timeout_s"),
        ("use_value_fn 是字符串", '{"smiles": "CCO", "use_value_fn": "yes"}', 2, "use_value_fn"),
        ("max_routes 超范围", '{"smiles": "CCO", "max_routes": 99999}', 2, "max_routes"),
    ]
    for label, stdin_text, want_code, want_field in bad_inputs:
        code, out, err = run_bridge(stdin_text, env_home=empty_home)
        payload = parse_only_json("bad_input[%s]" % label, code, out)
        if payload is None:
            continue
        check("bad_input[%s] · 退出码 %d（调用方 bug 与运行期失败分开）" % (label, want_code),
              code == want_code, "实际 %r" % code)
        check("bad_input[%s] · code == bad_request" % label,
              payload.get("code") == "bad_request", repr(payload.get("code")))
        check("bad_input[%s] · field == %s" % (label, want_field),
              payload.get("field") == want_field, repr(payload.get("field")))
        check("bad_input[%s] · 有人话 message" % label,
              isinstance(payload.get("message"), str) and len(payload["message"]) > 5)
        check("bad_input[%s] · message 里没有栈" % label,
              "Traceback" not in (payload.get("message") or ""))

    print("\n[7] 数据齐、但源码是假的 → 走完数据检查后仍然结构化报错（退出码 0）")
    fake_home = os.path.join(tmp, "fake-retro-home")
    package = os.path.join(fake_home, "retro_star")
    os.makedirs(os.path.join(package, "dataset"))
    os.makedirs(os.path.join(package, "one_step_model"))
    os.makedirs(os.path.join(package, "saved_models"))
    os.makedirs(os.path.join(package, "packages", "mlp_retrosyn", "mlp_retrosyn"))
    os.makedirs(os.path.join(package, "packages", "rdchiral", "rdchiral"))
    for rel in ("retro_star/api.py",
                "retro_star/dataset/origin_dict.csv",
                "retro_star/one_step_model/template_rules_1.dat",
                "retro_star/one_step_model/saved_rollout_state_1_2048.ckpt",
                "retro_star/saved_models/best_epoch_final_4.pt"):
        with open(os.path.join(fake_home, rel), "w") as handle:
            handle.write("")
    open(os.path.join(package, "__init__.py"), "w").close()
    open(os.path.join(package, "packages", "mlp_retrosyn", "mlp_retrosyn", "__init__.py"), "w").close()
    open(os.path.join(package, "packages", "rdchiral", "rdchiral", "__init__.py"), "w").close()

    code, out, err = run_bridge('{"smiles": "CCOC(=O)c1ccccc1"}', env_home=fake_home)
    payload = parse_only_json("fake_home", code, out)
    if payload:
        check("fake_home · 数据检查被通过了（不再是 retro_not_configured）",
              payload.get("code") != "retro_not_configured", repr(payload.get("code")))
        check("fake_home · 空 api.py 导致的失败被翻成 retro_backend_error",
              payload.get("code") == "retro_backend_error", repr(payload.get("code")))
        check("fake_home · ok 是 false 且没有编造路线", payload.get("ok") is False and "routes" not in payload)
        check("fake_home · 退出码 0（后端失败≠调用方失败）", code == 0, "实际 %r" % code)
        check("fake_home · message 是人话，指出是源码/兼容性问题",
              "import retro_star 失败" in (payload.get("message") or ""),
              repr(payload.get("message")))

    print("\n[8] 坏 SMILES 在加载模型之前就被拦下（省几十秒）")
    code, out, _ = run_bridge('{"smiles": "C1CC"}', env_home=fake_home)
    payload = parse_only_json("bad_smiles", code, out)
    if payload:
        check("bad_smiles · code == bad_request", payload.get("code") == "bad_request",
              repr(payload.get("code")))
        check("bad_smiles · field == smiles", payload.get("field") == "smiles")
        check("bad_smiles · 退出码 2", code == 2, "实际 %r" % code)
        check("bad_smiles · 进到 smiles 校验阶段（说明数据/依赖检查都过了）",
              "RDKit" in (payload.get("message") or ""), repr(payload.get("message")))

    print("\n[9] --doctor 诊断模式")
    code, out, _ = run_bridge("", env_home=empty_home, argv=["--doctor"])
    payload = parse_only_json("doctor_unconfigured", code, out)
    if payload:
        check("doctor · 数据缺失时退出码 1", code == 1, "实际 %r" % code)
        check("doctor · code == retro_not_configured", payload.get("code") == "retro_not_configured")
        check("doctor · heavy_imports_skipped == true", payload.get("heavy_imports_skipped") is True)
        check("doctor · 报出自己在哪个解释器里跑", isinstance(payload.get("python"), str))

    print("\n[9b] 成功路径的响应形状（用**桩后端**顶替 Retro*，只为验协议，不验化学）")
    stub_home = _stub_success_case(tmp)
    if stub_home:
        print("\n[9c] 超时必须真的掐断搜索（SIGALRM 打断 + 看门狗兜底）")
        _timeout_case(stub_home)
        print("\n[9d] gpu>=0 时的参数口径（argv 会被用来设 CUDA_VISIBLE_DEVICES）")
        _gpu_case(stub_home)


# 桩后端：冒充 retro_star.api.RSPlanner，返回一份和 api.py:69-77 同形状的结果。
# 为什么敢用桩：Retro* 真数据是 GB 级的，本机没有；而"成功响应长什么样"是桥接脚本
# 自己决定的，用桩正好能把这条路径钉死。**它不能证明真 Retro* 跑得通**。
_STUB_API = '''\
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


class RSPlanner(object):
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        with open(os.path.join(HERE, "..", "seen_kwargs.json"), "w") as handle:
            json.dump({k: v for k, v in kwargs.items() if isinstance(v, (str, int, float, bool))},
                      handle, ensure_ascii=False)

    def plan(self, target_mol):
        delay = float(os.environ.get("RETRO_STUB_SLEEP", "0") or 0)
        if delay:
            import time
            time.sleep(delay)
        return {
            "succ": True,
            "time": 1.234,
            "iter": 7,
            "routes": target_mol + ">0.5300>CCO.CC(=O)O|CCO>0.2000>CC.O",
            "route_cost": 2.1,
            "route_len": 2,
        }
'''


def _stub_success_case(tmp):
    stub_home = os.path.join(tmp, "stub-retro-home")
    package = os.path.join(stub_home, "retro_star")
    os.makedirs(os.path.join(package, "dataset"))
    os.makedirs(os.path.join(package, "one_step_model"))
    os.makedirs(os.path.join(package, "saved_models"))
    os.makedirs(os.path.join(package, "packages", "mlp_retrosyn", "mlp_retrosyn"))
    os.makedirs(os.path.join(package, "packages", "rdchiral", "rdchiral"))
    open(os.path.join(package, "__init__.py"), "w").close()
    open(os.path.join(package, "packages", "mlp_retrosyn", "mlp_retrosyn", "__init__.py"), "w").close()
    open(os.path.join(package, "packages", "rdchiral", "rdchiral", "__init__.py"), "w").close()
    with open(os.path.join(package, "api.py"), "w") as handle:
        handle.write(_STUB_API)
    for rel in ("retro_star/dataset/origin_dict.csv",
                "retro_star/one_step_model/template_rules_1.dat",
                "retro_star/one_step_model/saved_rollout_state_1_2048.ckpt",
                "retro_star/saved_models/best_epoch_final_4.pt"):
        open(os.path.join(stub_home, rel), "w").close()

    code, out, _ = run_bridge(
        '{"smiles": "CCOC(=O)c1ccccc1", "iterations": 42, "expansion_topk": 17, "max_routes": 3}',
        env_home=stub_home)
    payload = parse_only_json("stub_success", code, out)
    if payload is None:
        return None

    if payload.get("code") == "retro_backend_error" and payload.get("stage") == "preflight_import":
        # 这台机器缺 torch/pandas 之类 —— 桩后端也跑不起来，跳过（不是桥接的错）
        check("stub_success · 跳过（本机缺 %s，桩后端需要它）" % payload.get("missing_module"), True)
        return None

    check("stub_success · ok == true", payload.get("ok") is True, repr(payload.get("code")))
    check("stub_success · 退出码 0", code == 0, "实际 %r" % code)
    check("stub_success · target 回显", payload.get("target") == "CCOC(=O)c1ccccc1")
    check("stub_success · backend == retro_star", payload.get("backend") == "retro_star")
    check("stub_success · 有 elapsed_ms", isinstance(payload.get("elapsed_ms"), int))
    check("stub_success · 迭代/扩展参数透传", payload.get("iterations_requested") == 42
          and payload.get("expansion_topk") == 17)
    check("stub_success · CPU 请求的 gpu 口径一致",
          payload.get("gpu_requested") == -1 and payload.get("gpu_effective") == -1,
          repr((payload.get("gpu_requested"), payload.get("gpu_effective"))))

    routes = payload.get("routes")
    check("stub_success · routes 是一个元素的数组", isinstance(routes, list) and len(routes) == 1,
          repr(routes if not isinstance(routes, list) else len(routes)))
    if not routes:
        return stub_home
    route = routes[0]
    for field in ("score", "cost", "steps", "tree", "route_string"):
        check("stub_success · route 有字段 %s" % field, field in route, repr(sorted(route)))
    check("stub_success · score == exp(-cost)", abs(route.get("score", 0) - 2.718281828459045 ** -2.1) < 1e-9,
          repr(route.get("score")))
    check("stub_success · steps 来自后端 route_len", route.get("steps") == 2, repr(route.get("steps")))
    check("stub_success · route_string 原样带回（可对账）",
          isinstance(route.get("route_string"), str) and ">0.5300>" in route["route_string"])
    tree = route.get("tree") or {}
    check("stub_success · tree 根是目标", tree.get("smiles") == "CCOC(=O)c1ccccc1", repr(tree.get("smiles")))
    check("stub_success · tree 根 2 个子节点", len(tree.get("children") or []) == 2)
    kids = tree.get("children") or []
    grandkids = (kids[0].get("children") if kids else None) or []
    check("stub_success · 中间体接上了子节点（父子关系没断）", len(grandkids) == 2,
          repr([c.get("smiles") for c in grandkids]))
    check("stub_success · 叶子被标成砌块 is_starting_material",
          bool(grandkids) and all(c.get("is_starting_material") for c in grandkids),
          repr(grandkids))
    check("stub_success · 中间体不是砌块", kids and kids[0].get("is_starting_material") is False)
    check("stub_success · 多路线请求有 note 解释为什么只回 1 条",
          any("只返回" in n for n in (payload.get("notes") or [])), repr(payload.get("notes")))
    check("stub_success · 树里没有 None 形状的 children",
          all(isinstance(c.get("children"), list) for c in kids))

    seen_path = os.path.join(stub_home, "seen_kwargs.json")
    if os.path.isfile(seen_path):
        with open(seen_path) as handle:
            seen = json.load(handle)
        check("stub_success · 数据路径来自 retro_home（不是 RSPlanner 的默认值）",
              str(seen.get("starting_molecules", "")).startswith(stub_home)
              and str(seen.get("mlp_templates", "")).startswith(stub_home),
              repr(seen))
        check("stub_success · use_value_fn 默认 true 被传下去", seen.get("use_value_fn") is True,
              repr(seen.get("use_value_fn")))
    else:
        check("stub_success · 桩后端被真的调用到（写了 seen_kwargs.json）", False, "文件不存在")

    return stub_home


def _timeout_case(stub_home):
    """桩后端会 sleep 30 秒，timeout_s 只给 2 秒 —— 必须被掐断，而且**要快**。

    为什么单独测这个：超时是唯一一个"看起来在工作、其实没工作"的机制
    （SIGALRM 在某些状态下打不断）。所以除了看 code，还要量墙钟时间：
    2 秒就该回来；如果拖到 22 秒才回，说明走的是看门狗兜底路径
    （SIGALRM 没生效），那是要修的，不能算过。
    """
    started = time.time()
    code, out, _ = run_bridge('{"smiles": "CCO", "timeout_s": 2}',
                              env_home=stub_home,
                              extra_env={"RETRO_STUB_SLEEP": "30"},
                              timeout=90)
    wall = time.time() - started
    payload = parse_only_json("timeout", code, out)
    if payload is None:
        return
    check("timeout · code == retro_timeout", payload.get("code") == "retro_timeout",
          repr(payload.get("code")))
    check("timeout · ok 是 false", payload.get("ok") is False)
    check("timeout · 退出码 0（超时是运行期结果，不是调用方 bug）", code == 0, "实际 %r" % code)
    check("timeout · 说清停在哪个阶段", payload.get("stage") == "search",
          repr(payload.get("stage")))
    check("timeout · 回显 timeout_s", payload.get("timeout_s") == 2.0, repr(payload.get("timeout_s")))
    check("timeout · 给了人话建议", isinstance(payload.get("suggestions"), list)
          and len(payload["suggestions"]) > 0)
    check("timeout · 墙钟 < 15s（说明是 SIGALRM 打断的，不是 22s 的看门狗兜底）",
          wall < 15.0, "实际 %.1fs" % wall)
    check("timeout · 桩后端没有机会跑完（30s 的 sleep 被切掉了）", wall < 20.0, "实际 %.1fs" % wall)


def _gpu_case(stub_home):
    """gpu=N 会被翻译成 `--gpu N`（喂给上游的 parse_args）+ planner gpu=0。

    真 GPU 行为本机测不了，这里只钉住"翻译"这一步：argv 不能被上游当成脏参数
    SystemExit，传递下去的设备编号要是 0。
    """
    code, out, _ = run_bridge('{"smiles": "CCO", "gpu": 3}', env_home=stub_home)
    payload = parse_only_json("gpu", code, out)
    if payload is None:
        return
    check("gpu · 仍然 ok（argv 没把上游的 parse_args 惹炸）", payload.get("ok") is True,
          repr(payload.get("code")))
    check("gpu · gpu_requested == 3", payload.get("gpu_requested") == 3)
    check("gpu · gpu_effective == 0（CUDA_VISIBLE_DEVICES 里它才是 0 号）",
          payload.get("gpu_effective") == 0, repr(payload.get("gpu_effective")))
    check("gpu · notes 里说明了这个口径换算",
          any("CUDA_VISIBLE_DEVICES" in n for n in (payload.get("notes") or [])))
    seen_path = os.path.join(stub_home, "seen_kwargs.json")
    if os.path.isfile(seen_path):
        with open(seen_path) as handle:
            seen = json.load(handle)
        check("gpu · 传给 RSPlanner 的 gpu 是 0", seen.get("gpu") == 0, repr(seen.get("gpu")))


# ---------------------------------------------------------------------------
# B. 单元：路线串 → 树
# ---------------------------------------------------------------------------

def unit_cases():
    print("\n[10] 直接 import 桥接模块：不能牵连 torch（否则数据没装就没法单测）")
    sys.path.insert(0, HERE)
    try:
        import retro_star_bridge as bridge
    except Exception as exc:  # pragma: no cover
        check("import retro_star_bridge", False, "%s: %s" % (type(exc).__name__, exc))
        return
    check("import retro_star_bridge", True)
    check("import 桥接模块没有牵连 torch", "torch" not in sys.modules,
          "sys.modules 里有 torch —— 说明重量级 import 跑到模块顶层去了")

    print("\n[11] parse_route_string：单步路线")
    # 模拟 SynRoute.serialize()：'母体>exp(-cost)>反应物1.反应物2'
    root = bridge.parse_route_string("CCOC(=O)c1ccccc1>0.5300>CCO.CC(=O)O")
    check("单步 · 根是目标分子", root["smiles"] == "CCOC(=O)c1ccccc1", root["smiles"])
    check("单步 · 根有 2 个子节点（两个反应物）", len(root["children"]) == 2,
          repr([c["smiles"] for c in root["children"]]))
    check("单步 · 每步分数被解析出来", abs((root["score"] or 0) - 0.53) < 1e-9, repr(root["score"]))
    tree, notes = bridge.finalize_tree_wrapper("CCOC(=O)c1ccccc1>0.5300>CCO.CC(=O)O")
    check("单步 · 叶子被标成砌块（is_starting_material）",
          all(c["is_starting_material"] for c in tree["children"]))
    check("单步 · 非叶子不是砌块", tree["is_starting_material"] is False)
    check("单步 · 根 role == target", tree["role"] == "target", repr(tree["role"]))
    check("单步 · 叶子 role == building_block",
          all(c["role"] == "building_block" for c in tree["children"]))
    check("单步 · 步数 = 内部节点数 = 1", bridge._count_steps(tree) == 1)
    check("单步 · 叶子数 = 2", bridge._count_leaves(tree) == 2)

    print("\n[12] parse_route_string：多步路线（父子关系要正确）")
    route = ("CCOC(=O)c1ccccc1>0.5000>OB(O)c1ccccc1.CCO"
             "|OB(O)c1ccccc1>0.4000>Brc1ccccc1.CC(=O)O"
             "|CCO>0.3000>CC.O")
    tree, notes = bridge.finalize_tree_wrapper(route)
    check("多步 · 根 2 个子节点", len(tree["children"]) == 2)
    kids = {c["smiles"]: c for c in tree["children"]}
    check("多步 · 中间体 OB(O)c1ccccc1 有自己的子节点（父子关系接上了）",
          len(kids["OB(O)c1ccccc1"]["children"]) == 2)
    check("多步 · 中间体被标成 intermediate",
          kids["OB(O)c1ccccc1"]["role"] == "intermediate")
    check("多步 · 深度标注正确", tree["depth"] == 0 and kids["CCO"]["depth"] == 1
          and kids["CCO"]["children"][0]["depth"] == 2)
    check("多步 · 步数 = 3", bridge._count_steps(tree) == 3, repr(bridge._count_steps(tree)))
    check("多步 · 叶子数 = 4", bridge._count_leaves(tree) == 4, repr(bridge._count_leaves(tree)))
    check("多步 · 叶子都是砌块",
          all(c["is_starting_material"] for c in kids["CCO"]["children"]))
    check("多步 · 能 JSON 序列化（说明没有环）",
          isinstance(json.dumps(tree, ensure_ascii=False), str))

    print("\n[13] 目标本身就是砌块（0 步路线）")
    tree, notes = bridge.finalize_tree_wrapper("CCO")
    check("0 步 · 单节点", tree["smiles"] == "CCO" and tree["children"] == [])
    check("0 步 · is_starting_material == true", tree["is_starting_material"] is True)
    check("0 步 · 步数 0", bridge._count_steps(tree) == 0)

    print("\n[14] 菱形/回环兜底（Retro* 按 SMILES 索引节点，理论上会重复）")
    tree, notes = bridge.finalize_tree_wrapper("CCOC(=O)C>0.5000>CCO|CCO>0.4000>CCOC(=O)C")
    child = tree["children"][0]
    check("回环 · 子节点是 CCO", child["smiles"] == "CCO")
    check("回环 · 祖先重复处被截断，不再递归下去",
          child["children"][0].get("truncated") is True, repr(child["children"]))
    check("回环 · 截断节点被标 role == repeat", child["children"][0]["role"] == "repeat")
    check("回环 · 截断有 note 说明原因", any("重复出现" in n for n in notes), repr(notes))
    check("回环 · 结果仍可 JSON 序列化", isinstance(json.dumps(tree, ensure_ascii=False), str))

    print("\n[15] 损坏的路线串必须抛错（不许猜一个树出来）")
    for label, bad in (("段字段数不对", "CCO>0.5>x>y"),
                       ("空串", ""),
                       ("产品字段为空", ">0.5>C"),
                       ("不是字符串", None)):
        try:
            bridge.parse_route_string(bad)
            check("损坏串[%s] · 抛 ValueError" % label, False, "居然没抛错")
        except ValueError:
            check("损坏串[%s] · 抛 ValueError" % label, True)
        except Exception as exc:
            check("损坏串[%s] · 抛 ValueError" % label, False, "抛了 %s" % type(exc).__name__)

    print("\n[16] 分数读不出来时只把分数置空，不篡改结构")
    root = bridge.parse_route_string("CCO>not-a-number>CC")
    check("坏分数 · score 是 None", root["score"] is None, repr(root["score"]))
    check("坏分数 · 结构仍然保留", root["smiles"] == "CCO" and len(root["children"]) == 1)

    print("\n[17] 兼容垫片函数本身安全（不装 numpy 也能 import）")
    check("_safe_float 对垃圾输入返回 None", bridge._safe_float("abc") is None)


def main():
    print("=" * 78)
    print("retro_star_bridge 协议自检")
    print("  桥接脚本：%s" % BRIDGE)
    print("  解释器  ：%s (%s)" % (sys.executable, sys.version.split()[0]))
    print("  项目根  ：%s" % PROJECT_ROOT)
    print("=" * 78)

    if not os.path.isfile(BRIDGE):
        print("找不到桥接脚本：%s" % BRIDGE)
        return 1

    tmp = tempfile.mkdtemp(prefix="retro-selfcheck-")
    try:
        e2e_cases(tmp)
        unit_cases()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 78)
    print("通过 %d 项，失败 %d 项" % (len(PASSES), len(FAILURES)))
    if FAILURES:
        for name, detail in FAILURES:
            print("  [FAIL] %s%s" % (name, ("  ← " + detail) if detail else ""))
        print("结果：失败")
        return 1
    print("结果：全部通过 ✅")
    print("（本自检不依赖 Retro* 数据，因此在「没装数据」的机器上也应当全绿；"
          "它验的是协议与降级行为，不是化学正确性。）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
