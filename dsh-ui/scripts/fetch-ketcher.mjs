#!/usr/bin/env node
/**
 * 下载 Ketcher 的**独立构建**（可直接当静态站点托管的那个 zip）。
 *
 * 为什么不从 npm 装：`ketcher-standalone` 的 npm 包是**库**（dist/*.js），
 * 里面没有 index.html。工作台需要一个能直接塞进 iframe 的成品应用，
 * 那个只有 GitHub Release 的 `ketcher-standalone-<ver>.zip` 里有。
 *
 * 用法：
 *   node scripts/fetch-ketcher.mjs                 # 默认 3.18.0，解到 <包目录>/ketcher
 *   node scripts/fetch-ketcher.mjs --out /tmp/k    # 指定目录
 *   node scripts/fetch-ketcher.mjs --version 3.19.0-rc.3
 *   node scripts/fetch-ketcher.mjs --force         # 已有也重下
 *   node scripts/fetch-ketcher.mjs --from ~/ketcher-standalone-3.18.0.zip
 *                                                  # 用本地 zip（离线/内网机器）
 *
 * 解压完会打印该填进 cordis.patch.yml 的 ketcherDir。
 */

import { spawnSync } from 'node:child_process'
import { createWriteStream, existsSync, mkdirSync, readdirSync, renameSync, rmSync, statSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { pipeline } from 'node:stream/promises'
import { Readable } from 'node:stream'

const PKG_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..')

function parseArgs(argv) {
  const opts = { version: process.env.KETCHER_VERSION || '3.18.0', out: '', force: false, from: '' }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a === '--version') opts.version = argv[++i]
    else if (a === '--out') opts.out = argv[++i]
    else if (a === '--force') opts.force = true
    else if (a === '--from') opts.from = resolve(argv[++i])
    else if (a === '-h' || a === '--help') {
      console.log('用法: node scripts/fetch-ketcher.mjs [--version 3.18.0] [--out DIR] [--force] [--from FILE.zip]')
      process.exit(0)
    }
  }
  opts.out = resolve(opts.out || join(PKG_DIR, 'ketcher'))
  return opts
}

/** zip 里顶层就是一个目录（ketcher-standalone/）；把它里面的东西搬到 out。 */
function flattenInto(dir, out) {
  const entries = readdirSync(dir).filter((n) => !n.startsWith('__MACOSX'))
  const hasIndex = existsSync(join(dir, 'index.html'))
  if (hasIndex) return dir
  // 只包了一层目录 → 下钻
  for (const name of entries) {
    const sub = join(dir, name)
    if (statSync(sub).isDirectory() && existsSync(join(sub, 'index.html'))) {
      for (const child of readdirSync(sub)) {
        renameSync(join(sub, child), join(out, child))
      }
      return out
    }
  }
  return dir
}

function unzip(zipPath, dest) {
  // 优先用系统的 unzip；没有就退到 python3 的 zipfile（两个都试，别让用户卡在这）
  const attempts = [
    ['unzip', ['-q', '-o', zipPath, '-d', dest]],
    ['python3', ['-m', 'zipfile', '-e', zipPath, dest]],
  ]
  const errors = []
  for (const [cmd, args] of attempts) {
    const r = spawnSync(cmd, args, { stdio: 'inherit' })
    if (r.error) { errors.push(`${cmd}: ${r.error.message}`); continue }
    if (r.status === 0) return
    errors.push(`${cmd}: 退出码 ${r.status}`)
  }
  throw new Error(`解压失败（试过 unzip 与 python3 -m zipfile）：\n  ${errors.join('\n  ')}`)
}

async function download(url, dest) {
  const response = await fetch(url, { redirect: 'follow' })
  if (!response.ok) throw new Error(`下载失败：HTTP ${response.status} ${url}`)
  const total = Number(response.headers.get('content-length') || 0)
  let seen = 0
  let lastPct = -1
  const body = Readable.fromWeb(response.body)
  body.on('data', (chunk) => {
    seen += chunk.length
    if (!total) return
    const pct = Math.floor((seen / total) * 100)
    if (pct >= lastPct + 10) { lastPct = pct; process.stderr.write(`  已下载 ${pct}%\n`) }
  })
  await pipeline(body, createWriteStream(dest))
  return seen
}

async function main() {
  const opts = parseArgs(process.argv.slice(2))
  const marker = join(opts.out, 'index.html')

  if (existsSync(marker) && !opts.force) {
    console.log(`✅ Ketcher 已经在了，不重复下载：${opts.out}`)
    console.log(`   （要重下加 --force）`)
    printConfig(opts.out)
    return
  }

  // 本地 zip 优先（内网/离线机器，以及"我已经下过了"的情况）
  let zipPath = opts.from
  let tmp = ''
  if (zipPath) {
    if (!existsSync(zipPath)) {
      console.error(`❌ --from 指定的文件不存在：${zipPath}`)
      process.exit(1)
    }
    console.log(`📦 用本地 zip：${zipPath}`)
  } else {
    const url = `https://github.com/epam/ketcher/releases/download/v${opts.version}/ketcher-standalone-${opts.version}.zip`
    console.log(`↓ Ketcher ${opts.version}（约 35 MB，来自 GitHub Release）`)
    console.log(`  ${url}`)
    console.log(`  （慢的话可以先手动下好，再用 --from <zip>）`)
    tmp = join(PKG_DIR, `.ketcher-${opts.version}.zip`)
    zipPath = tmp
  }

  try {
    if (tmp) {
      const bytes = await download(url, tmp)
      console.log(`  下载完成：${(bytes / 1024 / 1024).toFixed(1)} MB`)
    }
    console.log(`  解压到 ${opts.out} …`)
    rmSync(opts.out, { recursive: true, force: true })
    mkdirSync(opts.out, { recursive: true })
    unzip(zipPath, opts.out)
    flattenInto(opts.out, opts.out)
  } finally {
    if (tmp) rmSync(tmp, { force: true })
  }

  if (!existsSync(marker)) {
    console.error(`\n❌ 解压完了但没找到 index.html，目录内容可能变了：${opts.out}`)
    console.error(`   请手动确认，或换个版本：--version <ver>`)
    process.exit(1)
  }
  console.log(`\n✅ 完成：${opts.out}`)
  printConfig(opts.out)
}

function printConfig(out) {
  console.log(`
   把它填进 profile 的 patch（或用环境变量 CHEM_KETCHER_DIR）：

     - id: chem-ui
       name: 'dsh-chem-ui'
       config:
         ketcherDir: ${out}
`)
}

main().catch((error) => {
  console.error(`\n❌ ${error.message}`)
  process.exit(1)
})
