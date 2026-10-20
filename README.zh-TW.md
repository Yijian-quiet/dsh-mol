<div align="center">

# dsh-mol · 化學工作台

**在 AI agent 的聊天框旁邊，放一張能畫分子的畫板 + 一個本地 RDKit 工作台。**

畫結構 → 點一下 → 分子式／分子量／logP／TPSA／類藥性／結構警示**當場算出來** →
把結構丟進對話，讓 agent 接著往下講。

純 RDKit，**零網路、零 API key、零外部服務**。也可作為 stdio MCP 服務被 Claude Code / Codex 等直接呼叫。

[![ci](https://github.com/Yijian-quiet/dsh-mol/actions/workflows/ci.yml/badge.svg)](https://github.com/Yijian-quiet/dsh-mol/actions/workflows/ci.yml)
[![Awesome DSH Plugin](https://awesome-dsh-plugin.com/badge.svg)](https://awesome-dsh-plugin.com)
[![M8ven Score](https://m8ven.ai/badge/mcp/yijian-quiet/dsh-mol)](https://m8ven.ai/mcp/yijian-quiet/dsh-mol?s=readme)
![python](https://img.shields.io/badge/python-3.9%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![tests](https://img.shields.io/badge/tests-71%20passed-brightgreen)
![network](https://img.shields.io/badge/network-none%20required-success)

[中文](README.md) | [English](README.en.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Français](README.fr.md) | **繁體中文**

<img src="docs/workbench-analyze.png" alt="化學工作台 · 分析頁籤" width="820">

</div>

---

## 30 秒看懂

| | |
|---|---|
| 🎨 **畫分子** | 聊天框旁一個按鈕 → Ketcher 畫板浮動視窗。**聊天不會被擠掉**，畫完一鍵插進輸入框 |
| ⚡ **即時分析** | 分子式、MW、精確質量、logP、TPSA、HBD/HBA、環數、Fsp³、立體中心 —— 本機 RDKit **現算**，不走模型、不等 LLM |
| 💊 **像不像藥** | Lipinski / Veber 逐條判定、QED、PAINS / BRENK 結構警示、Murcko 骨架 |
| 🧹 **髒資料急救** | 驗證（白話錯誤 + 字元定位）、標準化（逐步記錄改了什麼）、去重複、批次清洗 |
| 🧭 **逆合成** | 頁籤已就位，後端可插拔（目前接 Retro*）。**沒裝好模型就照實說沒裝好，絕不編一條路徑出來** |
| 🔌 **兩種用法** | 圖形工作台給人用；同一套核心又透過 MCP 給 agent 用 —— **一份實作，兩個入口** |

> 順帶說個背景：npm 上確認有 **618 個** DSH 外掛，其中**化學／材料／分子方向是 0 個**。
> 這個儲存庫就是來填這個空格的。

---

## 快速開始

```bash
# 1) 裝核心 + MCP 適配層（已上 PyPI）
pip install 'dsh-mol[mcp]'
#    裝不上時退回 git：pip install "dsh-mol[mcp] @ git+https://github.com/Yijian-quiet/dsh-mol.git"

# 2) 把外掛裝進你的 DSH profile（無需 npm 帳號，pnpm 支援 git 子目錄）
dsh plugin --profile web add 'github:Yijian-quiet/dsh-mol#path:dsh-bundle'
dsh plugin --profile web add 'github:Yijian-quiet/dsh-mol#path:dsh-ui'   # ← 圖形工作台

# 3) 打開 DSH Web，點輸入框左邊的「工作台」
```


> ✅ **已發佈到 PyPI**：`pip install 'dsh-mol[mcp]'`（2026-09-26 上線，裝完 `dsh-mol-mcp --selftest` 可自我檢查）。
> ⏳ **npm 尚未發佈**，所以外掛本身仍用 `dsh plugin add github:…` 安裝 —— 不影響任何功能。
>
> ✅ 本外掛已被 [dsh 外掛市集](https://awesome-dsh-plugin.com) 收錄（`dsh-mol#dsh-ui` 與
> `dsh-mol#dsh-bundle` 兩條，分類 `tools`），也可以直接在市集裡裝。

工作台需要本地有一個能 `import rdkit` 的 `python3`；畫板用的是 [Ketcher](https://github.com/epam/ketcher) 靜態建置，**在瀏覽器本地渲染，不經過任何後端**。

<details>
<summary>只想用命令列／其他 MCP 客戶端？</summary>

```bash
dsh-mol-mcp --selftest          # 先自我檢查（不需要任何 MCP 客戶端）
```

```yaml
# 手動疊加 patch，stdio 傳輸，純本地
- insert:
    - id: dsh-mol
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: chem
        transport: stdio
        command: python3
        args: ['-m', 'dsh_mol_mcp.server']
        env:
          PYTHONPATH: /path/to/dsh-mol/src
          MOL_OUT: /path/to/out
```

工具名會以 `mcp__chem__chem_check_smiles` 之類出現在模型側。
</details>

---

## 工作台長什麼樣

三個頁籤，一個分子：

<table>
<tr>
<td width="33%"><img src="docs/workbench-draw.png" alt="畫板頁籤"><br><b>① 畫板</b><br>Ketcher 全功能畫板（浮動視窗可拖曳、可最大化）。<b>貼一段 SMILES 就能直接畫上去</b>（或點「讀剪貼簿」），畫完點「插入到對話」把 SMILES 寫進輸入框 —— <b>文字只有結構本身，不夾帶任何內部路徑</b>。</td>
<td width="33%"><img src="docs/workbench-analyze.png" alt="分析頁籤"><br><b>② 分析</b><br>左邊輸入／按鈕，右邊出數。基礎性質 + 類藥性 + 結構警示 + 骨架一次給全，全部是本地 RDKit 現算。</td>
<td width="33%"><img src="docs/workbench-retro.png" alt="逆合成頁籤"><br><b>③ 逆合成</b><br>目標分子 → 多步路徑。未裝模型資料時，<b>它告訴你要下載什麼、放哪裡</b>，而不是假裝算過。</td>
</tr>
</table>

### 為什麼圖不畫在面板裡？

因為**圖應該跟著文字解釋走**。工作台裡那張縮圖只是讓你確認「算的是不是這個分子」；
真正的結構圖由 agent 在回覆裡內嵌畫出來（`read_image`），旁邊就是它對這分子的解釋。

這個選擇是被使用者否掉兩版之後定下來的：
先是「面板佔掉主區域把聊天擠沒了」，再是「在畫板裡再畫一張預覽圖沒什麼用」。
現在是**聊天保持原樣，工作台在旁邊**。

---

## 為什麼不是「包一層 RDKit」

因為直接包一層會給 AI agent 三個坑，這三個坑在科研場景裡都會真實咬人：

### 1. RDKit 解析失敗時**不拋異常**，只回傳 `None`

失敗原因寫在 C++ 層的 stderr。天真包裝下，模型只會拿到一個空洞的 `None`，完全不知道錯在哪。
本工具把 RDKit 日誌改道、捕捉、**翻譯成白話**，並在能定位時給出**字元位置**：

```jsonc
// chem_check_smiles("C1CC")
{ "level": "error",
  "diagnostics": [{ "code": "unclosed_ring",
                    "message": "环闭合标记没有配对：SMILES 里的成环数字（如 C1...C1）出现次数必须是偶数" }] }

// chem_check_smiles("CC(=O)O)")   ← 多餘的右括號，定位到第 7 個字元
{ "level": "error", "position": 7,
  "diagnostics": [{ "code": "extra_paren", "message": "多余的右括号：) 比 ( 多" }] }
```

### 2. `MolFromSmiles("")` 回傳的不是 `None`，而是**一個 0 原子的「空分子」**

天真寫法會把空輸入判成**合法**。而 `"   "`（純空白）**又會**回傳 `None`——
同一個函式，兩種空輸入兩種行為。本工具在領域層統一攔住。

### 3. 結果要**分三級**，不是「成功／失敗」

`[Fe+9]` 能解析，但電荷荒謬。這類應該**警告**而不是拒絕：

| level | 含義 |
|---|---|
| `ok` | 乾淨通過 |
| `warn` | 能解析，但結構可疑（異常電荷、芳香性可疑…），附帶原因 |
| `error` | 解析失敗，附白話原因 + 可定位的字元位置 |

**並且：批次介面絕不靜默丟資料。** 每一列都有明確歸屬（ok / warn / failed），
失敗逐條列出——科研資料裡「悄悄少了兩列」比報錯危險得多。

### 診斷文字支援中英雙語

預設中文；英文環境設一個環境變數即可：

```bash
export MOL_LANG=en        # zh（預設）/ en
```

> ⚠️ **契約是 `code`，不是文字。** `code`（`unclosed_ring` / `valence` …）與語言無關，
> 也**不隨語言改變 level / position / canonical**——有專門的回歸案例鎖住這一點。

---

## 工具一覽（13 個，全部純本地）

| 工具 | 作用 |
|---|---|
| `chem_check_smiles` | 驗證 + 正規化，三級結果 + 白話原因 + 字元定位 |
| `chem_properties` | 分子式 / MW / 精確質量 / logP / TPSA / HBD / HBA / 環數 / 立體中心 |
| `chem_analyze` | 一次給全：基礎性質 + 類藥性 + 結構警示 + Murcko 骨架 |
| `chem_druglikeness` | Lipinski / Veber 逐條判定、QED、PAINS / BRENK 結構警示 |
| `chem_draw_molecule` | 畫結構圖（PNG/SVG，可標原子編號、可標示子結構），回傳**檔案路徑** |
| `chem_draw_grid` | 多分子拼圖（簡報／論文附圖），壞條目跳過但逐條記錄 |
| `chem_convert` | smiles / inchi / inchikey / mol / sdf / formula 互轉 |
| `chem_bioseq` | 肽／核酸序列、HELM 或 IDT 記法 → 分子（給出正規 SMILES，可續接其他工具）；**kind 必須明確指定** |
| `chem_standardize` | 去鹽 / 去金屬 / 中和 / 正規化，**逐步記錄改了什麼** |
| `chem_dedupe` | 按正規化結構去重複，給出重複分組 |
| `chem_substructure_match` | SMARTS 子結構匹配，回傳原子索引 |
| `chem_similarity` | 指紋相似度（morgan / rdkit / maccs） |
| `chem_batch_clean` | 批次清洗一欄 SMILES，輸出計數摘要 + 失敗清單（可寫 CSV） |

工作台的「分析」頁籤跟這些工具**共用同一個 `chemcore`** —— 不存在「介面上算一套、agent 算另一套」的漂移。

> `chem_core` 還有一個 `python3 -m chemcore.cli` 的 JSON 入口（一行 JSON 進、一行 JSON 出），
> 工作台的即時數字就是走它。這是「給 AI 的工具」和「給人的介面」共用一份實作的接縫。

## 大分子（肽／核酸）怎麼處理

Ketcher 的大分子編輯器畫出來的肽／核酸**沒有 SMILES**，只有序列或 HELM。`chem_bioseq`
把它們解析成分子，並回傳一個**正規 SMILES** —— 於是上面所有工具（properties / analyze /
draw / convert）都能接著用同一個分子算下去。

```python
cc.parse_bioseq("GAVL", kind="peptide")            # 肽，1 字母碼 → C16H30N4O5 / 358.4
cc.parse_bioseq("Gly-Ala-Val", kind="peptide3")    # 肽，3 字母碼 → 三肽 C10H19N3O4 / 245.3
cc.parse_bioseq("AUGC", kind="rna")                # RNA → C38H48N15O26P3 / 1223.8
cc.parse_bioseq("ATGC", kind="dna")                # DNA → C39H50N15O22P3 / 1173.8
cc.parse_bioseq("PEPTIDE1{G.A.V.L}$$$$")           # HELM：前綴自帶類型，auto 即可
```

### 為什麼要明確給 `kind`

因為 `A/T/G/C` **既是胺基酸字母也是鹼基字母**（Ala/Thr/Gly/Cys ↔ 腺嘌呤／胸腺嘧啶／鳥嘌呤／胞嘧啶）。
同一段 `ATGC` 按肽算是 `C12H22N4O6S`、按 RNA 算是 `C39H50N15O26P3`、按 DNA 算是
`C39H50N15O22P3` —— 三個完全不同的分子，而 RDKit 的 `MolFromSequence` **預設只按肽解析、
不報任何錯**。

所以本工具的規矩是：

- **裸序列必須明確指定 `kind`**（`auto` 也要求），否則直接報錯 ——
  「無法判斷 … 是肽還是核酸，已拒絕解析」。**絕不替呼叫方選預設值**：
  選錯是「化學上完全錯誤且沒有任何跡象」，比報錯危險得多。
- `auto` 能確定推斷的**只有**兩類自帶類型資訊的記法：**HELM**（它的 `PEPTIDE1{` / `RNA1{` / `DNA1{` 前綴是**宣告**，不是猜）與 **IDT**（糖型前綴 `r`/`d` 同樣是宣告）。除此之外 `auto` 一律拒絕 —— 裸序列（`ACGU` / `ATGC` / `GAVL`）沒有類型資訊，不會拿到預設值。

> 兩個相關的 RDKit 坑（都實測過，本專案都繞開了）：**DNA 的 flavor 是 6 不是 3**
> （3 是「給 RNA 加 5' 磷酸帽」，會多接一個磷酸）；而 **3 字母胺基酸碼 RDKit 2023.09.6
> 根本不支援** —— 它會把 `Gly-Ala-Val` 按大小寫不敏感的單字母讀成 9 肽（MW 890.1）且
> 不報錯，所以 `peptide3` 由本層自己翻譯成 1 字母碼再算。序列裡的空白也會被 RDKit
> 悄悄變成額外的氫，本層先正規化並把這次改動記進 `warnings`。

### IDT 記法（Ketcher 匯出的核酸）

Ketcher 的大分子編輯器匯出核酸時給的是 **IDT 記法**（實測畫 RNA 得到 `rArCrGrTrU/3Phos/`）：
殘基帶糖型前綴（`r`=核糖、`d`=去氧、`m`=2′-O-甲基、`+`=LNA），還有 `/3Phos/`、`/5Phos/` 這類末端修飾。
`chem_bioseq` 直接吃它 —— `kind` 取值因此多了 `idt`（`auto` 也認：糖型前綴是**宣告**，不是猜）。

**但只在無損時才轉換。** 糖型統一、又沒有修飾，才轉成純序列交給 RDKit；只要有一點它表達不了，就拒絕並說明原因：

```python
cc.parse_bioseq("rArCrGrTrU", kind="idt")         # → RNA ACGTU / MW 1543.997（糖型統一、無修飾，無損）
cc.parse_bioseq("rArCrGrTrU/3Phos/", kind="idt")  # ✗ 拒絕：硬轉會靜默少掉一個 3′ 磷酸（≈79.97 Da）
```

拒絕時一律指名道姓，不含糊：

- 末端／骨架修飾：`/3Phos/`、`/5Phos/`、`*`（硫代磷酸）
- 非標準糖型：`m`（2′-O-甲基）、`+`（LNA）
- 混糖型：`rArCdT`（同一串裡既有核糖又有去氧 —— RDKit 一次只能表達一種）
- 與呼叫方給的 `kind` 衝突：`rArCrG` + `kind="dna"`（前綴宣告的是 RNA）

理由和上面一樣：硬轉不是「近似」，是**化學上完全錯誤卻看不出任何異常** —— 分子量少了 79.97 Da，介面上卻毫無異樣。

## Python API

```python
import chemcore as cc

cc.check("C1CC").diagnostics[0].message   # '环闭合标记没有配对：…'
cc.properties("CC(=O)Oc1ccccc1C(=O)O")    # {'formula': 'C9H8O4', 'mw': 180.159, …}
cc.analyze("CC(=O)Oc1ccccc1C(=O)O")       # + QED / Lipinski / PAINS 警示 / Murcko 骨架
cc.draw("CCO", atom_indices=True)         # {'path': '…/CCO.png', …}
cc.standardize("CC(=O)[O-].[Na+]")        # {'output': 'CC(=O)O', 'changes': [...]}
cc.batch_clean(["CCO", "C1CC"])           # {'ok': 1, 'failed': 1, 'failed_items': [...]}
cc.parse_bioseq("GAVL", kind="peptide")   # 肽／核酸／HELM → 分子 + 正規 SMILES（kind 必填）
```

## 實例：清洗一張「髒」的單體表

[`examples/monomer_cleanup.py`](examples/monomer_cleanup.py) 拿一張刻意做髒的單體表
（同一分子兩種寫法、一個鈉鹽、一個環未閉合錯字、一個價鍵超限、一個離譜電荷）跑完整條鏈：

```bash
python3 examples/monomer_cleanup.py
```

它報出 11 筆通過、1 筆警告、2 筆失敗，把重複項合併、逐步展示去鹽與中和的每一步，
並把能畫的 12 個結構畫出來、把跳過的 2 個連原因一起列出來。

![批次畫圖（中文圖說）](docs/monomers.png)

## 逆合成

逆合成頁籤的後端是**可插拔**的：外掛用 `child_process` 起一個「餵 JSON 進 stdin、
讀 JSON 出 stdout」的行程，預設指向儲存庫裡的 Retro* 橋接腳本。

- 後端**沒裝好**時：回傳結構化診斷（缺哪些檔案、去哪下、放哪裡），介面照實顯示 ——
  **不會編造路徑**，也不會拿「看起來像」的東西糊弄
- 想換後端（AiZynthFinder / 自研的 RetroChimera / 你們組的私服）：只要守著同一套
  stdin/stdout 協定，把 `retroCommand` 指過去即可

安裝 Retro*（原始碼 + 模型資料，GB 級）見 **[docs/RETROSYNTHESIS.md](docs/RETROSYNTHESIS.md)**。

## 測試

```bash
PYTHONPATH=src python3 tests/run_tests.py    # 71 個核心案例（零相依，不需要 pytest）
PYTHONPATH=src python3 tests/mcp_smoke.py    # MCP 協定級冒煙（真起服務、真呼工具）
bash tests/run_all.sh                        # 上面兩件 + 自測，一把梭
```

介面用 Playwright 無頭驗收（39 條斷言，涵蓋「打開工作台後聊天還能不能用」「數字是不是真算的」
「後端沒裝好時會不會編路徑」）：

```bash
dsh web --port 3081 --no-open > /tmp/chemver.log 2>&1 &
CHEM_BASE=http://127.0.0.1:3081 \
CHEM_TOKEN=$(grep -o 'token=[^ ]*' /tmp/chemver.log | cut -d= -f2) \
node dsh-ui/tests/verify-ui.cjs
```

> 別拿你正在用的那個埠做實驗 —— 另起一個實例，跑完就關。

## 設計原則

1. **零網路**：所有計算在本行程完成。
2. **零額外相依**：核心只用 RDKit；測試連 pytest 都不需要。
3. **失敗說白話**：把 RDKit 的英文 C++ 日誌翻譯成分級診斷。
4. **不靜默丟資料**：批次介面逐條報告。
5. **參數必帶口徑**：logP 會標註是 Crippen 估算值，`mw` / `exact_mw` 分別說明含義。
6. **落盤回傳路徑**：圖片不塞進協定載荷，而是寫檔回傳路徑——可重現、可進版本庫、可寫論文。
7. **沒有的東西就說沒有**：沒有實驗值、沒有活性預測、逆合成後端沒裝就說沒裝。

## 路線圖

- **v0.1（目前）**：13 個純本地工具 + 化學工作台（畫板 / 分析 / 逆合成框架）
- **v0.2**：逆合成後端真正跑通（Retro* 資料就位）+ 工作台裡直接看路徑圖
- **v0.3**：更多分析卡片（pKa / 構形 / 藥代性質），視覺化升級為「結構 + 圖表」
- **未定**：影像→結構辨識（OCSR）需要數百 MB 模型，**不屬於「基礎輕工具」**，會做成可插拔後端

## 邊界

- 這裡**沒有**實驗值。`logP`、`TPSA`、`QED` 都是計算／估算值，不替代實驗測量。
- 結構警示**不等於**「有毒」：它只是「這類子結構值得人工看一眼」。
- 這裡**沒有**影像辨識、名稱→結構（OPSIN 之類）。
- SMARTS 匹配是結構匹配，**不等於**化學反應性判斷。
- **大分子只涵蓋標準單體**：`peptide3` 只認 20 種標準胺基酸的三字母碼；修飾殘基、非天然
  單體、醣鏈等在 RDKit 這一層沒有可靠支援。另外實測 RDKit 2023.09.6 的 HELM 解析
  **不支援 `DNA1` 與 `CHEM1`**（直接回傳 None），碰到時我們明確報錯，而不是給個空結果。
- **序列類型必須由你指定**：`A/T/G/C` 在肽與核酸裡都合法，裸序列有歧義時我們**拒絕解析**，
  不提供預設值（詳見上面「大分子」一節）。
- **InChI 不支援 `*` 虛原子**：聚合物 RU-SMILES（如 `*OCCOC(=O)c1ccc(C(=O)O*)cc1`）**轉不了** InChI / InChIKey。
  我們**不會靜默回傳空字串**（RDKit 會），而是明確報錯並建議用 canonical SMILES 做唯一識別 ——
  因為這個領域最常見的輸入正好就是帶 `*` 的。
- 這是 **0.x 早期版本**：API 可能變；歡迎提 issue。

## 儲存庫結構

```
src/chemcore/          純 RDKit 核心（唯一的事實來源）+ JSON CLI 入口
src/dsh_mol_mcp/       stdio MCP 適配層（13 個工具）
dsh-ui/                化學工作台（DSH 客戶端外掛：宿主半邊 + 瀏覽器半邊）
dsh-ui/retro/          逆合成後端橋接（可插拔，預設 Retro*）
dsh-bundle/            DSH 組合包（只貢獻設定，指向上面的 MCP 服務）
dsh/                   手動疊加用的 patch（寫死本機路徑）
tests/                 零相依測試 + MCP 協定冒煙 + Playwright 介面驗收
docs/                  示範圖與專題文件
```

## 環境需求（一個真實的坑）

**MCP Python SDK 必須 1.x**：

```bash
pip install 'mcp>=1.0,<2'
```

SDK **2.x 把 `FastMCP` 改名成了 `MCPServer`**，API 有破壞性變更。
我們的 `[mcp]` extra 已釘住 `<2`；如果你手工裝了 2.x，`dsh-mol-mcp` 會**明確告訴你怎麼辦**
（而不是甩一條 traceback）—— 這個坑是 CI 在乾淨環境裡實測出來的，不是推測。

## 致謝

- [RDKit](https://www.rdkit.org/) —— 整個化學核心
- [Ketcher](https://github.com/epam/ketcher) —— 畫板（本地 wasm 渲染，不連網）
- [Retro*](https://github.com/binghong-ml/retro_star)（ICML 2020）—— 逆合成後端之一

## 授權

MIT

<!-- dsh-mol:test-count 71 -->
<!-- dsh-mol:tool-count 13 -->
<!-- dsh-mol:ui-assertions 39 -->
