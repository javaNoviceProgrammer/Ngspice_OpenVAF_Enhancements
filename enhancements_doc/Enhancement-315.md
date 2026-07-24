# Enhancement-315 — ngspice: analysis crash-hardening (`.tf` / `.pz` / `.disto`)

Three hard crashes in the shipped binary, each on adversarial-but-valid input, found by
command/netlist fuzzing (the E-222…228 / E-270…285 hardening family). Each is now a clean
error; legitimate analyses are unaffected (the guards fire only on the failure paths).

## [6] `.tf` on a singular circuit → SIGABRT

A dangling inductor (`l1 2 3 1`, with nodes 2 and 3 floating) makes the operating point
singular. `tfanal.c` **ignored `CKTop`'s return value**, so when the operating point failed the
matrix was never factored, and the following `SMPsolve()` tripped
`assert( IS_VALID(Matrix) && IS_FACTORED(Matrix) )` (`spsolve.c:137`, SIGABRT).

**Fix:** propagate the `CKTop` error before solving — a well-posed `.tf` returns 0 there and is
unaffected.

## [7] second `.pz` over a URC device → SIGSEGV

`CKTic` zeroes the RHS vectors with a loop the compiler vectorises into `memset(CKTrhs, …)`.
Running a second `.pz` over a URC device reaches `CKTic` with `ckt->CKTrhs == NULL`, so the
zeroing wrote through a NULL pointer (SIGSEGV in `_platform_memset`).

**Fix:** `CKTic` returns cleanly when the RHS vectors (or the matrix) are unallocated — there
are no initial conditions to place into vectors that do not exist.

## [8] `.disto` with no distortion sources → SIGSEGV

`.disto` on a circuit with no nonlinear distortion-generating device (a plain resistor) leaves
`distoan.c`'s output section with a failed `OUTpBeginPlot` whose result was **unchecked**, so
`acPlot` stayed NULL and `OUTattributes(acPlot, …)` dereferenced it (SIGSEGV at
`OUTattributes+268`, address `0x28`). The very first plot (line 107) already checked its result;
the five output-section plots did not.

**Fix:** capture and check the `OUTpBeginPlot` result at each output-section plot, and bail
cleanly on a NULL `acPlot`.

## Verification

`examples/ngcrashanalysis_examples/verify_ngcrashanalysis.py` — 4 checks. Each of the three
decks crashed the pre-fix binary (SIGSEGV/SIGABRT) and now exits cleanly; a forward guard
confirms a legitimate `.tf` still computes the correct transfer function (a 1k:1k divider →
0.5). Legitimate `.pz` and `.disto` (with a real nonlinear device) were confirmed unaffected.
The full example regression passes.

## Scope of change

`src/spicelib/analysis/tfanal.c` (propagate the `CKTop` error), `src/spicelib/analysis/cktic.c`
(NULL-RHS guard), `src/spicelib/analysis/distoan.c` (output-section `OUTpBeginPlot` checks). No
interface change. Prebuilt `bin/macos/apple-silicon/ngspice` rebuilt.
