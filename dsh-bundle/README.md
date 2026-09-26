# dsh-mol

[![Awesome DSH Plugin](https://awesome-dsh-plugin.com/badge.svg)](https://awesome-dsh-plugin.com)

把 **[dsh-mol](../README.md)**（本地优先的化学工作台）接入 **DeepSeek Harness**。

装上之后，模型侧会多出这 **12** 个工具：

```
mcp__chem__chem_check_smiles        SMILES 校验 + 规范化（三级结果 + 人话原因 + 字符定位）
mcp__chem__chem_properties          分子式 / MW / 精确质量 / logP / TPSA / HBD / HBA …
mcp__chem__chem_analyze             一次给全：性质 + 类药性 + 结构警报 + Murcko 骨架
mcp__chem__chem_druglikeness        Lipinski / Veber 逐条判定、QED、PAINS / BRENK 警报
mcp__chem__chem_draw_molecule       画结构图（PNG/SVG，可标原子编号、可高亮子结构）
mcp__chem__chem_draw_grid           多分子拼图
mcp__chem__chem_convert             smiles / inchi / inchikey / mol / sdf / formula 互转
mcp__chem__chem_standardize         去盐 / 去金属 / 中和 / 规范化（逐步记录改了什么）
mcp__chem__chem_dedupe              按规范化结构去重
mcp__chem__chem_substructure_match  SMARTS 子结构匹配
mcp__chem__chem_similarity          指纹相似度
mcp__chem__chem_batch_clean         批量清洗，逐条报告失败
```

**纯本地、零网络、零 API key。** 走的是 stdio MCP，不联网。
（容易混淆：只有"远端 MCP"才走网络。）

## 这个包是什么

它**只贡献配置、不含 JS 代码**：插入一条 `@deepseek-ai/dsh-mcp-client` 记录，
指向 dsh-mol 的 stdio MCP 服务。工具实现全部在 Python 侧，避免两套实现漂移。

## 前置条件

需要有 dsh-mol 的 MCP 服务可执行。**三条路都通，按方便程度选**：

**A. 从 PyPI 安装（推荐）**

```bash
pip install 'dsh-mol[mcp]'
# 之后 PATH 上会有 dsh-mol-mcp；自检：dsh-mol-mcp --selftest
```

**B. 从 Git 安装**（PyPI 不方便时用，比如内网/离线环境）

```bash
pip install "dsh-mol[mcp] @ git+https://github.com/Yijian-quiet/dsh-mol.git"
```

**C. 从源码运行（不装包）**

```bash
git clone https://github.com/Yijian-quiet/dsh-mol.git
export MOL_MCP_COMMAND=python3
export MOL_MCP_ARGS='-m dsh_mol_mcp.server'
export PYTHONPATH=/path/to/dsh-mol/src
```

> npm 上的 `dsh-mol` / `dsh-chem-ui` **尚未发布**（2026-09-26），所以插件本身仍用
> `dsh plugin add github:…` 安装。这不影响任何功能 —— 市场条目里给的也是这条命令。
> 发布后会更新这里（以及插件市场里那条描述）。

> 为什么用环境变量而不是写死路径：`cordis.patch.yml` 里用的是 `!!js` 表达式，
> 在 loader 上下文求值，因此可以读 `process.env`。这样一个 patch 能在不同机器、
> 不同安装方式下通用，而不是到处手改绝对路径。

## 安装

```bash
dsh plugin --profile <profile> add dsh-mol
```

`dsh plugin add` 会把包加进该 profile 的 `dsh.profile.bundles`，无需手改 YAML。
装完**重启 dsh** 生效（`dsh web` 之类的常驻进程需要重启）。

> ⚠️ **实测踩坑**：`dsh plugin --profile X add` 在 profile 不存在时会**从 `dsh-base` 初始化**，
> 而 base **不含任何 app bundle**。这样的 profile 启动后不会执行你给的一次性任务
> （命令行参数被静默忽略，什么都不输出）。要跑一次性任务，profile 里必须有 app 层
> （如 `@deepseek-ai/dsh-headless` 或 web app）。做法：把 bundle 装进
> **已有的** profile（如 `web`），或从模板建：`dsh --profile <name> --from-default-profile headless`。

## 输出目录

图片与报表默认写到 **dsh 进程的工作目录**下的 `dsh-mol-out/`
（patch 里 `cwd: !!js process.cwd()`）。要固定位置，导出环境变量：

```bash
export MOL_OUT=/path/to/chem-out
```

## 诊断语言

默认中文。英文环境在**启动 dsh 之前**导出即可（stdio 桥会继承该变量）：

```bash
export MOL_LANG=en     # zh（默认）/ en
```

`code` 字段与语言无关，别依赖文案做判断。

## 验证

```bash
# 1) 组合后的配置里应出现一条 id: dsh-mol
dsh --profile <profile> --dump-config | grep -A8 dsh-mol

# 2) 实际调用（新开一个会话，别复用旧会话的上下文）
dsh --profile headless "调用 chem 工具校验 C1CC，原样引用它给的中文错误原因"
```

期望看到：

> 环闭合标记没有配对：SMILES 里的成环数字（如 C1...C1）出现次数必须是偶数

## 卸载

```bash
dsh plugin --profile <profile> remove dsh-mol
```

## 许可

MIT
