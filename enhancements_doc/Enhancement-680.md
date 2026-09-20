# Enhancement-680: an integer operating-point variable survives `.option interp` — the interpolation path read it through the union's double

**Scope:** F10 of the
[bug hunt of 2026-09-19](../docs/bug_hunts/2026-09-19_openvaf-r-operators-folding-and-delays.md).
ngspice: `src/frontend/outitf.c` (`InterpFileAdd` and `InterpPlotAdd`: a
special vector read by its type), `src/frontend/spiceif.c` (`if_is_option`:
`interp` is a known option word). `examples/opvar_examples/` (four checks,
15). **ngspice only.**

**Suites:** [`opvar_examples`](../examples/opvar_examples/) 14 of 14 per
solver, both solvers (3 of the 4 new checks fail on the E-670 binaries;
the control passes); `optknown` unchanged; full sweep 531 of 531.

## What was wrong

```verilog
(*desc="k"*) integer k; (*desc="r"*) real r; (*desc="big"*) integer big;
k = (V(a,b) > 0.5) ? 7 : 3; r = k; big = 1000000;
```

`.print tran @n1[k] @n1[r] @n1[big]` under `.option interp`, a pulse rising
at 1 µs:

| t | `k` | `r` | `big` |
|---|---|---|---|
| 0 | **1.48e-323** | 3 | **3** |
| 0.5 µs | **0.125** | 3 | **3** |
| 1.5 µs | **0.125** | 7 | **7** |

Without `interp`, and under `dc`, `op` and `ac`, the integers print
correctly; the real beside them is right either way.

An operating-point variable is a "special" vector: the output interface asks
the device for it at every point (`getSpecial`) and gets an `IFvalue`, a
union, typed by the descriptor — `IF_INTEGER` for an integer opvar, which
[E-32](Enhancement-32.md) taught the ordinary output paths to record as a
real. The two interpolation routines `.option interp` switches in read every
special through `val.rValue` regardless of type. An integer's four bytes
then sit under the previous double's upper bytes: with nothing above them,
3 reads as 1.48e-323, the denormal whose bit pattern is 3; with the previous
column's 3.0 above them, `big`'s 1000000 reads as 3.0000000000004 — the
previous column's value with a few low bits changed, which is what looked
like a misaligned vector. Both output paths had it: the file path a batch
`.print tran` takes, and the plot path a control-block `tran` with saved
vectors takes.

## What changed

**The special is read by its type**, once, in both routines: an
`IF_INTEGER` value through `val.iValue`, cast to the double every plot
vector is — the rule E-32 set for the other paths — and a real through
`val.rValue` as before. The integer then interpolates linearly like any
other vector: on a grid point between two accepted points where it changed,
the value is fractional, exactly as the same quantity declared `real` would
be.

## Verification

| check | result |
|---|---|
| file path: `.print tran @n1[region] @n1[ids]` under `.option interp`, a pulse 0.4 → 0.6 V at 2 µs, `.tran 0.5u 4u` | region 1 on the grid before, 2 after; ids = V/1k beside it (was 5e-324, then 0.125; the ids column right) |
| plot path: `.save @n1[region] @n1[ids]`, a control-block `tran` and `print` | the same (was 5.2e-3, then 0.125) |
| the hunt's `k`, `r`, `big` | 3 / 3 / 1e6 then 7 / 7 / 1e6, on both paths |
| without `interp` (control) | the accepted points read the same integers |
| `.option interp` on the deck | no `unknown option 'interp'` warning (it warned, and took effect anyway) |
| the E-670 binaries on the suite | 3 of the 4 new checks fail |
| full sweep | 531 of 531 |

## What this does not do

- A plot-path `print @n1[x]` after a control-block `tran` without a `.save`
  of that opvar is one scalar, the current value, on every binary: an opvar
  is recorded per point only when it is saved. The suite's plot-path check
  saves it.
- The `.option interp` warning is the one side item taken along: the deck
  reader's list of known option words ([E-438](Enhancement-438.md), extended
  by E-445, E-447 and E-451 with words that demonstrably take effect) lacked
  `interp`, the manual's own transient option, so the deck drew `unknown
  option 'interp' ... ignored` and was then interpolated. It is on the list.
