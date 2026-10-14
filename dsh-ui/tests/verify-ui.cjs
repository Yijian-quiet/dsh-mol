/**
 * 化学工作台验收（Playwright，无头）
 *
 * 覆盖的是**交互质量**，不是"元素存不存在"：
 *   - 工作台打开后聊天还能不能用（这是当初否掉 main 面板的原因）
 *   - 画板 → 插入对话，文本是否干净（不含内部路径提示）
 *   - 分析页签的数字是不是**真的从 RDKit 来的**（拿乙醇/阿司匹林对已知值）
 *   - 逆合成后端没装好时，界面是否**如实说没装好**、而不是编一条路线出来
 *
 * 跑法（必须对着另起的实例，别拿用户正在用的 3080 做实验）：
 *   dsh web --port 3081 --no-open > /tmp/chemver.log 2>&1 &
 *   CHEM_BASE=http://127.0.0.1:3081 CHEM_TOKEN=$(grep -o 'token=[^ ]*' /tmp/chemver.log | cut -d= -f2) \
 *   NODE_PATH=... node tests/verify-ui.cjs
 */
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const BASE = process.env.CHEM_BASE || 'http://127.0.0.1:3080'
const TOKEN = process.env.CHEM_TOKEN || ''
const SHOTS = process.env.CHEM_SHOTS || '/tmp/chem-ui-shots'

const results = []
function check(name, ok, detail = '') {
  results.push({ name, ok })
  console.log(`${ok ? '  ✓' : '  ✗'} ${name}${detail ? '  — ' + detail : ''}`)
}

/**
 * 环境不满足时的"未验证"。
 *
 * 为什么要独立一类：在**干净的 DSH_HOME**（隔离验收环境）里没有"当前会话"，
 * 于是"把结构写进输入框"这类断言无从谈起 —— 但这跟被测插件毫无关系。
 * 标成 ✗ 会让人以为插件坏了；标成 ✓ 是撒谎。所以单独一类，结尾显式列出。
 */
const skipped = []
function skip(name, why) {
  skipped.push({ name, why })
  console.log(`  ⊘ ${name}  — 跳过：${why}`)
}

async function draftOf(page) {
  return page.evaluate(() => {
    const ctx = window.__DSH_CHEM_CTX__
    if (!ctx) return '(插件 ctx 未暴露)'
    const id = ctx.get('sessions').list.getSnapshot().current
    if (!id) return '(没有当前会话)'
    try { return ctx.get('conversation').input.shell(id).snapshot?.draft ?? '' } catch { return '(取草稿失败)' }
  })
}

/**
 * 按文本/aria-label 用 **JS 直接触发** 点击。
 *
 * 为什么不用 Playwright 的 click()：一次性模态框（首次配置向导、Preview Notice）
 * 和 Ketcher 的模式下拉都盖着一层 mask，Playwright 会等"可点击"等到超时（实测 8s 也过不去，
 * 报的是"元素被遮挡"）。JS 触发不经过命中测试，对这种"我就是要关掉它"的场景更合适。
 *
 * @returns 是否找到了目标
 */
async function jsClickByText(page, pattern) {
  return page.evaluate((src) => {
    const rx = new RegExp(src, 'i')
    const els = [...document.querySelectorAll('button, [role="button"], a[href]')]
    const el = els.find((b) => rx.test((b.textContent || '').trim()) || rx.test(b.getAttribute('aria-label') || ''))
    if (!el) return false
    el.scrollIntoView({ block: 'center' })
    el.click()
    return true
  }, pattern.source)
}

/**
 * 确保有当前会话。
 *
 * 为什么要这一步：在**全新的 DSH_HOME**（验收推荐的隔离环境）里一条会话都没有，
 * composer 根本不会渲染（`contenteditable × 0`），后面所有断言都会连带失败 ——
 * 而这跟被测插件毫无关系。所以先点一次「New Session」再开始。
 */
