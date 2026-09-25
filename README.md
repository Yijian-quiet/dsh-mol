<div align="center">

# dsh-mol · 化学工作台

**在 AI agent 的聊天框旁边，放一张能画分子的画板 + 一个本地 RDKit 工作台。**

画结构 → 点一下 → 分子式/分子量/logP/TPSA/类药性/结构警报**当场算出来** →
把结构丢进对话，让 agent 接着往下讲。

纯 RDKit，**零网络、零 API key、零外部服务**。也可作为 stdio MCP 服务被 Claude Code / Codex 等直接调用。

[![ci](https://github.com/Yijian-quiet/dsh-mol/actions/workflows/ci.yml/badge.svg)](https://github.com/Yijian-quiet/dsh-mol/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.9%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![tests](https://img.shields.io/badge/tests-52%20passed-brightgreen)
![network](https://img.shields.io/badge/network-none%20required-success)

[English](README.en.md) | 中文

<img src="docs/workbench-analyze.png" alt="化学工作台 · 分析页签" width="820">

</div>

---

## 30 秒看懂

| | |
|---|---|
| 🎨 **画分子** | 聊天框旁一个按钮 → Ketcher 画板浮层。**聊天不会被顶掉**，画完一键插进输入框 |
| ⚡ **即时分析** | 分子式、MW、精确质量、logP、TPSA、HBD/HBA、环数、Fsp³、立体中心 —— 本机 RDKit **现算**，不走模型、不等 LLM |
| 💊 **像不像药** | Lipinski / Veber 逐条判定、QED、PAINS / BRENK 结构警报、Murcko 骨架 |
| 🧹 **脏数据急救** | 校验（人话报错 + 字符定位）、标准化（逐步记录改了什么）、去重、批量清洗 |
| 🧭 **逆合成** | 页签已就位，后端可插拔（当前接 Retro*）。**没装好模型就如实说没装好，绝不编一条路线出来** |
| 🔌 **两种用法** | 图形工作台给人用；同一套核心又通过 MCP 给 agent 用 —— **一份实现，两个入口** |

> 顺带说个背景：npm 上确认有 **618 个** DSH 插件，其中**化学/材料/分子方向是 0 个**。
> 这个仓库就是来填这个空格的。

---

## 快速开始

```bash
# 1) 装核心 + MCP 适配层（无需 PyPI 账号，直接从 git 装）
pip install "dsh-mol[mcp] @ git+https://github.com/Yijian-quiet/dsh-mol.git"

# 2) 把插件装进你的 DSH profile（无需 npm 账号，pnpm 支持 git 子目录）
dsh plugin --profile web add 'github:Yijian-quiet/dsh-mol#path:dsh-bundle'
dsh plugin --profile web add 'github:Yijian-quiet/dsh-mol#path:dsh-ui'   # ← 图形工作台

# 3) 打开 DSH Web，点输入框左边的「工作台」
```


> ⏳ **PyPI / npm 尚未发布**（2026-09-26 核实：`dsh-mol`、`dsh_mol`、`dshmol` 在 PyPI 均 404，
> npm 上 `dsh-mol`、`dsh-chem-ui` 也未发布），所以上面的命令都是 **git 直装** —— 现在就能用。
> 包名都还空着，发布之后 `pip install 'dsh-mol[mcp]'` 与 `dsh plugin add dsh-mol` 才可用。
>
> ✅ 本插件已被 [dsh 插件市场](https://awesome-dsh-plugin.com) 收录（`dsh-mol#dsh-ui` 与
> `dsh-mol#dsh-bundle` 两条，分类 `tools`），也可以直接在市场里装。

工作台需要本地有一个能 `import rdkit` 的 `python3`；画板用的是 [Ketcher](https://github.com/epam/ketcher) 静态构建，**在浏览器本地渲染，不经过任何后端**。

<details>
<summary>只想用命令行 / 其他 MCP 客户端？</summary>

```bash
dsh-mol-mcp --selftest          # 先自检（不需要任何 MCP 客户端）
```

```yaml
# 手动叠加 patch，stdio 传输，纯本地
- insert:
    - id: dsh-mol
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: chem
        transport: stdio
        command: python3
        args: ['-m', 'dsh_mol_mcp.server']
        env:
          PYTHONPATH: /path/to/dsh-mol/src
          MOL_OUT: /path/to/out
```

工具名会以 `mcp__chem__chem_check_smiles` 之类出现在模型侧。
</details>

---

## 工作台长什么样

三个页签，一个分子：

<table>
<tr>
<td width="33%"><img src="docs/workbench-draw.png" alt="画板页签"><br><b>① 画板</b><br>Ketcher 全功能画板（浮层可拖动、可最大化）。「插入到对话」把 SMILES 写进输入框 —— <b>文本只有结构本身，不夹带任何内部路径</b>。</td>
<td width="33%"><img src="docs/workbench-analyze.png" alt="分析页签"><br><b>② 分析</b><br>左边输入/按钮，右边出数。基础性质 + 类药性 + 结构警报 + 骨架一次给全，全部是本地 RDKit 现算。</td>
<td width="33%"><img src="docs/workbench-retro.png" alt="逆合成页签"><br><b>③ 逆合成</b><br>目标分子 → 多步路线。未装模型数据时，<b>它告诉你要下载什么、放哪里</b>，而不是假装算过。</td>
</tr>
</table>

### 为什么图不画在面板里？

因为**图应该跟着文字解释走**。工作台里那张缩略图只是让你确认"算的是不是这个分子"；
真正的结构图由 agent 在回复里内联画出来（`read_image`），旁边就是它对这分子的解释。

这个选择是被用户否掉两版之后定下来的：
先是"面板占掉主区域把聊天挤没了"，再是"在画板里再画一张预览图没什么用"。
现在是**聊天保持原样，工作台在旁边**。

---

## 为什么不是"包一层 RDKit"

因为直接包一层会给 AI agent 三个坑，这三个坑在科研场景里都会真实咬人：

### 1. RDKit 解析失败时**不抛异常**，只返回 `None`

失败原因写在 C++ 层的 stderr。天真包装下，模型只会拿到一个空洞的 `None`，完全不知道错在哪。
本工具把 RDKit 日志改道、捕获、**翻译成人话**，并在能定位时给出**字符位置**：

```jsonc
// chem_check_smiles("C1CC")
{ "level": "error",
  "diagnostics": [{ "code": "unclosed_ring",
                    "message": "环闭合标记没有配对：SMILES 里的成环数字（如 C1...C1）出现次数必须是偶数" }] }

// chem_check_smiles("CC(=O)O)")   ← 多余右括号，定位到第 7 个字符
{ "level": "error", "position": 7,
  "diagnostics": [{ "code": "extra_paren", "message": "多余的右括号：) 比 ( 多" }] }
```

### 2. `MolFromSmiles("")` 返回的不是 `None`，而是**一个 0 原子的"空分子"**

天真写法会把空输入判成**合法**。而 `"   "`（纯空白）**又会**返回 `None`——
同一个函数，两种空输入两种行为。本工具在领域层统一拦住。

### 3. 结果要**分三级**，不是"成功/失败"

`[Fe+9]` 能解析，但电荷荒谬。这类应该**警告**而不是拒绝：

| level | 含义 |
|---|---|
| `ok` | 干净通过 |
| `warn` | 能解析，但结构可疑（异常电荷、芳香性可疑…），附带原因 |
| `error` | 解析失败，附人话原因 + 可定位的字符位置 |

**并且：批量接口绝不静默丢数据。** 每一行都有明确归属（ok / warn / failed），
失败逐条列出——科研数据里"悄悄少了两行"比报错危险得多。

### 诊断文案支持中英双语

默认中文；英文环境设一个环境变量即可：

```bash
export MOL_LANG=en        # zh（默认）/ en
```

> ⚠️ **契约是 `code`，不是文案。** `code`（`unclosed_ring` / `valence` …）与语言无关，
> 也**不随语言改变 level / position / canonical**——有专门的回归用例锁住这一点。

---

## 工具一览（12 个，全部纯本地）

| 工具 | 作用 |
|---|---|
| `chem_check_smiles` | 校验 + 规范化，三级结果 + 人话原因 + 字符定位 |
| `chem_properties` | 分子式 / MW / 精确质量 / logP / TPSA / HBD / HBA / 环数 / 手性中心 |
| `chem_analyze` | 一次给全：基础性质 + 类药性 + 结构警报 + Murcko 骨架 |
| `chem_druglikeness` | Lipinski / Veber 逐条判定、QED、PAINS / BRENK 结构警报 |
| `chem_draw_molecule` | 画结构图（PNG/SVG，可标原子编号、可高亮子结构），返回**文件路径** |
| `chem_draw_grid` | 多分子拼图（汇报/论文附图），坏条目跳过但逐条记录 |
| `chem_convert` | smiles / inchi / inchikey / mol / sdf / formula 互转 |
| `chem_standardize` | 去盐 / 去金属 / 中和 / 规范化，**逐步记录改了什么** |
| `chem_dedupe` | 按规范化结构去重，给出重复分组 |
| `chem_substructure_match` | SMARTS 子结构匹配，返回原子索引 |
| `chem_similarity` | 指纹相似度（morgan / rdkit / maccs） |
| `chem_batch_clean` | 批量清洗一列 SMILES，输出计数摘要 + 失败清单（可写 CSV） |

工作台的「分析」页签跟这些工具**共用同一个 `chemcore`** —— 不存在"界面上算一套、agent 算另一套"的漂移。

> `chem_core` 还有一个 `python3 -m chemcore.cli` 的 JSON 入口（一行 JSON 进、一行 JSON 出），
> 工作台的即时数字就是走它。这是"给 AI 的工具"和"给人的界面"共用一份实现的接缝。

## Python API

```python
import chemcore as cc

cc.check("C1CC").diagnostics[0].message   # '环闭合标记没有配对：…'
cc.properties("CC(=O)Oc1ccccc1C(=O)O")    # {'formula': 'C9H8O4', 'mw': 180.159, …}
cc.analyze("CC(=O)Oc1ccccc1C(=O)O")       # + QED / Lipinski / PAINS 警报 / Murcko 骨架
cc.draw("CCO", atom_indices=True)         # {'path': '…/CCO.png', …}
cc.standardize("CC(=O)[O-].[Na+]")        # {'output': 'CC(=O)O', 'changes': [...]}
cc.batch_clean(["CCO", "C1CC"])           # {'ok': 1, 'failed': 1, 'failed_items': [...]}
```

## 实例：清洗一张"脏"的单体表

[`examples/monomer_cleanup.py`](examples/monomer_cleanup.py) 拿一张刻意做脏的单体表
（同一分子两种写法、一个钠盐、一个环未闭合错字、一个价键超限、一个离谱电荷）跑完整条链：

```bash
python3 examples/monomer_cleanup.py
```

它报出 `通过 11 · 警告 1 · 失败 2`、把重复项合并、逐步展示去盐与中和的每一步，
并把能画的 12 个结构画出来、把跳过的 2 个连原因一起列出来。

![批量画图（中文图注）](docs/monomers.png)

## 逆合成

逆合成页签的后端是**可插拔**的：插件用 `child_process` 起一个"喂 JSON 进 stdin、
读 JSON 出 stdout"的进程，默认指向仓库里的 Retro* 桥接脚本。

- 后端**没装好**时：返回结构化诊断（缺哪些文件、去哪下、放哪里），界面照实显示 ——
  **不会编造路线**，也不会拿"看起来像"的东西糊弄
- 想换后端（AiZynthFinder / 自研的 RetroChimera / 你们组的私服）：只要守着同一套
  stdin/stdout 协议，把 `retroCommand` 指过去即可

安装 Retro*（源码 + 模型数据，GB 级）见 **[docs/RETROSYNTHESIS.md](docs/RETROSYNTHESIS.md)**。

## 测试

```bash
PYTHONPATH=src python3 tests/run_tests.py    # 52 个核心用例（零依赖，不需要 pytest）
PYTHONPATH=src python3 tests/mcp_smoke.py    # MCP 协议级冒烟（真起服务、真调工具）
bash tests/run_all.sh                        # 上面两件 + 自测，一把梭
```

界面用 Playwright 无头验收（26 条断言，覆盖"打开工作台后聊天还能不能用""数字是不是真算的"
"后端没装好时会不会编路线"）：

```bash
dsh web --port 3081 --no-open > /tmp/chemver.log 2>&1 &
CHEM_BASE=http://127.0.0.1:3081 \
CHEM_TOKEN=$(grep -o 'token=[^ ]*' /tmp/chemver.log | cut -d= -f2) \
node dsh-ui/tests/verify-ui.cjs
```

> 别拿你正在用的那个端口做实验 —— 另起一个实例，跑完就关。

## 设计原则

1. **零网络**：所有计算在本进程完成。
2. **零额外依赖**：核心只用 RDKit；测试连 pytest 都不需要。
3. **失败说人话**：把 RDKit 的英文 C++ 日志翻译成分级诊断。
4. **不静默丢数据**：批量接口逐条报告。
5. **参数必带口径**：logP 会标注是 Crippen 估算值，`mw` / `exact_mw` 分别说明含义。
6. **落盘返回路径**：图片不塞进协议载荷，而是写文件返回路径——可复现、可进版本库、可写论文。
7. **没有的东西就说没有**：没有实验值、没有活性预测、逆合成后端没装就说没装。

## 路线图

- **v0.1（当前）**：12 个纯本地工具 + 化学工作台（画板 / 分析 / 逆合成框架）
- **v0.2**：逆合成后端真正跑通（Retro* 数据就位）+ 工作台里直接看路线图
- **v0.3**：更多分析卡片（pKa / 构象 / 药代性质），可视化升级为"结构 + 图表"
- **未定**：图像→结构识别（OCSR）需要数百 MB 模型，**不属于"基础轻工具"**，会做成可插拔后端

## 边界

- 这里**没有**实验值。`logP`、`TPSA`、`QED` 都是计算/估算值，不替代实验测量。
- 结构警报**不等于**"有毒"：它只是"这类子结构值得人工看一眼"。
- 这里**没有**图像识别、名称→结构（OPSIN 之类）。
- SMARTS 匹配是结构匹配，**不等于**化学反应性判断。
- **InChI 不支持 `*` 虚原子**：聚合物 RU-SMILES（如 `*OCCOC(=O)c1ccc(C(=O)O*)cc1`）**转不了** InChI / InChIKey。
  我们**不会静默返回空串**（RDKit 会），而是明确报错并建议用 canonical SMILES 做唯一标识 ——
  因为这个领域最常见的输入正好就是带 `*` 的。
- 这是 `v0.0.1`：API 可能变；欢迎提 issue。

## 仓库结构

```
src/chemcore/          纯 RDKit 核心（唯一的事实来源）+ JSON CLI 入口
src/dsh_mol_mcp/       stdio MCP 适配层（12 个工具）
dsh-ui/                化学工作台（DSH 客户端插件：宿主半边 + 浏览器半边）
dsh-ui/retro/          逆合成后端桥接（可插拔，默认 Retro*）
dsh-bundle/            DSH 组合包（只贡献配置，指向上面的 MCP 服务）
dsh/                   手动叠加用的 patch（写死本机路径）
tests/                 零依赖测试 + MCP 协议冒烟 + Playwright 界面验收
docs/                  演示图与专题文档
```

## 环境要求（一个真实的坑）

**MCP Python SDK 必须 1.x**：

```bash
pip install 'mcp>=1.0,<2'
```

SDK **2.x 把 `FastMCP` 改名成了 `MCPServer`**，API 有破坏性变更。
我们的 `[mcp]` extra 已钉住 `<2`；如果你手工装了 2.x，`dsh-mol-mcp` 会**明确告诉你怎么办**
（而不是甩一条 traceback）—— 这个坑是 CI 在干净环境里实测出来的，不是推测。

## 致谢

- [RDKit](https://www.rdkit.org/) —— 整个化学核心
- [Ketcher](https://github.com/epam/ketcher) —— 画板（本地 wasm 渲染，不联网）
- [Retro*](https://github.com/binghong-ml/retro_star)（ICML 2020）—— 逆合成后端之一

## 许可

MIT
