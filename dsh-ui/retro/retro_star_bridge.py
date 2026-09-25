#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Retro* 逆合成后端桥接 —— 供 dsh-ui 宿主半边（Node）用 child_process 调用。

============================================================================
谁调用它
============================================================================
dsh-ui 的**宿主半边**（`dsh-ui/lib/index.js` 那一侧）这样拉起本脚本：

    const child = spawn(PYTHON, ['/abs/path/dsh-ui/retro/retro_star_bridge.py'], {
      stdio: ['pipe', 'pipe', 'pipe'],
    })
    child.stdin.end(JSON.stringify(request))     // stdin 只喂一个 JSON
    // stdout 收完 → JSON.parse

调用的解释器必须是**装了 retro_star/rdkit/torch 的那个**（Retro* 官方环境是
python 3.7）。桥接脚本自身只用标准库、不碰 3.8+ 专属语法，**设计上** 3.7~3.12
都能跑 —— 但本机只有 python 3.10.12，没有在 3.7 上实测过。
**不要给本脚本传命令行参数**——桥接模式下一律忽略多余 argv（`--doctor` 除外）。

============================================================================
协议（一个 JSON 进 / 一个 JSON 出）
============================================================================
请求字段（除 smiles 外都可省略）：
    smiles          str    必填，目标分子 SMILES
    iterations      int    A* 迭代上限（默认 100）
    expansion_topk  int    每步扩展保留的模板条数（默认 50）
    use_value_fn    bool   是否加载价值网络（默认 true，需 saved_models/best_epoch_final_4.pt）
    max_routes      int    期望路线条数上限（默认 5）—— 见 notes：Retro* 每次只给 1 条
    timeout_s       num    搜索+加载超时秒数（默认 300）
    retro_home      str    Retro* 仓库根目录（含 retro_star/ 包的那一层）；默认见下
    gpu             int    -1 = CPU（默认）；>=0 = 用第几块 GPU
    compat_shims    bool   是否打 numpy 兼容垫片（默认 true，理由见 _apply_compat_shims）

成功响应：
    {"ok": true, "backend": "retro_star", "target": ..., "elapsed_ms": ...,
     "routes": [{"score", "cost", "steps", "tree", "route_string"}], ...}

失败响应（**永不抛栈给上层**，一律结构化）：
    {"ok": false, "code": ..., "backend": "retro_star", "message": "<中文人话>", ...}
    code ∈ {retro_not_configured, retro_timeout, retro_no_route,
            retro_backend_error, bad_request, internal_error}

退出码：
    0  已产出结构化响应（**包括** retro_not_configured / retro_timeout /
       retro_no_route / retro_backend_error —— 这些是"可预期、要展示给用户"的结果）
    2  bad_request：请求本身不合法（stdin 不是 JSON、缺 smiles、字段类型错、
       SMILES 解析不了）—— 属于调用方 bug，仍然给结构化 JSON，不给栈
    1  internal_error：桥接脚本自己出了意料之外的错（结构化 JSON + stderr 里有 traceback）

`--doctor` 是**人看的诊断模式**，不遵守上面的 stdin/stdout 协议：
    python3 dsh-ui/retro/retro_star_bridge.py --doctor
退出码：0 = 数据齐、依赖也能 import；1 = 数据没装全；2 = 数据齐但依赖 import 失败。

============================================================================
三条硬规矩，以及为什么
============================================================================
1) **stdout 里只允许有那一个 JSON。** 一启动就把真 stdout 的 fd 复制走、再把
   fd 1 接到 stderr：这样 retro_star / torch / rdkit 往 stdout 打的任何废话
   （rdchiral 里就有裸 print，`bonds.py:71` 之类）都会落到 stderr，污染不了协议。

2) **数据文件检查排在 `import torch` / `import retro_star` 之前。** retro_star
   一被 import 就连锁加载 torch + rdchiral + 模板文件（数十秒、GB 级内存），
   而"数据没装"恰恰是最常见的路径 —— 不能让它既慢又可能崩。
   （连锁关系：`retro_star/common/__init__.py:1` → `parse_args`（import 期就
   解析 argv）→ `prepare_utils` → `mlp_retrosyn.mlp_inference` → torch。）

3) **绝不编造结果。** 数据不在就返回 retro_not_configured 说清缺什么、怎么补，
   退出码 0 —— 让上层能优雅展示，而不是拿一个假的路线糊弄用户。
