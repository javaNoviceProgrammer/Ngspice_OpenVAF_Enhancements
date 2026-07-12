# Enhancement-162 — `.hb` dot-card for harmonic balance

[Enhancement-134](Enhancement-134.md) added single-tone **harmonic balance** as
the `hb` command, run inside a `.control` block. But the rest of the
periodic-steady-state suite — `.pss`, `.pac`, `.pnoise`, `.pxf`, `.psp`, `.sp` —
is invoked as **netlist dot-cards**, so a deck that mixes them with HB had to
switch styles. This enhancement adds a `.hb` dot-card that dispatches to the same
E-134 engine, giving the HB family dot-card parity with the PSS family.

## What changed

A top-level `.hb` card in the netlist now runs harmonic balance:

```
* single-tone HB straight from the deck -- no .control block needed
V1 s 0 SIN(0 1 100meg)
Rs s a 100
D1 a n DMOD
Rn n 0 1k
.model DMOD D(IS=1e-12 N=1.2)
.hb 100meg 5
.end
```

`.hb <f0> <K> [points] [maxiter]` takes exactly the same arguments as the `hb`
command and produces the identical harmonic-balance spectrum — it *is* the same
engine.

## How it works

Rather than duplicating the HB machinery as a separate analysis job, `.hb` reuses
the deck→control mechanism that [Enhancement-146](Enhancement-146.md) introduced
for `.sweep`: during deck loading (`frontend/inp.c`), a top-level `.hb …` line is
stripped of its leading `.` and appended to the post-parse control list, so it
executes as `hb …` (the `com_hb` command) once the circuit is built. A boundary
check keeps `.hb` from swallowing any future `.hb*` card.

This is a one-branch change that inherits everything the `hb` command already does
— argument parsing, the E-121 conversion-matrix Jacobian, source-stepping
continuation (E-135), and solver independence.

Before this change, `.hb` fell through to the parser and produced
`unimplemented dot command '.hb'` (the only `.hb` handler in ngspice was a
disabled `#ifdef WITH_HB` upstream stub that merely redirected to PSS — not the
E-134 engine).

## Verification

[`examples/hb_examples/verify_hb.py`](../examples/hb_examples/verify_hb.py) gains
two checks on top of the existing E-134 suite:

- The `.hb` dot-card, run in **plain batch mode** (no `.control` block), converges
  and produces a spectrum **bit-for-bit identical** to the `hb` command form on a
  junction-limited diode rectifier.
- `.hb` threads its optional `[points] [maxiter]` arguments through and coexists
  with a following `.control` block (deck order preserved).

Both the Sparse and KLU solvers give identical results, exactly as for the `hb`
command (HB runs its own dense complex Newton solve; the linear solver only reads
`G(t)/C(t)`).

## Notes

- Like `.sweep`, a bare command-style dot-card in a deck with no other analysis
  card prints a benign "no simulations run" batch-mode notice even though HB ran
  and printed its spectrum — HB is a command-style analysis, not a deck analysis
  job. Add any other analysis or a `.control` block if the notice is unwanted.
- The `hb` command form is unchanged and remains available.

## Scope and follow-ups

This gives single-tone HB dot-card parity. The natural extension is dot-cards for
the rest of the HB family — `.qpss`, `.hbosc` — via the same deck→control bridge.
