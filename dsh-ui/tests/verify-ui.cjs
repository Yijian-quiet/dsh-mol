/**
 * chem-ui 验收（Playwright，无头）—— 2026-09-25 改版后
 *
 * 核心诉求（Mr.自由基 的反馈）：**聊天保持可用**，绘制按钮在输入框旁边，
 * 画板是可拖动的浮层，用化学功能按钮布置任务。
 */
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const BASE = process.env.CHEM_BASE || 'http://127.0.0.1:3080'
const TOKEN = process.env.CHEM_TOKEN || ''
const SHOTS = process.env.CHEM_SHOTS || '/tmp/chem-ui-shots'
const MOL = 'CCO'

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

;(async () => {
  fs.mkdirSync(SHOTS, { recursive: true })
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  const errors = []
  page.on('pageerror', e => errors.push(String(e)))

  await page.goto(TOKEN ? `${BASE}/?token=${TOKEN}` : BASE, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(8000)
  await page.screenshot({ path: path.join(SHOTS, 'n1-chat.png') })

  // 实测：DSH 的 composer 是 contenteditable，不是 textarea
  const composerCount = await page.locator('[contenteditable="true"]').count()
  check('聊天输入框存在（聊天功能保留）', composerCount > 0, `contenteditable × ${composerCount}`)
  const composer = page.locator('[contenteditable="true"]').first()
  check('输入框可编辑', await composer.isEditable().catch(() => false))

  const drawBtn = page.locator('[data-chem-draw]')
  const drawCount = await drawBtn.count()
  check('输入框旁出现「绘制分子」按钮', drawCount > 0, `找到 ${drawCount} 个`)
  if (!drawCount) {
    console.log('  页面错误：', errors.slice(0, 4))
    await browser.close(); process.exit(1)
  }

  // 不清空 composer：contenteditable 的 fill 语义不同，且我们的插入本就是追加

  await drawBtn.first().click()
  await page.waitForTimeout(2500)
  const panel = page.locator('[data-chem-panel]')
  check('点击后出现浮层画板', await panel.count() > 0)
  check('浮层出现后聊天输入框仍在（没顶掉聊天）', await page.locator('[contenteditable="true"]').count() > 0)
  await page.screenshot({ path: path.join(SHOTS, 'n2-panel.png') })

  let frame = null
  for (let i = 0; i < 60 && !frame; i++) {
    for (const f of page.frames()) {
      if (f === page.mainFrame()) continue
      try { if (await f.evaluate(() => typeof window.ketcher !== 'undefined')) { frame = f; break } } catch {}
    }
    if (!frame) await page.waitForTimeout(1000)
  }
  check('Ketcher 画板就绪', !!frame)

  if (await panel.count()) {
    const before = await panel.boundingBox()
    if (before) {
      await page.mouse.move(before.x + 60, before.y + 12)
      await page.mouse.down()
      await page.mouse.move(before.x + 60 - 140, before.y + 12 - 90, { steps: 10 })
      await page.mouse.up()
      await page.waitForTimeout(600)
      const after = await panel.boundingBox()
      const dx = after ? Math.round(after.x - before.x) : 0
      const dy = after ? Math.round(after.y - before.y) : 0
      check('画板可拖动', Math.abs(dx) > 40 || Math.abs(dy) > 30, `Δx=${dx} Δy=${dy}`)
    }
  }

  if (frame) {
    await frame.evaluate(async () => { await window.ketcher.setMolecule('CCO') })
    await page.waitForTimeout(1200)
    await page.getByRole('button', { name: '插入结构' }).click()
    await page.waitForTimeout(1200)
    const d1 = await draftOf(page)
    check('「插入结构」把 SMILES 写进输入框', d1.includes(MOL), JSON.stringify(d1.slice(0, 60)))

    await page.getByRole('button', { name: '结构性质' }).click()
    await page.waitForTimeout(1200)
    const d2 = await draftOf(page)
    check('「结构性质」写入带结构的任务指令', d2.includes(MOL) && d2.includes('性质'), JSON.stringify(d2.slice(0, 90)))
  }
  await page.screenshot({ path: path.join(SHOTS, 'n3-functions.png') })

  await page.locator('[data-chem-panel] button[aria-label="关闭画板"]').click()
  await page.waitForTimeout(800)
  check('关闭画板后浮层消失', await page.locator('[data-chem-panel]').count() === 0)
  check('关闭后聊天仍可编辑（核心诉求）', await page.locator('[contenteditable="true"]').first().isEditable().catch(() => false))

  const bad = results.filter(r => !r.ok)
  console.log(`\n通过 ${results.length - bad.length}/${results.length}`)
  console.log('截图：', SHOTS)
  if (errors.length) console.log('页面错误（前 3）：', errors.slice(0, 3))
  await browser.close()
  process.exit(bad.length ? 1 : 0)
})().catch(e => { console.error('验收脚本异常：', e); process.exit(2) })
