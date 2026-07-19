# Enhancement-240 — XSPICE `s_xfer`: fix an out-of-bounds crash on a static-gain transfer function

A sixth find from the same memory-safety deep dive (after E-235 – E-239),
surfaced by fuzzing XSPICE a-device instantiation and reproducible on the shipped
binary. It is the first find in the XSPICE analog code-model library rather than
the core simulator.

## The bug

The `s_xfer` analog code model
(`xspice/icm/analog/s_xfer/cfunc.mod`) realises a Laplace transfer function
`H(s) = num(s)/den(s)` in controller-canonical form. Its state arrays are
allocated to `den_size` elements — the number of denominator coefficients:

```c
integrator = (double **) calloc((size_t) den_size, sizeof(double *));
```

In the DC/transient evaluation branch it computed the output-vs-input partial
with an **unconditional**

```c
pout_pin = *(integrator[1]);
```

which assumes the system has at least two denominator coefficients (a first- or
higher-order denominator). A **0-order denominator** — `den_size == 1`, i.e. a
*static-gain* transfer function such as `s_xfer(num_coeff=[k] den_coeff=[1])`
(a plain constant gain `k`) — allocates `integrator` with a single element, so
`integrator[1]` is one past the end. Reading it dereferenced garbage and
**crashed (SIGSEGV)** at circuit load:

```
a1 1 2 sd
.model sd s_xfer(num_coeff=[3] den_coeff=[1])   →  cm_s_xfer ← MIFload ← CKTload  (EXC_BAD_ACCESS at 0x0)
```

The crash depends only on `den_size == 1`, not on the coefficient values:
`den_coeff=[1]` (a valid unity-denominator static gain), `[5]`, and `[0]` all
crash, while `[1 1]` and `[1 2 1]` (higher order) are fine. So this bit ordinary,
legitimate input — a static-gain `s_xfer` — not just degenerate decks. The AC
branch was already safe (its loops are bounded by `den_size`/`num_size`).

## The fix

Guard the `integrator[1]` read. For `den_size == 1` the realization reduces to
`out = gain·num_coeff[0]·in` (the single integrator holds the scaled input), so
the partial `d(out)/d(in)` is `gain·num_coeff[0]`:

```c
if (den_size > 1)
    pout_pin = *(integrator[1]);
else
    pout_pin = (num_size > 0) ? (*gain * *(num_coefficient[0])) : 0.0;
```

The output value itself is already computed correctly by the numerator sum, so
only the (previously out-of-bounds) partial needed handling. A zero-denominator
`den_coeff=[0]` (`H = ∞`) now yields a clean non-convergence instead of a crash,
and higher-order filters are unchanged.

The fix lives in a `.cm` code model, so `analog.cm` was regenerated (via `cmpp`)
and redeployed under `bin/<os>/<arch>/codemodels/`; the `ngspice` binary itself
is unchanged.

## Verification (`examples/sxfer_examples`)

`verify_sxfer.py` (4 checks): a static-gain `s_xfer(num=[3] den=[1])` no longer
crashes and gives the **exact** gain (H=3 → 4 V in → 12 V out); another static
gain (H=0.4 → 1.6 V); a zero denominator (`den=[0]`) no longer crashes; and a
genuine dynamic filter `H=1/(s+1)` still works (|H(DC)| ≈ 1). The XSPICE code
models load from the prebuilt bundle via `SPICE_LIB_DIR`; the test self-skips if
they are unavailable in the checkout. Full B-source / XSPICE fuzz sweep
crash-free after the fix.

## Scope

XSPICE analog code-model library only — one guard in the `s_xfer` code model
(`cfunc.mod`), plus the regenerated `analog.cm` bundle. No core simulator,
solver, analysis, device, or compiler change; dynamic-filter results are
unchanged. Full regression: 198/198.
