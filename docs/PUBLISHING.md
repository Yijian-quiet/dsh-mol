# 发布到 PyPI 与 npm（2026-09-26 准备）

> 这份是给 Mr.自由基 看的：**是什么、为什么要发、明天怎么做、哪里会翻车**。
> 每条命令都可以直接复制。**不需要你在本地装 Python 环境或 Node** —— 这台机器上已经备好了。

---

## 一、这两个东西是什么

| | **PyPI** | **npm** |
|---|---|---|
| 全称 | Python Package Index | Node Package Manager（的公共仓库） |
| 一句话 | **Python 界的应用商店** | **JavaScript 界的应用商店** |
| 装上之后用户能做什么 | `pip install dsh-mol[mcp]` | `dsh plugin add dsh-mol` / `dsh plugin add dsh-chem-ui` |
| 我们的包名 | `dsh-mol` | `dsh-mol`（配置包）、`dsh-chem-ui`（工作台） |
| 现状 | 未发布（`pypi.org/pypi/dsh-mol/json` → 404） | 未发布（两个名字都 404） |

发布 = 把打包好的文件**上传到公共仓库**，之后任何人一条命令就能装。上传要**账号 + 令牌（token）**，
令牌就是"给上传工具用的密码"，不用把账号密码给任何程序。

---

## 二、为什么值得发（两者价值不一样，PyPI 更值）

**PyPI 是真正的收获** —— 我们那个 `dsh-mol-mcp` 是**通用 MCP 服务**，
Claude Code、Codex、Cursor 任何支持 MCP 的客户端都能用（不是只能给 DSH）。
没上 PyPI 的时候，他们得会 git + 会配 PYTHONPATH；上了以后就是一行 `pip install dsh-mol[mcp]`。
**这是能让插件被 DSH 圈子之外的人用起来的唯一一步。**

**npm 是锦上添花**：
- 用户装起来少一步（不用 `#path:dsh-bundle` 这种 git 语法）
- 插件市场能显示**下载量**（目录里 `npm` 字段有值才会有那个数字）
- 但 git 安装**本来就是通的**（目录里 1958 条都是 git 安装）—— 所以 npm 不是必需品

---

## 三、⚠️ 发布前必须知道的三个坑

1. **名字一旦被占，基本拿不回来。**
   - PyPI：删掉一个版本/项目后，**同名不能再用**（防止别人抢注你删掉的名字）
   - npm：发布后 72 小时内可以 unpublish，之后要靠客服
   - 好消息：`dsh-mol`、`dsh-chem-ui` **两边都还空着**（2026-09-26 核实过）

2. **版本号只能往上走，不能覆盖。** 同一个版本号上传第二次会被拒。所以
   "传错了想重传"必须**升版本**（`0.0.1` → `0.0.2`）。第一次建议就用 `0.0.1`，出问题再升。

3. **令牌绝对不能进 git。** 我们的仓库是公开的。令牌只放：
   - 环境变量（`TWINE_PASSWORD` / `NODE_AUTH_TOKEN`），或
   - `~/.pypirc`（家目录，不在仓库里），或
   - 直接交给我，我只在当次命令的环境变量里用，**不写进任何文件**

---

## 四、明天怎么做（我可以全程带着走）

### 第 0 步：我这边已经备好的（今天做完了）

- ✅ `python3 -m build` / `twine` 已装到 `~/.local`
- ✅ wheel 已构建验证过：`dsh_mol-0.0.1-py3-none-any.whl`，内容正确
  （12 个 `chemcore` 模块 + `dsh_mol_mcp` + LICENSE + entry_points）
- ✅ 推荐安装路线（git 直装）实测能跑：干净目录装完 `--selftest` **11/11 通过**
- ✅ npm 侧障碍已清：`dsh-ui/package.json` 的 `private: true` 已移除（不移除 `npm publish` 直接拒绝）
- ✅ 两个包的 `repository` 字段都指回本仓库（npm 要求，也用于市场关联）

### 第 1 步：注册账号（只有你能做，约 10 分钟）

