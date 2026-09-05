# osdidist_examples — lognormal and truncated-Gaussian parameter statistics (Enhancement-554)

```
python3 verify_osdidist.py
```

18 checks, both solvers; compiles its own models with `openvaf-r`.

## The need

`.option osdimc` (E-530) draws every Verilog-A parameter declared with
`(* std= *)` / `(* std_rel= *)` from a gauss or a uniform. A gauss has no
regard for a `from (0:inf)` range: a wide sigma fails trials at the bound
(the compiled setup refuses the value with the model's own range error),
and the ensemble is truncated by *dropping* them — under `highsigma -scale`
in exactly the tail being measured. There was no shape that could not
violate a range.

## What changed

| attribute | meaning |
|---|---|
| `dist="lognormal"` (alias `lnorm`) | the draw is `nominal · exp(s·z)`, never crossing zero; `std_rel` is `s`, the sigma of the logarithm (about the relative sigma for small values); an absolute `std` is converted at the nominal, `s = std/|nominal|` |
| `trunc=n` | the Gaussian coordinate is confined to `|z| ≤ n` by deterministic rejection: the first attempt is the plain draw, so a draw inside the window is exactly the draw the untruncated parameter would have made, and a rejected one is redrawn from a sub-key of the same trial; composes with gauss and lognormal, no effect on a uniform |
| `dist="tgauss"` | gauss with `trunc=3` |

Both shapes inflate under `highsigma -scale` with the matching importance
weight — the truncated normalisers `erf(n/√2)` and `erf(n/(scale·√2))` join
the likelihood ratio, without which a truncated tail reads 30 % low — and
take a `wcd` walk coordinate, clamped at the truncation: a spec boundary
beyond the window is unreachable, and `wcd` says so instead of reporting a
zero gradient. The truncations ride a new optional side-table symbol,
`OSDI_STAT_PARAM_TRUNCS` (one double per statistics entry); an object
without a truncation does not carry it, a simulator that does not know it
draws untruncated.

```verilog
(* dist="lognormal", std_rel=0.3 *) parameter real is = 1e-15 from (0:inf);
(* std=25.0, trunc=2.0 *)           parameter real rs = 1000.0;
(* dist="tgauss", std_rel=0.05 *)   parameter real k  = 2.0;
```

Where it lives: the attribute parser in `openvaf/sim_back/src/module_info.rs`
(the `dist` names, the `trunc` attribute and its three diagnostics), the
side-table in `openvaf/osdi/src/{metadata,lib}.rs`, the loader in
`ngspice-46/src/osdi/osdiregistry.c` (INFOS and TRUNCS merged into
`OsdiStatParam` records) and the draw, walk and weight code in
`ngspice-46/src/osdi/osdisetup.c` (`osdimc_z`, `osdimc_sigma`,
`osdimc_value`, `osdimc_log_lr`).
