# LRM example suite — every code example in the Verilog-AMS LRM 2023, compiled

This folder extracts **all code examples from the Verilog-AMS LRM 2023 PDF**
(`docs/VAMS-LRM-2023.pdf`, Accellera) and compiles every one that is in
openvaf-r's scope (the Verilog-A analog subset). The examples are identified
by *font* — LRM code is typeset in Courier New — not by text heuristics, so
the sweep is exhaustive: 231 candidate blocks from 442 pages.

## Layout

| Directory | Contents | Verified as |
|---|---|---|
| `va/` | 44 in-scope examples | **compile cleanly** (exit 0) |
| `limitations/` | 15 in-scope examples openvaf-r rejects today | rejected with the exact pinned diagnostic, **without crashing** |
| `ams/` | 21 mixed-signal/digital examples (`reg`, `always`, `wire`, `connectmodule`, …) | out of Verilog-A scope by design — stored, not compiled |
| `findings/` | 6 micro-repros for the compiler defects the sweep exposed | fixed defects must compile, open gaps keep their pinned diagnostic |
| `fragments/` | 146 non-module snippets (expressions, declarations, syntax illustrations) | reference only (they double as a fuzz corpus: all must not crash the compiler) |

See **[RESULTS.md](RESULTS.md)** for the eight defect findings — all fixed
(six by Enhancement-84, the final two by Enhancement-85: `` `__FILE__``/
`` `__LINE__`` and connection part-selects) — the limitation inventory, and
two errata found in the LRM's own examples.

## Conventions

- Examples are kept **verbatim** from the PDF wherever possible. Where a
  minimal change was unavoidable it is annotated in-line:
  - `// [lrm_examples patch] …` — a one-line fix (e.g. the LRM's own
    `vout_q1b`/`vout_q2` typo, or an added port direction).
  - `// [lrm_examples context] …` — a stub module appended because the LRM
    example references a definition it never provides (`vertNPN`, the
    Annex E SPICE primitives).
- `disciplines.vams`/`constants.vams` includes are prepended when the
  example assumes them (the LRM text does).
- Several LRM examples omit port directions; those files are compiled with
  `-W port_without_direction` (recorded per-file in `manifest.json`) rather
  than patched.

## Regenerating / verifying

```bash
python3 extract_lrm_examples.py   # PDF -> raw_blocks/ (needs pymupdf)
python3 curate_suite.py           # raw_blocks/ -> va/ ams/ limitations/ findings/ fragments/ + manifest.json
python3 verify_lrm.py             # compiles va/ (expect clean) + limitations/ (expect pinned diagnostic)
```

`curate_suite.py` holds the per-block disposition table; every manual entry
carries a content fingerprint, so a re-extraction that renumbers blocks
fails loudly instead of misclassifying.
