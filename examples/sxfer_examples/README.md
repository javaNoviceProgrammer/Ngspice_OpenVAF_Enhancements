# XSPICE `s_xfer` static-gain crash fix (Enhancement-240)

A sixth find from the memory-safety deep dive (after
[E-235](../../enhancements_doc/Enhancement-235.md)–[E-239](../../enhancements_doc/Enhancement-239.md)),
surfaced by fuzzing XSPICE a-device instantiation — and the first one in the
XSPICE code-model library rather than the core simulator.

The `s_xfer` analog code model
([cfunc.mod](../../ngspice-46/src/xspice/icm/analog/s_xfer/cfunc.mod)) realises a
Laplace transfer function `H(s) = num(s)/den(s)` in controller-canonical form.
Its `integrator` state array is allocated to **`den_size`** elements (the number
of denominator coefficients). In the DC/transient branch it unconditionally read

```c
pout_pin = *(integrator[1]);      /* the d(out)/d(in) partial */
```

which assumes **at least two** denominator coefficients. A **0-order
denominator** — `den_size == 1`, i.e. a *static-gain* transfer function such as
`s_xfer(num_coeff=[k] den_coeff=[1])` = a constant `k` — has only
`integrator[0]`, so reading `integrator[1]` walked off a one-element array and
dereferenced garbage → **SIGSEGV** at circuit load (`cm_s_xfer` ← `MIFload` ←
`CKTload`). This bit **any** legitimate static-gain `s_xfer`, not just degenerate
input.

E-240 guards the access — for `den_size == 1`, `out = gain·num_coeff[0]·in`, so
the partial is `gain·num_coeff[0]`, and `integrator[1]` is read only when
`den_size > 1`. The `.cm` was rebuilt and redeployed under `bin/*/codemodels/`.

## Verify

```sh
python3 verify_sxfer.py
```

Four checks: a static-gain `s_xfer(num=[3] den=[1])` no longer crashes and gives
the exact gain (H=3 → 4 V in → 12 V out); another static gain (H=0.4 → 1.6 V); a
zero denominator (`den=[0]`, H=∞) no longer crashes (clean non-convergence); and
a genuine dynamic filter `H=1/(s+1)` still works (|H(DC)| ≈ 1). The XSPICE code
models load from the prebuilt bundle via `SPICE_LIB_DIR` (set by `_setup`); if
they are unavailable in this checkout, the test self-skips.
