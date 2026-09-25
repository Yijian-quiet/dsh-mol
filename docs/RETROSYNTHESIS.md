# 逆合成（Retrosynthesis）

> 面向实现的协议细节在 [`dsh-ui/retro/PROTOCOL.md`](../dsh-ui/retro/PROTOCOL.md)；
> 本文是给使用者和维护者看的状态 + 安装 + 风险说明。

## 1. 一句话现状

**框架已就位，模型数据未安装 —— 现在还不能真的算逆合成。**

桥接脚本、协议、自检、宿主可调用的入口都在仓库里了，跑起来是好的；
但 Retro* 的模型数据（building blocks、模板规则、两个模型权重，GB 级）**磁盘上不存在**，
需要自己从 Dropbox 下载。数据不在时，桥接脚本会**如实**返回
`retro_not_configured`（退出码 0）并告诉你缺什么、怎么补 —— 它不会编一条路线给你。

| 能力 | 现在 | 备注 |
|---|---|---|
| 桥接脚本本体（stdin JSON → stdout JSON） | ✅ 可用 | `dsh-ui/retro/retro_star_bridge.py` |
| 协议自检（199 项） | ✅ 全绿 | `python3 dsh-ui/retro/selfcheck.py`，不需要 Retro* 数据 |
| 「数据没装」的优雅降级 | ✅ 可用 | `retro_not_configured` + `missing[]` + `setup` |
| 坏请求 / 超时 / 后端崩的结构化错误 | ✅ 可用 | `bad_request` / `retro_timeout` / `retro_backend_error` |
| **真的跑出路线** | ❌ **不行** | 缺 4 个数据文件（见 §3） |
| 路线树 → 前端展示 | ⚠️ 未接通 | 宿主侧路由还没写；协议字段已冻结在 PROTOCOL.md |

## 2. Retro* 是什么

**Retro\*: Learning Retrosynthetic Planning with Neural Guided A\* Search**（ICML 2020，PMLR 119:1608–1616）。

- 它把逆合成规划写成 **AND-OR 树的启发式（A\* 类）最好优先搜索**：
  - 单步逆合成由一个 **MLP rollout policy** 给出（对 USPTO 抽出的反应模板打分，取 top-k）；
  - 搜索的优先级由一个**学出来的价值网络**给（off-policy 数据训练），也就是"神经引导"；
  - 维护一个 AND-OR 树，用 `V_target = V_self(subtree) + V_self(siblings)` 这类估计决定下一步展开谁。
