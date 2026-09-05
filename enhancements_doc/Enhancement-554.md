# Enhancement-554: lognormal and truncated-Gaussian parameter statistics — `dist="lognormal"`, `dist="tgauss"` and `trunc=<sigmas>`

**Scope:** the statistics attributes of Verilog-A parameters for
`.option osdimc` ([E-530](Enhancement-530.md)) — the compiler's attribute
parser and its diagnostics (`openvaf/sim_back/src/module_info.rs`), the
OSDI side-table (`openvaf/osdi/src/{metadata,lib}.rs`), the simulator's
loader (`src/osdi/osdiregistry.c`), its draw, walk and importance-weight
code (`src/osdi/osdisetup.c`) and the `wcd` diagnosis of a clamped walk
(`src/frontend/com_sweep.c`). **Compiler and ngspice together.**

**Suites:** [`osdidist_examples`](../examples/osdidist_examples/) (new, 18
checks, both solvers, measured over 300 draws); the 13 suites that share
the draw machinery pass; full sweep 458 of 458; compiler tests and the
model corpus unchanged from the unpatched tree. Handbook
[§2.13](../docs/handbook/02-verilog-a-language.md) and
[§3.6](../docs/handbook/03-ngspice-workflows.md), README_OSDI, the
[statistics guide](../docs/internals/ngspice_internals/ngspice_statistics.md).

## What was wrong

`.option osdimc` drew every `(* std *)` parameter from a gauss or a uniform,
and a gauss has no regard for a `from (0:inf)` range: a wide sigma fails
trials at the bound (the compiled setup refuses the value with the model's
own range error), and the ensemble is truncated by *dropping* them — under
`highsigma -scale` in exactly the tail being measured. There was no shape
that could not violate a range.

## What changed

| attribute | meaning |
|---|---|
| `dist="lognormal"` (alias `lnorm`) | the draw is `nominal · exp(s·z)`, never crossing zero; `std_rel` is `s`, the sigma of the logarithm (about the relative sigma for small values); an absolute `std` is converted at the nominal, `s = std/|nominal|` |
| `trunc=n` | the Gaussian coordinate is confined to `|z| ≤ n` by deterministic rejection: the first attempt is the plain draw, so a draw inside the window is exactly the draw the untruncated parameter would have made, and a rejected one is redrawn from a sub-key of the same trial (64 attempts, then clamped); composes with gauss and lognormal, warns and does nothing on a uniform |
| `dist="tgauss"` | gauss with `trunc=3` |

```verilog
(* dist="lognormal", std_rel=0.3 *) parameter real is = 1e-15 from (0:inf);
(* std=25.0, trunc=2.0 *)           parameter real rs = 1000.0;
(* dist="tgauss", std_rel=0.05 *)   parameter real k  = 2.0;
```

* **`highsigma -scale`** inflates both shapes with the matching importance
  weight: with a truncation both densities are confined to the same value
  window, and their normalisers `erf(n/√2)` and `erf(n/(scale·√2))` join
  the likelihood ratio — without them a truncated tail reads about 30 %
  low. A lognormal is a gauss in the log domain, so the same ratio applies.
* **`wcd`** gives both shapes a walk coordinate, clamped at the truncation.
  A boundary beyond the window is unreachable, and `wcd` now says so
  (*the walk is held at the `trunc` truncation of N model-declared
  parameters …*) instead of reporting a zero gradient.
* **Transport.** The truncations ride a new optional side-table symbol,
  `OSDI_STAT_PARAM_TRUNCS` (one double per statistics entry, in INFOS
  order), and lognormal is a new bit in the 16-byte INFOS record. An object
  without a truncation does not carry the symbol; a simulator that does not
  know it draws untruncated; an old object in the new simulator draws
  exactly what it drew before. The descriptor ABI is unchanged. The
  registry merges INFOS and TRUNCS into in-memory `OsdiStatParam` records.
* **Diagnostics.** A `trunc` that is not a positive real literal (a quoted
  number is accepted) is a located error; `trunc` on a uniform and `trunc`
  without a sigma warn; the unknown-distribution warning lists the four
  names.
* `osdimc_verbose` names the shape on every draw (`lognormal`, `trunc 3`).

## Verification

| check | result |
|---|---|
| lognormal `std_rel=0.2`, 300 draws | every draw positive; `ln(v/nom)` mean −0.015, sd 0.203 |
| lognormal `std=200` on nominal 1000 | sd of the logarithm 0.201 |
| lognormal `std_rel=1.0` on `from (0:inf)` | 300 trials, no range failure, sd 1.03 |
| the gauss control, same sigma, same range | 47 of 300 trials out of bounds |
| gauss `trunc=1`, σ 25 | every draw within ±25, sd 13.9 (0.54 σ), none clamped |
| `dist="tgauss"` | within ±3 σ; verbose says `trunc 3` |
| lognormal + `trunc=2` | every logarithm within ±0.4 |
| the same seed, card and id with and without `trunc=2` | 282 draws identical, 18 redrawn inside the window |
| `highsigma 4000 -scale 2` on gauss `trunc=2`, fail above 1.6 σ | 0.0346 against 0.0336 exact (0.024 without the normaliser) |
| the untruncated control | 0.0568 against 0.0548 exact |
| `wcd` with a boundary beyond the truncation | the truncation message, no distance; a boundary inside: β = 0.8000 |
| `trunc=-1`, `trunc="abc"` | located errors; `trunc` on a uniform and alone warn; `trunc="2.5"` accepted |
| the object without a truncation | exports no `OSDI_STAT_PARAM_TRUNCS`; one with it does |
| `osdidist_examples` | 18 / 18, both solvers |
| related suites; full sweep | 13 / 13; 458 of 458 |
