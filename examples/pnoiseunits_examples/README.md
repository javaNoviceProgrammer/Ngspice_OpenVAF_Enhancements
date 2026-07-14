# `.pnoise` honors `sqrnoise` — noise-density units fix (Enhancement-193)

Found while auditing the RF/PSS suite. The ngspice manual (§ `.noise`) defines
`onoise_spectrum` / `inoise_spectrum` as a noise **spectral density in V/√Hz**
(or A/√Hz) *by default*, switchable to the **squared V²/Hz** form by `set
sqrnoise`:

> "onoise_spectrum: … the output noise voltage … divided by √Hz. … Default
> setting of ngspice is *unset* sqrnoise, which delivers … Noise Spectral
> Density [V/√Hz]."

`.noise` obeys this. **`.pnoise` (periodic noise) did not** — it always emitted
the squared V²/Hz density and ignored `sqrnoise`. So the *same-named* vectors
carried different units across the two analyses (differing by a square), and the
documented `sqrnoise` control silently did nothing for pnoise:

```
                 sqrnoise unset (default)   set sqrnoise
   .noise        4.063e-9   (V/√Hz)         1.651e-17  (V²/Hz)
   .pnoise  ✗    1.651e-17  (V²/Hz)         1.651e-17  (V²/Hz)   <- ignored the var
```

## The fix

E-193 makes `.pnoise` read `sqrnoise` exactly like `.noise` (`dcpss.c`,
`pnoise_sweep`): default → V/√Hz; `set sqrnoise` → V²/Hz. Both emit paths (the
E-178 cyclostationary folding path and the standard adjoint-folding path) apply
the same conditional `sqrt`.

```
                 sqrnoise unset (default)   set sqrnoise
   .noise        4.063e-9   (V/√Hz)         1.651e-17  (V²/Hz)
   .pnoise  ✓    4.063e-9   (V/√Hz)         1.651e-17  (V²/Hz)   <- now conforms
```

Now `.pnoise` and `.noise` agree by default, and `sqrnoise` toggles both. (The
two-tone `qpnoise` command is out of scope here — its single-point diagnostic
already prints both V²/Hz and V/√Hz explicitly; only the `.pnoise` sweep vector
was inconsistent.)

## Correctness

On the driven RC low-pass (linear → pnoise reduces to `.noise`, only R1's thermal
noise), the analytic density is `S(f) = 4kT·R1/(1+(2πf·R1·C1)²)` [V²/Hz]. The
verification checks: default pnoise == `sqrt(S)` (V/√Hz); `set sqrnoise` pnoise ==
`S` (V²/Hz); default² == the squared form (the exact `sqrt` relation); and default
pnoise == default `.noise` — the last matches to **0.00** (the two analyses are
now byte-identical by default).

## Verification

`verify_pnoiseunits.py` — 4 checks on a small, fast linear-RC pnoise. A
`pnoiseunits_demo.cir` prints the same spectrum in both unit modes.

The wider RF/PSS audit that surfaced this found PAC (conversion matrix, incl. the
±1 conversion sidebands vs a transient DFT) and Harmonic Balance both **correct**;
it also documented the previously-undocumented trailing `maxsideband` argument of
the `.pac` card.

## Running

```sh
python3 verify_pnoiseunits.py
ngspice -b pnoiseunits_demo.cir
```
