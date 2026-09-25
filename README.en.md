# dsh-mol · a local-first chemistry workbench

[![ci](https://github.com/Yijian-quiet/dsh-mol/actions/workflows/ci.yml/badge.svg)](https://github.com/Yijian-quiet/dsh-mol/actions/workflows/ci.yml)


[中文](README.md) | English

Turn the most frequent small chores in chemistry into tools an **AI agent can call
reliably**: validate SMILES, draw structures, compute properties, convert formats,
standardize, clean batches.

Pure RDKit. **No network, no API key, no external service.** Exposed as a
**stdio MCP server**, so DeepSeek Harness / Claude Code / Codex can use it directly.

![batch drawing with Chinese legends](docs/monomers.png)

*`draw_grid` output: 12 monomers rendered, 2 malformed entries skipped — each with its
reason recorded, nothing dropped silently.*

---

## Status

| | |
|---|---|
| Version | `0.0.1` (early; API may change) |
| Tests | 44 core cases + 11 self-checks + MCP protocol smoke test, **all green** |
| Published | ⏳ not yet on PyPI / GitHub |
| Deps | `rdkit` (core); `mcp` (MCP adapter only) |
| License | MIT |

---

## Why not just wrap RDKit

Because a naive wrapper hands an AI agent three traps, and all three bite in real
research work.

### 1. RDKit does not raise on parse failure — it returns `None`

The reason is written to a C++ stderr log. A naive wrapper gives the model a bare
`None` with no idea what went wrong. This toolchain reroutes, captures and
**translates** that log into a human-readable diagnostic, with a **character
position** where one can be determined:

```jsonc
// chem_check_smiles("C1CC")
{ "level": "error",
  "diagnostics": [
    { "code": "unclosed_ring",
      "message": "环闭合标记没有配对：SMILES 里的成环数字（如 C1...C1）出现次数必须是偶数" },
    { "code": "unclosed_ring_position",
      "message": "成环编号 1 只出现了 1 次（最后一次在第 1 个字符）：成环数字必须成对出现，如 C1CC1 而不是 C1CC" }] }
```

(Diagnostics are written in Chinese by default; set `MOL_LANG=en` for English.
The `code` field is language-independent — assert on `code`, never on the message text.)

### 2. `MolFromSmiles("")` returns **an empty 0-atom molecule**, not `None`

A naive wrapper therefore judges empty input as *valid*. And `"   "` (whitespace)
**does** return `None` — the same function, two different behaviours for two
different kinds of "empty". This toolchain handles both at the domain layer.

### 3. The result is **three-valued**, not pass/fail

`[Fe+9]` parses, but the charge is absurd. That deserves a *warning*, not rejection:

| level | meaning |
|---|---|
| `ok` | clean |
| `warn` | parses, but suspicious (unusual charge, dubious aromaticity…), with reasons |
| `error` | parse failure, with a human-readable reason and a locatable character position |

**And batch APIs never drop data silently.** Every row is accounted for
(ok / warn / failed) with failures listed individually — in research data,
"two rows quietly disappeared" is more dangerous than an error.

---

## Install

**Not yet on PyPI / npm — but you do not have to wait.** Install straight from
GitHub (both paths verified):

```bash
# core (RDKit only)
pip install rdkit

# this repo including the MCP adapter — from git, no PyPI account needed
pip install "dsh-mol[mcp] @ git+https://github.com/Yijian-quiet/dsh-mol.git"

# development mode (edits take effect immediately)
git clone https://github.com/Yijian-quiet/dsh-mol.git && cd dsh-mol
pip install -e ".[mcp]"

# or run straight from source, no install
export PYTHONPATH=/path/to/dsh-mol/src
```

Self-check (no MCP client required):

```bash
dsh-mol-mcp --selftest
# without installing: PYTHONPATH=src python3 -m dsh_mol_mcp.server --selftest
```

## Use with DeepSeek Harness

### Option 1 (recommended): install the bundle

**No npm account needed** — pnpm supports git subdirectories, so install straight
from GitHub (verified):

```bash
dsh plugin --profile <profile> add 'github:Yijian-quiet/dsh-mol#path:dsh-bundle'
```

Once published to npm (not yet), this becomes:

```bash
dsh plugin --profile <profile> add dsh-mol
```

> Prerequisite: an executable `dsh-mol-mcp` on the Python side (provided by the
> install step above).

The bundle lives in [`dsh-bundle/`](dsh-bundle/README.md) and **contributes
configuration only, no JS code** — it inserts one `@deepseek-ai/dsh-mcp-client`
row pointing at this repo's stdio server, so the tool implementations exist in
exactly one place (Python) and cannot drift.

Paths are resolved from environment variables via `!!js` expressions rather than
hard-coded absolutes, so one patch works across machines and install modes. See
`dsh-bundle/README.md`.

### Option 2: overlay a patch (other MCP clients, or no install)

```yaml
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
```

```bash
dsh --profile headless --patch dsh/dsh-mol.cordis.yml "validate C1CC"
```

Tools appear to the model as `mcp__chem__chem_check_smiles` and friends.

> **Images and the UI**: `chem_draw_molecule` / `chem_draw_grid` write a file and
> return its **path**. In a context that mounts the `standard` agent preset
> (`dsh web` does), the model can then call `present` to surface it as a native
> deliverable. `headless` mounts no presets, so `present` is unavailable there —
> that is expected, not a bug.

### Optional: wiring in network-backed deep services

The local tools cover **general chemistry fundamentals** (offline, zero network).
Domain-depth capabilities (polymer property prediction, retrosynthesis) are a
second leg and belong to a **remote MCP server**.

[`dsh/polymer-platform.cordis.yml`](dsh/polymer-platform.cordis.yml) is a worked
**example** — it mounts a private HTTP MCP server (loopback-only read-only proxy,
Bearer auth):

```bash
export POLYMER_MCP_TOKEN=...        # token travels via env only, never in a file
dsh --profile headless \
    --patch dsh/dsh-mol.cordis.yml \
    --patch dsh/polymer-platform.cordis.yml \
    "predict Tg for PET"
```

Two deliberate choices:

- It is **not** part of `dsh-bundle/`. A public bundle must not hard-depend on
  anyone's private service; this overlay stays in the repo as a template for
  wiring a private HTTP MCP server.
- It sets `failOnStartupError: false`, so **a down platform does not break DSH
  startup** — those tools simply do not appear, and the local tools keep working.

## Tools

| Tool | Purpose |
|---|---|
| `chem_check_smiles` | validate + canonicalize: three-valued result, human-readable reasons, character position |
| `chem_properties` | formula / MW / exact mass / logP / TPSA / HBD / HBA / rings / stereocenters |
| `chem_draw_molecule` | render a structure (PNG/SVG, optional atom indices, substructure highlight) → returns a **file path** |
| `chem_draw_grid` | multi-molecule grid for reports/papers; bad entries skipped but recorded |
| `chem_convert` | smiles / inchi / inchikey / mol / sdf / formula |
| `chem_standardize` | strip salts, disconnect metals, neutralize, normalize — **recording every change** |
| `chem_dedupe` | deduplicate by canonical structure, with duplicate groups |
| `chem_substructure_match` | SMARTS substructure matching, returns atom indices |
| `chem_similarity` | fingerprint similarity (morgan / rdkit / maccs) |
| `chem_batch_clean` | clean a column of SMILES: counts + failure list (+ optional CSV report) |

## Python API

```python
import chemcore as cc

cc.check("C1CC").diagnostics[0].message   # '环闭合标记没有配对：…'
cc.properties("CC(=O)Oc1ccccc1C(=O)O")    # {'formula': 'C9H8O4', 'mw': 180.161, …}
cc.draw("CCO", atom_indices=True)         # {'path': '…/CCO.png', …}
cc.standardize("CC(=O)[O-].[Na+]")        # {'output': 'CC(=O)O', 'changes': [...]}
cc.batch_clean(["CCO", "C1CC"])           # {'ok': 1, 'failed': 1, 'failed_items': [...]}
```

## Worked example

[`examples/monomer_cleanup.py`](examples/monomer_cleanup.py) takes a deliberately
messy monomer table (duplicate written two ways, a sodium salt, a ring-closure
typo, an impossible valence, an absurd charge) and runs the whole chain:

```bash
python3 examples/monomer_cleanup.py
```

It reports `11 ok · 1 warn · 2 failed`, merges the duplicate, walks the salt
standardization step by step, and draws the 12 renderable structures while
listing the 2 that were skipped — with reasons.

## Tests

```bash
PYTHONPATH=src python3 tests/run_tests.py    # 44 core cases (zero deps, no pytest needed)
PYTHONPATH=src python3 tests/mcp_smoke.py    # MCP protocol smoke (real client, real server)
```

**Acceptance script** (all 10 tools once, with verdicts, timings and output paths):

```bash
python3 examples/acceptance.py               # artifacts land in ~/dsh-mol-out/ by default
```

## Design principles

1. **Zero network** — every computation happens in-process.
2. **Zero extra dependencies** — core needs only RDKit; the tests don't even need pytest.
3. **Failures speak human** — RDKit's English C++ logs become graded diagnostics.
4. **No silent data loss** — batch APIs account for every row.
5. **State your units** — `logP` is flagged as a Crippen estimate; `mw` vs `exact_mw` are explained.
6. **Write files, return paths** — images are not stuffed into protocol payloads; they stay reproducible, diffable and paper-ready.

## Roadmap

- **v0.1 (current)** — the 10 local tools above
- **v0.2** — DSH bundle polish (settings page, richer UI affordances)
- **v0.3** — network-backed deep services over MCP (property prediction, retrosynthesis)
- **Undecided** — image → structure (OCSR) needs a several-hundred-MB model; it is
  **not** a "light local tool" and will be a pluggable backend

## Boundaries

- There are **no experimental values** here. `logP`, `TPSA` etc. are computed/estimated.
- No image recognition, no name → structure (OPSIN).
- SMARTS matching is structural matching, **not** a reactivity judgement.
- **InChI does not support the `*` dummy atom**: polymer RU-SMILES (e.g. `*OCCOC(=O)c1ccc(C(=O)O*)cc1`) **cannot** be converted to InChI / InChIKey.
  We **refuse to return an empty string silently** (RDKit does); we raise a clear error and point you at canonical SMILES instead — precisely because dummy-atom input is the norm in this field.

## Repository layout

```
src/chemcore/          pure RDKit core (single source of truth)
src/dsh_mol_mcp/ stdio MCP adapter
dsh-bundle/            DSH bundle (configuration only, pointing at the MCP server)
dsh/                   manual overlay patch (absolute paths, for hand-editing)
tests/                 zero-dependency tests + MCP protocol smoke
examples/              worked example
docs/                  images
```

## License

MIT

## Requirement worth knowing

**The MCP Python SDK must be 1.x**:

```bash
pip install 'mcp>=1.0,<2'
```

SDK **2.x renamed `FastMCP` to `MCPServer`** with breaking API changes. Our `[mcp]`
extra pins `<2`, and if you end up with 2.x installed, `dsh-mol-mcp` tells you
exactly what to do instead of dumping a traceback — this trap was found by CI on a
clean runner, not guessed.
