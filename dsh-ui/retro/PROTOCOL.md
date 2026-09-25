# 逆合成桥接协议（dsh-ui ⇄ retro_star_bridge.py）

> 这份文件是给**写宿主半边路由的人**看的：一个 JSON 进、一个 JSON 出，没有别的花样。
> 面向用户的安装/解释文档在 [`docs/RETROSYNTHESIS.md`](../../docs/RETROSYNTHESIS.md)。

## 怎么拉起它

```js
import { spawn } from 'node:child_process'

// PYTHON 必须是**装了 retro_star / rdkit / torch 的那个解释器**，
// 不是宿主的 node，也不一定是系统 python3。优先取环境变量（例如 RETRO_STAR_PYTHON），
// 退化到 'python3'。
const child = spawn(PYTHON, [bridgePath], { stdio: ['pipe', 'pipe', 'pipe'] })

let out = ''
let err = ''
child.stdout.on('data', (c) => { out += c })
child.stderr.on('data', (c) => { err += c })   // 日志/警告在这里，当调试信息留着
child.on('close', (code) => {
  // 1) 先解析 stdout —— 不论退出码是多少，它都是一个完整 JSON
  // 2) 再按 payload.code 分支
})
child.stdin.end(JSON.stringify(request))
```

三条注意事项：

1. **stdout 是协议通道**，桥接脚本已经把 fd 1 接到 stderr 了，所以里面**只有**那一个 JSON。
2. **不要传命令行参数**（桥接模式下一律忽略；传了也不报错）。
3. **退出码不等于成败**，必须看 `ok`：

| 退出码 | 含义 | 该怎么办 |
|---|---|---|
| `0` | 桥接脚本正常跑完（**包括** `retro_not_configured` / `retro_timeout` / `retro_no_route` / `retro_backend_error`） | 按 `code` 展示对应 UI |
| `2` | `bad_request`：请求本身非法（调用方 bug） | 记日志 + 修请求 |
| `1` | `internal_error`：桥接脚本自己崩了 | 记日志，把 stderr 附上 |

## 请求字段

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `smiles` | string | **必填** | 目标分子 SMILES（RDKit 必须能解析） |
| `iterations` | int | `100` | A* 迭代上限，范围 1–100000 |
| `expansion_topk` | int | `50` | 每步保留的模板条数，范围 1–1000 |
| `use_value_fn` | bool | `true` | 是否加载价值网络；`false` 时不需要 `saved_models/best_epoch_final_4.pt` |
| `max_routes` | int | `5` | 期望路线条数；**Retro* 每次只给 1 条**（见下） |
| `timeout_s` | number | `300` | 加载+搜索的总超时，范围 1–86400 |
| `retro_home` | string | 见下 | Retro* 仓库根目录（含 `retro_star/` 包的那一层） |
| `gpu` | int | `-1` | `-1` = CPU；`>=0` = 用第几块 GPU |
| `compat_shims` | bool | `true` | 打 numpy 兼容垫片（`np.bool = bool`），见 `docs/RETROSYNTHESIS.md` 的已知风险 |

`retro_home` 解析优先级：环境变量 `RETRO_STAR_HOME` → 请求里的 `retro_home` → 脚本内置默认路径。
响应里的 `retro_home_source` 会告诉你最后用了哪个（`env:RETRO_STAR_HOME` / `request:retro_home` / `builtin_default`）。

## 成功响应

```jsonc
{
  "ok": true,
  "backend": "retro_star",
  "target": "CCOC(=O)c1ccccc1",
  "elapsed_ms": 1184,                 // 整个进程的墙钟耗时（含 import 与模型加载）
  "retro_home": "/path/to/retro_star-master",
  "iterations_requested": 100,
  "iterations_used": 7,               // 后端实际迭代次数（planner.plan() 的 'iter'）
  "expansion_topk": 50,
  "use_value_fn": true,
  "max_routes_requested": 5,
  "backend_search_time_s": 1.234,     // 后端自报的搜索耗时（不含加载）
  "routes": [                         // 长度 0 或 1；**没有路线时不会 ok:true**
    {
      "score": 0.1224564282529819,    // exp(-cost)，整条路线的模板概率乘积估计
      "cost": 2.1,                    // A* 累计代价 Σ(-ln p)
      "steps": 2,                     // 反应步数（后端 route_len）
      "leaf_count": 3,
      "tree": { /* 见下 */ },
      "route_string": "…>0.5300>CCO.CC(=O)O|CCO>0.2000>CC.O"   // 后端原话，留作对账
    }
  ],
  "notes": ["…"],                     // 给用户看的补充说明（例如为什么只回 1 条路线）
  "missing_optional": []              // 只在 use_value_fn=false 且价值网络缺失时出现
}
```

### `tree` 节点

```jsonc
{
  "smiles": "CCOC(=O)c1ccccc1",
  "children": [ /* 反应物 —— 父 = 产物，子 = 反应物，方向就是逆合成方向 */ ],
  "depth": 0,                          // 0 = 目标分子
  "score": 0.53,                       // 该节点那一步的模板概率 ≈ exp(-cost)，无子节点时为 null
  "is_starting_material": false,       // true = 文献/商业可得砌块（等价于"叶子"）
  "role": "target" | "intermediate" | "building_block" | "repeat",
  "truncated": true                    // 只在 role == "repeat" 时出现（回环兜底）
}
```

用 `role` 上色最省事：`target` 一个颜色、`intermediate` 一个颜色、`building_block` 一个颜色。

## 失败响应

| `code` | 退出码 | 何时出现 | 关键字段 |
|---|---|---|---|
| `retro_not_configured` | 0 | 数据文件缺失（**最常见的路径**） | `missing[]`、`missing_optional[]`、`checked[]`、`retro_home`、`setup`、`doc`、`heavy_imports_skipped` |
| `retro_timeout` | 0 | 超过 `timeout_s` | `timeout_s`、`stage`、`suggestions[]` |
| `retro_no_route` | 0 | 跑完了但搜不到路线 | `iterations`、`suggestions[]` |
| `retro_backend_error` | 0 | 依赖缺失 / 源码坏了 / 版本不兼容 / 路线串格式不认识 | `stage`（`preflight_import`/`import_retro_star`/`planner_init`/`search`/`route_parse`）、有时 `missing_module`、`raw_routes` |
| `bad_request` | 2 | stdin 不是 JSON / 缺 `smiles` / 类型错 / 超范围 / SMILES 解析不了 | `field`、`detail`、`expected_request` |
| `internal_error` | 1 | 桥接脚本自身未知异常 | `message`（完整栈只在 stderr） |

所有失败都是**中文人话** `message` + 可选 `suggestions[]` / `setup`，**从不把栈丢给上层**。

`retro_not_configured` 的展示建议：直接把 `message` 当正文、`setup` 当等宽代码块给用户，
别自己复述缺哪些文件 —— 那是脚本算出来的，复述容易漂。

## 关于 `max_routes`

Retro* 的 `RSPlanner.plan()` 每次只返回**一条**最优路线（`retro_star/api.py:72-77` →
`alg/mol_tree.py:92` `get_best_route`）。桥接照实返回 `routes` 长度 1，并在 `notes` 里说明；
请求要 5 条也只回 1 条 —— **这不是被截断，是后端能力边界**。
将来换多路线后端（AiZynthFinder 之类）时，协议不变，`routes` 变长即可。

## 自检

```bash
python3 dsh-ui/retro/selfcheck.py        # 协议自检：191 项，零依赖，不需要 Retro* 数据
python3 dsh-ui/retro/retro_star_bridge.py --doctor   # 数据/依赖诊断：人看的 JSON
```
