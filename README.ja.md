<div align="center">

# dsh-mol · 化学ワークベンチ

**AI agent のチャット欄の隣に、分子を描けるキャンバスとローカルの RDKit ワークベンチを。**

構造を描く → ワンクリック → 分子式／分子量／logP／TPSA／ドラッグライクネス／構造アラートが**その場で出る** →
その構造を会話に投げれば、あとは agent が続きを話す。

純 RDKit。**ネットワークなし、API キーなし、外部サービスなし。** stdio MCP サーバーとして Claude Code / Codex などから直接呼び出せる。

[![ci](https://github.com/Yijian-quiet/dsh-mol/actions/workflows/ci.yml/badge.svg)](https://github.com/Yijian-quiet/dsh-mol/actions/workflows/ci.yml)
[![Awesome DSH Plugin](https://awesome-dsh-plugin.com/badge.svg)](https://awesome-dsh-plugin.com)
[![M8ven Score](https://m8ven.ai/badge/mcp/yijian-quiet/dsh-mol)](https://m8ven.ai/mcp/yijian-quiet/dsh-mol?s=readme)
![python](https://img.shields.io/badge/python-3.9%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![tests](https://img.shields.io/badge/tests-71%20passed-brightgreen)
![network](https://img.shields.io/badge/network-none%20required-success)

[中文](README.md) | [English](README.en.md) | **日本語** | [한국어](README.ko.md) | [Français](README.fr.md) | [繁體中文](README.zh-TW.md)

<img src="docs/workbench-analyze.png" alt="化学ワークベンチ · 分析タブ" width="820">

</div>

---

## 30 秒でわかる

| | |
|---|---|
| 🎨 **分子を描く** | チャット欄の隣のボタン → Ketcher キャンバスのオーバーレイ。**チャットは押しのけられない**。描き終えたらワンクリックで入力欄へ |
| ⚡ **即時分析** | 分子式、MW、精密質量、logP、TPSA、HBD/HBA、環数、Fsp³、不斉中心 —— ローカル RDKit が**その場で**計算する。モデルも LLM も待たない |
| 💊 **薬らしいかどうか** | Lipinski / Veber の逐条判定、QED、PAINS / BRENK 構造アラート、Murcko 骨格 |
| 🧹 **汚いデータの応急処置** | 検証（人間の言葉のエラー + 文字位置）、標準化（変更点を逐次記録）、重複排除、バッチクリーニング |
| 🧭 **逆合成** | タブは用意済みで、バックエンドは差し替え可能（現在は Retro*）。**モデルが入っていなければ入っていないと正直に言い、ルートを捏造することは絶対にない** |
| 🔌 **2 通りの使い方** | グラフィカルなワークベンチは人向け。同じコアが MCP 経由で agent にも届く —— **実装は一つ、入口は二つ** |

> 背景を一つ：npm には DSH プラグインが **618 個**あることを確認済みで、そのうち**化学／材料／分子系は 0 個**。
> このリポジトリはその空白を埋めるためにある。

---

## クイックスタート

```bash
# 1) コア + MCP アダプターを導入（PyPI 公開済み）
pip install 'dsh-mol[mcp]'
#    入らないときは git から：pip install "dsh-mol[mcp] @ git+https://github.com/Yijian-quiet/dsh-mol.git"

# 2) プラグインを DSH profile に入れる（npm アカウント不要。pnpm は git のサブディレクトリを扱える）
dsh plugin --profile web add 'github:Yijian-quiet/dsh-mol#path:dsh-bundle'
dsh plugin --profile web add 'github:Yijian-quiet/dsh-mol#path:dsh-ui'   # ← グラフィカルなワークベンチ

# 3) DSH Web を開き、入力欄の左にある「ワークベンチ」をクリック
```


> ✅ **PyPI に公開済み**：`pip install 'dsh-mol[mcp]'`（2026-09-26 公開。入れたあと `dsh-mol-mcp --selftest` で自己診断できる）。
> ⏳ **npm は未公開**なので、プラグイン自体は今も `dsh plugin add github:…` で入れる —— 機能が損なわれることはない。
>
> ✅ 本プラグインは [dsh プラグインマーケット](https://awesome-dsh-plugin.com) に掲載済み（`dsh-mol#dsh-ui` と
> `dsh-mol#dsh-bundle` の 2 件、カテゴリは `tools`）。マーケットから直接入れることもできる。

ワークベンチを使うには、ローカルに `import rdkit` できる `python3` が必要。キャンバスは [Ketcher](https://github.com/epam/ketcher) の静的ビルドで、**ブラウザ内でローカルにレンダリングし、バックエンドを一切通らない**。

<details>
<summary>コマンドラインだけで使いたい／別の MCP クライアントを使いたい？</summary>

```bash
dsh-mol-mcp --selftest          # まず自己診断（MCP クライアントは不要）
```

```yaml
# patch を手で重ねる。stdio 転送、完全ローカル
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

ツール名はモデル側には `mcp__chem__chem_check_smiles` のような形で現れる。
</details>

---

## ワークベンチの外観

タブは三つ、分子は一つ：

<table>
<tr>
<td width="33%"><img src="docs/workbench-draw.png" alt="キャンバスタブ"><br><b>① キャンバス</b><br>Ketcher の全機能キャンバス（オーバーレイはドラッグでき、最大化もできる）。<b>SMILES を貼り付ければそのまま描画できる</b>（「クリップボードを読む」でも可）。「会話に挿入」で SMILES を入力欄に書き込む —— <b>テキストは構造そのものだけで、内部パスは一切混ざらない</b>。</td>
<td width="33%"><img src="docs/workbench-analyze.png" alt="分析タブ"><br><b>② 分析</b><br>左に入力とボタン、右に数値。基礎的な性質 + ドラッグライクネス + 構造アラート + 骨格を一度に全部、すべてローカル RDKit のその場計算。</td>
<td width="33%"><img src="docs/workbench-retro.png" alt="逆合成タブ"><br><b>③ 逆合成</b><br>目的分子 → 多段ルート。モデルデータが未導入のときは、<b>何をダウンロードしてどこに置くかを教える</b>。計算したふりはしない。</td>
</tr>
</table>

### なぜ図をパネルの中に描かないのか

**図は、それを説明する文章に沿って動くべき**だから。ワークベンチの中のサムネイルは「計算したのはこの分子で合っているか」を確かめるためのものにすぎない。
本当の構造図は agent が返信の中にインラインで描き（`read_image`）、そのすぐ隣にその分子の説明が並ぶ。

この判断は、二つの版がユーザーに却下された末に固まった：
最初は「パネルがメイン領域を占領してチャットが潰れる」、次は「キャンバスの中にもう一枚プレビューを描いても意味がない」。
今は**チャットはそのままの配置で、ワークベンチが隣に**ある。

---

## なぜ RDKit を「ラップするだけ」ではだめなのか

ただ包んだだけでは、AI agent に三つの罠を渡すことになる。この三つは研究の現場で実際に噛みつく：

### 1. RDKit は解析に失敗しても**例外を投げず**、`None` を返す

失敗の理由は C++ 層の stderr に書かれる。素朴なラッパーでは、モデルは中身のない `None` だけを受け取り、どこが悪いのか一切わからない。
本ツールは RDKit のログを別経路に流して捕捉し、**人間の言葉に翻訳**し、特定できるときは**文字位置**を添える：

```jsonc
// chem_check_smiles("C1CC")
{ "level": "error",
  "diagnostics": [{ "code": "unclosed_ring",
                    "message": "环闭合标记没有配对：SMILES 里的成环数字（如 C1...C1）出现次数必须是偶数" }] }

// chem_check_smiles("CC(=O)O)")   ← 右括弧が一つ多い。7 文字目を指す
{ "level": "error", "position": 7,
  "diagnostics": [{ "code": "extra_paren", "message": "多余的右括号：) 比 ( 多" }] }
```

### 2. `MolFromSmiles("")` が返すのは `None` ではなく、**原子 0 個の「空の分子」**

素朴な実装は、空の入力を**妥当**と判定してしまう。ところが `"   "`（空白だけ）は**やはり** `None` を返す ——
同じ関数、同じ「空の入力」、それなのに二通りの挙動。本ツールはドメイン層で両方をまとめて止める。

### 3. 結果は「成功／失敗」ではなく**三段階**

`[Fe+9]` は解析できるが、電荷が荒唐無稽。こういうものは拒否ではなく**警告**であるべき：

| level | 意味 |
|---|---|
| `ok` | きれいに通った |
| `warn` | 解析はできるが構造が疑わしい（異常な電荷、怪しい芳香性…）。理由付き |
| `error` | 解析失敗。人間の言葉の理由 + 特定できる文字位置 |

**そしてバッチ API はデータを黙って捨てない。** すべての行に明確な帰属があり（ok / warn / failed）、
失敗は一件ずつ列挙される —— 研究データでは「こっそり二行消えていた」のほうがエラーよりずっと危険だ。

### 診断メッセージは中英二言語

既定は中国語。英語環境では環境変数を一つ設定するだけ：

```bash
export MOL_LANG=en        # zh（既定）/ en
```

> ⚠️ **契約は `code` であって、文言ではない。** `code`（`unclosed_ring` / `valence` …）は言語に依存せず、
> 言語を変えても `level` / `position` / `canonical` は**変わらない** —— これを固定する専用の回帰ケースがある。

---

## ツール一覧（13 個、すべて完全ローカル）

| ツール | 役割 |
|---|---|
| `chem_check_smiles` | 検証 + 正規化。三段階の結果 + 人間の言葉の理由 + 文字位置 |
| `chem_properties` | 分子式 / MW / 精密質量 / logP / TPSA / HBD / HBA / 環数 / 不斉中心 |
| `chem_analyze` | 一度に全部：基礎的な性質 + ドラッグライクネス + 構造アラート + Murcko 骨格 |
| `chem_druglikeness` | Lipinski / Veber の逐条判定、QED、PAINS / BRENK 構造アラート |
| `chem_draw_molecule` | 構造図を描く（PNG/SVG。原子番号の表示、部分構造のハイライトが可能）。返すのは**ファイルパス** |
| `chem_draw_grid` | 複数分子のグリッド画像（報告や論文の図に）。壊れた項目は飛ばすが、一件ずつ記録に残す |
| `chem_convert` | smiles / inchi / inchikey / mol / sdf / formula の相互変換 |
| `chem_bioseq` | ペプチド／核酸の配列、HELM または IDT 記法 → 分子（正規化した SMILES を返し、他のツールに繋げられる）。**kind の明示が必須** |
| `chem_standardize` | 脱塩 / 金属の切断 / 中和 / 正規化。**変更点を逐次記録** |
| `chem_dedupe` | 正規化した構造で重複排除し、重複グループを返す |
| `chem_substructure_match` | SMARTS による部分構造マッチ。原子インデックスを返す |
| `chem_similarity` | フィンガープリント類似度（morgan / rdkit / maccs） |
| `chem_batch_clean` | SMILES 一列のバッチクリーニング。件数サマリ + 失敗一覧（CSV 出力も可） |

ワークベンチの「分析」タブは、これらのツールと**同じ `chemcore` を共有している** —— 「画面では A を計算し、agent は B を計算する」というずれは存在しない。

> `chem_core` には `python3 -m chemcore.cli` という JSON の入口もある（JSON 一行が入り、JSON 一行が出る）。
> ワークベンチの即時数値はここを通っている。「AI のためのツール」と「人のための画面」が実装を共有する継ぎ目が、これだ。

## 生体高分子（ペプチド / 核酸）の扱い

Ketcher の巨大分子エディタで描いたペプチド／核酸には **SMILES がない**。あるのは配列か HELM だけ。
`chem_bioseq` がそれを分子に解析し、**正規化した SMILES** を返す —— つまり上のツール群（properties / analyze /
draw / convert）は、同じ分子のまま続けて使える。

```python
cc.parse_bioseq("GAVL", kind="peptide")            # ペプチド、1 文字コード → C16H30N4O5 / 358.4
cc.parse_bioseq("Gly-Ala-Val", kind="peptide3")    # ペプチド、3 文字コード → 三ペプチド C10H19N3O4 / 245.3
cc.parse_bioseq("AUGC", kind="rna")                # RNA → C38H48N15O26P3 / 1223.8
cc.parse_bioseq("ATGC", kind="dna")                # DNA → C39H50N15O22P3 / 1173.8
cc.parse_bioseq("PEPTIDE1{G.A.V.L}$$$$")           # HELM：接頭辞が型を宣言しているので auto でよい
```

### なぜ `kind` を明示しなければならないのか

`A/T/G/C` は**アミノ酸の文字であり、同時に塩基の文字**でもあるから（Ala/Thr/Gly/Cys ↔ アデニン／チミン／グアニン／シトシン）。
同じ `ATGC` が、ペプチドとしてなら `C12H22N4O6S`、RNA としてなら `C39H50N15O26P3`、DNA としてなら
`C39H50N15O22P3` —— 三つとも別の分子だ。ところが RDKit の `MolFromSequence` は
**既定でペプチドとしてしか読まず、エラーも出さない**。

だから本ツールの決まりはこう：

- **裸の配列には `kind` の明示が必須**（`auto` でも必要）。なければエラーにする ——
  「…がペプチドなのか核酸なのか判断できないため、解析を拒否した」。**呼び出し側の代わりに既定値を選ぶことは絶対にしない**：
  選び間違えると「化学的に完全に間違っていて、しかもその痕跡が一切ない」状態になり、エラーより危険だから。
- `auto` で確実に推論できるのは、型情報を自前で持つ**二種類の記法だけ**：**HELM**（`PEPTIDE1{` / `RNA1{` / `DNA1{` という接頭辞は**宣言**であって、推測ではない）と **IDT**（糖型の接頭辞 `r`/`d` も同じく宣言）。それ以外は `auto` では一律に拒否する —— 裸の配列（`ACGU` / `ATGC` / `GAVL`）には型情報がなく、既定値も与えない。

> 関連する RDKit の罠が二つ（どちらも実測済みで、本プロジェクトはどちらも回避している）：**DNA の flavor は 3 ではなく 6**
> （3 は「RNA に 5' リン酸キャップを付ける」意味で、リン酸が一つ余分に付く）。そして **3 文字アミノ酸コードは
> RDKit 2023.09.6 ではまったく非対応** —— `Gly-Ala-Val` を大文字小文字を無視した 1 文字コードとして読み、
> 9 残基のペプチド（MW 890.1）と解釈してエラーを出さない。だから `peptide3` は本層が 1 文字コードに
> 翻訳してから計算する。配列中の空白も RDKit は黙って余分な水素に変えてしまうので、本層がまず正規化し、
> その変更を `warnings` に記録する。

### IDT 記法（Ketcher が核酸を書き出す形式）

Ketcher の巨大分子エディタで核酸を書き出すと出てくるのが **IDT 記法**（実測では RNA を描くと
`rArCrGrTrU/3Phos/`）。残基には糖型の接頭辞が付き（`r`=リボース、`d`=デオキシ、`m`=2′-O-メチル、
`+`=LNA）、`/3Phos/` `/5Phos/` のような末端修飾もある。`chem_bioseq` はこれをそのまま受け取る ——
`kind` の値に `idt` が増えたのはそのため（`auto` でも認識する：糖型の接頭辞は推測ではなく**宣言**）。

**ただし、変換するのは無損なときだけ。** 糖型が揃っていて修飾もなければ、純粋な配列として RDKit に
渡す。表現できないものが一つでもあれば拒否し、理由を明示する：

```python
cc.parse_bioseq("rArCrGrTrU", kind="idt")         # → RNA ACGTU / MW 1543.997（糖型が揃い修飾なし＝無損）
cc.parse_bioseq("rArCrGrTrU/3Phos/", kind="idt")  # ✗ 拒否：無理に変換すると 3′ リン酸が静かに消える（≈79.97 Da）
```

拒否するときは必ず名指しする：

- 末端／骨格の修飾：`/3Phos/`、`/5Phos/`、`*`（ホスホロチオエート）
- 非標準の糖型：`m`（2′-O-メチル）、`+`（LNA）
- 糖型の混在：`rArCdT`（同じ文字列にリボースとデオキシ —— RDKit は一度に片方しか表現できない）
- 呼び出し側が渡した `kind` との衝突：`rArCrG` + `kind="dna"`（接頭辞が宣言しているのは RNA）

理由は上と同じ：無理に変換するのは近似ではなく、**化学的に完全に誤っていて、しかも見た目には何も
おかしくない**ということ —— 分子量が 79.97 Da 軽いのに、画面はまったく普通に見える。

## Python API

```python
import chemcore as cc

cc.check("C1CC").diagnostics[0].message   # '环闭合标记没有配对：…'
cc.properties("CC(=O)Oc1ccccc1C(=O)O")    # {'formula': 'C9H8O4', 'mw': 180.159, …}
cc.analyze("CC(=O)Oc1ccccc1C(=O)O")       # + QED / Lipinski / PAINS アラート / Murcko 骨格
cc.draw("CCO", atom_indices=True)         # {'path': '…/CCO.png', …}
cc.standardize("CC(=O)[O-].[Na+]")        # {'output': 'CC(=O)O', 'changes': [...]}
cc.batch_clean(["CCO", "C1CC"])           # {'ok': 1, 'failed': 1, 'failed_items': [...]}
cc.parse_bioseq("GAVL", kind="peptide")   # ペプチド／核酸／HELM → 分子 + 正規化 SMILES（kind 必須）
```

## 実例：汚れたモノマー表を洗う

[`examples/monomer_cleanup.py`](examples/monomer_cleanup.py) は、わざと汚したモノマー表
（同じ分子の二通りの書き方、ナトリウム塩、環が閉じていない書き間違い、価標が超過したもの、荒唐無稽な電荷）を用意し、
処理の連鎖を丸ごと走らせる：

```bash
python3 examples/monomer_cleanup.py
```

11 件が通過、1 件が警告、2 件が失敗だと報告し、重複を統合し、脱塩と中和の各ステップを順に示し、
描ける 12 個の構造を描き、飛ばした 2 個は理由とともに列挙する。

![バッチ描画（図注は中国語）](docs/monomers.png)

## 逆合成

逆合成タブのバックエンドは**差し替え可能**：プラグインが `child_process` で「stdin に JSON を食わせ、stdout から JSON を読む」プロセスを起動し、既定ではリポジトリ内の Retro* ブリッジスクリプトを指す。

- バックエンドが**入っていない**とき：構造化された診断（足りないファイル、入手先、置き場所）を返し、画面はそれをそのまま表示する ——
  **ルートを捏造しない**し、「それらしいもの」でお茶を濁すこともしない
- 別のバックエンドに替えたいとき（AiZynthFinder / 自作の RetroChimera / 所属グループの内部サーバー）：同じ
  stdin/stdout プロトコルさえ守れば、`retroCommand` をそちらに向けるだけでよい

Retro* の導入（ソース + モデルデータ、GB 級）は **[docs/RETROSYNTHESIS.md](docs/RETROSYNTHESIS.md)** を参照。

## テスト

```bash
PYTHONPATH=src python3 tests/run_tests.py    # コアケース 71 件（依存ゼロ、pytest 不要）
PYTHONPATH=src python3 tests/mcp_smoke.py    # MCP プロトコルレベルのスモーク（実際にサーバーを起動し、実際にツールを呼ぶ）
bash tests/run_all.sh                        # 上の二つ + 自己診断を一気に
```

画面は Playwright のヘッドレスで受け入れている（アサーション 39 件。「ワークベンチを開いたあともチャットが使えるか」
「数値は本当に計算されたものか」「バックエンドが未導入のときにルートを捏造しないか」をカバー）：

```bash
dsh web --port 3081 --no-open > /tmp/chemver.log 2>&1 &
CHEM_BASE=http://127.0.0.1:3081 \
CHEM_TOKEN=$(grep -o 'token=[^ ]*' /tmp/chemver.log | cut -d= -f2) \
node dsh-ui/tests/verify-ui.cjs
```

> 自分が今使っているポートで実験しないこと —— 別のインスタンスを立て、終わったら閉じる。

## 設計原則

1. **ネットワークゼロ**：計算はすべてこのプロセス内で完結する。
2. **追加依存ゼロ**：コアが必要とするのは RDKit だけ。テストは pytest すら要らない。
3. **失敗は人間の言葉で**：RDKit の英語 C++ ログを、段階付きの診断に翻訳する。
4. **データを黙って捨てない**：バッチ API は一件ずつ報告する。
5. **数値には必ず前提を添える**：logP は Crippen の推定値だと明記し、`mw` / `exact_mw` はそれぞれの意味を説明する。
6. **ファイルに書いてパスを返す**：画像はプロトコルのペイロードに詰め込まず、ファイルに書いてパスを返す —— 再現でき、バージョン管理に入り、論文にも使える。
7. **無いものは無いと言う**：実験値は無い、活性予測は無い、逆合成バックエンドが未導入なら未導入だと言う。

## ロードマップ

- **v0.1（現在）**：完全ローカルなツール 13 個 + 化学ワークベンチ（キャンバス / 分析 / 逆合成の枠組み）
- **v0.2**：逆合成バックエンドが実際に動く（Retro* のデータを整備）+ ワークベンチ内でルート図を直接見る
- **v0.3**：分析カードの追加（pKa / 配座 / 薬物動態）、可視化を「構造 + グラフ」へ格上げ
- **未定**：画像 → 構造の認識（OCSR）は数百 MB のモデルを要するため、**「基礎的な軽量ツール」には属さない**。差し替え可能なバックエンドとして提供する

## 境界

- ここに実験値は**ない**。`logP`、`TPSA`、`QED` はいずれも計算値／推定値であり、実測の代わりにはならない。
- 構造アラートは「有毒」**ではない**：あくまで「この種の部分構造は人が一度見ておく価値がある」という印だ。
- ここに画像認識は**ない**し、名称 → 構造（OPSIN の類）も**ない**。
- SMARTS のマッチは構造のマッチであり、化学反応性の判定**ではない**。
- **生体高分子は標準モノマーまで**：`peptide3` が知っているのは 20 種の標準アミノ酸の 3 文字コードだけ。
  修飾残基、非天然モノマー、糖鎖などは RDKit の層では信頼できるサポートがない。また実測の結果、RDKit 2023.09.6 の
  HELM 解析は **`DNA1` と `CHEM1` に対応していない**（None を返す）。そういう場合は空の結果を返さず、
  はっきりエラーを出す。
- **配列の型は必ずあなたが指定する**：`A/T/G/C` はペプチドでも核酸でも合法なので、裸の配列が曖昧なときは
  **解析を拒否**し、既定値を与えない（上の「生体高分子」の節を参照）。
- **InChI は `*` のダミー原子に対応していない**：ポリマーの RU-SMILES（例 `*OCCOC(=O)c1ccc(C(=O)O*)cc1`）は
  InChI / InChIKey に**変換できない**。
  本ツールは**黙って空文字列を返したりしない**（RDKit は返す）。はっきりエラーを出し、一意な識別子には
  canonical SMILES を使うよう勧める —— この分野で最もよくある入力が、まさに `*` 付きだから。
- これは **0.x の初期リリース**：API は変わりうる。issue は歓迎。

## リポジトリ構成

```
src/chemcore/          純 RDKit のコア（唯一の情報源）+ JSON CLI の入口
src/dsh_mol_mcp/       stdio MCP アダプター（ツール 13 個）
dsh-ui/                化学ワークベンチ（DSH クライアントプラグイン：ホスト側 + ブラウザ側）
dsh-ui/retro/          逆合成バックエンドのブリッジ（差し替え可能、既定は Retro*）
dsh-bundle/            DSH バンドル（設定のみを提供し、上の MCP サーバーを指す）
dsh/                   手動で重ねるための patch（ローカルパスを直書き）
tests/                 依存ゼロのテスト + MCP プロトコルスモーク + Playwright の画面受け入れ
docs/                  デモ画像と解説ドキュメント
```

## 環境要件（実際に踏んだ罠）

**MCP Python SDK は 1.x でなければならない**：

```bash
pip install 'mcp>=1.0,<2'
```

SDK **2.x は `FastMCP` を `MCPServer` に改名**し、API に破壊的変更が入っている。
本プロジェクトの `[mcp]` extra は `<2` に固定済み。手で 2.x を入れてしまった場合も、`dsh-mol-mcp` は
**どうすればよいかをはっきり教える**（トレースバックを投げ捨てるのではなく）—— この罠は CI がクリーンな環境で
実測して見つけたもので、推測ではない。

## 謝辞

- [RDKit](https://www.rdkit.org/) —— 化学コアのすべて
- [Ketcher](https://github.com/epam/ketcher) —— キャンバス（ローカル wasm レンダリング、ネットワーク不使用）
- [Retro*](https://github.com/binghong-ml/retro_star)（ICML 2020）—— 逆合成バックエンドの一つ

## ライセンス

MIT

<!-- dsh-mol:test-count 71 -->
<!-- dsh-mol:tool-count 13 -->
<!-- dsh-mol:ui-assertions 39 -->
