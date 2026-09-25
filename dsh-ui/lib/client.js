/**
 * chem-ui · 客户端半边（浏览器 bundle）
 *
 * 这个文件是**手写的闭包工厂产物**，格式与官方 `tsdown.client.ts` 预设一致：
 *   window.__ModuleLoader__.load({ id, factory: (require) => module.exports })
 * 外部依赖（react 等）通过注入的 `require` 从 loader 模块表解析，没有 globals、没有 import map。
 *
 * 注册两处（id 必须一致，这是"左侧栏图标 ↔ 主面板"的对应关系）：
 *   ① main（keyed slot，key = PANEL_ID）      → 主区域里的化学工作台视图
 *   ② sidebar.panellist（list，id = PANEL_ID） → 左侧栏图标；按钮/点击由 shell 负责
 */

window.__ModuleLoader__.load({
  id: 'dsh-chem-ui',
  factory: (require) => {
    const React = require('react')
    const h = React.createElement

    /** 面板 ID：主面板的 key 与左侧栏图标的 id 必须是同一个值。 */
    const PANEL_ID = 'chem-workbench'
    /** Ketcher 的挂载前缀由宿主半边提供（同源），见 lib/index.js。 */
    const KETCHER_URL = '/chem/ketcher/index.html'

    /* ------------------------------------------------------------------ */
    /* 把 SMILES 送进输入框                                                */
    /* ------------------------------------------------------------------ */

    /** React 受控组件必须走原生 setter + input 事件，直接改 .value 不生效。 */
    function setNativeValue(el, value) {
      const proto = el instanceof HTMLTextAreaElement
        ? HTMLTextAreaElement.prototype
        : HTMLInputElement.prototype
      const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set
      if (setter) setter.call(el, value)
      else el.value = value
      el.dispatchEvent(new Event('input', { bubbles: true }))
    }

    /**
     * 把文本放进 composer（追加，不覆盖用户已输入的内容）。
     *
     * 为什么走服务而不是 DOM：**面板占用主区域时 composer 根本没渲染**（实测 textarea 数为 0），
     * 所以 DOM 路线在这个布局下必然失败。正确做法是写会话的草稿状态：
     *   sessions.list.getSnapshot().current  → 当前会话 id（DSH 内部同样这么取）
     *   conversation.input.shell(id).setDraft(text)
     * @returns {string} 实际走通的路径描述（用于界面反馈与排错）
     */
    function insertIntoComposer(text) {
      const ctx = window.__DSH_CHEM_CTX__
      if (!ctx || typeof ctx.get !== 'function') return 'failed: 客户端 ctx 不可用'

      let sessionId
      try {
        sessionId = ctx.get('sessions')?.list?.getSnapshot?.().current
      } catch (error) {
        return `failed: 取当前会话失败（${error?.message ?? error}）`
      }
      if (!sessionId) return 'failed: 当前没有打开的会话'

      let shell
      try {
        shell = ctx.get('conversation')?.input?.shell?.(sessionId)
      } catch (error) {
        return `failed: input.shell 失败（${error?.message ?? error}）`
      }
      if (!shell || typeof shell.setDraft !== 'function') return 'failed: input.shell 无 setDraft'

      try {
        const existing = shell.snapshot?.draft ?? ''
        const next = existing.trim() ? `${existing.replace(/\s*$/, '')} ${text}` : text
        shell.setDraft(next)
        return `service:input.shell → 会话 ${String(sessionId).slice(0, 8)}…`
      } catch (error) {
        return `failed: setDraft 抛错（${error?.message ?? error}）`
      }
    }

    /* ------------------------------------------------------------------ */
    /* 主面板：Ketcher + 读结构                                            */
    /* ------------------------------------------------------------------ */

    function ChemWorkbench() {
      const frameRef = React.useRef(null)
      const [smiles, setSmiles] = React.useState('')
      const [status, setStatus] = React.useState('画板加载中…')

      const onFrameLoad = React.useCallback(() => {
        const frame = frameRef.current
        let tries = 0
        const timer = setInterval(() => {
          tries += 1
          const ketcher = frame?.contentWindow?.ketcher
          if (ketcher) {
            clearInterval(timer)
            setStatus('画板就绪')
          } else if (tries > 60) {
            clearInterval(timer)
            setStatus('画板未能就绪（60s）')
          }
        }, 500)
      }, [])

      const readSmiles = React.useCallback(async () => {
        const ketcher = frameRef.current?.contentWindow?.ketcher
        if (!ketcher) { setStatus('画板未就绪'); return }
        try {
          const value = await ketcher.getSmiles()
          setSmiles(value || '')
          setStatus(value ? '已读取结构' : '画板是空的')
        } catch (error) {
          setStatus(`读取失败：${error?.message ?? error}`)
        }
      }, [])

      const insert = React.useCallback(() => {
        if (!smiles) { setStatus('先读取一个结构'); return }
        const how = insertIntoComposer(smiles)
        setStatus(how.startsWith('failed') ? how : `已插入输入框（${how}）`)
      }, [smiles])

      return h('div', { style: { display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 } },
        h('div', {
          style: {
            display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px',
            borderBottom: '1px solid var(--dsh-border, #e5e7eb)', flex: '0 0 auto',
          },
        },
          h('strong', { style: { fontSize: 13 } }, '化学工作台'),
          h('button', { type: 'button', onClick: readSmiles, style: btnStyle }, '读取结构'),
          h('button', {
            type: 'button', onClick: insert, disabled: !smiles,
            style: { ...btnStyle, opacity: smiles ? 1 : 0.5 },
          }, '插入输入框'),
          h('code', {
            style: {
              flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis',
              whiteSpace: 'nowrap', fontSize: 12, opacity: 0.85,
            },
            title: smiles,
          }, smiles || '（还没读结构）'),
          h('span', { style: { fontSize: 12, opacity: 0.6, flex: '0 0 auto' } }, status),
        ),
        h('iframe', {
          ref: frameRef,
          src: KETCHER_URL,
          onLoad: onFrameLoad,
          title: 'Ketcher',
          style: { flex: 1, width: '100%', border: 'none', minHeight: 0 },
        }),
      )
    }

    const btnStyle = {
      padding: '4px 10px', fontSize: 12, cursor: 'pointer',
      border: '1px solid var(--dsh-border, #d1d5db)', borderRadius: 6,
      background: 'transparent', color: 'inherit', flex: '0 0 auto',
    }

    /* ------------------------------------------------------------------ */
    /* 左侧栏图标                                                          */
    /* ------------------------------------------------------------------ */

    function ChemIcon(props) {
      const size = props?.size ?? 18
      return h('svg', {
        width: size, height: size, viewBox: '0 0 24 24', fill: 'none',
        stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round',
        'aria-hidden': 'true',
      },
        // 锥形瓶 + 一个苯环感的六边形内部线条
        h('path', { d: 'M9 3h6M10 3v6.2L5.4 17.4A2 2 0 0 0 7.2 20h9.6a2 2 0 0 0 1.8-2.6L14 9.2V3' }),
        h('path', { d: 'M7.6 14.5h8.8' }),
      )
    }

    /* ------------------------------------------------------------------ */
    /* 插件入口                                                            */
    /* ------------------------------------------------------------------ */

    /** 客户端服务名（不是包名）：只要 slots。 */
    const inject = ['slots']

    function apply(ctx) {
      // 留给 insertIntoComposer 用（客户端 ctx 需要时可达）
      try { window.__DSH_CHEM_CTX__ = ctx } catch { /* 忽略 */ }

      ctx.slots.inject('main', () => ctx.slots.register(
        { name: 'main', key: PANEL_ID },
        ChemWorkbench,
      ))

      ctx.slots.inject('sidebar.panellist', () => ctx.slots.register(
        { name: 'sidebar.panellist', id: PANEL_ID, order: 50, label: '化学工作台' },
        ChemIcon,
      ))
    }

    return { apply, inject }
  },
})