- **PyPI**：https://pypi.org/account/register/
  注册后**必须开 2FA**（现在强制），推荐用手机上的验证器 App（TOTP）
- **npm**：https://www.npmjs.com/signup
  注册后验证邮箱；也建议开 2FA

### 第 2 步：各建一个令牌（token）

- **PyPI**：https://pypi.org/manage/account/token/ → *Add API token*
  - 名字填 `dsh-mol-upload`，Scope 先选 **“Entire account”**（第一次必须，因为项目还不存在），
    发布成功后再建一个限定到 `dsh-mol` 项目的
  - 形如 `pypi-AgEIcHlwaS5vcmc...`，**只显示一次**
- **npm**：https://www.npmjs.com/settings/~/tokens → *Generate New Token* → **Automation**
  - 形如 `npm_xxxxx`，**只显示一次**

### 第 3 步：上传（两条命令，我给你现成的）

**PyPI：**
```bash
cd /home/zhangyijian/dsh-plugins/dsh-mol
rm -rf dist && python3 -m build            # 产出 dist/*.tar.gz 与 dist/*.whl
python3 -m twine check dist/*              # 先自检，不通过别上传
TWINE_USERNAME=__token__ TWINE_PASSWORD='<你的 pypi token>' \
  python3 -m twine upload dist/*
```

**npm：**
```bash
# 配置包（dsh-bundle 目录里的 name 就是 dsh-mol）
cd /home/zhangyijian/dsh-plugins/dsh-mol/dsh-bundle
npm publish --access public --//registry.npmjs.org/:_authToken='<你的 npm token>'

# 工作台（dsh-ui）
cd /home/zhangyijian/dsh-plugins/dsh-mol/dsh-ui
npm publish --access public --//registry.npmjs.org/:_authToken='<你的 npm token>'
```

> 两个命令都可以改成"你把 token 给我、我来跑"。token 只在当次命令的环境变量里出现，
> 不落盘、不进 git。你也可以自己跑 —— 那更稳。

### 第 4 步：发布后立刻验证（我会做）

```bash
# PyPI：在一个空目录里装（不是从 git，是从 PyPI）
python3 -m pip install --no-deps --target /tmp/pypi-check 'dsh-mol[mcp]'
PYTHONPATH=/tmp/pypi-check python3 -m dsh_mol_mcp.server --selftest   # 期望 11/11

# npm：确认包元数据与 marketplace 关联
curl -s https://registry.npmjs.org/dsh-mol | head -c 200
```

### 第 5 步：让描述跟着事实走（你之前说过的话，兑现）

发布成功后要改三处，**由我准备好内容，你决定怎么落地**：

1. 本仓库 `dsh-bundle/README.md`：把 C 路线（PyPI）从"尚未发布"改成正式安装
2. 本仓库 `README.md` / `README.en.md`：去掉"PyPI/npm 尚未发布"的提示
3. **插件市场的两条条目**：市场维护者（你）之前把 dsh-bundle 描述改成了
   "until the package is on PyPI the from-source one is what works" ——
   发布后这句要撤掉、把 `pip install` 写回去。你在 PR 里说过"发完说一声"，
   我会给你一条**可直接粘贴的 PR 文本**（只改你自己那条条目）

---

## 五、我需要你提供的（就这两样）

| | 用途 | 怎么给 |
|---|---|---|
| PyPI token | 上传 Python 包 | 直接粘贴，或你自己跑命令 |
| npm token | 上传两个 JS 包 | 同上 |

**不用**给我账号密码。发布完你可以立刻在网页上删掉这两个 token（上传过的包不受影响）。

---

## 六、如果明天时间不够，优先级

1. **PyPI**（价值最高的那一步：让 DSH 圈子外的人也能装）
2. npm 的 `dsh-mol`（配置包，让 `dsh plugin add dsh-mol` 生效）
3. npm 的 `dsh-chem-ui`（工作台；git 安装本来就通）

只做第 1 步也是完全值得的一步。
