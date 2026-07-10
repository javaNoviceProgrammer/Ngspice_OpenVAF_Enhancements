# Enhancement-123 — finish `.pac`: source stimulus + conversion sidebands

[E-122](Enhancement-122.md) landed a working `.pac` command, but two pieces were
deliberately deferred: the stimulus was a fixed unit current at the osc node, and
the output was only the 0-th sideband. E-123 completes both — `.pac` now drives a
**netlist-referenced small-signal source** and emits the **full set of conversion
sidebands** — so it is a general periodic-AC analysis.

## 1. Source-referenced stimulus

`.ac` takes its small-signal drive from sources carrying an `AC <mag> <phase>`
spec; `.pac` now does the same. During harmonic extraction the engine calls
`CKTacLoad`, which clears `CKTrhs`/`CKTirhs` and lets every device stamp — a source
with an `AC` spec stamps its (bias-independent) value there. `pac_extract_harmonics`
captures that vector as the sideband-0 stimulus `B_0`; `pac_solve_at` uses it when
present, falling back to the unit-current-at-osc-node probe otherwise.

The consequence is the physically meaningful one: with a source the PAC result is a
**transfer / conversion gain** (output per unit source), not a driving-point
impedance. For the RC driven by `V1 ... AC 1`, the sideband-0 response at `b` is the
low-pass transfer `|H(f)| = 1/√(1 + (2πfRC)²)` — `0.998` at 10 kHz down to `0.157`
at 1 MHz — versus E-122's driving-point `998 → 157 Ω`.

## 2. Multi-sideband conversion-gain output

A new optional trailing field selects how many conversion sidebands to emit:

```
.pac Fguess StabTime OscNode Points Harmonics SC_iter Steady_coeff \
     <DEC|OCT|LIN> Npts Fstart Fstop [maxsideband]
```

With `maxsideband = Ksb`, `pac_sweep` builds an expanded output name list and
writes, at every swept input frequency, the response at each sideband `f_in + k·f0`
for `k = −Ksb … Ksb` as its own complex vector. Sideband 0 keeps the plain node
name (so `plot b` still gives the fundamental), and the conversion sidebands are
named `<node>_usb<k>` (upper, `k > 0`) and `<node>_lsb<k>` (lower, `k < 0`) — e.g.
`b_usb1`, `b_lsb1` — created as vector UIDs with `IFnewUid`. `Ksb` defaults to 0
(sideband 0 only, exactly E-122) and is clamped to the number of harmonics the
conversion matrix carries.

## Verification

`rc_pac_src.cir` drives `V1 a 0 DC 0 AC 1 SIN(0 1 1meg)` and asks for two sidebands
each side (`.pac … dec 10 10k 1meg 2`):

```
PAC sweep: dec from 10000 to 1e+06 Hz (10 pts/decade) around f0 = 1e+06 Hz;
           stimulus: netlist AC source; 5 sidebands

  mag(b):      9.980e-01 (10 kHz) ... 1.572e-01 (1 MHz)     <- low-pass transfer
  mag(b_usb1): ~2e-17                                        <- no conversion (linear)
  mag(b_lsb1): ~1.7e-17
```

- The source-referenced sideband-0 response equals the analytic AC transfer
  `1/√(1+(2πfRC)²)` across the sweep (worst-case rel. err `< 2e−2`) — and is a
  thousand-fold different from E-122's unit-current driving-point impedance,
  confirming the stimulus is the netlist source.
- The `b_usb1` / `b_lsb1` conversion sidebands exist as named vectors and come back
  at floating-point zero — a **linear** circuit does not mix, exactly as it must. A
  pumped nonlinear circuit fills them with real conversion gain through the same
  path.

`verify_rcpac.py` runs both the E-122 (unit-current) and E-123 (source + sidebands)
decks under Sparse and asserts all of the above.

## Files changed

| File | Change |
|---|---|
| `ngspice-46/src/include/ngspice/pssdefs.h` | `PSSan.PACmaxSideband` + `PAC_MAXSB` param id |
| `ngspice-46/src/spicelib/analysis/psssetp.c` | `pac_maxsb` setter + IFparm entry |
| `ngspice-46/src/spicelib/parser/inp2dot.c` | `dot_pac` parses the optional trailing `maxsideband` |
| `ngspice-46/src/spicelib/analysis/dcpss.c` | capture the source AC RHS `B_0` in `pac_extract_harmonics`; `pac_solve_at` gains a `use_src` stimulus selector; `pac_sweep` emits `2·Ksb+1` sidebands as named vectors |
| `examples/rfpss_examples/rc_pac_src.cir`, `verify_rcpac.py` | source-referenced + multi-sideband example and checks |

## Scope

`.pac` is now a complete periodic-AC analysis: PSS operating point → periodic
Jacobian harmonics → conversion matrix → swept solve, driven by a netlist source and
reporting every conversion sideband. The same conversion-matrix solve is the
substrate for **periodic noise** (fold device-noise sidebands through `Hᵀ`) and
**PXF** (periodic transfer function), the natural next analyses.
