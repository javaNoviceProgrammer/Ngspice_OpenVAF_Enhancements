# Enhancement-100 — the first hundred: a milestone audit & retrospective

Enhancement-100 is a checkpoint, not a feature. Where Enhancements 1–99 each
added or fixed something in the compiler or the simulator, E-100 adds no
compiler or simulator code at all. Instead it does three things: it
**re-verifies the whole tree** from a clean state, it **audits the repository
for provenance and link hygiene**, and it **steps back to look at the arc** of
the first hundred enhancements. Every number below was measured on the tree as
it stands today (2026-07-08), not estimated.

## By the numbers

| Metric | Value |
|---|---|
| Feature / fix enhancements | 99 (E-1 … E-99) |
| GitHub releases | 95 (a few early enhancements shipped grouped) |
| Committed example suites | 90 (`verify_*.py`) |
| Pinned assertions across those suites | 635 |
| OpenVAF integration tests | 28 |
| Committed `.osdi` models under `examples/` | 231 |
| Enhancements that touched **openvaf-r** | 78 |
| Enhancements that touched **ngspice** | 27 |
| Commits on `main` | 306 |
| Span | 2026-06-26 → 2026-07-08 (~12 days) |

(78 + 27 exceeds 99 because a handful — e.g. the OSDI-parameter warning of
[E-93](Enhancement-93.md) — changed both sides in one fold.)

## Audit results

**Regression (today, from the committed binaries).** All **90 verify suites
pass, 0 fail**, and the OpenVAF integration suite is **28/28**. This is the
same suite set that has gated every fold; running it end-to-end at the
hundred-mark confirms no suite has silently rotted.

**Provenance.** Zero git-tracked files under `examples/` contain an absolute
path (`/Users/…`, `/home/…`, `/private/tmp/…`). The 231 committed `.osdi`
binaries carry only bare or repo-relative names in their baked-in provenance
strings, per the standing portability rule — a machine that clones the repo
sees nothing about the machine that built it. (Absolute paths do exist in
*untracked* local build scratch — `.build/`, `benchmark/cir/`, `__pycache__` —
but those are gitignored and never leave the build host.)

**Links.** All **216 relative navigation links in the README resolve**, every
one of the 99 `enhancements_doc/Enhancement-N.md` files is present on disk, and
a sweep of ~991 relative links across all 109 Markdown files found no broken
file references. (The handful the sweep flagged were Verilog signal lists such
as `V(out, gnd)` inside inline code — matched by the link regex, not real
links.)

## The arc, by theme

The hundred enhancements fall into a few broad families:

- **Core Verilog-A language.** The bulk of the early and middle work: transport
  delay ([E-1](Enhancement-1.md)), indirect branch assignment
  ([E-2](Enhancement-2.md)), bus nets and ports ([E-3](Enhancement-3.md)),
  `laplace_*`/`zi_*` filters ([E-4](Enhancement-4.md)), module hierarchy
  ([E-5](Enhancement-5.md)), arrays and multi-dimensional arrays
  (E-14/15), `$table_model` and its multi-dimensional and cubic-spline forms
  (E-16/17/22/40), `defparam`, `paramset`, generate constructs, concatenation,
  the integrator family, and a long tail of system functions and operators.

- **Correctness & ICE fixes.** Compiler crashes and wrong answers rooted out
  one at a time — the comment-at-EOF lexer hang ([E-35](Enhancement-35.md)),
  the bus-port node-ordering bug ([E-90](Enhancement-90.md)), the
  contribute-to-ground panic ([E-97](Enhancement-97.md)), integer-state slot
  types ([E-32](Enhancement-32.md)), and many more.

- **ngspice simulator features.** The `.dc @inst[param]` sweeps, RF and
  Touchstone I/O (E-62/63/64/72), Monte-Carlo, lifecycle/leak fixes, the
  zero-warning rebuild ([E-77](Enhancement-77.md)), and the whole `pyplot`
  command family (E-94/95/98/99).

- **Systematic audits.** Deliberate probe-sweeps over a construct class that
  then fix whatever real gap surfaces: operators (E-37/38/61), the preprocessor
  ([E-65](Enhancement-65.md)), generate ([E-67](Enhancement-67.md)), display
  tasks ([E-71](Enhancement-71.md)), opvars ([E-69](Enhancement-69.md)), the
  231-example LRM-2023 sweep ([E-84](Enhancement-84.md)).

- **Validation, benchmarks & docs.** OSDI-vs-built-in benchmarks (E-74/79),
  static and dynamic physics cross-checks (E-57/75/80), the user handbook
  ([E-73](Enhancement-73.md)), and the change-log reports.

## Recurring engineering lessons

A few patterns showed up often enough to be worth naming:

1. **"Scaffolded but unwired."** More than once, a feature's machinery was
   already present in the tree but never connected at some node-kind or
   signature boundary, so it silently did nothing — the macro-recursion guard
   ([E-65](Enhancement-65.md)), derived natures ([E-39](Enhancement-39.md)),
   and others. The fix was usually small; *finding* it was the work.

2. **Signature/builtin tables are a defect magnet.** The argument-type tables
   for built-in functions were behind a recurring class of bugs (E-33, E-40,
   E-47, E-49) — an off-by-one or a too-eager `resize()` there corrupts a whole
   family of calls.

3. **Textual pre-passes are a clean extension seam.** Several late language
   features (name-then-range decls, legacy/bare generate, source-location
   macros) were implemented as ordered normalization passes in
   `hir/src/elaborate.rs` rather than deep parser surgery (E-85/88/89/91/96).

4. **The OSDI ABI is a living contract.** Runtime features repeatedly required
   bumping the OSDI descriptor ABI (0.4 → 0.7) and regenerating `.osdi` in
   lockstep with ngspice's loader (E-45/51/54/93) — a reminder to keep the two
   halves of the toolchain versioned together.

5. **Every enhancement ships a pinned example.** The single most valuable habit
   is that each enhancement lands with a `verify_*.py` suite that becomes a
   permanent regression pin. The 90-green run above is the compounding interest
   on that discipline.

## What's next

The most concrete deferred item is **`$table_model` with runtime array data
arguments** (the grid/values passed as array variables rather than inline or
from a file), explicitly held back from [E-91](Enhancement-91.md). Beyond that,
the audit-and-fix loop still has surface area: the LRM sweep graduated 231
examples, but AMS-level constructs remain out of scope by design.

The first hundred are done and green. Onward.
