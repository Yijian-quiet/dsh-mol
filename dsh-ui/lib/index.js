/**
 * chem-ui · 宿主半边
 *
 * 三件事：
 *   1. `/chem/ketcher/*`  —— 把 Ketcher 静态构建挂在 DSH 自己的源上
 *   2. `/chem/tool`       —— 把 JSON 转发给 `python3 -m chemcore.cli`，**同步拿回 RDKit 结果**
 *   3. `/chem/retro`      —— 转发给逆合成后端（桥接脚本，协议见 dsh-ui/retro/）
 *
 * 为什么 1 必须同源：客户端面板用 `<iframe>` 嵌 Ketcher，之后要读
 * `iframe.contentWindow.ketcher.getSmiles()`。跨源会被同源策略直接挡掉 ——
 * 所以不能让用户另起一个静态服务，必须由插件在 DSH 这个源上提供。
 *
 * 为什么 2 要有：工作台的价值就在"点一下马上看到数"。如果分子性质也要绕一圈
 * 去问模型，那它只是个聊天提示词的发射器，不是工作台。宿主半边进程里直接
 * fork 一个 python 就够了（实测冷启动 ~0.2s，RDKit 导入比想象中快）。
 *
 * 路由前缀刻意**避开 `/api`** —— 那一段是 DSH 自己的 RPC 与浏览器信任栅栏的地盘。
 *
 * WebRoute 契约见 @deepseek-ai/dsh-host-webserver
 */

import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { homedir } from 'node:os'
import { readFile, stat } from 'node:fs/promises'
import { dirname, extname, join, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

export const name = 'chem-ui'

/** 需要 webServer 才能注册路由。 */
export const inject = ['webServer']

/** 挂载前缀：客户端 iframe 指向 `${KETCHER_PATH}/index.html`。 */
export const KETCHER_PATH = '/chem/ketcher'
export const TOOL_PATH = '/chem/tool'
export const RETRO_PATH = '/chem/retro'
export const STATUS_PATH = '/chem/status'

/** 够用就行的 MIME 表（Ketcher 构建里只有这些类型）。 */
const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.txt': 'text/plain; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.ttf': 'font/ttf',
  '.wasm': 'application/wasm',
}

/** 本包目录（lib/ 的上一层），用来找同仓的 src/ 和 retro/。 */
const PKG_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..')

/**
 * Ketcher 构建目录：配置 → 环境变量 → 几个约定位置。
 *
 * 为什么要自动找：Ketcher 的独立构建有 116 MB，不能塞进 git；用户被要求
 * "自己下载、自己填绝对路径"是推广时最容易掉链子的那一步。所以
 * `node scripts/fetch-ketcher.mjs` 默认就解到 `<包目录>/ketcher`，
 * 这里按同样的约定找回去 —— 大多数情况下用户什么都不用配。
 */
function resolveKetcherDir(configured) {
  const candidates = [
    configured,
    process.env.CHEM_KETCHER_DIR,
    join(PKG_DIR, 'ketcher'),                       // fetch-ketcher.mjs 的默认落点
    resolve(PKG_DIR, '..', 'ketcher'),              // 仓库根（历史落点）
    join(homedir(), '.cache', 'dsh-chem-ui', 'ketcher'),
    join(homedir(), '.dsh', 'ketcher'),
  ].filter(Boolean)
  for (const dir of candidates) {
    if (existsSync(join(dir, 'index.html'))) return resolve(dir)
  }
  return ''
}
/** 仓库根的 src/：开发态直接跑源码；发布态 chemcore 走 pip 安装，这个路径不存在。 */
const REPO_SRC = resolve(PKG_DIR, '..', 'src')
const RETRO_DIR = join(PKG_DIR, 'retro')

/** 单次请求体上限：工作台会贴 SMILES 清单，1 MB 够放几万条，也防了内存炸弹。 */
const MAX_BODY = 1024 * 1024
/** 单次工具调用超时。RDKit 本地算，20 秒已经是异常值。 */
const TOOL_TIMEOUT_MS = 20_000