- 论文：ICML 2020，[PMLR 页面](https://proceedings.mlr.press/v119/chen20k.html) ｜ [arXiv:2006.15820](http://arxiv.org/abs/2006.15820)
- 官方代码：[binghong-ml/retro_star](https://github.com/binghong-ml/retro_star)
- 本仓库的桥接脚本按 stdio 协议调用它，所以源码放哪都行，用 `RETRO_STAR_HOME` 或插件配置 `retroHome` 指过去即可

BibTeX：

```bibtex
@inproceedings{chen2020retro,
  title={Retro*: Learning Retrosynthetic Planning with Neural Guided A* Search},
  author={Chen, Binghong and Li, Chengtao and Dai, Hanjun and Song, Le},
  booktitle={Proceedings of the 37th International Conference on Machine Learning},
  pages={1608--1616},
  year={2020},
  volume={119},
  series={Proceedings of Machine Learning Research},
  publisher={PMLR}
}
```

代码结构（读源码时的地图，供后续维护）：

```
retro_star/
├── api.py                     RSPlanner：对外入口（plan() 返回什么见 PROTOCOL.md）
├── alg/
│   ├── molstar.py             搜索主循环
│   ├── mol_tree.py            AND-OR 树；get_best_route() 只取一条最优路线
│   ├── mol_node.py / reaction_node.py
│   └── syn_route.py           最优路线；serialize() 成字符串（桥接就是解析它）
├── common/
│   ├── parse_args.py          ⚠️ import 期就 argparse.parse_args()
│   ├── prepare_utils.py       装配：读 building blocks / 加载模型 / 造 planner
│   └── smiles_to_fp.py        ⚠️ 用了 numpy 1.24 起被删的 np.bool
├── packages/mlp_retrosyn/     单步模型（要 pip install -e）
├── packages/rdchiral/         rdchiral（逆反应模板应用，要 pip install -e）
└── dataset/ one_step_model/ saved_models/   ← 这三个目录就是缺的数据
```

## 3. 缺的到底是什么

桥接脚本会检查这 5 个路径（相对 `retro_home`，即含 `retro_star/` 包的仓库根目录）：

| 路径 | 作用 | 缺了会怎样 |
|---|---|---|
| `retro_star/api.py` | Retro* 源码本身 | 有（本机这份源码在，只是数据没下） |
| `retro_star/dataset/origin_dict.csv` | building blocks：商业/文献可得砌块清单 | 无法判断路线叶子是否"买得到" |
| `retro_star/one_step_model/template_rules_1.dat` | 单步逆合成模板规则 | 无法做单步扩展 |
| `retro_star/one_step_model/saved_rollout_state_1_2048.ckpt` | 单步模型权重（MLP） | 无法给模板打分 |
| `retro_star/saved_models/best_epoch_final_4.pt` | 价值网络权重 | `use_value_fn=true` 时需要；设 `false` 可跳过（搜索会变慢变笨） |

后 4 个来自 README 里的 Dropbox 包：

```
https://www.dropbox.com/s/ar9cupb18hv96gj/retro_data.zip?dl=0
```

> 体积：README 只说是数据集 + 预训练模型，**GB 级**；本次勘察没有下载，所以给不出精确大小 ——
> 下载前先确认磁盘空间和网络。

## 4. 装起来（可复制的命令）

设一个变量少打点字（路径按你的实际情况改）：

```bash
export RETRO_STAR_HOME="/path/to/retro_star-master"        # 放着 retro_star/ 包的那一层
export DSH_MOL="/path/to/dsh-mol"                       # 本仓库的克隆位置
```

### 4.1 下载数据并摆位

```bash
cd "$RETRO_STAR_HOME"

# 方式 A：有浏览器/能访问 Dropbox 时直接下
curl -L -o /tmp/retro_data.zip \
  "https://www.dropbox.com/s/ar9cupb18hv96gj/retro_data.zip?dl=0"

# 方式 B：只拿到 zip 的话，手动放进 /tmp/retro_data.zip 也一样

# 解压后要让 dataset/ one_step_model/ saved_models/ 三个目录整体落在
# <RETRO_HOME>/retro_star/ 下面（注意：是 retro_star/ 包目录里面）
unzip -o /tmp/retro_data.zip -d /tmp/retro_data
ls /tmp/retro_data                       # 先看清 zip 里到底是哪一层
mv /tmp/retro_data/dataset /tmp/retro_data/one_step_model /tmp/retro_data/saved_models \
   "$RETRO_STAR_HOME/retro_star/"

# 摆对了应该是这样
ls "$RETRO_STAR_HOME/retro_star/dataset/origin_dict.csv" \
   "$RETRO_STAR_HOME/retro_star/one_step_model/template_rules_1.dat" \
   "$RETRO_STAR_HOME/retro_star/one_step_model/saved_rollout_state_1_2048.ckpt" \
   "$RETRO_STAR_HOME/retro_star/saved_models/best_epoch_final_4.pt"
```

### 4.2 环境与依赖

Retro\* 官方 `environment.yml` **指名 python 3.7**。本机**没有 conda**，所以有两条路：

**路 A（推荐，按官方来的话）—— 装 miniconda 再建环境：**

```bash
# 装 miniconda（跳过已有则忽略）
#   https://docs.conda.io/en/latest/miniconda.html
conda env create -f "$RETRO_STAR_HOME/environment.yml"
conda activate retro_star_env

# 三个包，缺一不可（mlp_retrosyn 和 rdchiral 是 Retro* 自带的源码包）
pip install -e "$RETRO_STAR_HOME/retro_star/packages/mlp_retrosyn"
pip install -e "$RETRO_STAR_HOME/retro_star/packages/rdchiral"
pip install -e "$RETRO_STAR_HOME"
```

**路 B（本机现状）—— 用系统 python 3.10 硬上：**

本机已经有 python 3.10.12 + rdkit 2023.09.6 + torch 2.11.0+cu130 + numpy 1.26.4 +
pandas 2.3.3 + networkx 2.8.8 + graphviz，可以直接试：

```bash
pip install -e "$RETRO_STAR_HOME/retro_star/packages/mlp_retrosyn"
pip install -e "$RETRO_STAR_HOME/retro_star/packages/rdchiral"
pip install -e "$RETRO_STAR_HOME"
```

⚠️ **这条路没有任何人验证过**（因为数据没下，连一次真跑都做不了）。风险见 §6。

### 4.3 告诉桥接脚本去哪找

任选其一（**环境变量优先**）：

```bash
export RETRO_STAR_HOME   # 已经设过，这里只是提醒桥接脚本认的就是这个变量
```

或在请求 JSON 里写 `"retro_home": "/path/to/retro_star-master"`，
或在插件配置里写 `retroHome`（见 §6）。
桥接脚本的解析顺序是 `RETRO_STAR_HOME` → 请求字段 → 内置默认路径
（默认就是上面那个 Windows 挂载路径）。

## 5. 装好了怎么验证

### 第 1 步：诊断模式（人看的）

```bash
# 用**装着 retro_star 的那个解释器**跑。conda 环境的话用环境的绝对路径：
#   conda run -n retro_star_env python3 "$DSH_MOL/dsh-ui/retro/retro_star_bridge.py" --doctor
python3 "$DSH_MOL/dsh-ui/retro/retro_star_bridge.py" --doctor
```

- 没装好：退出码 `1`，JSON 里 `code: "retro_not_configured"`，`missing[]` 列清楚缺哪些。
- 装好了：退出码 `0`，`code: "ready"`，且有 `"retro_star_import": "ok"`。
- 数据齐但依赖缺：退出码 `2`，`code: "retro_backend_error"`，`missing_module` 告诉你是哪个包。

### 第 2 步：真发一个请求（冒烟）

```bash
echo '{"smiles": "CCOC(=O)c1ccccc1", "iterations": 100, "use_value_fn": false, "timeout_s": 600}' \
  | python3 "$DSH_MOL/dsh-ui/retro/retro_star_bridge.py"
```

第一次跑会花时间加载模板和模型；先给 `use_value_fn: false` 能少加载一个网络。
成功时 stdout 是一个 `{"ok": true, ...}`，里面 `routes[0].tree` 就是可展示的路线树；
失败时一定是 `{"ok": false, "code": ...}` + 中文 `message`，不会甩栈。

### 第 3 步：协议自检（任何时候都能跑，不需要数据）

```bash
python3 "$DSH_MOL/dsh-ui/retro/selfcheck.py"
```

这条验证的是**桥接协议与降级行为**（数据缺失退出码 0、坏 JSON 结构化报错、
超时被掐断、路线串能还原成树…），共 199 项，零依赖。它**不**验证化学正确性。

## 6. 已知风险（未实测的地方 + 已经踩到的坑）

诚实起见分两栏：**已经在源码里确证的**（有行号）、**还没验证的**。

### 6.1 已经确证的坑（桥接已经绕过）

| 坑 | 证据 | 桥接怎么处理 |
|---|---|---|
| `np.bool` 在 numpy ≥1.24 已被删，但代码还在用 | `retro_star/common/smiles_to_fp.py:10`；本机 numpy 1.26.4 实测 `np.zeros(3, dtype=np.bool)` 直接报错 | 打兼容垫片 `np.bool = bool`（语义与旧 numpy 一致，`compat_shims` 默认开；响应 `notes` 里会说明） |
| `parse_args()` 在 **import 期**执行，多余 argv 直接 `SystemExit(2)` | `retro_star/common/parse_args.py` 末尾 `args = parser.parse_args()`，由 `common/__init__.py:1` 触发 | 桥接模式忽略命令行参数，并在 import 前把 `sys.argv` 收敛 |
| GPU 卡号口径自相矛盾：一边设 `CUDA_VISIBLE_DEVICES=N`，一边用 `cuda:N` | `parse_args.py:63` vs `api.py:29` | 请求 `gpu=N` 时翻译成 `--gpu N` + planner `gpu=0`（N=0/N>0 都自洽）；**未在带 GPU 的机器上实测** |
| 单步模型的输入预处理要用 `useChirality=True` 的 Morgan 指纹 | `mlp_retrosyn/mlp_policies.py` 的 `preprocess()` | 无（如报错按 `retro_backend_error` 展示） |

### 6.2 还没验证的（数据到手前无法证伪）

1. **python 3.10 跑 3.7 时代的代码：完全未验证。** 这是最大的不确定性。
   已知的语法层面没有 py2-ism（粗查无 `iteritems`/`xrange`/`collections.Iterable`），
   但第三方 API 漂移（rdkit / numpy / pandas / torch / networkx）没法静态确认。
2. **`torch.load` 的 `weights_only` 默认值变了**：`mlp_policies.py:317` 与 `api.py:44`
   都直接 `torch.load(...)`，而 torch ≥2.6 默认 `weights_only=True`。
   state_dict（张量字典）通常没问题，但**没有实测**。若这里报错，退路是设
   `PYTORCH_ENABLE_UNSAFE...`/改源码加 `weights_only=False`。
3. **rdchiral 是 2019 年的代码**，依赖 rdkit 老 API；本机 rdkit 2023.09.6 能否跑通未知。
4. **同一输入可能给出不同路线（理论上）。** `alg/molstar.py:52` 用
   `list(set(...))` 决定反应物顺序，而 Python 字符串 `set` 的顺序受解释器哈希随机化
   （`PYTHONHASHSEED`）影响，进而在并列分数处影响 A\* 的展开次序。
   **建议宿主 spawn 时带上 `PYTHONHASHSEED=0`** 换可复现性 —— 这条也**没实测**。
5. **数据包大小/下载可行性未验证**：GB 级，Dropbox 在国内网络可能需要梯子。
6. **单条路线限制**：`RSPlanner.plan()` 只返回一条最优路线
   （`api.py:72-77` → `mol_tree.py:92`）。`max_routes` 现在不起作用，
   桥接会在 `notes` 里明说。
7. **没有模板信息**：`SynRoute.serialize()`（`syn_route.py:92-99`）没把
   `self.templates` 写进串里，所以桥接还原出的 `tree` **没有 `template` 字段**。
   想要"这一步用了哪条反应规则"，得改用 `planner.plan_handle`（上游实现细节，
   非公开 API）或改上游 `serialize()`——不建议，会绑定到这份代码的内部结构。
8. **耗时/内存**：首次 import + 加载模板可能几十秒、内存上 GB；`iterations=500`
   （上游默认）下单个目标可能跑几分钟。桥接默认 `iterations=100`、`timeout_s=300`。
9. **本机没有 conda**：官方 `environment.yml` 用不了，只能走路 B（系统 python 3.10），
   这正好把风险 1 顶到最前面。

## 7. 换后端：只要守住同一个 stdin/stdout 协议

逆合成这块**故意**做成"一个进程 + 一段 JSON 协议"的形状，就是为了换后端时宿主不用改。
可替换的候选：

- **AiZynthFinder**（AstraZeneca，开源，有维护，文档好）：同样吃 building blocks +
  模板/单步模型，但它自己带 CLI/Python API，路线是"反应树"结构，比 Retro\* 的单条路线更好用。
- **自研 RetroChimera**：如果之后要上自己的模型，只要套上这个协议即可。

替换时需要满足的契约（详见 [`PROTOCOL.md`](../dsh-ui/retro/PROTOCOL.md)）：

1. 从 **stdin 读一个 JSON** 请求，往 **stdout 写且只写一个 JSON** 响应，日志走 stderr；
2. 请求至少认 `smiles` / `iterations` / `expansion_topk` / `use_value_fn` /
   `max_routes` / `timeout_s` / `retro_home`（认不了的可以忽略，但要不报错）；
3. 成功响应要有 `ok: true` + `routes[]`，每条含 `score` / `steps` / `tree`；
   `tree` 节点含 `smiles` / `children`（**父 = 产物，子 = 反应物**）/
   `is_starting_material` / `score` / `role`；
4. 失败一律 `{"ok": false, "code": ..., "message": "<中文人话>"}`，**不抛栈**；
5. 环境/数据缺失时 `code: "retro_not_configured"` + `missing[]` + `setup`，退出码 0。

协议只认 `code` 不认文案，所以文案可以随便改，`code` 集合要保持稳定。

## 8. 自检与文件清单

```bash
python3 dsh-ui/retro/selfcheck.py                     # 协议自检，199 项，零依赖
python3 dsh-ui/retro/retro_star_bridge.py --doctor    # 数据/依赖诊断
```

| 文件 | 作用 |
|---|---|
| `dsh-ui/retro/retro_star_bridge.py` | 桥接脚本：stdin JSON → stdout JSON；`--doctor` 诊断模式 |
| `dsh-ui/retro/selfcheck.py` | 零依赖协议自检（含一个桩后端，用来验成功响应形状与超时） |
| `dsh-ui/retro/PROTOCOL.md` | 给宿主侧看的字段表 + 退出码表 |
| `docs/RETROSYNTHESIS.md` | 本文件 |

## 9. 下一步（给要接着干的人）

1. 下数据（§4.1），跑 `--doctor` 到 `ready`。
2. 跑一次真冒烟（§5 第 2 步），把 §6.2 里 1/2/3 条的风险逐条证伪或证实。
3. 证伪成功后再写宿主侧路由：`spawn(retroPython, [bridgePath], { env: { PYTHONHASHSEED: '0' } })`，
   按 `PROTOCOL.md` 的 `code` 分支渲染。
4. 前端把 `tree` 画成路线图（`role` 直接拿来上色）。
