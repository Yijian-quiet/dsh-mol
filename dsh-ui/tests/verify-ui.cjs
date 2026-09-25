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

async function draftOf(page) {
  return page.evaluate(() => {
    const ctx = window.__DSH_CHEM_CTX__
    if (!ctx) return '(插件 ctx 未暴露)'
    const id = ctx.get('sessions').list.getSnapshot().current
    return ctx.get('conversation').input.shell(id).snapshot?.draft ?? ''
  })
}

async function clearDraft(page) {
  await page.evaluate(() => {
    const ctx = window.__DSH_CHEM_CTX__
    const id = ctx.get('sessions').list.getSnapshot().current
    ctx.get('conversation').input.shell(id).setDraft('')
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

  // 全新 browser context 会弹首次配置向导，它拦截所有点击 —— 先关掉，
  // 否则后面每条断言都会以"元素被遮挡"超时，且看不出原因。
  for (const name of [/Configure later/i, /稍后配置/, /以后再说/, /Skip/i]) {
    const btn = page.getByRole('button', { name }).first()
    if (await btn.count().catch(() => 0)) {
      await btn.click({ timeout: 5000 }).catch(() => {})
      await page.waitForTimeout(1200)
    }
  }
  await page.keyboard.press('Escape').catch(() => {})
  await page.waitForTimeout(600)

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
  check('「插入到对话」写进输入框', draft.includes('CCO'), JSON.stringify(draft))
  check('文本里不含内部路径提示', !/\[.*目录|dsh-mol-out|保存到/.test(draft), JSON.stringify(draft))
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
  console.log(`\n通过 ${results.length - failed.length}/${results.length}`)
  console.log(`截图： ${SHOTS}`)
  await browser.close()
  process.exit(failed.length ? 1 : 0)
})()
