<div align="center">

# dsh-mol · a chemistry workbench

**A molecule sketchpad plus a local RDKit workbench, sitting next to your AI agent's chat box.**

Draw a structure → click once → formula / MW / logP / TPSA / drug-likeness / structural alerts **computed on the spot** →
drop the structure into the conversation and let the agent take it from there.

Pure RDKit. **No network, no API key, no external service.** Also usable as a stdio MCP server, callable directly by Claude Code / Codex.

[![ci](https://github.com/Yijian-quiet/dsh-mol/actions/workflows/ci.yml/badge.svg)](https://github.com/Yijian-quiet/dsh-mol/actions/workflows/ci.yml)
[![Awesome DSH Plugin](https://awesome-dsh-plugin.com/badge.svg)](https://awesome-dsh-plugin.com)
[![M8ven Score](https://m8ven.ai/badge/mcp/yijian-quiet/dsh-mol)](https://m8ven.ai/mcp/yijian-quiet/dsh-mol?s=readme)
![python](https://img.shields.io/badge/python-3.9%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![tests](https://img.shields.io/badge/tests-71%20passed-brightgreen)
![network](https://img.shields.io/badge/network-none%20required-success)

[中文](README.md) | **English** | [日本語](README.ja.md) | [한국어](README.ko.md) | [Français](README.fr.md) | [繁體中文](README.zh-TW.md)

<img src="docs/workbench-analyze.png" alt="Chemistry workbench · Analyze tab" width="820">

</div>

---

## Understand it in 30 seconds

| | |
|---|---|
| 🎨 **Draw molecules** | One button next to the chat box → a Ketcher canvas overlay. **The chat is not pushed aside**, and one click inserts the structure into the input box |
| ⚡ **Instant analysis** | Formula, MW, exact mass, logP, TPSA, HBD/HBA, rings, Fsp³, stereocenters — computed **right now** by local RDKit, no model call, no waiting on an LLM |
| 💊 **Drug-like or not** | Lipinski / Veber rule-by-rule verdicts, QED, PAINS / BRENK structural alerts, Murcko scaffold |
| 🧹 **Dirty-data first aid** | Validation (plain-language errors + character positions), standardization (every change recorded), dedupe, batch cleanup |
| 🧭 **Retrosynthesis** | The tab is in place and the backend is pluggable (Retro* today). **If the model data is not installed, it says so honestly — it never invents a route** |
| 🔌 **Two ways in** | The graphical workbench is for people; the same core reaches agents over MCP — **one implementation, two entry points** |

> Some context: npm has **618** DSH plugins, of which **0** are chemistry / materials / molecules.
> This repo exists to fill that gap.

---

## Quick start

```bash
# 1) Install the core + MCP adapter (published on PyPI)
pip install 'dsh-mol[mcp]'
#    Fall back to git if that fails: pip install "dsh-mol[mcp] @ git+https://github.com/Yijian-quiet/dsh-mol.git"

# 2) Install the plugin into your DSH profile (no npm account needed; pnpm handles git subdirectories)
dsh plugin --profile web add 'github:Yijian-quiet/dsh-mol#path:dsh-bundle'
dsh plugin --profile web add 'github:Yijian-quiet/dsh-mol#path:dsh-ui'   # ← the graphical workbench

# 3) Open DSH Web and click "workbench" to the left of the input box
```


> ✅ **Published on PyPI**: `pip install 'dsh-mol[mcp]'` (live 2026-09-26; run `dsh-mol-mcp --selftest` to check).
> ⏳ **Not yet on npm**, so the plugin itself still installs with `dsh plugin add github:…` — nothing is blocked.
>
> ✅ Listed in the [DSH plugin market](https://awesome-dsh-plugin.com) (entries
> `dsh-mol#dsh-ui` and `dsh-mol#dsh-bundle`, category `tools`) — you can also install it there.

The workbench needs a local `python3` that can `import rdkit`; the canvas is a [Ketcher](https://github.com/epam/ketcher) static build that **renders locally in the browser and goes through no backend**.

<details>
<summary>Command line only, or a different MCP client?</summary>

```bash
dsh-mol-mcp --selftest          # self-check first (no MCP client required)
```

```yaml
# overlay the patch by hand; stdio transport, fully local
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

Tools show up on the model side as `mcp__chem__chem_check_smiles` and friends.
</details>

---

## What the workbench looks like

Three tabs, one molecule:

<table>
<tr>
<td width="33%"><img src="docs/workbench-draw.png" alt="Draw tab"><br><b>① Draw</b><br>The full Ketcher canvas (the overlay drags and maximizes). "Insert into chat" writes the SMILES into the input box — <b>the text is the structure alone, with no internal path smuggled in</b>.</td>
<td width="33%"><img src="docs/workbench-analyze.png" alt="Analyze tab"><br><b>② Analyze</b><br>Input and buttons on the left, numbers on the right. Basic properties + drug-likeness + structural alerts + scaffold in one pass, all computed live by local RDKit.</td>
<td width="33%"><img src="docs/workbench-retro.png" alt="Retrosynthesis tab"><br><b>③ Retrosynthesis</b><br>Target molecule → multi-step route. With no model data installed, <b>it tells you what to download and where to put it</b> instead of pretending it computed something.</td>
</tr>
</table>

### Why isn't the drawing rendered in the panel?

Because **an image should follow the prose that explains it**. The thumbnail in the workbench only confirms *which molecule* was computed;
the real structure image is drawn inline by the agent in its reply (`read_image`), right next to its explanation of that molecule.

That call came after two rejected versions:
first "the panel eats the main area and squeezes the chat out", then "a second preview inside the canvas is useless".
Now **the chat keeps its layout and the workbench sits beside it**.

---

## Why not just wrap RDKit

Because a naive wrapper hands an AI agent three traps, and all three bite for real in research work:

### 1. When RDKit fails to parse it **does not raise** — it returns `None`

The reason goes to a C++ stderr log. Under a naive wrapper the model only gets an empty `None` and has no idea what went wrong.
This toolchain reroutes and captures the RDKit log, **translates it into plain language**, and gives a **character position** where one can be located:

```jsonc
// chem_check_smiles("C1CC")
{ "level": "error",
  "diagnostics": [{ "code": "unclosed_ring",
                    "message": "环闭合标记没有配对：SMILES 里的成环数字（如 C1...C1）出现次数必须是偶数" }] }

// chem_check_smiles("CC(=O)O)")   ← one closing paren too many, located at character 7
{ "level": "error", "position": 7,
  "diagnostics": [{ "code": "extra_paren", "message": "多余的右括号：) 比 ( 多" }] }
```

### 2. `MolFromSmiles("")` does not return `None` — it returns **an empty 0-atom molecule**

A naive implementation would call empty input **valid**. Yet `"   "` (whitespace only) **does** return `None` —
one function, two kinds of empty input, two behaviours. This toolchain catches both at the domain layer.

### 3. Results are **three-valued**, not pass/fail

`[Fe+9]` parses, but the charge is absurd. That deserves a *warning*, not a rejection:

| level | meaning |
|---|---|
| `ok` | clean |
| `warn` | parses, but the structure is suspicious (unusual charge, dubious aromaticity…), with reasons |
| `error` | parse failure, with a plain-language reason and a locatable character position |

**And batch APIs never drop data silently.** Every row is accounted for (ok / warn / failed),
with failures listed one by one — in research data, "two rows quietly went missing" is far more dangerous than an error.

### Diagnostics are bilingual

Chinese by default; one environment variable switches an English environment over:

```bash
export MOL_LANG=en        # zh (default) / en
```

> ⚠️ **The contract is `code`, not the message text.** `code` (`unclosed_ring` / `valence` …) is language-independent,
> and it **does not change `level` / `position` / `canonical` when the language changes** — dedicated regression cases lock this down.

---

## Tools (13, all local-only)

| Tool | Purpose |
|---|---|
| `chem_check_smiles` | validate + canonicalize: three-valued result, plain-language reasons, character position |
| `chem_properties` | formula / MW / exact mass / logP / TPSA / HBD / HBA / rings / stereocenters |
| `chem_analyze` | everything at once: basic properties + drug-likeness + structural alerts + Murcko scaffold |
| `chem_druglikeness` | Lipinski / Veber rule-by-rule verdicts, QED, PAINS / BRENK structural alerts |
| `chem_draw_molecule` | render a structure (PNG/SVG, optional atom indices, substructure highlight) → returns a **file path** |
| `chem_draw_grid` | multi-molecule grid (for reports/papers); bad entries skipped but recorded one by one |
| `chem_convert` | smiles / inchi / inchikey / mol / sdf / formula conversion |
| `chem_bioseq` | peptide / nucleic-acid sequence, HELM or IDT notation → a molecule (and a canonical SMILES the other tools can consume); **kind must be given explicitly** |
| `chem_standardize` | strip salts / disconnect metals / neutralize / normalize — **recording every change** |
| `chem_dedupe` | deduplicate by canonical structure, with duplicate groups |
| `chem_substructure_match` | SMARTS substructure matching, returns atom indices |
| `chem_similarity` | fingerprint similarity (morgan / rdkit / maccs) |
| `chem_batch_clean` | clean a column of SMILES: count summary + failure list (+ optional CSV report) |

The workbench's "Analyze" tab and these tools **share the same `chemcore`** — there is no drift between "the UI computes one thing and the agent another".

> `chem_core` also has a `python3 -m chemcore.cli` JSON entry point (one JSON line in, one JSON line out);
> the workbench's live numbers go through it. That is the seam where "tools for the AI" and "a UI for people" share one implementation.

## Biomolecules (peptides / nucleic acids)

Peptides and nucleic acids drawn in Ketcher's macromolecule editor **have no SMILES** — only a
sequence or HELM. `chem_bioseq` turns them into a molecule and hands back a **canonical SMILES**,
so every tool above (properties / analyze / draw / convert) keeps working on the same molecule.

```python
cc.parse_bioseq("GAVL", kind="peptide")            # peptide, 1-letter → C16H30N4O5 / 358.4
cc.parse_bioseq("Gly-Ala-Val", kind="peptide3")    # peptide, 3-letter → tripeptide C10H19N3O4 / 245.3
cc.parse_bioseq("AUGC", kind="rna")                # RNA → C38H48N15O26P3 / 1223.8
cc.parse_bioseq("ATGC", kind="dna")                # DNA → C39H50N15O22P3 / 1173.8
cc.parse_bioseq("PEPTIDE1{G.A.V.L}$$$$")           # HELM: the prefix declares the type, auto is fine
```

### Why `kind` has to be explicit

Because `A/T/G/C` are **valid both as amino acids and as bases**
(Ala/Thr/Gly/Cys ↔ adenine/thymine/guanine/cytosine). The same `ATGC` is `C12H22N4O6S` as a
peptide, `C39H50N15O26P3` as RNA and `C39H50N15O22P3` as DNA — three different molecules —
while RDKit's `MolFromSequence` **defaults to reading it as a peptide without any error**.

So the rule here is:

- **A bare sequence must carry an explicit `kind`** (even with `auto`); otherwise it errors out —
  "Cannot tell whether … is a peptide or a nucleic acid, so parsing was refused".
  **We never pick a default for you**: a wrong choice is "chemically completely wrong with no
  trace at all", which is more dangerous than an error.
- **Only** two notations that carry their own type information can be inferred under `auto`:
  **HELM** (its `PEPTIDE1{` / `RNA1{` / `DNA1{` prefix is a **declaration**, not a guess) and
  **IDT** (the sugar prefix `r`/`d` is equally a declaration). Everything else is refused under
  `auto` — a bare sequence (`ACGU` / `ATGC` / `GAVL`) carries no type information and gets no default.

> Two RDKit traps we measured and work around: **DNA is flavor 6, not 3**
> (3 means "RNA with a 5' phosphate cap" and adds an extra phosphate); and **3-letter amino-acid
> codes are not supported at all in RDKit 2023.09.6** — it reads `Gly-Ala-Val` as
> case-insensitive single letters, giving a 9-mer (MW 890.1) with no error, so `peptide3` is
> translated into 1-letter codes right here. Whitespace inside a sequence is also silently turned
> into extra hydrogens by RDKit; we normalize it first and record the change in `warnings`.

### IDT notation (what Ketcher exports)

When Ketcher's macromolecule editor exports a nucleic acid it hands you **IDT notation**
(drawing an RNA measured out as `rArCrGrTrU/3Phos/`): residues carry a sugar prefix
(`r`=ribose, `d`=deoxy, `m`=2'-O-methyl, `+`=LNA), plus terminal modifications like `/3Phos/`
and `/5Phos/`. `chem_bioseq` takes it as-is — which is why `idt` is now one of the `kind` values
(`auto` recognizes it too: the sugar prefix is a **declaration**, not a guess).

**But it only converts when the conversion is lossless.** Uniform sugar type and no modifications,
and the notation becomes a plain sequence handed to RDKit; the moment something cannot be
expressed, it refuses and says why:

```python
cc.parse_bioseq("rArCrGrTrU", kind="idt")         # → RNA ACGTU / MW 1543.997 (uniform sugar, no mods: lossless)
cc.parse_bioseq("rArCrGrTrU/3Phos/", kind="idt")  # ✗ refused: forcing it would silently drop a 3′ phosphate (≈79.97 Da)
```

Every refusal names the culprit:

- terminal / backbone modifications: `/3Phos/`, `/5Phos/`, `*` (phosphorothioate)
- non-standard sugars: `m` (2'-O-methyl), `+` (LNA)
- mixed sugars: `rArCdT` (ribose and deoxy in one string — RDKit can express only one at a time)
- a conflict with the `kind` the caller passed: `rArCrG` + `kind="dna"` (the prefix declares RNA)

The reason is the same as above: forcing it is not an approximation, it is **chemically completely
wrong with nothing looking wrong** — 79.97 Da lighter, and the UI looks perfectly normal.

## Python API

```python
import chemcore as cc

cc.check("C1CC").diagnostics[0].message   # '环闭合标记没有配对：…'
cc.properties("CC(=O)Oc1ccccc1C(=O)O")    # {'formula': 'C9H8O4', 'mw': 180.159, …}
cc.analyze("CC(=O)Oc1ccccc1C(=O)O")       # + QED / Lipinski / PAINS alerts / Murcko scaffold
cc.draw("CCO", atom_indices=True)         # {'path': '…/CCO.png', …}
cc.standardize("CC(=O)[O-].[Na+]")        # {'output': 'CC(=O)O', 'changes': [...]}
cc.batch_clean(["CCO", "C1CC"])           # {'ok': 1, 'failed': 1, 'failed_items': [...]}
cc.parse_bioseq("GAVL", kind="peptide")   # peptide/RNA/DNA/HELM → molecule + canonical SMILES
```

## Worked example: cleaning a dirty monomer table

[`examples/monomer_cleanup.py`](examples/monomer_cleanup.py) takes a deliberately messy monomer table
(the same molecule written two ways, a sodium salt, a ring-closure typo, an impossible valence, an absurd charge) and runs the whole chain:

```bash
python3 examples/monomer_cleanup.py
```

It reports `11 ok · 1 warn · 2 failed`, merges the duplicates, walks through each salt-stripping and neutralization step,
and draws the 12 renderable structures while listing the 2 skipped ones together with their reasons.

![batch drawing with Chinese legends](docs/monomers.png)

## Retrosynthesis

The retrosynthesis tab's backend is **pluggable**: the plugin uses `child_process` to start a process that takes JSON on stdin
and writes JSON to stdout, pointing at the Retro* bridge script in this repo by default.

- When the backend is **not installed**: it returns a structured diagnostic (which files are missing, where to download them, where to put them) and the UI shows that honestly —
  **it does not invent a route**, and it does not paper over the gap with something that merely "looks like" one
- To swap the backend (AiZynthFinder / your own RetroChimera / your group's internal server): keep to the same
  stdin/stdout protocol and point `retroCommand` at it

Installing Retro* (source + model data, GB-scale) is covered in **[docs/RETROSYNTHESIS.md](docs/RETROSYNTHESIS.md)**.

## Tests

```bash
PYTHONPATH=src python3 tests/run_tests.py    # 71 core cases (zero deps, no pytest needed)
PYTHONPATH=src python3 tests/mcp_smoke.py    # MCP protocol smoke (real server, real tool calls)
bash tests/run_all.sh                        # the two above plus self-checks, in one shot
```

The UI is accepted headless with Playwright (33 assertions, covering "can you still use the chat after opening the workbench",
"are those numbers actually computed", and "does it invent a route when the backend is not installed"):

```bash
dsh web --port 3081 --no-open > /tmp/chemver.log 2>&1 &
CHEM_BASE=http://127.0.0.1:3081 \
CHEM_TOKEN=$(grep -o 'token=[^ ]*' /tmp/chemver.log | cut -d= -f2) \
node dsh-ui/tests/verify-ui.cjs
```

> Do not experiment on the port you are using — start a separate instance and shut it down when you are done.

## Design principles

1. **Zero network**: every computation happens in this process.
2. **Zero extra dependencies**: the core needs only RDKit; the tests don't even need pytest.
3. **Failures speak human**: RDKit's English C++ logs become graded diagnostics.
4. **No silent data loss**: batch APIs report every row.
5. **State your terms**: logP is flagged as a Crippen estimate; `mw` and `exact_mw` are each explained.
6. **Write files, return paths**: images are not stuffed into protocol payloads but written to disk and returned as a path — reproducible, versionable, paper-ready.
7. **Say what's missing**: no experimental values, no activity prediction; if the retrosynthesis backend isn't installed, say it isn't installed.

## Roadmap

- **v0.1 (current)**: 13 local-only tools + the chemistry workbench (canvas / analyze / retrosynthesis framework)
- **v0.2**: retrosynthesis backend running end to end (Retro* data in place) + view routes inside the workbench
- **v0.3**: more analysis cards (pKa / conformers / PK properties), visualization upgraded to "structure + charts"
- **Undecided**: image → structure (OCSR) needs a several-hundred-MB model, so it is **not a "light basic tool"** and will ship as a pluggable backend

## Boundaries

- There are **no experimental values** here. `logP`, `TPSA` and `QED` are computed/estimated and do not replace measurement.
- A structural alert **does not mean** "toxic": it only means "this kind of substructure deserves a human look".
- There is **no** image recognition and **no** name → structure (OPSIN and the like).
- SMARTS matching is structural matching, **not** a reactivity judgement.
- **Biomolecules cover standard monomers only**: `peptide3` knows the 20 standard three-letter
  amino-acid codes; modified residues, non-natural monomers and glycans have no reliable support
  at the RDKit layer. As measured, HELM parsing in RDKit 2023.09.6 **does not support `DNA1` or
  `CHEM1`** (it returns None); when that happens we raise a clear error instead of returning an
  empty result.
- **You must state the sequence type**: `A/T/G/C` are legal in both peptides and nucleic acids, so
  an ambiguous bare sequence is **refused** rather than defaulted (see the "Biomolecules" section).
- **InChI does not support the `*` dummy atom**: polymer RU-SMILES (e.g. `*OCCOC(=O)c1ccc(C(=O)O*)cc1`) **cannot** be converted to InChI / InChIKey.
  We **do not silently return an empty string** (RDKit does); we raise a clear error and suggest canonical SMILES as the unique identifier —
  because the most common input in this field is exactly the one carrying `*`.
- This is `v0.0.3`: the API may change; issues are welcome.

## Repository layout

```
src/chemcore/          pure RDKit core (single source of truth) + JSON CLI entry
src/dsh_mol_mcp/       stdio MCP adapter (13 tools)
dsh-ui/                chemistry workbench (DSH client plugin: host half + browser half)
dsh-ui/retro/          retrosynthesis backend bridge (pluggable, Retro* by default)
dsh-bundle/            DSH bundle (configuration only, pointing at the MCP server above)
dsh/                   patch for manual overlay (hard-coded local paths)
tests/                 zero-dependency tests + MCP protocol smoke + Playwright UI acceptance
docs/                  demo images and deep-dive docs
```

## A requirement worth knowing

**The MCP Python SDK must be 1.x**:

```bash
pip install 'mcp>=1.0,<2'
```

SDK **2.x renamed `FastMCP` to `MCPServer`** with breaking API changes.
Our `[mcp]` extra already pins `<2`; if you installed 2.x by hand, `dsh-mol-mcp` **tells you exactly what to do**
(instead of dumping a traceback) — CI found this trap on a clean environment, it is not a guess.

## Acknowledgements

- [RDKit](https://www.rdkit.org/) — the entire chemistry core
- [Ketcher](https://github.com/epam/ketcher) — the canvas (local wasm rendering, no network)
- [Retro*](https://github.com/binghong-ml/retro_star) (ICML 2020) — one of the retrosynthesis backends

## License

MIT

<!-- dsh-mol:test-count 71 -->
<!-- dsh-mol:tool-count 13 -->
<!-- dsh-mol:ui-assertions 33 -->