async function ensureSession(page) {
  const read = () => page.evaluate(() => {
    try { return window.__DSH_CHEM_CTX__?.get('sessions')?.list?.getSnapshot?.()?.current ?? null } catch { return null }
  })
  if (await read()) return true
  // 再清一次可能后到的模态框（它们会让「New Session」点不动）
  for (const name of [/^Continue$/i, /^继续$/, /Configure later/i, /知道了/]) {
    if (await jsClickByText(page, name)) await page.waitForTimeout(1500)
  }
  for (const name of [/New Session/i, /新建会话/, /新会话/, /新建对话/]) {
    if (await jsClickByText(page, name)) {
      await page.waitForTimeout(5000)
      if (await read()) return true
    }
  }
  return Boolean(await read())
}

async function clearDraft(page) {
  await page.evaluate(() => {
    const ctx = window.__DSH_CHEM_CTX__
    const id = ctx.get('sessions').list.getSnapshot().current
    if (!id) return
    try { ctx.get('conversation').input.shell(id).setDraft('') } catch { /* 无会话时忽略 */ }
  })
}

/** 找 Ketcher 所在的子 frame（必须 await：`find(async …)` 永远为真，踩过） */
async function findKetcher(page, tries = 60) {
  for (let i = 0; i < tries; i++) {
    for (const f of page.frames()) {
      if (f === page.mainFrame()) continue
      try { if (await f.evaluate(() => typeof window.ketcher !== 'undefined')) return f } catch { /* 跨域/未就绪 */ }
    }
    await page.waitForTimeout(1000)
  }
  return null
}