function sendJson(res, status, payload) {
  const body = Buffer.from(JSON.stringify(payload), 'utf8')
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': String(body.byteLength),
    // 结果必须现算现看，缓存住会让用户以为按钮坏了
    'cache-control': 'no-store',
  })
  res.end(body)
}

function readBody(req) {
  return new Promise((resolvePromise, rejectPromise) => {
    const chunks = []
    let size = 0
    req.on('data', (chunk) => {
      size += chunk.length
      if (size > MAX_BODY) {
        rejectPromise(Object.assign(new Error('请求体过大'), { code: 'body_too_large' }))
        req.destroy()
        return
      }
      chunks.push(chunk)
    })
    req.on('end', () => resolvePromise(Buffer.concat(chunks).toString('utf8')))
    req.on('error', rejectPromise)
  })
}

async function readJson(req) {
  const raw = await readBody(req)
  if (!raw.trim()) return {}
  try {
    const parsed = JSON.parse(raw)
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error('请求体必须是 JSON 对象')
    }
    return parsed
  } catch (error) {
    throw Object.assign(new Error(`请求体不是合法 JSON：${error.message}`), { code: 'invalid_json' })
  }
}

/**
 * 跑一个"喂 JSON 进 stdin、读 JSON 出 stdout"的子进程。
 *
 * stdout 一定只有那一行 JSON（子进程的日志约定走 stderr），所以这里不做解析容错，
 * 解析失败就是真故障，照实上报 —— 静默吞掉会让人对着空白面板猜半天。
 */
function runJsonProcess({ command, args, payload, env, cwd, timeoutMs, label }) {
  return new Promise((resolvePromise) => {
    let child
    try {
      child = spawn(command, args, {
        cwd,
        env: { ...process.env, ...env },
        stdio: ['pipe', 'pipe', 'pipe'],
      })
    } catch (error) {
      resolvePromise({
        ok: false, code: 'spawn_failed',
        message: `${label} 启动失败：${error?.message ?? error}`,
      })
      return
    }

    let stdout = ''
    let stderr = ''
    let settled = false
    const finish = (value) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      resolvePromise(value)
    }

    const timer = setTimeout(() => {
      child.kill('SIGKILL')
      finish({
        ok: false, code: 'timeout',
        message: `${label} 超过 ${Math.round(timeoutMs / 1000)} 秒仍未返回，已中止`,
      })
    }, timeoutMs)

    child.stdout.on('data', (chunk) => { stdout += chunk })
    child.stderr.on('data', (chunk) => { stderr += chunk })
    child.on('error', (error) => {
      finish({
        ok: false, code: 'spawn_failed',
        message: `${label} 启动失败：${error?.message ?? error}`,
      })
    })
    child.on('close', (code, signal) => {
      const text = stdout.trim()
      if (!text) {
        // 被信号杀死（尤其 SIGKILL）而没有任何输出，最常见的成因就是**内存不足**：
        // Retro* 光读 2300 万条 building blocks 就要几个 GB，窄内存机器上会被
        // 内核直接 OOM-kill —— 这时子进程连写一行错误的机会都没有。
        const oom = signal === 'SIGKILL'
        finish({
          ok: false,
          code: oom ? 'killed_likely_oom' : 'no_output',
          message: oom
            ? `${label} 被系统杀掉了（SIGKILL），而且没来得及输出任何东西 —— 通常意味着内存不够。` +
              '这个后端在加载模型数据时需要数 GB 空闲内存；可以先看看 free -g 还有多少。'
            : `${label} 没有输出（退出码 ${code}）`,
          signal: signal ?? null,
          stderr: stderr.trim().slice(0, 2000),
        })
        return
      }
      try {
        finish(JSON.parse(text))
      } catch (error) {
        finish({
          ok: false, code: 'bad_output',
          message: `${label} 的输出不是合法 JSON：${error.message}`,
          stdout: text.slice(0, 2000),
          stderr: stderr.trim().slice(0, 2000),
        })
      }
    })

    child.stdin.on('error', () => { /* 子进程早退时 EPIPE 属于预期，交由 close 分支报告 */ })
    child.stdin.end(JSON.stringify(payload ?? {}))
  })
}

