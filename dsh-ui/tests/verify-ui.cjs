/**
 * chem-ui 阶段 0 spike 验收（Playwright，无头）
 *
 * 验收目标：
 *   ① 左侧栏出现「化学工作台」图标
 *   ② 点击后主区域出现面板，且 Ketcher iframe 真的就绪（frame 内 window.ketcher 存在）
 *   ③ 往画板塞一个分子，点「读取结构」，界面显示出 SMILES
 * 全程截图存 /tmp/chem-ui-shots/
 */
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const BASE = process.env.CHEM_BASE || 'http://127.0.0.1:3081'
const TOKEN = process.env.CHEM_TOKEN || ''
const SHOTS = '/tmp/chem-ui-shots'
const PANEL_LABEL = '化学工作台'

const results = []
function check(name, ok, detail = '') {
  results.push({ name, ok, detail })
  console.log(`${ok ? '  ✓' : '  ✗'} ${name}${detail ? '  — ' + detail : ''}`)
}

;(async () => {
  fs.mkdirSync(SHOTS, { recursive: true })
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  const errors = []
  page.on('pageerror', e => errors.push(String(e)))
  page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()) })

  const url = TOKEN ? `${BASE}/?token=${TOKEN}` : BASE
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(8000)               // 壳子 + 30MB 画板都要时间
  await page.screenshot({ path: path.join(SHOTS, '01-app.png') })

  // ① 左侧栏图标
  const icon = page.locator(`button[aria-label="${PANEL_LABEL}"]`)
  const iconCount = await icon.count()
  check('左侧栏出现「化学工作台」图标', iconCount > 0, `找到 ${iconCount} 个`)
  if (iconCount === 0) {
    const labels = await page.locator('button[aria-label]').evaluateAll(
      els => els.map(e => e.getAttribute('aria-label')).slice(0, 30))
    console.log('    侧栏可见的 aria-label：', JSON.stringify(labels))
    console.log('    页面错误：', errors.slice(0, 5))
    await browser.close()
    process.exit(1)
  }
  await page.screenshot({ path: path.join(SHOTS, '02-sidebar.png') })

  // ② 点击 → 主面板
  await icon.first().click()
  await page.waitForTimeout(3000)
  const iframe = page.locator('iframe[title="Ketcher"]')
  const iframeCount = await iframe.count()
  check('主区域出现 Ketcher iframe', iframeCount > 0, `找到 ${iframeCount} 个`)
  await page.screenshot({ path: path.join(SHOTS, '03-panel.png') })

  // ③ 画板就绪（frame 内 window.ketcher）
  let ready = false
  for (let i = 0; i < 60; i++) {
    for (const f of page.frames()) {
      if (f === page.mainFrame()) continue
      try {
        if (await f.evaluate(() => typeof window.ketcher !== 'undefined')) { ready = true; break }
      } catch { /* 跨源或未就绪 */ }
    }
    if (ready) break
    await page.waitForTimeout(1000)
  }
  check('Ketcher 画板就绪（frame 内 window.ketcher 可用）', ready)
  await page.screenshot({ path: path.join(SHOTS, '04-ketcher.png') })

  // ④ 塞一个分子 → 读取结构
  // 注意：不能用 frames().find(async ...) —— 异步谓词返回 Promise，恒为真，会选错 frame
  let ketcherFrame = null
  for (const f of page.frames()) {
    if (f === page.mainFrame()) continue
    try {
      if (await f.evaluate(() => typeof window.ketcher !== 'undefined')) { ketcherFrame = f; break }
    } catch { /* 忽略 */ }
  }
  if (ready && ketcherFrame) {
    const frame = ketcherFrame
    try {
      await frame.evaluate(async () => { await window.ketcher.setMolecule('CCO') })
      await page.waitForTimeout(1500)
      await page.getByRole('button', { name: '读取结构' }).click()
      await page.waitForTimeout(1500)
      const shown = await page.locator('code').first().innerText()
      check('读出 SMILES 并显示在面板上', /CCO/.test(shown), `显示：${shown}`)
    } catch (e) {
      check('读出 SMILES 并显示在面板上', false, String(e).slice(0, 120))
    }
  }
  await page.screenshot({ path: path.join(SHOTS, '05-read.png'), fullPage: false })

  // ⑤ 插入输入框（smiles 为空时按钮是 disabled，先确认已读到结构）
  try {
    const insertBtn = page.getByRole('button', { name: '插入输入框' })
    for (let i = 0; i < 20 && await insertBtn.isDisabled(); i++) await page.waitForTimeout(500)
    check('「插入输入框」按钮已启用（说明读到了结构）', !(await insertBtn.isDisabled()))
    await insertBtn.click()
    await page.waitForTimeout(1500)
    const status = await page.locator('span').filter({ hasText: /已插入|failed|未找到/ }).first().innerText().catch(() => '')
    check('插入输入框', /已插入/.test(status), `状态：${status}`)
  } catch (e) {
    check('插入输入框', false, String(e).slice(0, 120))
  }
  await page.screenshot({ path: path.join(SHOTS, '06-insert.png') })

  // ⑥ 强验证：草稿真的写进了会话状态（composer 渲染的就是它）
  const draft = await page.evaluate(() => {
    const ctx = window.__DSH_CHEM_CTX__
    const id = ctx.get('sessions').list.getSnapshot().current
    return ctx.get('conversation').input.shell(id).snapshot.draft
  })
  check('会话草稿里确实出现了该 SMILES', /CCO/.test(draft || ''), `draft=${JSON.stringify(draft)}`)

  const rejected = results.filter(r => !r.ok)
  console.log(`\n通过 ${results.length - rejected.length}/${results.length}`)
  console.log('截图：', SHOTS)
  if (errors.length) console.log('页面错误（前 5）：', errors.slice(0, 5))
  await browser.close()
  process.exit(rejected.length ? 1 : 0)
})().catch(e => { console.error('验收脚本异常：', e); process.exit(2) })