;(async () => {
  fs.mkdirSync(SHOTS, { recursive: true })
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  const errors = []
  page.on('pageerror', (e) => errors.push(String(e)))

  await page.goto(TOKEN ? `${BASE}/?token=${TOKEN}` : BASE, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(8000)

  // 全新 context / 全新 DSH_HOME 会弹各种一次性模态框（首次配置向导、Preview Notice…），
  // 它们**拦截所有点击**，不关掉的话后面每条断言都会以"元素被遮挡"超时，且原因极难看出。
  // 实测踩到过两个：Configure later（配置向导）和 Continue（Preview Notice）。
  for (const name of [/Configure later/i, /稍后配置/, /以后再说/, /Skip/i,
                     /^Continue$/i, /^继续$/, /知道了/, /Got it/i]) {
    if (await jsClickByText(page, name)) await page.waitForTimeout(1500)
  }
  await page.keyboard.press('Escape').catch(() => {})
  await page.waitForTimeout(600)

  const hasSession = await ensureSession(page)
  if (hasSession) check('有可用的会话', true)
  else skip('有可用的会话', '干净 DSH_HOME 里没有 current 会话 → 下面 2 条草稿断言一并跳过')
  await page.waitForTimeout(2000)

  /* ── 1. 聊天是主场 ─────────────────────────────────────────────── */

  const composerCount = await page.locator('[contenteditable="true"]').count()
  check('聊天输入框存在', composerCount > 0, `contenteditable × ${composerCount}`)
  check('输入框可编辑', await page.locator('[contenteditable="true"]').first().isEditable().catch(() => false))

  const openBtn = page.locator('[data-chem-draw]')
  check('输入框旁有「工作台」按钮', await openBtn.count() > 0)
  await clearDraft(page)

  /* ── 2. 打开工作台，三个页签 ───────────────────────────────────── */

  await openBtn.first().click()
  await page.waitForTimeout(2500)
  check('工作台浮层出现', await page.locator('[data-chem-panel]').count() > 0)
  check('打开后聊天输入框仍在（没顶掉聊天）', await page.locator('[contenteditable="true"]').count() > 0)
  for (const tab of ['draw', 'analyze', 'retro']) {
    check(`有「${tab}」页签`, await page.locator(`[data-chem-tab="${tab}"]`).count() > 0)
  }

  const frame = await findKetcher(page)
  check('Ketcher 画板就绪', !!frame)

  // 画一个乙醇 —— 后面所有数字都对着它验
  if (frame) await frame.evaluate(() => window.ketcher.setMolecule('CCO'))
  await page.waitForTimeout(1200)
  await page.screenshot({ path: path.join(SHOTS, 'wb-draw.png') })

  /* ── 3. 画板 → 插入对话，文本必须干净 ──────────────────────────── */

  await page.locator('[data-chem-fn="insert"]').click()
  await page.waitForTimeout(800)
  const draft = await draftOf(page)
  if (hasSession) {
    check('「插入到对话」写进输入框', draft.includes('CCO'), JSON.stringify(draft))
    // 这一条要**先要求草稿非空**：没有会话时 draft 是 "(没有当前会话)"，直接跑正则会"通过" ——
    // 那是假通过（踩过）。空草稿必须判失败。
    check('文本里不含内部路径提示',
      draft.trim().length > 0 && !draft.startsWith('(') && !/\[.*目录|dsh-mol-out|保存到/.test(draft),
      JSON.stringify(draft))
  } else {
    skip('「插入到对话」写进输入框', '当前环境没有 current 会话（干净 DSH_HOME 的已知限制）')
    skip('文本里不含内部路径提示', '同上；该断言在带会话的环境里已验证通过')
  }
  await clearDraft(page)

  /* ── 4. 分析页签：数字要是真的（本地 RDKit，不经模型） ──────────── */

  await page.locator('[data-chem-tab="analyze"]').click()
  await page.waitForTimeout(500)
  // 三个页签都常驻 DOM（只切 display），所以必须挑**可见**的那个，
  // 否则 .first() 会命中隐藏页签里的输入框，填不进去（踩过）
  const smilesInput = page.locator('[data-chem-panel] input[type="text"]:visible').first()
  await smilesInput.fill('CCO')
  await page.locator('[data-chem-fn="analyze"]').click()
  await page.waitForTimeout(2500)

  const panelText = async () => (await page.locator('[data-chem-panel]').innerText())
  let text = await panelText()
  check('分析页签给出分子式 C2H6O', text.includes('C2H6O'))
  check('分析页签给出分子量 46.069', text.includes('46.069'))
  check('分析页签给出 logP -0.0014', text.includes('-0.0014'))
  check('分析页签给出 TPSA 20.23', text.includes('20.23'))
  check('分析页签给出 QED', /QED/.test(text))
  const thumbCount = await page.locator('[data-chem-panel] img').count()
  check('分析页签显示当前结构缩略图', thumbCount > 0, `img × ${thumbCount}`)

  // 换阿司匹林，数字必须跟着变 —— 防"渲染的是写死的假数"
  await smilesInput.fill('CC(=O)Oc1ccccc1C(=O)O')
  await page.locator('[data-chem-fn="analyze"]').click()
  await page.waitForTimeout(2500)
  text = await panelText()
  check('换分子后数字跟着变（阿司匹林 C9H8O4 / 180.159）', text.includes('C9H8O4') && text.includes('180.159'))
  check('类药性规则有通过/不通过标记', /✓|✗/.test(text))
  check('给出 Murcko 骨架', text.includes('Murcko'))
  await page.screenshot({ path: path.join(SHOTS, 'wb-analyze.png') })

  // 坏结构要被当场说人话，而不是沉默
  await smilesInput.fill('C1CC')
  await page.locator('[data-chem-fn="check"]').click()
  await page.waitForTimeout(2000)
  text = await panelText()
  check('坏 SMILES 给出人话诊断', /环闭合|无法解析|配对/.test(text))

  /* ── 4.5 大分子入口（Ketcher 自带 Macromolecules 模式的适配） ──────
     只验"入口在、且不误判"：真正在大分子模式下画肽需要人操作单体库，
     无头自动化放不上单体（试过），所以那段靠人工/控制台确认。 */

  const bioKind = page.locator('[data-chem-select="bio-kind"]')
  check('分析页签有「大分子类型」下拉', await bioKind.count() > 0)
  check('分析页签有「按大分子解析」按钮', await page.locator('[data-chem-fn="bioseq"]').count() > 0)
  if (await bioKind.count()) {
    const opts = await bioKind.first().locator('option').evaluateAll(os => os.map(o => o.value))
    check('大分子类型含 6 种口径（auto/peptide/peptide3/rna/dna/helm）',
      ['auto', 'peptide', 'peptide3', 'rna', 'dna', 'helm'].every(v => opts.includes(v)),
      JSON.stringify(opts))
  }
  // 关键：纯字母的 SMILES（CCO）**不能**被当成序列 —— 必须显式点「按大分子解析」才走那条路。
  // 所以这里验的是：输入 CCO 时既有分析按钮仍然按小分子工作（上一步已验），
  // 而裸序列交给 auto 会被后端拒绝（有明确报错，不是静默算错）。
  await smilesInput.fill('ATGC')
  await page.locator('[data-chem-select="bio-kind"]').first().selectOption('auto')
  await page.locator('[data-chem-fn="bioseq"]').click()
  await page.waitForTimeout(2500)
  text = await panelText()
  check('裸序列 ATGC + auto 被拒绝并解释歧义（不静默猜类型）',
    /无法判断|歧义|显式指定/.test(text))
  await smilesInput.fill('GAVL')
  await page.locator('[data-chem-select="bio-kind"]').first().selectOption('peptide')
  await page.locator('[data-chem-fn="bioseq"]').click()
  await page.waitForTimeout(2500)
  text = await panelText()
  check('肽序列 GAVL 解析成功（C16H30N4O5 / 358.439）',
    text.includes('C16H30N4O5') && text.includes('358.439'))
  check('解析后把生成的 SMILES 填回输入框（既有分析管线可复用）',
    (await smilesInput.inputValue()).length > 5)

  // 子结构匹配：SMARTS 苯环应当命中阿司匹林
  await smilesInput.fill('CC(=O)Oc1ccccc1C(=O)O')
  await page.locator('[data-chem-fn="substructure"]').click()
  await page.waitForTimeout(2000)
  text = await panelText()
  check('子结构匹配苯环命中', text.includes('命中'))

  /* ── 5. 逆合成：没装好就必须说没装好 ───────────────────────────── */

  await page.locator('[data-chem-tab="retro"]').click()
  await page.waitForTimeout(400)
  const retroInput = page.locator('[data-chem-panel] input[type="text"]:visible').first()
  await retroInput.fill('CCOC(=O)c1ccccc1')
  await page.locator('[data-chem-fn="retro-run"]').click()
  await page.waitForTimeout(6000)
  text = await panelText()
  const claimsRoute = /路线\s*1/.test(text)
  check('逆合成没有编造路线', !claimsRoute)
  check('逆合成如实说明状态（未配置/失败都有提示）', /逆合成|后端/.test(text))
  await page.screenshot({ path: path.join(SHOTS, 'wb-retro.png') })

  /* ── 6. 关闭后聊天照旧 ─────────────────────────────────────────── */

  await page.locator('[data-chem-panel] button[aria-label="关闭工作台"]').click()
  await page.waitForTimeout(700)
  check('关闭工作台后浮层消失', await page.locator('[data-chem-panel]').count() === 0)
  check('关闭后聊天仍可编辑', await page.locator('[contenteditable="true"]').first().isEditable().catch(() => false))

  console.log(`\n页面错误：`, errors.slice(0, 4))
  const failed = results.filter(r => !r.ok)
  const total = results.length + skipped.length
  console.log(`\n通过 ${results.length - failed.length}/${results.length}`)
  if (skipped.length) console.log(`跳过 ${skipped.length} 条（环境不满足，见上方 ⊘）`)
  console.log(`截图： ${SHOTS}`)

  // 把本次的真实断言**总数**记下来（= 执行数 + 跳过数，与环境无关）。
  // 6 份 README 里的 `dsh-mol:ui-assertions` 标记由 tests/run_tests.py 拿它与这里比对，
  // 免得"加了断言忘了改文档"（这个项目已经因为数字过期被打回过一次）。
  try {
    fs.writeFileSync(path.join(__dirname, 'ui-assertions.json'),
      JSON.stringify({ total, ran: results.length, passed: results.length - failed.length,
                       skipped: skipped.length, at: new Date().toISOString() }, null, 2) + '\n')
    console.log(`断言总数已记录：tests/ui-assertions.json（${total}）`)
  } catch (error) {
    console.log(`（记录断言数失败：${error.message}）`)
  }
  await browser.close()
  process.exit(failed.length ? 1 : 0)
})()
