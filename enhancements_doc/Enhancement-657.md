# Enhancement-657: a corner on a parameter the model tests with `$param_given` moves it only when the deck gave it — the E-555 gate exported for corners

**Scope:** F4 of the
[bug hunt of 2026-09-18](../docs/bug_hunts/2026-09-18_openvaf-r-corners-and-run-control.md).
Compiler: `openvaf/osdi/src/metadata.rs` (`corner_params` carries the
parameter's `given_tested` bit), `openvaf/osdi/src/lib.rs` (the optional
`OSDI_CORNER_GATED` array beside the corner records). ngspice: `src/osdi/osdi.h`
(`OsdiCornerParam.gated`), `src/osdi/osdiregistry.c` (the array read at load),
`src/osdi/osdisetup.c` (the corner writer's gate and its note).
`examples/vacorner_examples/` (five checks added, 23 per solver). Handbook
[§2.13](../docs/handbook/02-verilog-a-language.md) row and
[§3.7](../docs/handbook/03-ngspice-workflows.md). **Compiler and ngspice
together.**

**Suites:** [`vacorner_examples`](../examples/vacorner_examples/) 23 of 23 per
solver, both solvers (3 fail on the E-656 binaries); `paramgiven`, `cornerscmd`,
`autocorner`, `osdimc`, `savemc` unchanged; the compiler's workspace tests green
(the three sourcegen rewrites are the known drift); full sweep 529 of 529.

## What was wrong

A corner is a write through the descriptor's setter, and the setter marks the
parameter *given*. [E-555](Enhancement-555.md) established what that does to a
model that picks a default with `$param_given`: BSIM4 derives `toxp` from `toxe`
unless `toxp` is given, so a machine write of `toxp` that the deck never gave
does not vary the model — it switches it to the "given" branch at the written
value. E-555 therefore had the compiler mark such a parameter in its statistics
record (`OSDI_DIST_GATED`) and the draw applier skip it, with a note, when the
deck never gave it.

The corner writer of [E-654](Enhancement-654.md) reused that gate — but the gate
lives in the statistics record only. A parameter with a `corner` attribute and
no `std` has no such record, so its corner went through ungated:

```verilog
(* corner="ss=2" *) parameter real a = 1;
real g;
analog begin g = $param_given(a) ? a : 10; ... end
```

At `.option corner=ss` with `a` never given, the model computed with `g = 2`
where the nominal run had `g = 10`: the corner marked `a` given and the model
took its given branch — a branch flip, not a corner shift, and no message. The
`corners` loop, `.option autocorner`, `set corner=` between runs all took the
same path. With `std` beside the corner the gate did fire, but the note it
printed was the draw's: *a draw would switch the model … not drawn. Give it on
the card, or altermod it, to vary it*, which for a corner names the wrong
mechanism.

## What changed

* **The compiler exports the gate for corners.** `corner_params` carries the
  parameter's `given_tested` bit (the E-555 analysis, `module_given_tests`) and
  the OSDI export writes it as `OSDI_CORNER_GATED` — one `u32` per
  `OSDI_CORNER_INFOS` record, in the same order, emitted only when some entry is
  gated. The record layout and the other two corner symbols are unchanged; an
  older simulator ignores the new symbol, an object from an older compiler has
  none and is read as ungated.
* **The registry reads it** into a `gated` field of the in-memory
  `OsdiCornerParam` record.
* **The corner writer gates on it.** A cornered parameter the model tests with
  `$param_given` and the deck never gave is left at its nominal, whether the gate
  comes from the corner table (a corner-only parameter) or from the statistics
  record (a parameter with both; an object from a pre-E-657 compiler carries only
  that one). The note is the corner's, once per parameter: *`corner ss: gm:a` is
  not given by the deck and the model tests `$param_given(a)`: the corner's write
  would switch the model to its "given" branch instead of moving it — left at its
  nominal. Give it on the card, or altermod it, for the corner to move it.* The
  parameter given on the card, or `altermod`ed (which makes it given, E-614),
  moves to the corner as before. An untested parameter beside it is not
  affected.

No compile-time warning, deliberately, for the reason E-555 gave none: a PDK
card that gives the parameter makes its corner work exactly as declared, and a
warning at the declaration would fire on every BSIM-class model whose corners sit
on `$param_given`-tested parameters.

## Verification

`cg` has `a` (corner only, tested), `b` (`std` beside the corner, tested) and
`c` (corner only, untested); the model conducts `(g_a + g_b + c)` mS with each
`g` the parameter when given, 10 otherwise.

| check | result |
|---|---|
| `.option corner=ss`, `a` never given, two runs | `a` 1 on both, `c` 3, i = −23 mA; the corner's note once; no draw wording |
| `a=1` on the card | `a` 2, i = −15 mA, no note for `a` |
| `b` (`std` beside the corner) | the corner's note once, not the draw's; under `.option osdimc` `b` 1 on three trials, no draw note |
| `corners -output i=i(v1) a=@gm[a] c=@gm[c]` | `a` 1 1 1, `c` 1 3 1, i −21 −23 −21 mA; the notes once each |
| `altermod gm a=1`, `set corner=ss` | `a` 2, i = −15 mA |
| the E-656 binaries on the same suite | 3 of the 5 fail (`a` 2 at the corner; the draw's note for `b`) |

Full sweep 529 of 529 on both solvers.

## What this does not do

- A parameter with a corner *and* statistics, compiled before E-657, is still
  gated through its statistics record — that path is unchanged and now prints
  the corner's note. A corner-only parameter from such an object is ungated, as
  it was: recompile the model.
- The gate follows the deck's givenness at capture, as E-555's does: a
  parameter made given by `altermod` is moved from the next run on.
- The other findings of the hunt (F1: the first cornered run under `osdimc`;
  F2: quoted words on the `corners` line; …) are separate.