"""

from __future__ import annotations  # 兼容 3.7：注解延迟求值，别让 list[str] 之类炸在 import 期

import json
import math
import os
import signal
import sys
import threading
import time

BACKEND = "retro_star"

ENV_RETRO_HOME = "RETRO_STAR_HOME"

# 没配 RETRO_STAR_HOME / retro_home 时按顺序找这几个中立位置。
# 刻意**不**写死任何开发机路径：这是要公开发布的工具，默认值应该对所有人都成立。
DEFAULT_RETRO_STAR_HOMES = (
    os.path.join(os.path.expanduser("~"), ".dsh", "retro_star"),
    os.path.join(os.path.expanduser("~"), "retro_star"),
    os.path.join(os.path.expanduser("~"), "retro_star-master"),
    "/opt/retro_star",
)

# 必需文件清单：(相对 retro_home 的路径, 它是干嘛的, 是否"本请求一定需要")
# 最后一项 False = 只有 use_value_fn=true 时才必需。
REQUIRED_FILES = (
    ("retro_star/api.py",
     "Retro* 源码本身（有它才有 RSPlanner）", True),
    ("retro_star/dataset/origin_dict.csv",
     "building blocks：商业/文献可得砌块清单（也是判定路线叶子节点的依据）", True),
    ("retro_star/one_step_model/template_rules_1.dat",
     "单步逆合成模板规则（USPTO 抽出来的反应模板）", True),
    ("retro_star/one_step_model/saved_rollout_state_1_2048.ckpt",
     "单步模型权重（MLP rollout policy，输出模板概率）", True),
    ("retro_star/saved_models/best_epoch_final_4.pt",
     "价值网络权重（use_value_fn=true 时必需，给 A* 当启发式）", False),
)

DATA_ZIP_URL = "https://www.dropbox.com/s/ar9cupb18hv96gj/retro_data.zip?dl=0"

# 看门狗宽限：SIGALRM 若卡在 torch 的 C 调用里没能立刻打断，再等这么久就硬退。
WATCHDOG_GRACE_S = 20.0

# 参数夹取范围，防止一个手抖的 0/负数/天文数字把进程挂死。
LIMITS = {
    "iterations": (1, 100000),
    "expansion_topk": (1, 1000),
    "max_routes": (1, 100),
    "timeout_s": (1.0, 86400.0),
    "gpu": (-1, 64),
}


# ---------------------------------------------------------------------------
# stdout 保护 + 唯一写出点
# ---------------------------------------------------------------------------

_real_stdout_fd = None
_emit_lock = threading.Lock()
_emitted = False
_start_monotonic = time.monotonic()


def _detach_stdout():
    """把真 stdout 的 fd 藏起来，再把 fd 1 接到 stderr（见文件头"规矩 1"）。"""
    global _real_stdout_fd
    if _real_stdout_fd is None:
        _real_stdout_fd = os.dup(1)
        os.dup2(2, 1)  # 从此 sys.stdout / 任何 C 层 printf 都进 stderr
    return _real_stdout_fd


def _write_all(fd, data):
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def _emit(payload, exit_code=0, hard_exit=False):
    """唯一向协议 stdout 写字节的地方。

    用锁 + _emitted 标志保证**只写一次**：看门狗线程和主线程可能同时想写，
    谁先拿到锁谁写，另一个直接让路 —— 否则上层会收到两个拼在一起的 JSON。
    """
    global _emitted
    with _emit_lock:
        if _emitted:
            return
        _emitted = True
        payload.setdefault("backend", BACKEND)
        payload.setdefault("elapsed_ms", int((time.monotonic() - _start_monotonic) * 1000))
        data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        fd = _real_stdout_fd if _real_stdout_fd is not None else 1
        try:
            _write_all(fd, data)
        except OSError:
            # stdout 管道可能已对端关闭；此时已无处可说，只能退到 stderr 留个痕
            sys.stderr.write("[retro_star_bridge] stdout 写入失败，响应无法送出\n")
    if hard_exit:
        # 看门狗用：主线程可能正卡在 C 调用里，sys.exit 叫不停它，只能硬退
        os._exit(exit_code)
    sys.exit(exit_code)


def _log(msg):
    """日志一律走 stderr —— stdout 是协议通道，不是日志通道。"""
    sys.stderr.write("[retro_star_bridge] %s\n" % msg)
    sys.stderr.flush()


# ---------------------------------------------------------------------------
# 超时：SIGALRM 主打断 + 看门狗兜底
# ---------------------------------------------------------------------------

class _SearchTimeout(Exception):
    pass


def _install_alarm(seconds):
    """用 SIGALRM 打断纯 Python 层的搜索循环。

    为什么不用子进程 + kill：Retro* 要 import torch，fork 一个已经初始化了
    OpenMP 线程池的进程是有死锁风险的；而搜索循环（molstar.py:19 的 for）是
    Python 层字节码，SIGALRM 能可靠打断。
    """
    if not hasattr(signal, "setitimer"):
        return False

    def _handler(signum, frame):
        raise _SearchTimeout()

    signal.signal(signal.SIGALRM, _handler)
    signal.setitimer(signal.ITIMER_REAL, float(seconds))
    return True


def _clear_alarm():
    try:
        if hasattr(signal, "setitimer"):
            signal.setitimer(signal.ITIMER_REAL, 0)
    except Exception:
        pass


def _start_watchdog(timeout_s, ctx):
    """兜底看门狗。

    为什么还要它：SIGALRM 只在 Python 字节码边界生效，若刚好卡在一个长时间的
    C/torch 调用里（模板加载、大矩阵乘），异常要等那次调用返回才抛得出来。
    宿主等不起，所以到点直接吐超时响应并硬退。
    """
    def _worker():
        deadline = time.monotonic() + float(timeout_s) + WATCHDOG_GRACE_S
        while time.monotonic() < deadline:
            time.sleep(0.5)
        _emit(_timeout_payload(ctx, note="看门狗兜底：SIGALRM 没能及时打断（多半卡在 C/torch 调用里）"),
              exit_code=0, hard_exit=True)

    thread = threading.Thread(target=_worker, name="retro-watchdog")
    thread.daemon = True
    thread.start()
    return thread


def _timeout_payload(ctx, note=None):
    payload = {
        "ok": False,
        "code": "retro_timeout",
        "target": ctx.get("smiles"),
        "timeout_s": ctx.get("timeout_s"),
        "retro_home": ctx.get("retro_home"),
        "stage": ctx.get("stage"),
        "message": (
            "Retro* 在 %.0f 秒内没给出结果，已中止本次搜索。"
            "常见原因：iterations 太大（A* 每轮都要跑一次单步模型）、"
            "expansion_topk 太大（每轮要跑更多 rdchiral 模板）、"
            "或者这个目标确实很难找路线。可以把 iterations / expansion_topk 调小，"
            "或把 timeout_s 调大再试。"
        ) % float(ctx.get("timeout_s") or 0),
        "suggestions": [
            "调小 iterations（例如 50）先看能不能快出结果",
            "调小 expansion_topk（例如 20）",
            "把 timeout_s 调到 600~1200（首次运行还要额外算上模型加载时间）",
            "确认真的在用 GPU：请求里给 \"gpu\": 0",
        ],
    }
    if note:
        payload["note"] = note
    return payload


# ---------------------------------------------------------------------------
# 请求解析与校验
# ---------------------------------------------------------------------------

class _BadRequest(Exception):
    def __init__(self, message, field=None, detail=None):
        super(_BadRequest, self).__init__(message)
        self.message = message
        self.field = field
        self.detail = detail


def _bad_request_payload(exc, raw_preview=None):
    payload = {
        "ok": False,
        "code": "bad_request",
        "message": exc.message,
        "field": exc.field,
    }
    if exc.detail:
        payload["detail"] = exc.detail
    if raw_preview is not None:
        payload["stdin_preview"] = raw_preview
    payload["expected_request"] = {
        "smiles": "CCOC(=O)c1ccccc1",
        "iterations": 100,
        "expansion_topk": 50,
        "use_value_fn": True,
        "max_routes": 5,
        "timeout_s": 300,
    }
    return payload


def _coerce_int(req, key, default):
    if key not in req or req[key] is None:
        return default
    value = req[key]
    if isinstance(value, bool):
        raise _BadRequest("字段 %r 应该是整数，收到布尔值" % key, field=key)
    if isinstance(value, int):
        out = value
    elif isinstance(value, float) and value.is_integer():
        out = int(value)
    elif isinstance(value, str) and value.strip().lstrip("+-").isdigit():
        out = int(value.strip())
    else:
        raise _BadRequest(
            "字段 %r 应该是整数，收到 %s（%r）" % (key, type(value).__name__, value),
            field=key,
        )
    lo, hi = LIMITS[key]
    if out < lo or out > hi:
        raise _BadRequest(
            "字段 %r = %r 超出允许范围 [%s, %s]" % (key, out, lo, hi),
            field=key,
            detail="范围是桥接脚本设的护栏，防止一个手抖的参数把进程挂死",
        )
    return out


def _coerce_float(req, key, default):
    if key not in req or req[key] is None:
        return default
    value = req[key]
    if isinstance(value, bool):
        raise _BadRequest("字段 %r 应该是数字，收到布尔值" % key, field=key)
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise _BadRequest(
            "字段 %r 应该是数字，收到 %s（%r）" % (key, type(value).__name__, value),
            field=key,
        )
    lo, hi = LIMITS[key]
    if out < lo or out > hi:
        raise _BadRequest(
            "字段 %r = %r 超出允许范围 [%s, %s] 秒" % (key, out, lo, hi), field=key
        )
    return out


def _coerce_bool(req, key, default):
    if key not in req or req[key] is None:
        return default
    value = req[key]
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    raise _BadRequest(
        "字段 %r 应该是 true/false，收到 %s（%r）" % (key, type(value).__name__, value),
        field=key,
    )


def _load_request(raw):
    text = (raw or "").strip()
    if not text:
        raise _BadRequest(
            "stdin 是空的。本脚本的协议是：stdin 喂一个 JSON 请求，stdout 回一个 JSON 响应。",
            field="<stdin>",
        )
    try:
        req = json.loads(text)
    except ValueError as exc:
        raise _BadRequest(
            "stdin 不是合法 JSON：%s" % exc,
            field="<stdin>",
            detail="注意 stdout 只回 JSON，所以请求必须走 stdin，不要用命令行参数传",
        )
    if not isinstance(req, dict):
        raise _BadRequest(
            "请求 JSON 的顶层必须是对象（{...}），收到 %s" % type(req).__name__,
            field="<root>",
        )
    return req


def _settings_from(req):
    smiles = req.get("smiles")
    if smiles is None:
        raise _BadRequest("缺少必填字段 smiles（目标分子的 SMILES）", field="smiles")
    if not isinstance(smiles, str):
        raise _BadRequest(
            "字段 smiles 应该是字符串，收到 %s（%r）" % (type(smiles).__name__, smiles),
            field="smiles",
        )
    smiles = smiles.strip()
    if not smiles:
        raise _BadRequest("字段 smiles 是空串/空白", field="smiles")

    return {
        "smiles": smiles,
        "iterations": _coerce_int(req, "iterations", 100),
        "expansion_topk": _coerce_int(req, "expansion_topk", 50),
        "use_value_fn": _coerce_bool(req, "use_value_fn", True),
        "max_routes": _coerce_int(req, "max_routes", 5),
        "timeout_s": _coerce_float(req, "timeout_s", 300.0),
        "gpu": _coerce_int(req, "gpu", -1),
        "gpu_effective": _coerce_int(req, "gpu", -1),  # _prepare_runtime_args 会改写
        "compat_shims": _coerce_bool(req, "compat_shims", True),
        # force=true 跳过内存预检（明知道可能被 OOM-kill 也要试一次）
        "force": _coerce_bool(req, "force", False),
    }


def _resolve_retro_home(req):
    """优先级：环境变量 RETRO_STAR_HOME → 请求里的 retro_home → 几个约定位置。

    为什么环境变量优先：它是**机器级**配置，同一个 dsh 实例下所有请求都该一致；
    请求字段留给"临时换个数据目录做对比实验"这种场景。

    约定的默认位置见 DEFAULT_RETRO_STAR_HOMES —— 挑**第一个存在**的，
    一个都不存在时返回第一个（让报错里给出的路径是个合理的"你该放这儿"）。
    """
    explicit = []
    for candidate, source in (
        (os.environ.get(ENV_RETRO_HOME), "env:%s" % ENV_RETRO_HOME),
        (req.get("retro_home"), "request:retro_home"),
    ):
        if candidate:
            if not isinstance(candidate, str):
                raise _BadRequest(
                    "retro_home 应该是字符串路径，收到 %s" % type(candidate).__name__,
                    field="retro_home",
                )
            explicit.append((candidate, source))
    for candidate, source in explicit:
        home = os.path.abspath(os.path.expanduser(candidate.strip()))
        return home, source
    for candidate in DEFAULT_RETRO_STAR_HOMES:
        if os.path.isdir(candidate):
            return os.path.abspath(candidate), "default_candidate"
    return os.path.abspath(DEFAULT_RETRO_STAR_HOMES[0]), "default_candidate"


# ---------------------------------------------------------------------------
# 内存够不够（同样必须在重量级 import 之前 —— 不够时内核会直接 OOM-kill，
# 子进程连写一行错误的机会都没有，用户只能看到一个莫名其妙的 SIGKILL）
# ---------------------------------------------------------------------------

#: building blocks 的常驻内存按**文件大小的倍数**估。实测锚点：
#: `set(pd.read_csv(origin_dict.csv)['mol'])`，文件 1298 MB / 2308 万条，
#: 峰值 RSS 3917 MB ≈ 文件大小的 3.0 倍（换 usecols / 分块读只降到 ~3.7 GB ——
#: 大头是那 2308 万个字符串本身，不是 pandas 的开销）。
#: 用倍数而不是写死 3900：换了子集数据文件时估算跟着走（小文件不该被误判成不够）。
BLOCKS_FILE_FACTOR = 3.0

#: 再小的数据集也得留出解释器与解析的底。
BLOCKS_MIN_MB = 50

#: torch + rdchiral + rdkit 导入后的常驻开销（同一台机器实测约 400-600 MB）。
RUNTIME_MB = 600

#: 模型权重要读进内存，解析期还会有一份峰值副本，所以按文件大小的 1.5 倍估。
MODEL_FILE_FACTOR = 1.5

#: 留一点余量，别卡在临界值上换来一次 OOM。
SAFETY_MB = 400


def _mem_available_mb():
    """读 /proc/meminfo 的 MemAvailable。读不到就返回 None（不阻塞流程）。"""
    try:
        with open("/proc/meminfo", "r") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        return None
    return None


def _estimate_required_mb(retro_home, use_value_fn):
    """估一次规划需要多少内存。给的是**可解释的估算**，不是精确值。

    构成：building blocks（按文件大小 3 倍）+ 模型权重（文件 1.5 倍）
    + 运行时（torch/rdkit 常驻）+ 安全余量。
    """
    parts = {}
    try:
        blocks_mb = os.path.getsize(
            os.path.join(retro_home, "retro_star/dataset/origin_dict.csv")) / (1024 * 1024)
        parts["building_blocks"] = max(BLOCKS_MIN_MB, int(blocks_mb * BLOCKS_FILE_FACTOR))
    except OSError:
        parts["building_blocks"] = BLOCKS_MIN_MB
    parts["runtime"] = RUNTIME_MB
    for rel, _why, always in REQUIRED_FILES:
        # 源码与 building blocks 已单独算过；剩下的按模型权重处理
        if rel.endswith((".py", ".csv")):
            continue
        if not always and not use_value_fn:
            continue
        try:
            size_mb = os.path.getsize(os.path.join(retro_home, rel)) / (1024 * 1024)
        except OSError:
            continue
        parts[rel] = int(size_mb * MODEL_FILE_FACTOR)
    return sum(parts.values()) + SAFETY_MB, parts


def _memory_payload(retro_home, home_source, use_value_fn, available_mb, required_mb, parts):
    return {
        "ok": False,
        "code": "retro_insufficient_memory",
        "backend": BACKEND,
        "retro_home": retro_home,
        "retro_home_source": home_source,
        "available_mb": available_mb,
        "required_mb": required_mb,
        "estimate_parts": parts,
        "message": (
            "Retro* 的数据和依赖都齐了，但这台机器的空闲内存不够："
            "现在可用 %d MB，估下来需要约 %d MB。"
            "不等它跑，内核会先把进程 OOM-kill 掉（你只会看到一个 SIGKILL，没有任何报错）。"
            % (available_mb, required_mb)
        ),
        "suggestions": [
            "先看 `free -g`：如果 used 很高，关掉占内存的服务再试（本机实测：两个 uvicorn 能占 3 GB）",
            "WSL2 默认只给宿主内存的 50%。宿主 16 GB 时 WSL 只有 7.7 GB —— "
            "在 C:\\Users\\<你>\\.wslconfig 里写 [wsl2] memory=12GB，再 `wsl --shutdown` 重开，最省事",
            "确认要试就带 force=true 强制跑（可能被 OOM-kill）",
        ],
        "doc": _doc_path(),
        "heavy_imports_skipped": True,
    }


# ---------------------------------------------------------------------------
# 数据齐不齐（这一步必须在任何重量级 import 之前）
# ---------------------------------------------------------------------------

def _check_data(retro_home, use_value_fn):
    missing, missing_optional, checked = [], [], []
    for rel, why, always_required in REQUIRED_FILES:
        required = always_required or use_value_fn
        exists = os.path.isfile(os.path.join(retro_home, rel))
        checked.append({
            "path": rel,
            "exists": exists,
            "required": required,
            "why": why,
        })
        if not exists:
            (missing if required else missing_optional).append(rel)
    return missing, missing_optional, checked


def _doc_path():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(os.path.dirname(here)), "docs", "RETROSYNTHESIS.md")


def _setup_howto(retro_home, use_value_fn, missing):
    lines = []
    if "retro_star/api.py" in missing:
        lines += [
            "0) 先摆正 RETRO_STAR_HOME —— 它要指向**含 retro_star/ 包的那一层目录**（仓库根）：",
            "     现在 %s 下面没有 retro_star/api.py。" % retro_home,
            "   Retro* 源码：git clone https://github.com/binghong-ml/retro_star",
            "   （仓库里那层 retro_star/ 才是 python 包，摆好后应该是 <retro_home>/retro_star/api.py）",
            "",
        ]
    lines += [
        "1) 下载数据包并解压（GB 级）：",
        "     " + DATA_ZIP_URL,
        "   解压后把 dataset/ 、one_step_model/ 、saved_models/ 三个目录**整体**放进",
        "     %s/retro_star/" % retro_home,
        "   补齐后下面这些路径必须都存在：",
    ]
    for rel in missing:
        if rel != "retro_star/api.py":
            lines.append("     %s" % os.path.join(retro_home, rel))
    lines += [
        "",
        "2) 建环境 + 装三个包（官方 environment.yml 要 python 3.7）：",
        "     conda env create -f %s/environment.yml" % retro_home,
        "     conda activate retro_star_env",
        "     pip install -e %s/retro_star/packages/mlp_retrosyn" % retro_home,
        "     pip install -e %s/retro_star/packages/rdchiral" % retro_home,
        "     pip install -e %s" % retro_home,
        "",
        "3) 让桥接脚本知道去哪找（任选其一）：",
        "     export RETRO_STAR_HOME=%s" % retro_home,
        "   或在请求 JSON 里写 \"retro_home\": \"%s\"" % retro_home,
        "",
        "4) 自检（先跑这个，别急着发请求）：",
        "     python3 %s --doctor" % os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                 "retro_star_bridge.py"),
    ]
    if use_value_fn:
        lines += [
            "",
            "注：本次请求 use_value_fn=true，所以还需要 %s。" % os.path.join(retro_home, "retro_star/saved_models/best_epoch_final_4.pt"),
            "    只想先跑通、不加载价值网络：请求里给 \"use_value_fn\": false。",
        ]
    return "\n".join(lines)


def _not_configured_payload(retro_home, home_source, use_value_fn, missing,
                            missing_optional, checked):
    short = "、".join(os.path.basename(p) for p in missing)
    return {
        "ok": False,
        "code": "retro_not_configured",
        "target": None,
        "retro_home": retro_home,
        "retro_home_source": home_source,
        "missing": missing,
        "missing_optional": missing_optional,
        "checked": checked,
        "message": (
            "Retro* 逆合成后端还没装好：%s 下缺 %d 个必需文件（%s）。"
            "这些是 Retro* 的模型数据/源码，需要单独下载（GB 级），仓库里没有。"
            "桥接脚本没有跑任何预测，也没有编造任何路线 —— 按 setup 里的步骤补齐后重试即可。"
            % (retro_home, len(missing), short)
        ),
        "setup": _setup_howto(retro_home, use_value_fn, missing),
        "doc": _doc_path(),
        "heavy_imports_skipped": True,
        "notes": [
            "按设计，数据检查排在 import torch / import retro_star 之前 —— 否则光是 import 就要几十秒，"
            "而「没装数据」是最常见的路径（该标记为 true 即表示这一条被遵守了）。",
            "数据齐了但还想确认依赖装没装：跑 --doctor。",
        ],
    }


# ---------------------------------------------------------------------------
# 从 planner.plan() 的返回值还原路线树
# ---------------------------------------------------------------------------

def _new_node(smiles):
    return {"smiles": smiles, "children": [], "score": None}


def _safe_float(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def parse_route_string(route_str):
    """把 `SynRoute.serialize()` 的字符串还原成树。

    `planner.plan()` 返回的 `routes` **不是结构体，是一个字符串**：
    `retro_star/api.py:74` → `msg[0].serialize()`，而 `SynRoute.serialize()`
    （`retro_star/alg/syn_route.py:92-99`）把每个"有子节点的分子"写成
    `母体>exp(-cost)>反应物1.反应物2`，段与段之间用 `|` 连接：

        "目标>0.5300>砌块A.中间体B|中间体B>0.4000>砌块C.砌块D"

    所以能还原，但**只有结构 + 每步分数**：模板字符串没被 serialize 进去
    （对比 `syn_route.py:39-52` 存了 `self.templates`，但 `serialize()` 没用它）。
    想要模板就得换用 `planner.plan_handle`（实现细节，非公开 API），本桥接不碰。

    关于"按 SMILES 合并节点"：这里用 smiles 字符串做 key，是与后端一致的 ——
    `SynRoute.add_reaction` 自己就是 `self.mols.index(mol)`（`syn_route.py:45-47`），
    同一分子多次出现会落到同一个节点上。代价是理论上会出现"菱形"甚至回环，
    所以调用方必须再用祖先检测兜一层（见 `finalize_tree`）。

    返回：叶子层节点表（dict: smiles → node）里的根节点。
    路由串结构性损坏时抛 ValueError —— 由上层翻成 retro_backend_error，绝不忍着编。
    """
    if not isinstance(route_str, str):
        raise ValueError("路线串类型不对：%s" % type(route_str).__name__)

    nodes = {}
    order = []
    for segment in route_str.split("|"):
        parts = segment.split(">")
        product = parts[0]
        if not product:
            raise ValueError("路线串里有一段的产品字段是空的：%r" % segment)
        if len(parts) not in (1, 3):
            raise ValueError(
                "路线串里有一段字段数是 %d（应为 1 或 3）：%r" % (len(parts), segment)
            )

        node = nodes.get(product)
        if node is None:
            node = _new_node(product)
            nodes[product] = node
            order.append(product)

        if len(parts) == 3:
            node["score"] = _safe_float(parts[1])
            node["children"] = []
            if parts[2]:
                for reactant in parts[2].split("."):
                    if not reactant:
                        continue
                    child = nodes.get(reactant)
                    if child is None:
                        child = _new_node(reactant)
                        nodes[reactant] = child
                        order.append(reactant)
                    if child not in node["children"]:
                        node["children"].append(child)

    if not order:
        raise ValueError("路线串是空的")
    return nodes[order[0]]


def finalize_tree(node, ancestors=None, notes=None, depth=0):
    """把共享节点表摊平成一棵**可 JSON 序列化**的树，并做两件事：

    1) 祖先检测：同一 SMILES 若踩着祖先出现，就地截断（`truncated: true`），
       避免菱形/回环把递归挂死；
    2) 标注角色：叶子 = 砌块。为什么敢这么标 —— 成功的路线里，能被继续展开的
       节点都不是砌块（`mol_tree.py:106-108` 的 `if mol.is_known: continue`），
       而每个反应节点 succ 的前提是**所有**反应物都 succ
       （`reaction_node.py:40-47`），递归下来路线的每个叶子必然 ∈ building blocks。
       所以 `is_starting_material` 在树里恒等于"没有子节点"，这不是猜的。
    """
    if ancestors is None:
        ancestors = set()
    if notes is None:
        notes = []

    smiles = node["smiles"]
    children = []
    for child in node["children"]:
        if child["smiles"] in ancestors:
            notes.append(
                "分子 %s 在其祖先链上重复出现（Retro* 的路线树按 SMILES 索引节点，"
                "允许这种菱形/回环），已在第 %d 层截断以免无限递归。" % (child["smiles"], depth + 1)
            )
            children.append({
                "smiles": child["smiles"],
                "children": [],
                "depth": depth + 1,
                "score": child["score"],
                "is_starting_material": False,
                "role": "repeat",
                "truncated": True,
            })
            continue
        children.append(finalize_tree(child, ancestors | {smiles}, notes, depth + 1))

    if depth == 0:
        role = "target"
    elif children:
        role = "intermediate"
    else:
        role = "building_block"

    return {
        "smiles": smiles,
        "children": children,
        "depth": depth,
        "score": node["score"],                       # 这一步的模板概率 ≈ exp(-cost)
        "is_starting_material": not children,         # 叶子 = 砌块，理由见 docstring
        "role": role,
    }


def _count_steps(tree):
    """内部节点数 = 反应步数。仅当后端没给 route_len 时兜底用。"""
    total = 0
    stack = [tree]
    while stack:
        node = stack.pop()
        if node["children"]:
            total += 1
            stack.extend(node["children"])
    return total


def _count_leaves(tree):
    leaves, stack = 0, [tree]
    while stack:
        node = stack.pop()
        if node["children"]:
            stack.extend(node["children"])
        else:
            leaves += 1
    return leaves


# ---------------------------------------------------------------------------
# 兼容垫片
# ---------------------------------------------------------------------------

def _apply_compat_shims(notes):
    """给老代码补上被新库删掉的别名。

    具体是 `retro_star/common/smiles_to_fp.py:10` 的 `dtype=np.bool`：
    NumPy 1.24 起 `np.bool` 被删（本机 numpy 1.26.4，实测 `np.zeros(3, dtype=np.bool)`
    直接 AttributeError）。而这行**只在 use_value_fn=true 的路径上被调用**
    （`api.py:48` 的 value_fn），所以不打垫片的话"带价值函数"必崩。
    `np.bool = bool` 还原的就是它当年的语义（0/1 布尔数组），不改变任何计算结果 ——
    这不是把错误藏起来，是补回一个被删掉的等价别名。
    """
    try:
        import warnings
        import numpy as np
    except ImportError:
        return False
    # 探测 np.bool 时要吞掉 FutureWarning：numpy 1.26 在 AttributeError 之前还会
    # 先打一句"In the future np.bool will be defined as..."，那不是问题，别吓人。
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        has_alias = hasattr(np, "bool")
    if not has_alias:
        np.bool = bool  # type: ignore[attr-defined]
        notes.append(
            "已应用兼容垫片 np.bool = bool：Retro* 的 smiles_to_fp.py:10 用了 NumPy 1.24 起"
            "已删除的 np.bool 别名（本机 numpy>=1.24 时价值函数路径必崩）。"
            "垫片语义与旧 numpy 完全一致，不影响结果。"
        )
        return True
    return False


def _preflight_imports(retro_home, notes):
    """在构造 planner 之前把依赖逐个点名检查 —— 缺谁就给谁对应的 pip 命令。

    为什么值得单独做：`from retro_star.api import RSPlanner` 是一条长长的
    import 链，中间任何一环缺失都只抛一句 ImportError，用户根本不知道
    该装哪个包（尤其 mlp_retrosyn / rdchiral 这两个是 pip install -e 来的）。
    """
    probes = (
        ("numpy", "pip install numpy"),
        ("pandas", "pip install pandas"),
        ("networkx", "pip install networkx"),
        ("graphviz", "pip install graphviz   # 只是 python 包；viz=False 时不需要 graphviz 可执行文件"),
        ("rdkit", "conda install -c conda-forge rdkit   # 或 pip install rdkit"),
        ("torch", "conda install pytorch cpuonly -c pytorch   # 或 pip install torch"),
    )
    for module, hint in probes:
        try:
            __import__(module)
        except ImportError as exc:
            return {
                "ok": False,
                "code": "retro_backend_error",
                "target": None,
                "stage": "preflight_import",
                "missing_module": module,
                "message": (
                    "数据文件齐了，但 Python 依赖 %r 没装好（%s）。"
                    "Retro* 需要它。建议在**你准备跑 Retro* 的那个环境里**执行：%s"
                    % (module, exc, hint)
                ),
                "suggestions": [
                    "确认宿主用的是 retro 环境里的解释器，而不是系统 python3",
                    "官方的 environment.yml：conda env create -f %s/environment.yml" % retro_home,
                ],
            }

    # 这两个是 Retro* 自带的源码包，官方要求 pip install -e 进去；
    # 但它们的目录本身就是可 import 的包，所以顺手把源码目录追加到 sys.path 末尾兜底
    # （追加而不是插到最前，已安装的版本优先 —— 免得"兜底"反过来盖掉正规安装）。
    fallback_dirs = [
        os.path.join(retro_home, "retro_star", "packages", "mlp_retrosyn"),
        os.path.join(retro_home, "retro_star", "packages", "rdchiral"),
    ]
    for module, rel_dir in (("mlp_retrosyn", fallback_dirs[0]), ("rdchiral", fallback_dirs[1])):
        try:
            __import__(module)
        except ImportError:
            if os.path.isdir(rel_dir) and rel_dir not in sys.path:
                sys.path.append(rel_dir)
                try:
                    __import__(module)
                    notes.append(
                        "模块 %s 不是 pip 装进来的，已用源码目录兜底：%s"
                        "（官方步骤是 pip install -e，建议补上）" % (module, rel_dir)
                    )
                    continue
                except ImportError:
                    pass
            return {
                "ok": False,
                "code": "retro_backend_error",
                "target": None,
                "stage": "preflight_import",
                "missing_module": module,
                "message": (
                    "数据文件齐了，但 %r 这个包 import 不了。Retro* 把它当独立包装，"
                    "安装步骤里漏了或者装到了别的解释器里。请在 retro 环境里执行："
                    "pip install -e %s" % (module, rel_dir)
                ),
            }
    return None


# ---------------------------------------------------------------------------
# 真正跑 Retro*
# ---------------------------------------------------------------------------

def _prepare_runtime_args(settings, notes):
    """在 import retro_star 之前把 argv / GPU 口径摆平。

    两件事：

    1) `retro_star/common/parse_args.py` 在 **import 期**就 `argparse.parse_args()`
       （`parse_args.py:69`），任何多余 argv 都会让整个 import 链 SystemExit(2)。
       协议只走 stdin，所以默认把 argv 清成只剩脚本名。

    2) GPU 口径在上游是**自相矛盾**的：`parse_args.py:63` 把
       `CUDA_VISIBLE_DEVICES` 设成 `--gpu` 的值，而 `api.py:29` 又用
       `torch.device('cuda:%d' % gpu)` 直接按原编号取卡。只设
       `CUDA_VISIBLE_DEVICES=N` 时可见设备只剩一块、编号是 0，于是 `cuda:N`
       （N>0）必然无效；反过来什么都不设时它会被设成 `-1`，`cuda:0` 也会失败。
       所以：请求里要 gpu=N，就用 `--gpu N` 喂给上游让它把可见设备露出来，
       再把传给 RSPlanner 的 gpu 固定成 0（就是那块卡）。这样 N=0 和 N>0 都对。
       **注意：本机没有 GPU，这条路径没有被实测过。**
    """
    if settings["gpu"] >= 0:
        sys.argv = [sys.argv[0], "--gpu", str(settings["gpu"])]
        settings["gpu_effective"] = 0
        notes.append(
            "GPU：请求 gpu=%d，已通过 --gpu %d 让上游把 CUDA_VISIBLE_DEVICES 设好，"
            "并把 planner 的设备固定为 cuda:0（该卡在进程内就是 0 号）。"
            "Retro* 的 api.py:29 与 parse_args.py:63 对卡号口径不一致，桥接已代为对齐 —— "
            "但这条路没有在带 GPU 的机器上实测过。"
            % (settings["gpu"], settings["gpu"])
        )
    else:
        sys.argv = [sys.argv[0]]
        settings["gpu_effective"] = -1


def _build_planner(RSPlanner, settings, retro_home):
    """显式传全部数据路径。

    为什么不靠 RSPlanner 的默认值：默认值取自 `retro_star/api.py:11` 的
    `dirpath`，也就是**被 import 到的那个 retro_star 包**的位置；万一它和
    用户给的 retro_home 不是同一份（比如 pip 装过一份、源码又放了一份），
    就会拿错数据还不出声。显式传 = retro_home 说话算数。
    """
    package_dir = os.path.join(retro_home, "retro_star")
    return RSPlanner(
        # 用 gpu_effective 而不是 gpu：见 _prepare_runtime_args 里关于
        # CUDA_VISIBLE_DEVICES 与 'cuda:%d' 口径不一致的说明。
        gpu=settings["gpu_effective"],
        expansion_topk=settings["expansion_topk"],
        iterations=settings["iterations"],
        use_value_fn=settings["use_value_fn"],
        starting_molecules=os.path.join(package_dir, "dataset", "origin_dict.csv"),
        mlp_templates=os.path.join(package_dir, "one_step_model", "template_rules_1.dat"),
        mlp_model_dump=os.path.join(package_dir, "one_step_model", "saved_rollout_state_1_2048.ckpt"),
        save_folder=os.path.join(package_dir, "saved_models"),
        value_model="best_epoch_final_4.pt",
        fp_dim=2048,
        viz=False,
    )


def _success_payload(ctx, settings, planner, result):
    notes = list(ctx["notes"])
    route_str = result.get("routes")
    tree, parse_notes = finalize_tree_wrapper(route_str)
    notes.extend(parse_notes)

    cost = result.get("route_cost")
    score = None
    if isinstance(cost, (int, float)):
        # Retro* 的 total_cost = Σ(-ln 模板概率)，所以整条路线的概率 = exp(-total_cost)
        score = math.exp(-float(cost))

    route_len = result.get("route_len")
    steps = int(route_len) if isinstance(route_len, (int, float)) else _count_steps(tree)

    requested = settings["max_routes"]
    if requested > 1:
        notes.append(
            "请求要 %d 条路线，但 Retro* 的 RSPlanner.plan() 每次只返回**一条**最优路线"
            "（api.py:72-77 → mol_tree.get_best_route），所以 routes 长度为 1。"
            "这是后端能力边界，不是被截断。" % requested
        )

    return {
        "ok": True,
        "target": settings["smiles"],
        "retro_home": ctx["retro_home"],
        "iterations_requested": settings["iterations"],
        "iterations_used": result.get("iter"),
        "expansion_topk": settings["expansion_topk"],
        "use_value_fn": settings["use_value_fn"],
        "gpu_requested": settings["gpu"],
        "gpu_effective": settings["gpu_effective"],
        "max_routes_requested": requested,
        "backend_search_time_s": result.get("time"),
        "routes": [{
            "score": score,            # exp(-total_cost)：整条路线的（模板概率）乘积估计
            "cost": cost,              # A* 累计代价 Σ(-ln p)
            "steps": steps,            # 反应步数
            "leaf_count": _count_leaves(tree),
            "tree": tree,
            "route_string": route_str,  # 后端原话，留作追溯 / 对账
        }],
        "notes": notes,
    }


def finalize_tree_wrapper(route_str):
    """把"解析 + 摊平"的异常翻成人话，绝不把半个树当结果返回。"""
    root = parse_route_string(route_str)     # ValueError 由上层统一接住
    notes = []
    tree = finalize_tree(root, None, notes, 0)
    return tree, notes


def _run_planner(ctx, settings):
    """所有重量级动作集中在这里：import、校验 SMILES、建 planner、搜索。"""
    retro_home = ctx["retro_home"]
    notes = ctx["notes"]

    if settings["compat_shims"]:
        _apply_compat_shims(notes)

    preflight = _preflight_imports(retro_home, notes)
    if preflight is not None:
        ctx["stage"] = "preflight_import"
        return preflight

    # SMILES 先校验：坏分子没必要花几十秒加载模型才知道
    ctx["stage"] = "smiles_validation"
    from rdkit import Chem
    if Chem.MolFromSmiles(settings["smiles"]) is None:
        return {
            "ok": False,
            "code": "bad_request",
            "field": "smiles",
            "message": "RDKit 解析不了这个 SMILES：%r。它可能括号没配平、环没闭合、或者压根不是 SMILES。"
                       % settings["smiles"],
            "target": settings["smiles"],
        }

    # argv / GPU 口径必须在 import retro_star 之前摆平（理由见 _prepare_runtime_args）
    _prepare_runtime_args(settings, notes)
    if retro_home not in sys.path:
        sys.path.insert(0, retro_home)

    ctx["stage"] = "import_retro_star"
    try:
        from retro_star.api import RSPlanner
    except Exception as exc:  # import 链里什么都可能抛，一律翻成结构化错误
        return {
            "ok": False,
            "code": "retro_backend_error",
            "stage": ctx["stage"],
            "message": "import retro_star 失败：%s: %s。（常见原因：retro_star 没装、或 python 版本不兼容 —— "
                       "Retro* 官方环境是 python 3.7，本机是 %s）"
                       % (type(exc).__name__, exc, sys.version.split()[0]),
            "retro_home": retro_home,
        }

    ctx["stage"] = "planner_init"
    try:
        planner = _build_planner(RSPlanner, settings, retro_home)
    except Exception as exc:
        return {
            "ok": False,
            "code": "retro_backend_error",
            "stage": ctx["stage"],
            "message": "加载 Retro* 模型失败（%s: %s）。数据文件在磁盘上，但读不动 —— "
                       "多半是 numpy/torch 版本与这份 2020 年的代码不兼容，细节见 stderr。"
                       % (type(exc).__name__, exc),
        }

    ctx["stage"] = "search"
    result = planner.plan(settings["smiles"])
    if not result or not result.get("succ"):
        return {
            "ok": False,
            "code": "retro_no_route",
            "target": settings["smiles"],
            "message": "Retro* 跑完了但没找到可行路线（iterations=%d、expansion_topk=%d 内没搜到）。"
                       "这不是报错，是「确实没搜出来」—— 提高 iterations 或 expansion_topk 再试。"
                       % (settings["iterations"], settings["expansion_topk"]),
            "suggestions": [
                "把 iterations 从 %d 提到 500 或 1000" % settings["iterations"],
                "把 expansion_topk 提到 100（代价是每轮更慢）",
                "开 use_value_fn=true（默认就是开的）—— 有启发式更省迭代",
            ],
            "iterations": settings["iterations"],
        }

    ctx["stage"] = "serialize"
    try:
        return _success_payload(ctx, settings, planner, result)
    except ValueError as exc:
        # 只可能是路线串格式不认识 —— 把后端原话一起带回去，方便对账，绝不猜一个树给上层
        return {
            "ok": False,
            "code": "retro_backend_error",
            "stage": "route_parse",
            "target": settings["smiles"],
            "message": "Retro* 说找到了路线，但它的路线串格式本桥接不认识：%s。"
                       "这属于后端返回格式变了，需要改 dsh-ui/retro/retro_star_bridge.py 的解析。"
                       % exc,
            "raw_routes": result.get("routes"),
        }


# ---------------------------------------------------------------------------
# 桥接模式入口
# ---------------------------------------------------------------------------

def run_bridge():
    _detach_stdout()   # 第一件事：把 stdout 保护起来（见文件头"规矩 1"）

    try:
        raw = sys.stdin.read()
    except Exception as exc:
        _emit(_bad_request_payload(_BadRequest("读 stdin 失败：%s" % exc)), exit_code=2)

    raw_preview = None
    try:
        req = _load_request(raw)
    except _BadRequest as exc:
        preview = (raw or "")[:200]
        raw_preview = preview if preview else None
        _emit(_bad_request_payload(exc, raw_preview), exit_code=2)

    try:
        settings = _settings_from(req)
        retro_home, home_source = _resolve_retro_home(req)
    except _BadRequest as exc:
        _emit(_bad_request_payload(exc), exit_code=2)

    # ---- 数据检查：务必在所有重量级 import 之前（见文件头"规矩 2"）----
    missing, missing_optional, checked = _check_data(retro_home, settings["use_value_fn"])
    if missing:
        _emit(_not_configured_payload(retro_home, home_source, settings["use_value_fn"],
                                      missing, missing_optional, checked), exit_code=0)

    # ---- 内存预检：宁可提前说"不够"，也不要换来一个没有信息的 SIGKILL ----
    if not settings.get("force"):
        available_mb = _mem_available_mb()
        if available_mb is not None:
            required_mb, parts = _estimate_required_mb(retro_home, settings["use_value_fn"])
            if available_mb < required_mb:
                _emit(_memory_payload(retro_home, home_source, settings["use_value_fn"],
                                      available_mb, required_mb, parts), exit_code=0)

    ctx = {
        "smiles": settings["smiles"],
        "retro_home": retro_home,
        "retro_home_source": home_source,
        "timeout_s": settings["timeout_s"],
        "stage": "start",
        "notes": [],
    }
    if missing_optional:
        ctx["notes"].append(
            "这几个可选文件没装：%s。本次 use_value_fn=false 用不到它们。"
            % "、".join(missing_optional)
        )

    _install_alarm(settings["timeout_s"])
    _start_watchdog(settings["timeout_s"], ctx)
    try:
        payload = _run_planner(ctx, settings)
    except _SearchTimeout:
        payload = _timeout_payload(ctx)
    except MemoryError:
        _clear_alarm()
        _emit({
            "ok": False,
            "code": "retro_backend_error",
            "stage": ctx["stage"],
            "message": "内存不够了。Retro* 加载模板+模型本来就吃内存，可以在请求里把 use_value_fn 设为 false "
                       "（省掉价值网络）或换台机器。",
        }, exit_code=0)
    except Exception as exc:
        _clear_alarm()
        import traceback
        traceback.print_exc(file=sys.stderr)   # 完整栈只进 stderr，给人排查用
        _emit({
            "ok": False,
            "code": "retro_backend_error",
            "stage": ctx["stage"],
            "message": "Retro* 后端抛了 {0}: {1}（完整栈在 stderr）。这多半是这份 2020 年的代码"
                       "和本机 numpy/torch/rdkit 版本不兼容导致的，不是请求写错了。"
                       .format(type(exc).__name__, exc),
        }, exit_code=0)
    finally:
        _clear_alarm()

    payload["elapsed_ms"] = int((time.monotonic() - _start_monotonic) * 1000)
    _emit(payload, exit_code=0 if payload.get("ok") or payload.get("code") != "bad_request" else 2)


# ---------------------------------------------------------------------------
# 诊断模式（人看的，不遵守 stdin/stdout 协议）
# ---------------------------------------------------------------------------

DOCTOR_USAGE = """\
用法：
  python3 dsh-ui/retro/retro_star_bridge.py --doctor [--retro-home DIR] [--no-value-fn]

