# Enhancement-158 — Power-grid EMIR (electromigration + IR-drop)

Every chip is powered through a metal grid, and that grid is a reliability
liability in two ways. Under load the resistive grid drops `I·R` between the
supply pad and each cell, so logic far from the pad sees a sagging rail
(**IR-drop**) that slows it down or breaks it. And the metal wires carrying that
current wear out over years as momentum-transfer from electrons pushes metal
atoms downstream (**electromigration**), eventually voiding a wire open. Sign-off
runs an "EMIR" analysis to find the worst IR-drop and the wires most at risk.
This enhancement adds that as a new `emir` command, completing the reliability
row of `ngspice_gaps.md` alongside device aging ([Enhancement-157](Enhancement-157.md)).

## What changed

A new command:

```
emir [rail <V>] [thresh <frac>] [thick <m>] [jmax <A/m2>] [n <exp>] [tref <s>] [top <k>] [verbose]
```

`emir` runs a DC solve of the power-distribution network and reports:

- **IR-drop** — for every node, the drop below the ideal rail (`rail − V(node)`);
  the worst node, and every node past a threshold (default 10 % of the rail).
- **Electromigration** — for every wire-segment resistor, the current **density**
  `J = |I| / (w · thickness)`, ranked; the worst segment, every segment past the
  current-density limit `Jmax`, and a Black's-equation relative lifetime.

## Electromigration is about current density, not current

The key physics — and the reason a dedicated analysis is worthwhile — is that EM
depends on **current density**, not current. A fat trunk wire carrying a huge
current can be perfectly safe, while a thin wire carrying a fraction of that
current voids first, because the *density* in the thin wire is higher. Black's
equation makes this quantitative:

```
MTTF = A · J^(−n) · exp(Ea / kT)
```

so lifetime falls as the square of density (`n ≈ 2` for Cu/Al). `emir` reports a
**relative** MTTF, `MTTF/ref = (Jmax/J)^n`, which needs no process-specific
prefactor: a segment sitting exactly at `Jmax` has `MTTF = tref`, one at twice
the limit has a quarter of the lifetime, and one at half the limit has four times.

That is exactly why real power grids **taper** wire width with carried current —
wide near the pad where current is high, narrow at the leaves — to keep `J`
roughly constant across the grid.

## Implementation notes

- **`frontend/com_emir.c`** (new). Runs a fresh `op` (the `com_optimize`
  synchronous-dispatch pattern), then:
  - **IR-drop** walks the current plot's node-voltage vectors
    (`plot_cur->pl_dvecs`, filtered to `SV_VOLTAGE`), auto-detecting the rail as
    the highest node voltage unless one is given.
  - **EM** enumerates the resistor instances (the device type whose name is
    `"Resistor"`), reading each segment's current and width with the nutmeg
    expression engine (`@Rk[i]`, `@Rk[w]`) — so it works for any resistor and
    needs no device-struct access. Segments without a width are skipped and
    counted.
  Both tables are `qsort`-ranked (IR by drop, EM by density) and truncated to
  `top` rows.
- Registered in **`frontend/commands.c`** / **`com_commands.h`** and the frontend
  **`Makefile.am`**.

## Verification

[`examples/emir_examples/verify_emir.py`](../examples/emir_examples/verify_emir.py),
under **both** the Sparse and KLU solvers (EMIR reads a DC solution, so it is
solver-independent), on a 3-segment ladder off a 1 V rail with tapering widths:

- **IR-drop** — the worst drop is 0.30 V (30 %) at the far tap, matching the exact
  ladder solve, and scales linearly with load current.
- **EM density** — `J = I/(w·thick)` is exact, and the worst-density segment is
  the *narrow, low-current* wire, not the high-current wide one.
- **Black's law** — the MTTF ratio between two segments equals `(J₂/J₁)^n`.
- **violations** — with `Jmax` set between the trunk and leaf densities, exactly
  the under-sized segments fail.
- **rail auto-detect** equals an explicit rail.
- **OSDI load** — a Verilog-A device sinking current at a tap is handled
  identically to a current source.

![IR-drop and electromigration](../examples/emir_examples/emir_grid.png)

The figure makes the central point visible: along a 10-segment ladder the
well-tapered segments sit at a constant density below the limit, while two
deliberately under-sized segments violate `Jmax` **even though they carry less
current than the safe trunk**.

## Scope and follow-ups

The first cut is DC (static) EMIR: worst-case IR-drop and average-current EM on
the resistive grid. Natural follow-ups: **transient/RMS** EM (integrate the
current waveform for AC-stress current density and add the separate RMS-limited
"self-heating" and peak-limited checks), **ground-bounce** as a distinct
Vss-grid report, and true **Black-equation MTTF with a temperature map** (couple
the local `J²R` heating back into `T`).
