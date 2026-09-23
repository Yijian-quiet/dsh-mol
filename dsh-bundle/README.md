# dsh-chemworkbench

把 **[chemworkbench](../README.md)**（本地优先的化学工作台）接入 **DeepSeek Harness**。

装上之后，模型侧会多出这些工具：

```
mcp__chem__chem_check_smiles        SMILES 校验 + 规范化（三级结果 + 人话原因 + 字符定位）
mcp__chem__chem_properties          分子式 / MW / 精确质量 / logP / TPSA / HBD / HBA …
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
指向 chemworkbench 的 stdio MCP 服务。工具实现全部在 Python 侧，避免两套实现漂移。

## 前置条件

需要有 chemworkbench 的 MCP 服务可执行。二选一：

**A. 正式安装（推荐）**

```bash
pip install 'chemworkbench[mcp]'
# 之后 PATH 上会有 chemworkbench-mcp
```

**B. 从源码运行**

```bash
export CHEMWORKBENCH_MCP_COMMAND=python3
export CHEMWORKBENCH_MCP_ARGS='-m chemworkbench_mcp.server'
export PYTHONPATH=/path/to/chemworkbench/src
```

> 为什么用环境变量而不是写死路径：`cordis.patch.yml` 里用的是 `!!js` 表达式，
> 在 loader 上下文求值，因此可以读 `process.env`。这样一个 patch 能在不同机器、
> 不同安装方式下通用，而不是到处手改绝对路径。

## 安装

```bash
dsh plugin --profile <profile> add dsh-chemworkbench
```

`dsh plugin add` 会把包加进该 profile 的 `dsh.profile.bundles`，无需手改 YAML。
装完**重启 dsh** 生效（`dsh web` 之类的常驻进程需要重启）。

> ⚠️ **实测踩坑**：`dsh plugin --profile X add` 在 profile 不存在时会**从 `dsh-base` 初始化**，
> 而 base **不含任何 app bundle**。这样的 profile 启动后不会执行你给的一次性任务
> （命令行参数被静默忽略，什么都不输出）。要跑一次性任务，profile 里必须有 app 层
> （如 `@deepseek-ai/dsh-headless` 或 web app）。做法：把 bundle 装进
> **已有的** profile（如 `web`），或从模板建：`dsh --profile <name> --from-default-profile headless`。

## 输出目录

图片与报表默认写到 **dsh 进程的工作目录**下的 `chemworkbench-out/`
（patch 里 `cwd: !!js process.cwd()`）。要固定位置，导出环境变量：

```bash
export CHEMWORKBENCH_OUT=/path/to/chem-out
```

## 验证

```bash
# 1) 组合后的配置里应出现一条 id: chemworkbench
dsh --profile <profile> --dump-config | grep -A8 chemworkbench

# 2) 实际调用（新开一个会话，别复用旧会话的上下文）
dsh --profile headless "调用 chem 工具校验 C1CC，原样引用它给的中文错误原因"
```

期望看到：

> 环闭合标记没有配对：SMILES 里的成环数字（如 C1...C1）出现次数必须是偶数

## 卸载

```bash
dsh plugin --profile <profile> remove dsh-chemworkbench
```

## 许可

MIT
