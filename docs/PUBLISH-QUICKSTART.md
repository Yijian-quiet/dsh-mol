# 发布照抄清单（PyPI + npm）

> 只含命令和判断点。背景解释在 `docs/PUBLISHING.md`。
> 每步都写了**预期输出**；输出不一样就停下来，别硬往下走。

---

## 已经做好的（不用管，列出来是让你知道起点是干净的）

- `dist/dsh_mol-0.0.1.tar.gz` + `dist/dsh_mol-0.0.1-py3-none-any.whl` —— `twine check` 两个都 PASSED
- 构建 0 告警；wheel 里的 long_description 已含最新 README（含徽章）
- `npm pack --dry-run` 两个包都已验：`dsh-mol` 3 个文件 / `dsh-chem-ui` 13 个文件，
  没有 `__pycache__`、没有 116 MB 的 Ketcher、没有 tests
- 包名两边都还空着（`dsh-mol` / `dsh-chem-ui`）

---

## ① PyPI：注册 + 令牌（约 5 分钟）

1. https://pypi.org/account/register/ → 注册（用户名建议 `Yijian-quiet`）
2. **必须开 2FA**：https://pypi.org/manage/account/ → *Two-factor authentication* →
   用手机验证器 App（TOTP）。保存好恢复码
3. 验证邮箱（不验证不能发布）
4. 建令牌：https://pypi.org/manage/account/token/ → *Add API token*
   - Token name: `dsh-mol-upload`
   - Scope: **Entire account**（第一次只能这样，因为项目还不存在）
   - 复制那串 `pypi-AgEIcHlwaS5vcmc...`（**只显示一次**）

### ①.5 2FA 验证器怎么弄（只有 PyPI 需要）

**2FA 是什么**：除了密码，再要一个**每 30 秒变一次的 6 位数字**。
它由"验证器"根据一串共享密钥在**本地**算出来，不联网、不发短信 —— 所以不受信号影响。

**先明确一件事：上传**（`twine upload`）**用 API token 就够了，不需要输这 6 位码。**
2FA 是给**网页登录**用的。别被"发布要 2FA"吓到。

**路线 A：手机 App（推荐，最省心）**

1. 应用商店搜 **Microsoft Authenticator**（微软出品；华为/小米/OPPO 应用商店、App Store 都有，中文界面）
   —— 也可以选 Google Authenticator / Authy，任一个都行
2. PyPI → https://pypi.org/manage/account/ → *Two-factor authentication* → **Add 2FA device**
3. 选 **Authenticator app** → 屏幕给出**二维码**和一串**文字密钥（setup key，形如 `JBSWY3DPEHPK3PXP`）**
4. App 里「添加账户 → 扫描二维码」（扫不动就手动输入那串文字密钥）
5. App 会显示 6 位码 → 填回 PyPI 页面 → 确认
6. ⚠️ **立刻保存 PyPI 给的恢复码（recovery codes）** —— 存到密码管理器或打印出来。
   **手机丢了又没有恢复码，PyPI 账号基本救不回来**（有官方申诉流程，但很慢）

**路线 B：不碰手机，用桌面**

