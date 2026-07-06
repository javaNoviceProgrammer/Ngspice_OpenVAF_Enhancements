# Enhancement-73 — the user handbook: 72 enhancements consolidated into `docs/handbook/` (version11)

This document describes Enhancement-73: a **documentation deliverable** —
the repository's first consolidated user guide. No compiler or ngspice
source changes.

## Why

After 72 enhancements the top-level README had grown to ~950 lines of
chronological, per-enhancement narrative — the story of the project, but
not a usable reference: to learn whether arrays work, a user had to know
that Enhancements 14, 15, 18, 20, 23, 33, 43 exist and read all seven. The
handbook reorganizes the same verified material **by what the user wants to
do**.

## The handbook (`docs/handbook/`, six files)

- **README.md** — orientation: the chapter map, how features are verified
  (every claim is pinned by a committed verify script), the reference PDFs.
- **01-getting-started.md** — prebuilt binaries; building from source
  (LLVM 18 pin, the ngspice configure line); a complete first-model
  walkthrough (`myres.va` → `openvaf-r` → `pre_osdi` deck → `v(mid)`);
  the example-suite and `_setup.py` conventions; VA_TEST and the
  integration suite.
- **02-verilog-a-language.md** — the **feature matrix**, 13 sections
  organized by LRM area (hierarchy/elaboration, nets/disciplines/natures,
  types/arrays, parameters, operators/literals, analog operators,
  contributions/probes, events, analog functions, statements/loops, system
  tasks, preprocessor, attributes). Every row links its enhancement doc
  and names the example folder that proves it.
- **03-ngspice-workflows.md** — simulator-side recipes: model cards vs
  instance lines, opvar access, `alter`/`.dc @inst[param]` sweeps, the
  analysis-coverage table, S-parameters + the full Touchstone
  import/export surface, both Monte Carlo idioms, debugging aids.
- **04-limitations-and-gotchas.md** — the honest map: Verilog-A (Annex C)
  vs AMS scope, fallback-semantics builtins, the compile-time/simulation-
  time binding model, documented design decisions (stateless `limexp`,
  non-advancing RNG seeds, `.disto`), ngspice control-language traps, and
  assorted pinned edges.
- **05-enhancement-index.md** — E-1…E-73 in one table: one line each,
  linking the `enhancements_doc/` write-up and the example folder.

## The PDF edition (`docs/Ngspice-OpenVAF-Handbook.pdf`)

The handbook **and the complete text of all 73 enhancement write-ups** are
also compiled into a single 202-page PDF with a linked table of contents:
Part I = the five handbook chapters, Part II = `enhancements_doc/`
Enhancement-1 … 73 in order, each starting on a fresh page. The committed
generator (`docs/handbook/build_pdf.py`, pandoc + xelatex) demotes headings
under the two Part headings, rewrites cross-document links into internal
PDF anchors (links to example folders/README sections become absolute
GitHub URLs so they stay clickable), strips the historical "(versionN)"
workflow tags from the enhancement titles, assigns proportional column widths to
the wide feature-matrix tables via a pandoc Lua filter (the gfm reader
emits none, which overflows the page), and maps the handful of math glyphs
missing from STIX Two Text (→ ≥ ≈ ≡ ∠ √ …) onto math-mode equivalents —
the final build has **zero missing-glyph warnings and zero undefined link
references**. Building the PDF also surfaced (and fixed) a stale intra-doc
anchor in `enhancements_doc/Enhancement-2.md` (`§6` pointing at a heading
numbered 5 — broken on GitHub too).

## The README consolidation

With the handbook in place, the top-level README's ~850 lines of
per-enhancement narrative sections (E-1 … E-72) were replaced by the
handbook's one-line **index table** (Doc + Examples links, re-anchored to
the repo root) plus a prominent pointer to the handbook and its PDF
edition — the README drops from 965 to ~210 lines and now reads: header /
Precursors / the enhancements index / VA_TEST / Prebuilt Binaries / CI.
The detailed narratives remain where they always lived in full,
`enhancements_doc/`, and the result plots remain in their example folders.

## Verified

- **Link integrity**: a checker walks every markdown link and `#anchor` in
  the six files (GitHub slug rules, code spans excluded) — **205 links, 0
  failures** — and every `examples/<name>` mention in code spans is a real
  committed folder.
- **Link integrity, README**: the same checker logic over the rewritten
  README — 110 relative links, 0 failures.
- **Command truth**: the getting-started model and deck were run verbatim
  with the repo binaries (`v(mid) = 1.000000e+00` exactly as printed in
  the guide); the chapter-3 command spellings (`alter @n1[r]`,
  `.dc @n1[r] … V1 …`, `agauss`/`sgauss`/`setseed`, `portnum 1 z0 50`,
  `wrsnp`/`rdsnp`) were cross-checked against the committed tutorial
  decks.
- **One matrix claim corrected by testing**: `casex` — written from
  memory as supported — was probe-compiled and is **not** implemented; the
  matrix and the limitations chapter now say so explicitly (plain `case`,
  including over strings and arrays, is supported). The project's own
  audit lesson — *verify, don't assume* — applied to its documentation.

## Regression

No compiler or ngspice source changes; the Enhancement-72 regression state
stands (66/66 example suites, integration 28/28, corpus 92/92).
