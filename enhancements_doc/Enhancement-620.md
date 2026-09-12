# Enhancement-620: statistics that can never vary are said — `std_rel` on a nominal of 0, a sigma of 0

**Scope:** the compiler — `openvaf/sim_back/src/module_info.rs`, two warnings at the
attribute (`ZeroSigma`: `std=0` / `std_rel=0`; `RelSigmaOnZeroDefault`: `std_rel` on a
parameter whose default is the constant 0). ngspice — `src/osdi/osdisetup.c`,
`osdimc_zero_sigma()`: the draw applier says once per parameter when a relative sigma
meets a nominal of 0. `examples/osdimc_examples/` grows 42 → 44 checks per solver with a
new `smczero.va`; handbook [§2](../docs/handbook/02-verilog-a-language.md) attribute row,
the [statistics guide](../docs/internals/ngspice_internals/ngspice_statistics.md) §7, the
suite README. **Compiler and ngspice together.** F16 of the
[2026-09-12 hunt](../docs/bug_hunts/2026-09-12_statistics-record-and-kicad-hunt.md).

**Suites:** [`osdimc_examples`](../examples/osdimc_examples/) 44 of 44 per solver, both
solvers; the ten sibling suites green; full sweep 505 of 505 with the rebuilt compiler.

## What was wrong

```verilog
(* type="instance", std_rel=0.1 *) parameter real dr = 0.0;   // a mismatch parameter's natural default
```
```
osdimc: trial 2: mm:dr = 0 (nominal 0)
osdimc: trial 3: mm:dr = 0 (nominal 0)
```

`std_rel` is relative to the nominal; on a nominal of 0 the sigma is 0, the draw is
exactly 0 on every trial, and 300 `montecarlo` samples gave `minimum(dr) = maximum(dr)
= 0` — the declared statistics could never vary, and nothing said so. A `std=0.0`
compiled without a word and the parameter simply never appeared in the statistics: the
compiler dropped it ("a zero sigma would only produce exact-zero draws") in silence.

## What changed

**At compile time**, two located warnings where the attribute is:

```
warning: 'std_rel' is relative to the nominal and the default of 'dr' is 0: with the default in force the sigma is 0 and the parameter will not vary under .option osdimc; give 'dr' a value on the card or line, or declare an absolute 'std'
  |
5 | (* type="instance", std_rel=0.1 *) parameter real dr = 0.0;
  |                     ^^^^^^^^^^^ relative to a default of 0

warning: 'std' attribute is 0: the parameter declares statistics with no width and will not vary under .option osdimc; give it a sigma or drop the attribute
  |
6 | (* std=0.0 *) parameter real z1 = 5.0;
  |    ^^^^^^^ a zero sigma is not exported
```

The first fires only when the default is a compile-time constant 0 (`param_default_const`,
the L027 machinery); the statistics are still exported, because the deck may give the
value (`N1 a 0 mm dr=50` draws around 50). The second covers `std=0` and `std_rel=0`
alike; the parameter is not exported, as before, but now the model says why.

**At the draw**, once per parameter, whatever the source of the 0 — the default, the
deck's own `dr=0`, an `altermod` to 0:

```
osdimc: n2:dr declares std_rel=0.1 on a nominal of 0: the sigma is 0 and the parameter never varies; give it a nonzero value, or declare an absolute std (said once)
```

The draw is skipped (the value stays the nominal, as it effectively did); a later
recentre to a nonzero value draws again. A sigma of 0 in an older object, should one
carry it, gets `declares a sigma of 0: the parameter never varies`.

## Verification

| check | result |
|---|---|
| `smczero.va`: `std_rel` on `dr = 0.0` and `dg = 0.0`, `std=0` on `z1`, `std_rel=0` on `z2`, `std_rel=0.05` on `ok = 2.0` | four located warnings, `ok` none; the model compiles |
| `N1 … dg=50`, `N2` bare, three runs | `n1:dr`, `n2:dr`, `n2:dg` said once each and stay 0; `n1:dg` draws around 50; `z1`/`z2` absent |
| `altermod zm ok=0`, then `altermod zm ok=3` | said once, stays 0; then draws around 3 |
| the 42 existing checks; the ten sibling suites | unchanged (no model in the corpus trips the new warnings) |
| `osdimc_examples` | 44 / 44, both solvers |
| full sweep, rebuilt compiler | 505 of 505 |
