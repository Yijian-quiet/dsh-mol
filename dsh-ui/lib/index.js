/**
 * chem-ui · 宿主半边
 *
 * 职责只有一个：**把 Ketcher 静态构建挂到 DSH 自己的源上**。
 *
 * 为什么必须同源：客户端面板用 `<iframe>` 嵌 Ketcher，之后要读
 * `iframe.contentWindow.ketcher.getSmiles()`。如果 Ketcher 跑在另一个端口，
 * 那就是**跨源**，同一个源策略会直接挡掉 —— 所以不能让用户另起一个静态服务，
 * 必须由插件在 3080 这个源上提供。
 *
 * 用到的服务：`ctx.webServer.register({ kind: 'prefix', path, handler })`
 * （WebRoute 契约见 @deepseek-ai/dsh-host-webserver）
 */

import { readFile, stat } from 'node:fs/promises'
import { extname, join, resolve, sep } from 'node:path'

export const name = 'chem-ui'

/** 需要 webServer 才能注册路由。 */
export const inject = ['webServer']

/** 挂载前缀：客户端 iframe 指向 `${KETCHER_PATH}/index.html`。 */
export const KETCHER_PATH = '/chem/ketcher'

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

/**
 * 注册 Ketcher 静态路由。
 * @param ctx - 宿主上下文（需已注入 webServer）。
 * @param config - 插件配置：`ketcherDir` 指向解压后的 Ketcher 构建目录。
 */
export function apply(ctx, config = {}) {
  const root = resolve(config.ketcherDir || process.env.CHEM_KETCHER_DIR || '')
  if (!config.ketcherDir && !process.env.CHEM_KETCHER_DIR) {
    ctx.logger?.warn?.('chem-ui: 未配置 ketcherDir，分子面板将无法加载画板')
    return
  }

  const handler = async (req, res) => {
    try {
      // 1) 解析出前缀之后的相对路径
      const url = new URL(req.url ?? '/', 'http://127.0.0.1')
      let rest = decodeURIComponent(url.pathname).slice(KETCHER_PATH.length)
      if (rest === '' || rest === '/') rest = '/index.html'

      // 2) 目录穿越防护：解析后必须仍在 root 之内
      const target = resolve(join(root, '.' + rest))
      if (target !== root && !target.startsWith(root + sep)) {
        res.writeHead(403)
        res.end('forbidden')
        return
      }

      // 3) 目录 → index.html
      let file = target
      const info = await stat(file).catch(() => null)
      if (!info) {
        res.writeHead(404)
        res.end('not found')
        return
      }
      if (info.isDirectory()) file = join(file, 'index.html')

      // 4) 送出
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
    () => ctx.webServer.register({ kind: 'prefix', path: KETCHER_PATH, handler }),
    'chem-ui: ketcher static route',
  )
}
