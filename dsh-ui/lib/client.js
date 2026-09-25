/**
 * chem-ui · 客户端半边（浏览器 bundle）
 *
 * 格式与官方 `tsdown.client.ts` 预设一致：window.__ModuleLoader__.load({ id, factory: (require) => ... })
 * 外部依赖（react 等）通过注入的 `require` 从 loader 模块表解析。
 *
 * ── 这是什么 ────────────────────────────────────────────────────────────────
 * 一个**化学工作台**：聊天输入框左侧一个按钮打开，三个页签
 *   画板   Ketcher 画分子（前端本地渲染，不经后端）
 *   分析   RDKit 现算的分子数据（分子式/MW/logP/TPSA/类药性/结构警报/骨架…）
 *   逆合成 多步路线规划（后端可插拔，未配置时**如实说未配置**）
 *
 * ── 三条设计红线（都是踩出来的） ────────────────────────────────────────────
 * 1. **不许顶掉聊天**：所以是 shell.overlay 上的浮层，不是 main 面板。
 *    早期版本占了主区域，用户说"有点不太合理"——聊天才是主战场。
 * 2. **结构图要跟着文字走，不是附件**：工作台里不放"预览图"当交付物，
 *    图交给 agent 在回复里内联（`read_image`）。分析页签里那张缩略图是**界面的一部分**
 *    （让你确认"算的是不是这个分子"），不是产物。
 * 3. **插入到对话的文本必须干净**：只有结构和任务，不夹带内部路径之类的噪音。
 *
 * 两个注册点：
 *   conversation.input.left（list, session）→ 工作台按钮（自带 sessionId）
 *   shell.overlay        （list, root）    → 工作台浮层（靠 store 拿 sessionId）
 */

