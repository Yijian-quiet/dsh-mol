/**
 * chem-ui · 客户端半边（浏览器 bundle）
 *
 * 格式与官方 `tsdown.client.ts` 预设一致：window.__ModuleLoader__.load({ id, factory: (require) => ... })
 * 外部依赖（react 等）通过注入的 `require` 从 loader 模块表解析。
 *
 * 交互设计（2026-09-25 按 Mr.自由基 的反馈重做）：
 *   ✗ 旧：注册 main 面板 → 占掉主区域 → 聊天看不见、结构插进"看不见的会话"
 *   ✓ 新：**聊天保持原样**；输入框左侧一个绘制按钮 → 打开一个**可拖动的浮层画板**；
 *        浮层里用**化学功能按钮**布置任务（把带结构的指令写进输入框，你再补一句就发）
 *
 * 两个注册点：
 *   conversation.input.left（list, session）→ 绘制按钮（自带 sessionId）
 *   shell.overlay        （list, root）    → 浮层画板（root 作用域，靠 store 拿 sessionId）
 *   —— 不再注册 main / sidebar.panellist
 */

window.__ModuleLoader__.load({
  id: 'dsh-chem-ui',
  factory: (require) => {
    const React = require('react')
    const h = React.createElement

    /** Ketcher 由宿主半边挂在同源前缀下（见 lib/index.js）。 */
    const KETCHER_URL = '/chem/ketcher/index.html'

    /* ------------------------------------------------------------------ */
    /* 浮层状态（一个极小的外部 store；按钮与浮层分处两个作用域，靠它通信）    */
    /* ------------------------------------------------------------------ */

    // 注意：useSyncExternalStore 用 Object.is 比较快照 —— **必须换新对象**，
    // 原地改同一个对象不会触发重渲染（踩过：浮层永远不出现）。
    let state = { open: false, sessionId: null, x: null, y: null, w: 580, h: 540 }
    const listeners = new Set()
    const emit = () => { for (const l of listeners) l() }
    const setState = (patch) => { state = { ...state, ...patch }; emit() }
    const store = {
      ctx: null,
      subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener) },
      getSnapshot() { return state },
      close() { setState({ open: false }) },
      toggle(sessionId) {
        const id = sessionId ?? null
        if (state.open && state.sessionId === id) setState({ open: false })
        else setState({ sessionId: id, open: true })
      },
      place(x, y) { setState({ x, y }) },
    }
    const useStore = () => React.useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot)

    /* ------------------------------------------------------------------ */
    /* 写进会话草稿（追加，不覆盖用户已输入的内容）                          */
    /* ------------------------------------------------------------------ */

    function appendToDraft(sessionId, text) {
      const ctx = store.ctx
      if (!ctx || typeof ctx.get !== 'function') return 'failed: ctx 不可用'
      const id = sessionId ?? ctx.get('sessions')?.list?.getSnapshot?.().current
      if (!id) return 'failed: 没有目标会话'
      try {
        const shell = ctx.get('conversation')?.input?.shell?.(id)
        if (!shell || typeof shell.setDraft !== 'function') return 'failed: input.shell 无 setDraft'
        const existing = shell.snapshot?.draft ?? ''
        shell.setDraft(existing.trim() ? `${existing.replace(/\s*$/, '')} ${text}` : text)
        return 'ok'
      } catch (error) {
        return `failed: ${error?.message ?? error}`
      }
    }

    /* ------------------------------------------------------------------ */
    /* 化学功能按钮：读结构 → 把"带结构的指令"写进输入框（= 布置任务）        */
    /* ------------------------------------------------------------------ */

    /**
     * 本次会话的产物目录。
     *
     * 为什么由插件给：MCP 服务是**按插件常驻**的，它不知道调用来自哪个会话
     * （DSH 的 MCP 客户端不转发会话身份），所以只有插件知道 sessionId。
     * 不这么做，所有会话的产物会平铺在同一个目录里 —— 实测一个下午就乱了。
     */
    const outHint = (sessionId) => sessionId
      ? `（图片等产物请写到 ~/dsh-mol-out/sessions/${String(sessionId).replace(/^session-/, '').slice(0, 8)}/）`
      : ''

    const FUNCTIONS = [
      { id: 'smiles', label: '插入结构', hint: '只把 SMILES 放进输入框' },
      { id: 'check', label: '校验结构', hint: '让 agent 校验合法性并说明问题',
        prompt: s => `请校验这个分子结构的合法性，有问题就说明原因：${s}` },
      { id: 'props', label: '结构性质', hint: '分子式 / MW / logP / TPSA / HBD / HBA / 环数',
        prompt: s => `请算一下这个分子的性质（分子式、MW、logP、TPSA、HBD、HBA、环数）：${s}` },
      { id: 'standardize', label: '标准化', hint: '去盐 / 中和 / 规范化，并说明改了什么',
        prompt: s => `请对这个结构做标准化（去盐、中和电荷、规范化），并说明改了什么：${s}` },
      { id: 'retro', label: '逆合成分析', hint: '待接入（需要平台侧能力）', disabled: true },
    ]

    /* ------------------------------------------------------------------ */
    /* 浮层：可拖动的 Ketcher 画板                                          */
    /* ------------------------------------------------------------------ */

    function ChemPanel() {
      const s = useStore()
      const frameRef = React.useRef(null)
      const dragRef = React.useRef(null)
      const [status, setStatus] = React.useState('')
      const [ready, setReady] = React.useState(false)

      React.useEffect(() => {
        if (!s.open) { setReady(false); setStatus(''); return undefined }
        let tries = 0
        const timer = setInterval(() => {
          tries += 1
          if (frameRef.current?.contentWindow?.ketcher) { setReady(true); clearInterval(timer) }
          else if (tries > 60) { setStatus('画板未能就绪'); clearInterval(timer) }
        }, 500)
        return () => clearInterval(timer)
      }, [s.open])

      if (!s.open) return null

      const readSmiles = async () => {
        const k = frameRef.current?.contentWindow?.ketcher
        if (!k) return null
        try { return (await k.getSmiles()) || '' } catch { return null }
      }

      const runFunction = async (fn) => {
        const smiles = await readSmiles()
        if (smiles === null) { setStatus('画板未就绪'); return }
        if (!smiles) { setStatus('画板是空的'); return }
        const base = fn.id === 'smiles' ? smiles : fn.prompt(smiles)
        const text = `${base}${outHint(s.sessionId)}`
        const result = appendToDraft(s.sessionId, text)
        setStatus(result === 'ok' ? `「${fn.label}」已写入输入框` : result)
      }

      const onHeaderDown = (e) => {
        e.preventDefault()
        const rect = e.currentTarget.parentElement.getBoundingClientRect()
        dragRef.current = { dx: e.clientX - rect.left, dy: e.clientY - rect.top }
        const move = (ev) => {
          if (!dragRef.current) return
          store.place(Math.max(0, ev.clientX - dragRef.current.dx), Math.max(0, ev.clientY - dragRef.current.dy))
        }
        const up = () => {
          dragRef.current = null
          window.removeEventListener('pointermove', move)
          window.removeEventListener('pointerup', up)
        }
        window.addEventListener('pointermove', move)
        window.addEventListener('pointerup', up)
      }

      const cardStyle = {
        position: 'fixed',
        left: s.x ?? Math.max(16, window.innerWidth - s.w - 32),
        top: s.y ?? Math.max(16, window.innerHeight - s.h - 140),
        width: s.w, height: s.h,
        zIndex: 9999, display: 'flex', flexDirection: 'column',
        // 显式配色：不依赖主题变量 —— 深色主题下 var(--dsh-surface) 与 color:inherit
        // 会组合成"浅字白底"，文字直接看不见（踩过）。Ketcher 本身就是浅色画布，
        // 所以这里固定浅色卡片 + 深色文字，两种主题下都清晰。
        background: '#ffffff', color: '#111827',
        border: '1px solid #d1d5db', borderRadius: 10,
        boxShadow: '0 12px 32px rgba(0,0,0,.18)', overflow: 'hidden',
      }

      return h('div', { style: cardStyle, 'data-chem-panel': 'true' },
        h('div', {
          onPointerDown: onHeaderDown,
          style: {
            display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px',
            cursor: 'move', userSelect: 'none', flex: '0 0 auto',
            background: '#f3f4f6', color: '#111827',
            borderBottom: '1px solid #e5e7eb',
          },
        },
          h('strong', { style: { fontSize: 12 } }, '分子画板'),
          h('span', { style: { fontSize: 11, opacity: 0.6, flex: 1 } },
            status || (ready ? '' : '加载中…')),
          h('button', {
            type: 'button', onClick: () => store.close(), 'aria-label': '关闭画板',
            style: { border: 'none', background: 'transparent', cursor: 'pointer', fontSize: 14, color: '#6b7280' },
          }, '✕'),
        ),
        h('iframe', {
          ref: frameRef, src: KETCHER_URL, title: 'Ketcher',
          style: { flex: 1, width: '100%', border: 'none', minHeight: 260 },
        }),
        h('div', {
          style: {
            display: 'flex', flexWrap: 'wrap', gap: 6, padding: '8px 10px',
            background: '#f9fafb',
            borderTop: '1px solid #e5e7eb', flex: '0 0 auto',
          },
        }, FUNCTIONS.map(fn => h('button', {
          key: fn.id, type: 'button', title: fn.hint, disabled: !!fn.disabled,
          onClick: () => { void runFunction(fn) },
          style: {
            padding: '4px 10px', fontSize: 12, borderRadius: 6,
            border: '1px solid #d1d5db', background: '#ffffff',
            color: '#111827', cursor: fn.disabled ? 'not-allowed' : 'pointer',
            opacity: fn.disabled ? 0.45 : 1,
          },
        }, fn.label))),
      )
    }

    /* ------------------------------------------------------------------ */
    /* 输入框左侧的绘制按钮                                                 */
    /* ------------------------------------------------------------------ */

    function DrawButton(props) {
      // session 作用域插槽会自动注入会话标准工具包（含 sessionId）
      const sessionId = props?.sessionId
      const s = useStore()
      const active = s.open && s.sessionId === (sessionId ?? null)
      return h('button', {
        type: 'button',
        title: '绘制分子结构',
        'aria-label': '绘制分子',
        'data-chem-draw': 'true',
        onClick: () => store.toggle(sessionId),
        style: {
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          width: 28, height: 28, borderRadius: 6, cursor: 'pointer',
          border: `1px solid ${active ? 'var(--dsh-accent, #4d6bfe)' : 'transparent'}`,
          background: active ? 'var(--dsh-accent-weak, rgba(77,107,254,.12))' : 'transparent',
          color: 'inherit',
        },
      }, h('svg', {
        width: 17, height: 17, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
        strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': 'true',
      },
        h('path', { d: 'M9 3h6M10 3v6.2L5.4 17.4A2 2 0 0 0 7.2 20h9.6a2 2 0 0 0 1.8-2.6L14 9.2V3' }),
        h('path', { d: 'M7.6 14.5h8.8' }),
      ))
    }

    /* ------------------------------------------------------------------ */
    /* 入口                                                                */
    /* ------------------------------------------------------------------ */

    const inject = ['slots']

    function apply(ctx) {
      store.ctx = ctx
      // 调试/验收用的句柄（无副作用；自动化脚本靠它读会话草稿）
      try { window.__DSH_CHEM_CTX__ = ctx } catch { /* 忽略 */ }

      ctx.slots.inject('conversation.input.left', () => ctx.slots.register(
        { name: 'conversation.input.left', id: 'chem-draw', order: 40 },
        DrawButton,
      ))

      ctx.slots.inject('shell.overlay', () => ctx.slots.register(
        { name: 'shell.overlay', id: 'chem-panel', order: 40 },
        ChemPanel,
      ))
    }

    return { apply, inject }
  },
})