这是**诊断模式**：检查 Retro* 数据齐不齐、依赖能不能 import，结果以 JSON 打到 stdout。
它和"桥接模式"（stdin 进 JSON / stdout 出 JSON）是两码事。
退出码：0 = 一切就绪；1 = 数据没装全；2 = 数据齐但依赖 import 失败。
"""


def run_doctor(argv):
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--retro-home", dest="retro_home", default=None)
    parser.add_argument("--no-value-fn", dest="use_value_fn", action="store_false")
    parser.add_argument("-h", "--help", dest="help", action="store_true")
    args = parser.parse_args(argv)

    if args.help:
        sys.stderr.write(DOCTOR_USAGE)
        return 0

    home = os.path.abspath(os.path.expanduser(
        args.retro_home or os.environ.get(ENV_RETRO_HOME)
        or next((d for d in DEFAULT_RETRO_STAR_HOMES if os.path.isdir(d)),
                DEFAULT_RETRO_STAR_HOMES[0])))
    use_value_fn = bool(args.use_value_fn)

    missing, missing_optional, checked = _check_data(home, use_value_fn)
    report = {
        "mode": "doctor",
        "backend": BACKEND,
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "retro_home": home,
        "retro_home_source": ("cli" if args.retro_home else
                              ("env:" + ENV_RETRO_HOME if os.environ.get(ENV_RETRO_HOME) else
                               "builtin_default")),
        "use_value_fn": use_value_fn,
        "checked": checked,
        "missing": missing,
        "missing_optional": missing_optional,
    }

    if missing:
        report["ok"] = False
        report["code"] = "retro_not_configured"
        report["message"] = "数据没装全，缺 %d 个必需文件。按 setup 补齐后再跑一次。" % len(missing)
        report["setup"] = _setup_howto(home, use_value_fn, missing)
        report["heavy_imports_skipped"] = True
        report["doc"] = _doc_path()
        _emit(report, exit_code=1)

    notes = []
    if use_value_fn:
        _apply_compat_shims(notes)
    report["compat_notes"] = notes

    preflight = _preflight_imports(home, notes)
    if preflight is not None:
        report["ok"] = False
        report["code"] = preflight["code"]
        report["stage"] = preflight["stage"]
        report["message"] = preflight["message"]
        _emit(report, exit_code=2)

    sys.argv = [sys.argv[0]]
    if home not in sys.path:
        sys.path.insert(0, home)
    try:
        from retro_star.api import RSPlanner  # noqa: F401
        report["retro_star_import"] = "ok"
    except Exception as exc:
        report["ok"] = False
        report["code"] = "retro_backend_error"
        report["stage"] = "import_retro_star"
        report["message"] = "数据齐、依赖齐，但 import retro_star 失败：%s: %s" % (type(exc).__name__, exc)
        _emit(report, exit_code=2)

    report["ok"] = True
    report["code"] = "ready"
    report["message"] = "Retro* 就绪：数据齐、依赖齐、能 import。可以发桥接请求了。"
    report["doc"] = _doc_path()
    _emit(report, exit_code=0)


# ---------------------------------------------------------------------------

def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--doctor":
        _detach_stdout()
        try:
            sys.exit(run_doctor(argv[1:]))
        except SystemExit:
            raise
        except Exception as exc:
            import traceback
            traceback.print_exc(file=sys.stderr)
            _emit({"ok": False, "code": "internal_error",
                   "message": "--doctor 自己崩了：%s: %s（完整栈在 stderr）" % (type(exc).__name__, exc)},
                  exit_code=1)
    if argv and argv[0] in ("-h", "--help"):
        sys.stderr.write(__doc__ or "")
        sys.stderr.write("\n" + DOCTOR_USAGE)
        sys.exit(0)

    # 桥接模式：多余 argv 一律忽略（协议只走 stdin/stdout）
    _detach_stdout()
    try:
        run_bridge()
    except SystemExit:
        raise
    except BaseException as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        _emit({"ok": False, "code": "internal_error",
               "message": "桥接脚本自己出了意料之外的错：%s: %s（完整栈在 stderr，不在 stdout）。"
                          .format(type(exc).__name__, exc)}, exit_code=1)


if __name__ == "__main__":
    main()