window.__ModuleLoader__.load({
  id: 'dsh-chem-ui',
  factory: (require) => {
    const React = require('react')
    const h = React.createElement

    /** Ketcher 由宿主半边挂在同源前缀下（见 lib/index.js）。 */
    const KETCHER_URL = '/chem/ketcher/index.html'
    /** 宿主半边的本地计算与逆合成入口。 */
    const TOOL_URL = '/chem/tool'
    const RETRO_URL = '/chem/retro'
    const STATUS_URL = '/chem/status'

    /* ------------------------------------------------------------------ */
    /* 配色：显式写死，不依赖主题变量                                        */
    /* ------------------------------------------------------------------ */
    // 踩过的坑：早先用 var(--dsh-surface) + color:inherit，深色主题下变成
    // "浅色字 + 白底"，文字直接消失。Ketcher 本身就是浅色画布，干脆整窗固定浅色。
    const C = {
      bg: '#ffffff', text: '#111827', muted: '#6b7280', faint: '#9ca3af',
      border: '#e5e7eb', header: '#f3f4f6', soft: '#f9fafb',
      accent: '#2563eb', accentSoft: '#eff6ff',
      ok: '#059669', okSoft: '#ecfdf5',
      warn: '#b45309', warnSoft: '#fffbeb',
      err: '#dc2626', errSoft: '#fef2f2',
    }

    /* ------------------------------------------------------------------ */
    /* 状态：一个极小的外部 store（按钮与浮层分处两个作用域，靠它通信）        */
    /* ------------------------------------------------------------------ */

    // 注意：useSyncExternalStore 用 Object.is 比较快照 —— **必须换新对象**，
    // 原地改同一个对象不会触发重渲染（踩过：浮层永远不出现）。
    const initial = {
      open: false, sessionId: null, maximized: false,
      x: null, y: null, w: 1060, h: 680,
      tab: 'draw',
      smiles: '',            // 当前分子：画板/输入框/分析页签共享
      draftInput: '',        // 分析页签的 SMILES 输入框
      compare: '',           // 相似度对比分子
      smarts: 'c1ccccc1',    // 子结构匹配的 SMARTS
      batch: '',             // 批量页签的清单
      thumb: '',             // 分析页签的结构缩略图（object URL）
      result: null,          // { kind, ok, data, error }
      busy: false,
      retro: null, retroBusy: false,
      caps: null,
      status: '', statusTone: 'muted',
    }
    let state = initial
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
        // 每次打开都回到画板页：iframe 藏在 display:none 里初始化不可靠
        else setState({ sessionId: id, open: true, tab: 'draw' })
      },
      place(x, y) { setState({ x, y }) },
    }
    const useStore = () => React.useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot)

    const say = (status, statusTone = 'muted') => setState({ status, statusTone })

    /* ------------------------------------------------------------------ */
    /* 后端调用                                                            */
    /* ------------------------------------------------------------------ */

    async function postJson(url, payload) {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload ?? {}),
      })
      const text = await response.text()
      try {
        return JSON.parse(text)
      } catch {
        // 宿主半边多半是抛了异常才回非 JSON —— 原文给人看，别吞
        return { ok: false, code: 'bad_response', message: `后端返回了非 JSON（HTTP ${response.status}）：${text.slice(0, 300)}` }
      }
    }

    /** 调一个 chemcore 本地操作。永远 resolve 成 `{ok, ...}`，不抛。 */
    async function callTool(op, params) {
      try {
        return await postJson(TOOL_URL, { op, ...params })
      } catch (error) {
        return { ok: false, code: 'network', message: `连不上本地计算服务：${error?.message ?? error}` }
      }
    }

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
    /* 读画板 / 用画板出缩略图                                              */
    /* ------------------------------------------------------------------ */

    function ketcherApi(frame) {
      try { return frame?.contentWindow?.ketcher ?? null } catch { return null }
    }

    async function readCanvas(frame) {
      const k = ketcherApi(frame)
      if (!k) return null
      try { return (await k.getSmiles()) || '' } catch { return null }
    }

    /**
     * 用画板引擎把 SMILES 渲成一张小图，纯粹为了"让人确认算的是哪个分子"。
     * Ketcher 的 generateImage 走本地 indigo wasm，不联网、不经后端。
     * 失败就静默跳过 —— 这是锦上添花，不该因为它报错而挡住数据。
     */
    async function makeThumb(frame, smiles) {
      const k = ketcherApi(frame)
      if (!k || !smiles) return ''
      try {
        const blob = await k.generateImage(smiles, { outputFormat: 'svg' })
        if (!blob) return ''
        return URL.createObjectURL(blob)
      } catch {
        return ''
      }
    }

    /* ------------------------------------------------------------------ */
    /* 小积木                                                              */
    /* ------------------------------------------------------------------ */

    const button = (label, onClick, opts = {}) => h('button', {
      type: 'button',
      onClick: opts.disabled || opts.busy ? undefined : onClick,
      title: opts.title,
      key: opts.key,
      'data-chem-fn': opts.id,
      style: {
        padding: opts.big ? '6px 14px' : '4px 10px',
        fontSize: opts.big ? 13 : 12,
        fontWeight: opts.primary ? 600 : 400,
        borderRadius: 6,
        border: `1px solid ${opts.primary ? C.accent : C.border}`,
        background: opts.primary ? C.accent : '#ffffff',
        color: opts.primary ? '#ffffff' : C.text,
        cursor: opts.disabled || opts.busy ? 'not-allowed' : 'pointer',
        opacity: opts.disabled || opts.busy ? 0.45 : 1,
        whiteSpace: 'nowrap',
      },
    }, opts.busy ? `${label}…` : label)

    const section = (title, children, extra) => h('div', {
      style: { marginBottom: 14 },
    },
      h('div', {
        style: {
          display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6,
          fontSize: 12, fontWeight: 600, color: C.muted, letterSpacing: '.02em',
        },
      }, title, extra ?? null),
      children,
    )

    const field = (value, onChange, opts = {}) => h('input', {
      type: 'text', value, placeholder: opts.placeholder, onChange: (e) => onChange(e.target.value),
      spellCheck: false,
      style: {
        flex: 1, minWidth: 0, padding: '5px 8px', fontSize: 13, fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
        border: `1px solid ${C.border}`, borderRadius: 6, background: '#ffffff', color: C.text,
      },
    })

    function kv(label, value, opts = {}) {
      return h('div', {
        key: label,
        style: {
          display: 'flex', flexDirection: 'column', gap: 1,
          padding: '6px 8px', borderRadius: 6,
          background: opts.soft ? C.accentSoft : C.soft,
          border: `1px solid ${opts.soft ? '#dbeafe' : C.border}`,
          minWidth: 92,
        },
      },
        h('span', { style: { fontSize: 10, color: C.muted } }, label),
        h('span', { style: { fontSize: 14, fontWeight: 600, fontVariantNumeric: 'tabular-nums' } }, String(value)),
      )
    }

    const alertBox = (tone, children) => h('div', {
      style: {
        padding: '8px 10px', borderRadius: 6, fontSize: 12, lineHeight: 1.6,
        background: tone === 'err' ? C.errSoft : tone === 'warn' ? C.warnSoft : C.accentSoft,
        border: `1px solid ${tone === 'err' ? '#fecaca' : tone === 'warn' ? '#fde68a' : '#dbeafe'}`,
        color: tone === 'err' ? C.err : tone === 'warn' ? C.warn : C.accent,
        whiteSpace: 'pre-wrap', wordBreak: 'break-word',
      },
    }, children)

    const mono = (text, opts = {}) => h('code', {
      style: {
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
        fontSize: opts.size ?? 12, background: C.soft, border: `1px solid ${C.border}`,
        borderRadius: 4, padding: '1px 5px', wordBreak: 'break-all',
      },
    }, text)

    /* ------------------------------------------------------------------ */
    /* 画板页签                                                            */
    /* ------------------------------------------------------------------ */

    function DrawTab(props) {
      const { s, frameRef } = props
      const take = async (then) => {
        const smiles = await readCanvas(frameRef.current)
        if (smiles === null) { say('画板还没就绪', 'warn'); return }
        if (!smiles) { say('画板是空的', 'warn'); return }
        setState({ smiles, draftInput: smiles })
        const thumb = await makeThumb(frameRef.current, smiles)
        setState({ thumb: thumb || state.thumb })
        say(`已读入结构：${smiles.length > 40 ? smiles.slice(0, 40) + '…' : smiles}`, 'ok')
        if (then) then(smiles)
      }

      const insert = async () => {
        const smiles = await readCanvas(frameRef.current)
        if (!smiles) { say('画板是空的', 'warn'); return }
        const r = appendToDraft(s.sessionId, smiles)
        say(r === 'ok' ? '结构已写入输入框' : r, r === 'ok' ? 'ok' : 'err')
      }

      const ask = async (fn) => {
        const smiles = await readCanvas(frameRef.current)
        if (!smiles) { say('画板是空的', 'warn'); return }
        const r = appendToDraft(s.sessionId, fn.prompt(smiles))
        say(r === 'ok' ? `「${fn.label}」已写入输入框` : r, r === 'ok' ? 'ok' : 'err')
      }

      const ASKS = [
        {
          id: 'ask-check', label: '校验结构', title: '让小深校验合法性并解释问题',
          prompt: (x) => `请校验这个分子结构的合法性，有问题就说明原因：${x}`,
        },
        {
          id: 'ask-explain', label: '讲这个分子', title: '让小深画图 + 讲解（图会内联在回复里）',
          prompt: (x) => `请画一下这个分子并讲讲它是什么、有什么值得注意的性质：${x}`,
        },
        {
          id: 'ask-standardize', label: '标准化', title: '去盐/中和/规范化，并说明改了什么',
          prompt: (x) => `请对这个结构做标准化（去盐、中和电荷、规范化），并说明改了什么：${x}`,
        },
      ]

      return h('div', { style: { flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 } },
        h('iframe', {
          ref: frameRef, src: KETCHER_URL, title: 'Ketcher 画板',
          'data-chem-canvas': 'true',
          style: { flex: 1, width: '100%', border: 'none', minHeight: 220, background: '#ffffff' },
        }),
        h('div', {
          style: {
            display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center',
            padding: '8px 10px', background: C.soft, borderTop: `1px solid ${C.border}`,
          },
        },
          button('插入到对话', insert, { id: 'insert', primary: true, title: '把 SMILES 放进聊天输入框' }),
          button('取到分析页', () => { void take(() => setState({ tab: 'analyze' })) }, { id: 'to-analyze', title: '读当前结构并切到分析' }),
          h('span', { style: { width: 1, height: 18, background: C.border, margin: '0 2px' } }),
          ASKS.map(fn => button(fn.label, () => { void ask(fn) }, { id: fn.id, title: fn.title })),
        ),
      )
    }

    /* ------------------------------------------------------------------ */
    /* 分析页签：本地 RDKit 现算                                            */
    /* ------------------------------------------------------------------ */

    function PropTable(props) {
      const p = props.data
      const cells = [
        ['分子式', p.formula], ['分子量', p.mw], ['精确质量', p.exact_mw],
        ['logP', p.logp], ['TPSA / Å²', p.tpsa], ['氢键给体', p.hbd], ['氢键受体', p.hba],
        ['可旋转键', p.rotatable_bonds], ['重原子', p.heavy_atoms], ['环数', p.rings],
        ['芳香环', p.aromatic_rings], ['脂肪环', p.aliphatic_rings], ['杂原子', p.heteroatoms],
        ['形式电荷', p.formal_charge], ['Fsp³', p.fraction_csp3], ['立体中心', p.stereocenters],
      ]
      return h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 6 } },
        cells.map(([k, v]) => kv(k, v)))
    }

    function DrugBlock(props) {
      const d = props.data
      return h('div', null,
        h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 } },
          kv('QED', d.qed, { soft: true }),
          kv('摩尔折射率', d.molar_refractivity),
          kv('Lipinski 违反', d.lipinski_violations, { soft: d.lipinski_violations === 0 }),
          kv('规则通过', `${d.rules.filter(r => r.passed).length}/${d.rules.length}`),
          kv('结构警报', d.structural_alerts.length, { soft: d.structural_alerts.length === 0 })),
        h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 } },
          d.rules.map(r => h('span', {
            key: r.rule,
            style: {
              fontSize: 11, padding: '2px 8px', borderRadius: 999,
              background: r.passed ? C.okSoft : C.errSoft,
              border: `1px solid ${r.passed ? '#a7f3d0' : '#fecaca'}`,
              color: r.passed ? C.ok : C.err,
            },
            title: r.detail,
          }, `${r.passed ? '✓' : '✗'} ${r.rule}（${r.detail}）`))),
        h('div', { style: { fontSize: 11, color: C.muted, marginBottom: 8 } }, d.qed_note),
        d.structural_alerts.length
          ? section('结构警报（命中即需人工确认，不是"有毒"的结论）',
            h('div', { style: { display: 'flex', flexDirection: 'column', gap: 4 } },
              d.structural_alerts.map((a, i) => h('div', { key: i, style: { fontSize: 12 } },
                h('span', {
                  style: { fontSize: 10, padding: '1px 6px', borderRadius: 4, background: C.warnSoft, color: C.warn, marginRight: 6 },
                }, a.catalog), a.description))),
            )
          : h('div', { style: { fontSize: 12, color: C.ok, marginBottom: 10 } }, '✓ PAINS / BRENK 都没命中'),
        section('Murcko 骨架', h('div', { style: { display: 'flex', flexDirection: 'column', gap: 4 } },
          h('div', null, mono(d.murcko_scaffold || '（无环系）')),
          d.murcko_scaffold_generic && d.murcko_scaffold_generic !== d.murcko_scaffold
            ? h('div', { style: { fontSize: 11, color: C.muted } }, '抹平元素类型：', mono(d.murcko_scaffold_generic))
            : null)),
      )
    }

    function ResultView(props) {
      const r = props.result
      if (!r) {
        return h('div', { style: { fontSize: 12, color: C.muted, padding: '14px 2px' } },
          '输入或读入一个 SMILES，再点上面的分析按钮 —— 这些数在本机用 RDKit 现算，不经过模型。')
      }
      if (!r.ok) return alertBox('err', r.message || '未知错误')

      const d = r.data
      if (r.kind === 'analyze') {
        return h('div', null,
          section('基础性质', h(PropTable, { data: d.properties })),
          section('类药性 / 结构警报 / 骨架', h(DrugBlock, { data: d.druglikeness })))
      }
      if (r.kind === 'check') {
        const tone = d.level === 'ok' ? 'ok' : d.level === 'warn' ? 'warn' : 'err'
        return h('div', null,
          h('div', { style: { display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 } },
            kv('结论', d.level, { soft: tone === 'ok' }),
            d.formula ? kv('分子式', d.formula) : null,
            d.canonical ? kv('规范化', '见下') : null),
          d.canonical ? h('div', { style: { marginBottom: 8 } }, mono(d.canonical)) : null,
          d.diagnostics.length
            ? h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } },
              d.diagnostics.map((g, i) => alertBox(g.level === 'error' ? 'err' : 'warn',
                h('div', null,
                  h('div', { style: { fontWeight: 600 } }, g.message),
                  g.position != null ? h('div', { style: { fontSize: 11, opacity: .8 } }, `位置：第 ${g.position} 个字符`) : null))))
            : alertBox('ok', '✓ 结构合法，没有发现问题'))
      }
      if (r.kind === 'standardize') {
        return h('div', null,
          h('div', { style: { display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 } },
            kv('是否改变', d.changed ? '是' : '没有', { soft: !d.changed })),
          h('div', { style: { marginBottom: 8 } },
            h('div', { style: { fontSize: 11, color: C.muted, marginBottom: 2 } }, '规范化结果'),
            mono(d.output, { size: 13 })),
          d.changes?.length
            ? section('改了什么', h('div', { style: { display: 'flex', flexDirection: 'column', gap: 4 } },
              d.changes.map((c, i) => h('div', { key: i, style: { fontSize: 12 } },
                h('strong', null, c.step), `：${c.before ?? ''} → ${c.after ?? ''}`))))
            : h('div', { style: { fontSize: 12, color: C.muted } }, '没有需要改的地方'))
      }
      if (r.kind === 'convert') {
        return h('div', null,
          h('div', { style: { display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 } },
            kv('从', d.from), kv('到', d.to)),
          mono(d.value, { size: 13 }))
      }
      if (r.kind === 'substructure') {
        return h('div', null,
          h('div', { style: { display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 } },
            kv('是否命中', d.matched ? '命中' : '没命中', { soft: d.matched }),
            kv('匹配数', d.count)),
          d.matches?.length
            ? h('div', { style: { maxHeight: 200, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 4 } },
              d.matches.map((m, i) => h('div', { key: i, style: { fontSize: 11, fontFamily: 'monospace' } },
                `[${m.join(', ')}]`)))
            : null)
      }
      if (r.kind === 'similarity') {
        return h('div', null,
          h('div', { style: { display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 } },
            kv('Tanimoto', d.score, { soft: true }),
            kv('指纹', d.fingerprint), kv('度量', d.metric)),
          h('div', { style: { fontSize: 12, color: C.muted } }, `${d.a}  vs  ${d.b}`))
      }
      if (r.kind === 'batch' || r.kind === 'dedupe') {
        const tone = d.failed ? 'warn' : 'ok'
        return h('div', null,
          h('div', { style: { display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 } },
            kv('总数', d.total),
            kv('通过', d.ok ?? d.unique, { soft: true }),
            d.warn != null ? kv('警告', d.warn) : null,
            d.failed != null ? kv('失败', d.failed, { soft: !d.failed }) : null,
            d.duplicates ? kv('重复', d.duplicates.length) : null),
          d.failed_items?.length
            ? section('失败的条目（逐条给原因，不静默丢）',
              h('div', { style: { maxHeight: 220, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 4 } },
                d.failed_items.map((f, i) => h('div', { key: i, style: { fontSize: 12 } },
                  h('span', { style: { color: C.err } }, `#${f.index} ${f.input}`), ' — ', f.reason))))
            : null,
          d.duplicates?.length
            ? section('重复项', h('div', { style: { maxHeight: 180, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 4 } },
              d.duplicates.map((x, i) => h('div', { key: i, style: { fontSize: 12 } },
                mono(x.smiles), ` 与 #${x.duplicate_of_index} 相同（${x.canonical}）`))))
            : null,
          !d.failed && !d.duplicates?.length ? alertBox('ok', '✓ 全部通过') : null)
      }
      return h('pre', { style: { fontSize: 11, overflow: 'auto', maxHeight: 300 } }, JSON.stringify(d, null, 2))
    }

    function AnalyzeTab(props) {
      const { s, frameRef } = props

      const run = async (kind, op, params, label) => {
        const smiles = (params?.smiles ?? s.draftInput ?? '').trim()
        const isBatch = op === 'batch_clean' || op === 'dedupe'
        if (!isBatch && !smiles) { say('先给一个 SMILES', 'warn'); return }
        setState({ busy: true, status: `${label} 计算中…`, statusTone: 'muted' })
        const response = await callTool(op, params)
        if (response.ok && smiles) {
          const thumb = await makeThumb(frameRef.current, smiles)
          setState({ thumb: thumb || state.thumb, smiles })
        }
        setState({
          busy: false,
          result: response.ok
            ? { kind, ok: true, data: response.result }
            : { kind, ok: false, message: response.message, code: response.code },
          status: response.ok ? `${label} 完成` : `${label} 失败`,
          statusTone: response.ok ? 'ok' : 'err',
        })
      }

      const takeFromCanvas = async () => {
        const smiles = await readCanvas(frameRef.current)
        if (!smiles) { say('画板是空的', 'warn'); return }
        setState({ draftInput: smiles, smiles })
        const thumb = await makeThumb(frameRef.current, smiles)
        setState({ thumb: thumb || '' })
      }

      const handOff = () => {
        const smiles = (s.draftInput || s.smiles || '').trim()
        if (!smiles) { say('先给一个 SMILES', 'warn'); return }
        const r = appendToDraft(s.sessionId,
          `这是我用工作台算过的分子：${smiles}\n请画一下它，并结合性质/类药性讲讲它是什么、有什么值得注意的地方。`)
        say(r === 'ok' ? '已写入输入框，补一句就能发' : r, r === 'ok' ? 'ok' : 'err')
      }

      const listOf = (text) => text.split(/[\n,;，；]+/).map(x => x.trim()).filter(Boolean)

      return h('div', { style: { flex: 1, display: 'flex', minHeight: 0 } },
        // 左栏：输入与按钮
        h('div', {
          style: {
            width: 300, flex: '0 0 auto', borderRight: `1px solid ${C.border}`,
            padding: 12, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 10,
          },
        },
          h('div', { style: { fontSize: 12, fontWeight: 600, color: C.muted } }, '分子'),
          h('div', { style: { display: 'flex', gap: 6 } },
            field(s.draftInput, (v) => setState({ draftInput: v }), { placeholder: 'SMILES，如 CCO' }),
            button('取画板', () => { void takeFromCanvas() }, { id: 'take' })),
          h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 6 } },
            button('基础性质 + 类药性', () => { void run('analyze', 'analyze', { smiles: s.draftInput }, '分析') },
              { id: 'analyze', primary: true, busy: s.busy }),
            button('校验', () => { void run('check', 'check', { smiles: s.draftInput }, '校验') }, { id: 'check' }),
            button('标准化', () => { void run('standardize', 'standardize', { smiles: s.draftInput }, '标准化') }, { id: 'standardize' })),

          h('div', { style: { height: 1, background: C.border, margin: '2px 0' } }),

          section('格式转换', h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 6 } },
            [['smiles', 'SMILES'], ['inchi', 'InChI'], ['inchikey', 'InChIKey'], ['formula', '分子式']].map(([to, label]) => button(label, () => {
              void run('convert', 'convert', { value: s.draftInput, to }, `转换 ${label}`)
            }, { key: to, id: `convert-${to}` })))),

          section('子结构（SMARTS）', h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } },
            field(s.smarts, (v) => setState({ smarts: v }), { placeholder: 'c1ccccc1' }),
            button('匹配', () => {
              void run('substructure', 'substructure', { smiles: s.draftInput, smarts: s.smarts }, '子结构匹配')
            }, { id: 'substructure' }))),

          section('相似度（与另一个分子）', h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } },
            field(s.compare, (v) => setState({ compare: v }), { placeholder: '另一个 SMILES' }),
            button('算 Tanimoto', () => {
              void run('similarity', 'similarity', { a: s.draftInput, b: s.compare }, '相似度')
            }, { id: 'similarity' }))),

          section('批量（一行一个）', h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } },
            h('textarea', {
              value: s.batch, onChange: (e) => setState({ batch: e.target.value }),
              placeholder: 'CCO\nCCC\nc1ccccc1', rows: 4, spellCheck: false,
              style: {
                width: '100%', boxSizing: 'border-box', fontSize: 12, padding: '5px 8px', resize: 'vertical',
                fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
                border: `1px solid ${C.border}`, borderRadius: 6, background: '#ffffff', color: C.text,
              },
            }),
            h('div', { style: { display: 'flex', gap: 6 } },
              button('清洗', () => {
                void run('batch', 'batch_clean', { smiles_list: listOf(s.batch) }, '批量清洗')
              }, { id: 'batch-clean' }),
              button('去重', () => {
                void run('dedupe', 'dedupe', { smiles_list: listOf(s.batch) }, '去重')
              }, { id: 'dedupe' })))),

          h('div', { style: { marginTop: 'auto', paddingTop: 6 } },
            button('把结果交给小深解读', handOff, { id: 'handoff', big: true })),
        ),

        // 右栏：结果
        h('div', { style: { flex: 1, minWidth: 0, padding: 12, overflow: 'auto' } },
          s.thumb
            ? h('div', {
              style: {
                display: 'flex', justifyContent: 'center', alignItems: 'center',
                background: C.soft, border: `1px solid ${C.border}`, borderRadius: 8,
                padding: 6, marginBottom: 12, minHeight: 90,
              },
            }, h('img', { src: s.thumb, alt: '当前结构', style: { maxHeight: 130, maxWidth: '100%' } }))
            : null,
          s.caps?.rdkit && s.caps.rdkit.ready === false
            ? alertBox('err', `本地计算服务没起来：${s.caps.rdkit.detail || 'RDKit 不可用'}\n请检查 dsh 日志里 chem-ui 的报错，或确认 python3 环境里有 rdkit。`)
            : null,
          h(ResultView, { result: s.result }),
        ),
      )
    }

    /* ------------------------------------------------------------------ */
    /* 逆合成页签                                                          */
    /* ------------------------------------------------------------------ */

    function RouteNode(props) {
      const node = props.node
      const depth = props.depth ?? 0
      const children = node.children || []
      return h('div', { style: { marginLeft: depth ? 14 : 0, borderLeft: depth ? `1px dashed ${C.border}` : 'none', paddingLeft: depth ? 8 : 0 } },
        h('div', { style: { display: 'flex', alignItems: 'center', gap: 6, padding: '2px 0' } },
          node.is_starting_material
            ? h('span', { style: { fontSize: 10, padding: '1px 6px', borderRadius: 4, background: C.okSoft, color: C.ok, border: '1px solid #a7f3d0' } }, '砌块')
            : h('span', { style: { fontSize: 10, color: C.faint } }, depth ? '中间体' : '目标'),
          mono(node.smiles),
          node.score != null ? h('span', { style: { fontSize: 10, color: C.muted } }, `score ${node.score}`) : null),
        children.length
          ? h('div', null,
            h('div', { style: { fontSize: 10, color: C.faint } }, '↑ 可由这些原料经一步反应得到'),
            children.map((c, i) => h(RouteNode, { key: i, node: c, depth: depth + 1 })))
          : null)
    }

    function RetroTab(props) {
      const { s } = props
      const run = async () => {
        const smiles = (s.draftInput || s.smiles || '').trim()
        if (!smiles) { say('先给一个目标分子', 'warn'); return }
        setState({ retroBusy: true, retro: null, status: '逆合成规划中…（可能要几十秒）', statusTone: 'muted' })
        let response
        try {
          response = await postJson(RETRO_URL, { smiles, iterations: 100, expansion_topk: 50, use_value_fn: true })
        } catch (error) {
          response = { ok: false, code: 'network', message: `连不上逆合成后端：${error?.message ?? error}` }
        }
        setState({
          retroBusy: false, retro: response,
          status: response.ok ? '规划完成' : '没有拿到路线',
          statusTone: response.ok ? 'ok' : 'warn',
        })
      }

      const r = s.retro
      let body
      if (!r) {
        body = h('div', { style: { fontSize: 12, color: C.muted, lineHeight: 1.8 } },
          '输入目标分子，让后端搜索多步合成路线。',
          h('br'),
          '当前后端：Retro*（神经引导 A*，ICML 2020）。**未安装模型数据时不会编造路线**，会如实告诉你缺什么。')
      } else if (r.ok) {
        const routes = r.routes || []
        body = h('div', null,
          h('div', { style: { display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 } },
            kv('路线数', routes.length, { soft: true }),
            kv('后端', r.backend || 'retro_star'),
            r.elapsed_ms != null ? kv('耗时', `${(r.elapsed_ms / 1000).toFixed(1)} s`) : null),
          routes.length
            ? routes.map((route, i) => h('div', {
              key: i,
              style: { border: `1px solid ${C.border}`, borderRadius: 8, padding: 10, marginBottom: 10, background: '#ffffff' },
            },
              h('div', { style: { fontSize: 12, fontWeight: 600, marginBottom: 6 } },
                `路线 ${i + 1}`, route.score != null ? h('span', { style: { color: C.muted, fontWeight: 400 } }, ` · score ${route.score}`) : null,
                route.steps != null ? h('span', { style: { color: C.muted, fontWeight: 400 } }, ` · ${route.steps} 步`) : null),
              h(RouteNode, { node: route.tree || route, depth: 0 })))
            : alertBox('warn', '后端返回成功，但没找到完整路线（可能是迭代次数不够，或目标不在已知模板覆盖范围内）'))
      } else {
        // 未配置 / 失败：把后端说的话原样给人看，并给出可执行的一步
        body = h('div', null,
          alertBox(r.code === 'retro_not_configured' ? 'warn' : 'err',
            h('div', null,
              h('div', { style: { fontWeight: 600, marginBottom: 4 } },
                r.code === 'retro_not_configured' ? '逆合成后端还没装好' : '逆合成没跑成'),
              h('div', null, r.message || '未知错误'))),
          r.missing?.length
            ? section('缺这些文件', h('div', { style: { display: 'flex', flexDirection: 'column', gap: 3 } },
              r.missing.map((m, i) => h('div', { key: i, style: { fontSize: 12 } }, mono(m)))))
            : null,
          r.setup ? section('怎么补', h('pre', {
            style: {
              fontSize: 11, whiteSpace: 'pre-wrap', background: C.soft, border: `1px solid ${C.border}`,
              borderRadius: 6, padding: 8, margin: 0, overflow: 'auto', maxHeight: 240,
            },
          }, r.setup)) : null,
          h('div', { style: { marginTop: 10 } },
            button('让小深来配这个后端', () => {
              const rr = appendToDraft(s.sessionId,
                `逆合成后端还没打通（目标分子：${(s.draftInput || s.smiles || '').trim()}）。请看一下工作台的诊断信息，帮我把 Retro* 后端装起来：\n${r.message || ''}`)
              say(rr === 'ok' ? '已写入输入框' : rr, rr === 'ok' ? 'ok' : 'err')
            }, { id: 'retro-ask' })))
      }

      return h('div', { style: { flex: 1, display: 'flex', minHeight: 0 } },
        h('div', {
          style: {
            width: 300, flex: '0 0 auto', borderRight: `1px solid ${C.border}`,
            padding: 12, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 10,
          },
        },
          h('div', { style: { fontSize: 12, fontWeight: 600, color: C.muted } }, '目标分子'),
          h('div', { style: { display: 'flex', gap: 6 } },
            field(s.draftInput, (v) => setState({ draftInput: v }), { placeholder: 'SMILES' }),
            button('取画板', async () => {
              const smiles = await readCanvas(props.frameRef.current)
              if (!smiles) { say('画板是空的', 'warn'); return }
              setState({ draftInput: smiles, smiles })
            }, { id: 'retro-take' })),
          button('开始逆合成', () => { void run() }, { id: 'retro-run', primary: true, big: true, busy: s.retroBusy }),
          h('div', { style: { fontSize: 11, color: C.muted, lineHeight: 1.7 } },
            '迭代 100 · 每步展开 50 · 启用价值函数。',
            h('br'),
            '首次规划要加载模型，慢是正常的；后续会快很多。')),
        h('div', { style: { flex: 1, minWidth: 0, padding: 12, overflow: 'auto' } }, body),
      )
    }

    /* ------------------------------------------------------------------ */
    /* 工作台浮层                                                          */
    /* ------------------------------------------------------------------ */

    const TABS = [
      { id: 'draw', label: '画板' },
      { id: 'analyze', label: '分析' },
      { id: 'retro', label: '逆合成' },
    ]

    function Workbench() {
      const s = useStore()
      const frameRef = React.useRef(null)
      const dragRef = React.useRef(null)
      const [ready, setReady] = React.useState(false)

      React.useEffect(() => {
        if (!s.open) { setReady(false); return undefined }
        let tries = 0
        const timer = setInterval(() => {
          tries += 1
          if (ketcherApi(frameRef.current)) { setReady(true); clearInterval(timer) }
          else if (tries > 80) { say('画板未能就绪', 'warn'); clearInterval(timer) }
        }, 400)
        return () => clearInterval(timer)
      }, [s.open])

      // 能力自检：只做一次，用来在界面上诚实标注"后端有没有装好"
      React.useEffect(() => {
        if (!s.open || s.caps) return
        let alive = true
        fetch(STATUS_URL).then(r => r.json()).then(caps => { if (alive) setState({ caps }) }).catch(() => {})
        return () => { alive = false }
      }, [s.open, s.caps])

      if (!s.open) return null

      const onHeaderDown = (e) => {
        if (s.maximized) return
        if (e.target.closest?.('button')) return
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

      const maximized = s.maximized
      const cardStyle = {
        position: 'fixed',
        left: maximized ? 8 : (s.x ?? Math.max(16, Math.round((window.innerWidth - s.w) / 2))),
        top: maximized ? 8 : (s.y ?? 56),
        width: maximized ? window.innerWidth - 16 : s.w,
        height: maximized ? window.innerHeight - 16 : s.h,
        zIndex: 9999, display: 'flex', flexDirection: 'column',
        background: C.bg, color: C.text,
        border: `1px solid ${C.border}`, borderRadius: 12,
        boxShadow: '0 16px 40px rgba(0,0,0,.22)', overflow: 'hidden',
        fontFamily: 'system-ui, -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
      }

      const tabBtn = (tab) => h('button', {
        key: tab.id, type: 'button',
        'data-chem-tab': tab.id,
        onClick: () => setState({ tab: tab.id }),
        style: {
          padding: '5px 14px', fontSize: 13, cursor: 'pointer',
          border: 'none', borderBottom: `2px solid ${s.tab === tab.id ? C.accent : 'transparent'}`,
          background: 'transparent', color: s.tab === tab.id ? C.accent : C.muted,
          fontWeight: s.tab === tab.id ? 600 : 400,
        },
      }, tab.label)

      const tone = s.statusTone === 'err' ? C.err : s.statusTone === 'ok' ? C.ok : s.statusTone === 'warn' ? C.warn : C.muted

      // 三个页签都保持挂载，只切显示 —— 卸载 iframe 会重载 Ketcher（很慢）。
      const panelStyle = (id) => ({
        display: s.tab === id ? 'flex' : 'none',
        flex: 1, minHeight: 0, flexDirection: 'column',
      })

      return h('div', { style: cardStyle, 'data-chem-panel': 'true', 'data-chem-tab-active': s.tab },
        // 标题栏
        h('div', {
          onPointerDown: onHeaderDown,
          style: {
            display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px',
            cursor: maximized ? 'default' : 'move', userSelect: 'none', flex: '0 0 auto',
            background: C.header, borderBottom: `1px solid ${C.border}`,
          },
        },
          h('strong', { style: { fontSize: 13 } }, '化学工作台'),
          h('span', { style: { fontSize: 10, color: C.faint, border: `1px solid ${C.border}`, borderRadius: 4, padding: '0 4px' } }, 'dsh-mol'),
          h('span', { style: { fontSize: 11, color: tone, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } },
            s.status || (ready ? '' : '画板加载中…')),
          h('button', {
            type: 'button', title: maximized ? '还原' : '最大化', 'data-chem-max': 'true',
            onClick: () => setState({ maximized: !maximized }),
            style: { border: 'none', background: 'transparent', cursor: 'pointer', fontSize: 13, color: C.muted },
          }, maximized ? '❐' : '⛶'),
          h('button', {
            type: 'button', onClick: () => store.close(), 'aria-label': '关闭工作台',
            style: { border: 'none', background: 'transparent', cursor: 'pointer', fontSize: 14, color: C.muted },
          }, '✕')),
        // 页签
        h('div', {
          style: { display: 'flex', alignItems: 'center', gap: 2, padding: '0 8px', background: '#ffffff', borderBottom: `1px solid ${C.border}`, flex: '0 0 auto' },
        }, TABS.map(tabBtn)),
        // 页体
        h('div', { style: { flex: 1, minHeight: 0, display: 'flex' } },
          h('div', { style: panelStyle('draw') }, h(DrawTab, { s, frameRef })),
          h('div', { style: panelStyle('analyze') }, h(AnalyzeTab, { s, frameRef })),
          h('div', { style: panelStyle('retro') }, h(RetroTab, { s, frameRef })),
        ),
      )
    }

    /* ------------------------------------------------------------------ */
    /* 输入框左侧的工作台按钮                                                */
    /* ------------------------------------------------------------------ */

    function WorkbenchButton(props) {
      // session 作用域插槽会自动注入会话标准工具包（含 sessionId）
      const sessionId = props?.sessionId
      const s = useStore()
      const active = s.open && s.sessionId === (sessionId ?? null)
      return h('button', {
        type: 'button',
        title: '化学工作台：画分子 / RDKit 分析 / 逆合成',
        'aria-label': '化学工作台',
        'data-chem-draw': 'true',
        onClick: () => store.toggle(sessionId),
        style: {
          display: 'inline-flex', alignItems: 'center', gap: 5,
          height: 28, padding: '0 8px', borderRadius: 6, cursor: 'pointer',
          border: `1px solid ${active ? 'var(--dsh-accent, #4d6bfe)' : 'transparent'}`,
          background: active ? 'var(--dsh-accent-weak, rgba(77,107,254,.12))' : 'transparent',
          color: 'inherit', fontSize: 12,
        },
      },
        h('svg', {
          width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
          strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': 'true',
        },
          h('path', { d: 'M9 3h6M10 3v6.2L5.4 17.4A2 2 0 0 0 7.2 20h9.6a2 2 0 0 0 1.8-2.6L14 9.2V3' }),
          h('path', { d: 'M7.6 14.5h8.8' }),
        ),
        h('span', null, '工作台'),
      )
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
        WorkbenchButton,
      ))

      ctx.slots.inject('shell.overlay', () => ctx.slots.register(
        { name: 'shell.overlay', id: 'chem-workbench', order: 40 },
        Workbench,
      ))
    }

    return { apply, inject }
  },
})
