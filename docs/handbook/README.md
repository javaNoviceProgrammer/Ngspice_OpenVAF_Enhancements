# The Enhanced ngspice + OpenVAF Handbook

This handbook is the consolidated user guide to the enhanced toolchain in this
repository: **openvaf-r** (the Verilog-A compiler) and **ngspice-46** (the
simulator), as extended by the enhancement series (see the
[index](05-enhancement-index.md)). The repository's top-level
[README](../../README.md) carries the one-line enhancement index; the
detailed write-ups live in [`enhancements_doc/`](../../enhancements_doc/),
one per enhancement, in the order the work happened. This handbook
reorganizes that material by **what you want to do** — so you don't need to
know the project history to find out whether a language feature works, how
to run an analysis, or where the sharp edges are.

> **Prefer a single file?** The whole handbook *plus the complete text of
> every enhancement write-up* is compiled into one PDF with a linked table
> of contents: [`docs/Ngspice-OpenVAF-Handbook.pdf`](../Ngspice-OpenVAF-Handbook.pdf).
> Regenerate it after edits with `python3 docs/handbook/build_pdf.py`
> (needs pandoc + xelatex).

## The chapters

| Chapter | Read it when you want to… |
|---|---|
| [1 · Getting started](01-getting-started.md) | install or build the tools, compile your first Verilog-A model, load it in ngspice, and run the shipped example suites |
| [2 · Verilog-A language support](02-verilog-a-language.md) | know whether a language construct works — the full feature matrix, organized by LRM area, with a pointer to the example folder that proves each entry |
| [3 · Simulating with ngspice](03-ngspice-workflows.md) | run analyses over your compiled models — operating point through S-parameters, parameter sweeps, Monte Carlo, noise, measurements, Touchstone import/export |
| [4 · Limitations and gotchas](04-limitations-and-gotchas.md) | know what *doesn't* work, what is out of scope by design, and the traps that cost real debugging time |
| [5 · Enhancement index](05-enhancement-index.md) | trace a feature back to the enhancement that built it — one line per enhancement with links to the detailed write-up and the example folder |

## How the material is verified

Every feature claimed in this handbook is guarded by a **verify script** in
[`examples/`](../../examples/): a self-contained Python script that compiles the
relevant Verilog-A model with the committed compiler, runs it through the
committed ngspice, and checks the numbers against closed-form expectations.
The feature-matrix entries in chapter 2 and the workflow recipes in chapter 3
each link to the folder that pins them. If you want to see a feature in
action, running its verify script is the fastest way:

```bash
python3 examples/dowhile_examples/verify_dowhile.py
```

Two larger guards sit on top of the per-feature suites:

- **`VA_TEST/`** — the public VA-Models collection (BSIM4/6/BULK/CMG/IMG/SOI,
  PSP, HiCUM, MEXTRAM, EKV, ASM-HEMT, and more; 92 standalone models), all of
  which compile with `python3 VA_TEST/compile_all.py`;
- **`examples/physcheck_examples/`** — a physics regression suite that checks
  industry models against analytic device laws (60 mV/decade junction slope,
  4kT/R thermal noise identity, AC-vs-numeric-derivative Jacobian
  cross-checks) through the whole toolchain.

## Reference documents

The [`docs/`](..) folder holds the primary sources this project is written
against: the Verilog-AMS Language Reference Manual (`VAMS-LRM-2023.pdf` —
Verilog-A is its Annex C subset), the ngspice-46 manual, and the OSDI
interface specification. Its [`compliance/`](../compliance/) subfolder holds the
[Verilog-A LRM compliance document](../compliance/OpenVAF_Verilog-A_LRM_Compliance.md)
(with a PDF edition) — clause-by-clause language coverage with verified
code examples. Its [`change_log/`](../change_log/) subfolder holds the two full
change reports — [ngspice](../change_log/ngspice_changes_full-report.md) and
[openvaf-r](../change_log/openvaf_changes_full-report.md), each with a PDF edition —
documenting every modification this project applied to either tool,
organized by subsystem, with its reason and enhancement link. When the handbook cites "LRM 4.5.1" or similar,
that's the document it means.
