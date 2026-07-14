# Enhancement-193 — `.pnoise` honors `sqrnoise` (noise-density units fix)

A correctness fix found while auditing the RF / PSS periodic-steady-state suite. The ngspice manual (§ `.noise`, pp. 326–327) defines `onoise_spectrum` / `inoise_spectrum` as a noise **spectral density in V/√Hz** (or A/√Hz) *by default*, switchable to the **squared V²/Hz** form with the `sqrnoise` control variable:

> "onoise_spectrum: … the output noise voltage … divided by √Hz. … Default setting of ngspice is *unset* sqrnoise, which delivers … Noise Spectral Density [V/√Hz]."

`.noise` obeys this. **`.pnoise` (periodic noise) did not** — it always emitted the squared V²/Hz density and ignored `sqrnoise`. So the *same-named* output vectors carried different units across the two analyses (differing by a square), and the documented `sqrnoise` control silently did nothing for pnoise:

| | `sqrnoise` unset (default) | `set sqrnoise` |
|---|---|---|
| `.noise` `onoise_spectrum` | 4.063e-9 (V/√Hz) | 1.651e-17 (V²/Hz) |
| `.pnoise` `onoise_spectrum` (before) | **1.651e-17 (V²/Hz)** | 1.651e-17 (V²/Hz) |

The `sqrnoise` toggle test makes the divergence unambiguous: `.noise` flips units with the variable; `.pnoise` returned the squared value regardless.

## The change

`pnoise_sweep` (`spicelib/analysis/dcpss.c`) now reads `sqrnoise` (via `cp_getvar`, exactly as `noisean.c` does) and, when it is unset (the default), applies `sqrt` to the emitted `onoise`/`inoise` densities — so the default is V/√Hz and `set sqrnoise` gives V²/Hz. Both emit paths — the Enhancement-178 cyclostationary folding path and the standard adjoint-folding path — get the same conditional `sqrt`.

| | `sqrnoise` unset (default) | `set sqrnoise` |
|---|---|---|
| `.pnoise` `onoise_spectrum` (after) | **4.063e-9 (V/√Hz)** | 1.651e-17 (V²/Hz) |

`.pnoise` and `.noise` now agree by default, and `sqrnoise` toggles both.

**Scope.** This fix is `.pnoise` only. The two-tone `qpnoise` command's single-point diagnostic already prints *both* the V²/Hz and V/√Hz forms explicitly (no ambiguity), and its swept and single-point paths share the V²/Hz convention internally, so reconciling it is deferred; only the `.pnoise` sweep vector was inconsistent with the manual.

## Examples updated

Several existing pnoise examples asserted the old V²/Hz values. Their physics (the noise folding) is unchanged — only the final output units — so they were adjusted minimally:

- `rfpss/rc_pnoise` now checks the default V/√Hz form (`sqrt` of the analytic) and cross-checks against `.noise` **without** forcing `sqrnoise` — the two now match to 0.00.
- `rfpss/rc_cyclo`, `cyclofold`, `pnoisefold` are inherently power-density relations (`onoise·f == …`, referee sums of `|Z|²·S`), so they `set sqrnoise` to keep the V²/Hz form; two LTI-limit checks that previously compared `pnoise(V²)` to `.noise(V/√Hz)²` become direct equalities.

## Also from this audit

The wider RF/PSS audit found the conversion machinery **correct**: PAC's driving-point response and its ±1 **conversion sidebands** (via the `.pac` card's trailing `maxsideband` argument) match a clean transient DFT to ~0.1 %, and Harmonic Balance matches a transient DFT to 4–5 digits. It also documented the previously-undocumented trailing `maxsideband` argument of the `.pac` card (`dcpss.c` comment + the `rc_pac.cir` example).

## Verification

[`examples/pnoiseunits_examples/verify_pnoiseunits.py`](../examples/pnoiseunits_examples/verify_pnoiseunits.py) — 4 checks on a small linear-RC pnoise: default pnoise == `sqrt(4kTR/(1+(ωRC)²))` (V/√Hz); `set sqrnoise` pnoise == the density (V²/Hz); default² == the squared form (the exact `sqrt` relation); and default pnoise == default `.noise` (matches to 0.00). A [`pnoiseunits_demo.cir`](../examples/pnoiseunits_examples/) prints the spectrum in both unit modes. The updated pnoise-family examples (rc_pnoise, rc_cyclo, cyclofold, pnoisefold) continue to pass. Full example regression: 157/157.