/**
 * 注册全部路由。
 * @param ctx - 宿主上下文（需已注入 webServer）。
 * @param config - 支持 `ketcherDir` / `python` / `retroCommand` / `retroHome` / `retroTimeoutMs`。
 */
export function apply(ctx, config = {}) {
  const python = config.python || process.env.MOL_PYTHON || 'python3'
  const ketcherDir = resolveKetcherDir(config.ketcherDir)
  const retroCommand = config.retroCommand || process.env.MOL_RETRO_COMMAND || ''
  const retroHome = config.retroHome || process.env.RETRO_STAR_HOME || ''
  const retroTimeoutMs = Number(config.retroTimeoutMs || 600_000)

  // chemcore 从哪来：开发态用仓库里的 src/，发布态用 pip 装好的包。
  // 两个都存在时优先源码 —— 改了立刻生效，不用重装。
  const pythonEnv = {}
  if (existsSync(REPO_SRC)) {
    pythonEnv.PYTHONPATH = [REPO_SRC, process.env.PYTHONPATH].filter(Boolean).join(':')
  }

  /** 工具调用：客户端点按钮 → 这里 → chemcore.cli → 结果回浏览器。 */
  const handleTool = async (req, res) => {
    let request
    try {
      request = await readJson(req)
    } catch (error) {
      sendJson(res, 400, { ok: false, code: error.code ?? 'invalid_request', message: error.message })
      return
    }
    const result = await runJsonProcess({
      command: python,
      args: ['-m', 'chemcore.cli'],
      payload: request,
      env: pythonEnv,
      cwd: PKG_DIR,
      timeoutMs: TOOL_TIMEOUT_MS,
      label: `chemcore ${request.op ?? '?'}`,
    })
    // 领域错误（SMILES 画错了之类）也是 200：它是**业务答案**，不是 HTTP 故障。
    sendJson(res, 200, result)
  }

  /**
   * 逆合成：交给桥接脚本。没配后端时桥接脚本会回一个结构化的
   * `retro_not_configured`（含缺什么、怎么补），前端照着显示即可 —— 不许编结果。
   */
  const handleRetro = async (req, res) => {
    let request
    try {
      request = await readJson(req)
    } catch (error) {
      sendJson(res, 400, { ok: false, code: error.code ?? 'invalid_request', message: error.message })
      return
    }
    const bridge = join(RETRO_DIR, 'retro_star_bridge.py')
    // 配了 retroCommand 就用它（可以是任意后端，只要守着同一套 stdin/stdout 协议）；
    // 没配就退回内置的 Retro* 桥接脚本。
    const parts = retroCommand.split(/\s+/).filter(Boolean)
    const command = retroCommand ? parts[0] : python
    const args = retroCommand ? parts.slice(1) : [bridge]
    if (!retroCommand && !existsSync(bridge)) {
      sendJson(res, 200, {
        ok: false, code: 'retro_not_configured', backend: 'retro_star',
        message: '逆合成桥接脚本不存在，插件安装可能不完整',
      })
      return
    }
    const result = await runJsonProcess({
      command,
      args,
      payload: {
        ...request,
        ...(retroHome ? { retro_home: request.retro_home || retroHome } : {}),
      },
      // PYTHONHASHSEED 固定：Retro* 的 molstar 里有 list(set(...))，
      // 哈希随机化会让同一分子每次给出不同路线（桥接脚本的建议）
      env: { ...pythonEnv, PYTHONHASHSEED: '0' },
      cwd: PKG_DIR,
      timeoutMs: retroTimeoutMs,
      label: '逆合成后端',
    })
    sendJson(res, 200, result)
  }

  /** 能力自述：前端据此决定按钮是"能点"还是"待配置"。 */
  const handleStatus = async (req, res) => {
    const probe = await runJsonProcess({
      command: python,
      args: ['-m', 'chemcore.cli'],
      payload: { op: 'properties', smiles: 'CCO' },
      env: pythonEnv,
      cwd: PKG_DIR,
      timeoutMs: TOOL_TIMEOUT_MS,
      label: 'chemcore 自检',
    })
    const bridge = join(RETRO_DIR, 'retro_star_bridge.py')
    sendJson(res, 200, {
      ok: true,
      rdkit: { ready: probe.ok === true, detail: probe.ok ? undefined : probe.message },
      retro: {
        backend: retroCommand ? 'custom' : 'retro_star',
        configured: Boolean(retroCommand),
        bridge: existsSync(bridge),
        home: retroHome || null,
        // 前端不拿这个路径做展示，只用来判断"有没有指定过"
        note: 'retroCommand 未配置时走内置 retro_star 桥接脚本',
      },
      ketcher: { dir: ketcherDir || null, mounted: Boolean(ketcherDir) },
    })
  }

  /** Ketcher 静态文件。 */
  const handleKetcher = async (req, res) => {
    const root = resolve(ketcherDir)
    try {
      const url = new URL(req.url ?? '/', 'http://127.0.0.1')
      let rest = decodeURIComponent(url.pathname).slice(KETCHER_PATH.length)
      if (rest === '' || rest === '/') rest = '/index.html'

      // 目录穿越防护：解析后必须仍在 root 之内
      const target = resolve(join(root, '.' + rest))
      if (target !== root && !target.startsWith(root + sep)) {
        res.writeHead(403)
        res.end('forbidden')
        return
      }

      let file = target
      const info = await stat(file).catch(() => null)
      if (!info) {
        res.writeHead(404)
        res.end('not found')
        return
      }
      if (info.isDirectory()) file = join(file, 'index.html')

      const body = await readFile(file)
      res.writeHead(200, {
        'content-type': MIME[extname(file).toLowerCase()] ?? 'application/octet-stream',
        'content-length': String(body.byteLength),
        // Ketcher 构建带内容哈希文件名；但 index.html 必须不缓存，否则升级后拿旧壳
        'cache-control': file.endsWith('index.html') ? 'no-cache' : 'public, max-age=3600',
      })
      res.end(body)
    } catch (error) {
      res.writeHead(500)
      res.end(`chem-ui ketcher route error: ${error?.message ?? error}`)
    }
  }

  ctx.effect(
    () => ctx.webServer.register({
      kind: 'prefix', path: KETCHER_PATH,
      handler: async (req, res) => {
        if (!ketcherDir) {
          res.writeHead(503, { 'content-type': 'text/plain; charset=utf-8' })
          res.end('chem-ui: 未配置 ketcherDir')
          return
        }
        await handleKetcher(req, res)
      },
    }),
    'chem-ui: ketcher static route',
  )

  if (!ketcherDir) {
    ctx.logger?.warn?.(
      'chem-ui: 找不到 Ketcher 构建，工作台的画板页签无法加载。' +
      `请运行： node ${join(PKG_DIR, 'scripts', 'fetch-ketcher.mjs')}   （约 35 MB）`,
    )
  }

  ctx.effect(
    () => ctx.webServer.register({ kind: 'prefix', path: TOOL_PATH, handler: handleTool }),
    'chem-ui: local chemcore tool route',
  )
  ctx.effect(
    () => ctx.webServer.register({ kind: 'prefix', path: RETRO_PATH, handler: handleRetro }),
    'chem-ui: retrosynthesis route',
  )
  ctx.effect(
    () => ctx.webServer.register({ kind: 'prefix', path: STATUS_PATH, handler: handleStatus }),
    'chem-ui: capability status route',
  )
}
