# Enhancement-708: four diagnostic slips — a based literal wider than its size draws L030 instead of being truncated in silence, `` `include "" `` names the empty name, a format width or precision above 4096 is refused at compile time and a `*` width is clamped at run time, and `laplace_nd`'s highest-order coefficient must be a finite non-zero number — said so for a NaN, refused for an infinity

**Scope:** F10 of the
[robustness campaign of 2026-09-23](../docs/bug_hunts/2026-09-23_openvaf-r-robustness-campaign.md).
**Compiler only.** `syntax/src/ast/expr_ext.rs` (`parse_based`, `BasedInt`,
`IntNumber::based_overflow`), `hir_def/src/body.rs` and `body/lower.rs`
(`based_overflow_literals`), `hir_ty/src/validation/body.rs` and `validation.rs`
(`BasedLiteralOverflow`, under lint L030), `preprocessor/src/diagnostics.rs` and
`processor.rs` and `basedb/src/diagnostics/preprocessor_error.rs` (`IncludeEmptyName`),
`hir_ty/src/inference.rs`, `inference/fmt_parser.rs` and `diagnostics.rs`
(`MAX_FMT_WIDTH`, `FmtWidthTooLarge`), `hir/src/lib.rs` (the limit re-exported),
`hir_lower/src/fmt.rs` (the `*` clamp), `hir_lower/src/expr.rs` (the Laplace check).
[`examples/diagslips_examples/`](../examples/diagslips_examples/) (14 checks, 46 per
solver). The handbook's L030 and format rows, the compliance document, the hunt page.

**Suites:** `diagslips` 46 of 46 per solver, both solvers (36 of 46 on the E-704
binaries), `fmtdiag` 40 of 40, `hunt13slips` (E-640, L030), `intrange`, `preproc`,
`stringio`, `lrmfilters`, `lrmlex`, `langguard` 132 of 132, `powguard` 37 of 37 and
`multimod` 28 of 28 unchanged; the compiler workspace tests green apart from the three
pre-existing sourcegen drift failures (221 passed), no build warnings; full sweep
532 of 532, run alone.

## What was wrong

- **A based literal that does not fit was truncated in silence.** `'hFFFFFFFFFF` (40
  bits) evaluated to −1 with no message; the decimal `4294967295` draws L030 ("integer
  literal … does not fit a 32-bit integer", E-590). The based literal takes another path
  — `parse_based_int_masked`, whose digit loop masks the value to the size (32 when
  unsized) exactly as IEEE 1364-2005 3.5.1 prescribes — and nothing reported the
  truncation; `8'hFFF` read as 255 the same way.
- **`` `include "" ``** was reported as `failed to read '/…/the/including/directory': is
  a directory`: the empty name joined onto the including file's directory and the read
  of that directory failed.
- **`$sformat` honoured a width up to 10⁹ and dropped a wider one in silence.**
  `$sformat(s, "%999999999d", 1)` compiled and allocated 2.0 GB at run time (the run
  time formats twice, once to measure and once into a buffer of that size);
  `"%2147483647d"` and `"%99999999999999999999d"` compiled too and printed the plain
  value, because the C library refuses a width past 2³¹ and the specifier was dropped. A
  `*` width fed 10⁹ from a variable did the same.
- **`laplace_nd` with a NaN highest-order coefficient** was refused at run time as "the
  denominator's highest-order coefficient must not be zero" (the check is `|a| > 0`,
  false for NaN), and an infinite one passed: it normalised every other coefficient to 0
  and the filter ran as a silent 0.

## What changed

1. **L030 for a based literal wider than its size.** `parse_based` measures the width
   of the digits as written — from the first digit that is not `0`, an `x`/`z` digit
   counting as a full digit, by digit count rather than through the 128-bit
   accumulator, so a 100 000-digit literal is measured and not shifted to nothing —
   and `IntNumber::based_overflow` reports `(spelling, bits, size)` when the bits exceed
   the size. Body lowering records it beside E-590's decimal case, and validation warns
   under the same lint: "based literal 'hFFFFFFFFFF has 40 significant bits, more than
   the 32 of an `integer`" / "the high 8 bits are dropped; it reads as -1", or "8'hFFF has
   12 significant bits, more than its declared size of 8 … reads as 255", with the note
   that a real is the spelling for more than 32 bits. `-A L030` silences it with the
   decimal case; a literal longer than 48 characters is abbreviated in the message
   (`'hFFFFFFFFFFFFFFFFFFFFFF...FFFFFFFF (100002 characters)`). `'hFFFFFFFF`,
   `'h0FFFFFFFF` (a leading `0` adds no bits) and `8'hFF` are silent.
2. **`` `include "" `` names the empty name.** Before the file is looked up: an error
   saying the directive "names no file", labelled "empty file name", with the help line
   that the name is looked up in the including file's directory and then the `-I`
   directories.
3. **A format width or precision is bounded.** `MAX_FMT_WIDTH = 4096` in
   `hir_ty::inference` (re-exported by `hir`). The format parser accumulates the literal
   width and precision as written and refuses either above the limit — "the field width
   999999999 is above the limit of 4096", "the field precision 99999999999999999999 is
   above the limit of 4096", the digits quoted as written rather than as a wrapped
   number — labelled at the digits, with the help line that a width only pads and the
   run time formats into a buffer of that size. A `*` width or precision supplied at run
   time is clamped to [−4096, 4096] in the lowering (a negative width is C's
   left-justify), so `$strobe("[%*d]", w, 7)` with `w = 100000` prints a 4096-wide field.
   `%4096d` and `%08.3f` compile as before.
4. **The Laplace highest-order coefficient must be finite and non-zero.** The run-time
   check is `|a| > 0 && |a| < ∞` and its fatal reads "the denominator's highest-order
   coefficient must be a finite non-zero number, but is nan" (or "inf"). With
   Enhancement-706 the literal `'{1, 0.0/0.0}` never reaches it; the check is for the
   deck-fixed value (`parameter real a = 0.0, b = 0.0; … '{1, a/b}`).

## Verification

`diagslips_examples` (Enhancement-650's diagnostic-slips suite) gains checks [33]–[46]:
the 40-bit, 33-bit, sized and decimal-based literals warn with their bit counts and
values, the 32-bit, leading-zero and in-size ones are silent, the 100 000-digit literal
is measured and abbreviated, `-A L030` silences it; `` `include "" `` gets its sentence
and no "is a directory"; `%999999999d` and a 20-digit precision are refused with the
digits as written, `%4096d` and `%08.3f` compile, a `*` width of 100 000 prints a
4096-wide field at run time; and a deck-fixed NaN and a deck-fixed infinite highest-order
coefficient are each refused as "must be a finite non-zero number, but is nan/inf". Ten
of the fourteen fail on the E-704 binaries (36 of 46). By hand: the campaign's F10 probe
set, plus `'b1` followed by 32 zeros (33 bits, warned) and `'d4294967295` (32 bits,
silent).

## What this does not do

- A based literal with `x`/`z` digits as a `casex`/`casez` item is judged by
  Enhancement-78's rules and is not measured here.
- The width limit is a constant. LRM 9.4 (IEEE 1364-2005 17.1.1.2) sets no bound; 4096
  is above any field a model prints and below any buffer worth reserving. `$strobe`'s
  own line buffer truncates a long line as before.
- The run-time `$sformat` still formats twice (measure, then write); a width under the
  limit costs what it always cost.
