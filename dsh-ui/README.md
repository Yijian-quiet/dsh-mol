# dsh-chem-ui · 化学工作台（DSH Web UI 插件）

给 DeepSeek Harness 的**化学工作台**：左侧栏一个独立入口，点进去是分子画板（Ketcher），
画完把结构**直接送进对话输入框**交给 agent。

![化学工作台](tests/panel.png)

---

## 它解决什么

`dsh-mol`（同仓）是**引擎**：SMILES 校验、性质计算、标准化、批量清洗 —— 但它只能由模型调工具。
**"让人在界面里画分子、再把结构交给 agent"这件事只有 UI 能做。**

## 架构（两块）

```
dsh-ui/
├── lib/index.js    宿主半边：把 Ketcher 静态构建挂在 DSH 自己的源下（/chem/ketcher）
├── lib/client.js   客户端半边：左侧栏图标 + 主面板（Ketcher iframe + 读取/插入）
└── cordis.patch.yml  挂载层（ketcherDir 指向解压后的 Ketcher 构建）
```

### 为什么宿主半边必须存在

面板用 `<iframe>` 嵌 Ketcher，之后要读 `iframe.contentWindow.ketcher.getSmiles()`。
若 Ketcher 跑在别的端口，就是**跨源**，同源策略会直接挡掉 ——
所以必须由插件在 DSH 自己的源上提供（`ctx.webServer.register({ kind:'prefix', path:'/chem/ketcher' })`）。
**不能让用户另起一个静态服务。**

### 左侧栏入口是"全局面板"机制（不是 hack）

| 注册 | slot | 字段 |
|---|---|---|
| 主区域视图 | `main`（keyed） | `key: 'chem-workbench'` |
| 左侧栏图标 | `sidebar.panellist`（list） | `id: 'chem-workbench'`、`order`、`label` |

**两处的 id/key 必须一致** —— 这是"图标 ↔ 面板"的对应关系。
按钮、tooltip、点击、高亮都由 shell 负责，我们只提供图标和元数据。
`sidebar.panellist` 与 `sidebar.workspaces`（会话/工作区浏览区）是两个不同席位，
所以这个入口天然落在**工作区之外**。

### 把结构交给 agent：走服务，不走 DOM

**关键实测结论：面板占用主区域时，composer 根本没有渲染**（页面里 textarea 数为 0），
所以 DOM 路线在这个布局下必然失败。正确做法是写会话的草稿状态：

```js
const sessionId = ctx.get('sessions').list.getSnapshot().current   // DSH 内部同样这么取
ctx.get('conversation').input.shell(sessionId).setDraft(text)
```

**追加而不是覆盖**：已读 `shell.snapshot.draft`，非空时拼在后面，不吞用户已输入的内容。

## 安装

1. 取 Ketcher 独立构建（[ketcher-standalone](https://github.com/epam/ketcher/releases)），解压到任意目录
2. 把本包装进 profile，并在 patch 层挂载（`ketcherDir` 指向第 1 步的目录）：

```yaml
- insert:
    - id: chem-ui
      name: 'dsh-chem-ui'
      config:
        ketcherDir: /path/to/ketcher
```

> 开发期可以 `pnpm add <本目录>` 后只改 profile 的 `cordis.patch.yml`——
> 若该 profile 是 `patchReload: live`，**不必重启 dsh**（实测热加载生效）。

3. **刷新页面**（客户端 bundle 是懒加载的，页面刷新后才会拉取）

## 验收（可自动化，不需要人盯屏幕）

```bash
CHEM_BASE=http://127.0.0.1:3080 CHEM_TOKEN=<token> node tests/verify-ui.cjs
```

需要 Playwright（`npx playwright` 会带 chromium）。它断言 7 项并逐步截图到 `/tmp/chem-ui-shots/`：

1. 左侧栏出现「化学工作台」图标
2. 点击后主区域出现 Ketcher iframe
3. 画板就绪（frame 内 `window.ketcher` 可用）
4. 塞入 `CCO` 后能读出并显示
5. 「插入输入框」按钮启用
6. 插入动作走通（报告实际路径）
7. **会话草稿里确实出现了该 SMILES**（强断言，不只是按钮状态）

## 已知限制

- 客户端插件**改动后要刷新页面**才生效（没有第三方插件级别的 HMR）
- 目前只有"读取结构 / 插入输入框"两个动作；性质显示、批量面板见
  本仓外部的设计文档 的阶段 1-2
- 面板激活时主区域被占用（这是 `main` slot 的语义），对话视图暂时不可见；
  草稿写的是会话状态，切回对话即可见

## 许可

MIT