- **Windows**：装 [KeePassXC](https://keepassxc.org/)（有 Windows 版，自带 TOTP）→
  新建一个库 → 新建条目 → 在条目里「设置 TOTP」→ 粘贴上面那串 setup key → 就能显示 6 位码。
  好处：顺便把密码也管起来
- **Edge/Chrome 扩展**：加载项商店搜 "Authenticator" 类扩展，添加后扫二维码。
  ⚠️ 风险：扩展数据跟着浏览器配置走，换机器/清配置就丢 —— **恢复码必须另存一份**

**两条路都适用的一条铁律**：恢复码不要只存在存验证器的那个设备里。

## ② npm：注册 + 令牌（约 5 分钟）

1. https://www.npmjs.com/signup → 注册 → 验证邮箱
2. https://www.npmjs.com/settings/~/tokens → *Generate New Token* → 选 **Automation**
   - 复制 `npm_xxxxx`（**只显示一次**）
   - 选 Automation 而不是 Publish 的原因：**Automation token 不需要 OTP**
     （否则每次发布都要手输 6 位验证码）

---

## ③ 上传（把两个 token 填进去，或交给我跑）

### PyPI

```bash
cd /home/zhangyijian/dsh-plugins/dsh-mol
TWINE_USERNAME=__token__ TWINE_PASSWORD='pypi-你的令牌' \
  python3 -m twine upload dist/*
```

预期输出（最后两行）：

```
View at:
https://pypi.org/project/dsh-mol/0.0.1/
```

### npm

```bash
# 令牌写到家目录的临时 npmrc（不放仓库里，也不进 argv），用完删掉
umask 077
printf '//registry.npmjs.org/:_authToken=%s\n' 'npm_你的令牌' > ~/.npmrc-dsh-mol

cd /home/zhangyijian/dsh-plugins/dsh-mol/dsh-bundle
npm publish --userconfig ~/.npmrc-dsh-mol --access public
# 预期：+ dsh-mol@0.0.1

cd /home/zhangyijian/dsh-plugins/dsh-mol/dsh-ui
npm publish --userconfig ~/.npmrc-dsh-mol --access public
# 预期：+ dsh-chem-ui@0.0.1

shred -u ~/.npmrc-dsh-mol 2>/dev/null || rm -f ~/.npmrc-dsh-mol   # 用完就删
```

---

## ④ 立刻验证（**这步别跳**）

```bash
# PyPI：从 PyPI 装（不是从 git），跑自检
rm -rf /tmp/pypi-check && python3 -m pip install --no-deps --target /tmp/pypi-check 'dsh-mol[mcp]'
PYTHONPATH=/tmp/pypi-check python3 -m dsh_mol_mcp.server --selftest
# 预期：自测：11/11 通过

# npm：确认包在 registry 上、元数据正确
npm view dsh-mol version description
npm view dsh-chem-ui version
```

预期：`0.0.1`；npm 上 `dsh-mol` 的 repository 指向本仓库。

---

## ⑤ 发布成功后要同步的三处（我准备好文本）

1. `dsh-bundle/README.md`：**C 路线（PyPI）从"尚未发布"改成正式安装**
2. `README.md` / `README.en.md`：去掉"PyPI / npm 尚未发布"那段提示
3. **插件市场那两条条目**：维护者之前把 `dsh-bundle` 描述改成了
   "until the package is on PyPI the from-source one is what works" —— 现在要撤掉这半句、
   把 `pip install 'dsh-mol[mcp]'` 写回去
   （这是维护者自己说过"发完说一声"的事，属于他自己那条条目的正常更新）

---

## 出错时看这里

| 现象 | 原因 | 怎么办 |
|---|---|---|
| twine: `403 Invalid or non-existent authentication` | token 错/带空格/用了密码 | 重新复制 token；用户名必须是 `__token__` |
| twine: `400 File already exists` | 同版本传过第二次 | 升版本号（`0.0.1`→`0.0.2`）再构建 |
| twine: `403 ... not allowed to upload to project` | token scope 限了别的项目 | 用 Entire account 的 token |
| npm: `E403 You do not have permission` | 名字被占 / token 无权限 | 换名字或换 token（`dsh-mol` 目前是空的） |
| npm: `EOTP` | 用了 Publish 类 token（要验证码） | 换 **Automation** token，或加 `--otp=123456` |
| npm: `ENEEDAUTH` | npmrc 没被读到 | 确认 `--userconfig ~/.npmrc-dsh-mol` 路径对 |
| npm: 包里出现 `__pycache__` | `dsh-ui/.npmignore` 被删了 | 恢复它（已提交到仓库） |
