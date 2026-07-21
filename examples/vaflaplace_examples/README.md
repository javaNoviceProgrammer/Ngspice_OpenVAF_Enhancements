# vaflaplace_examples — Enhancement-265

openvaf-r robustness: a malformed **`laplace_*`/`zi_*` coefficient argument** now
produces a clean type-mismatch diagnostic instead of a compiler **panic**.

The numerator / denominator (and pole/zero) argument of an analog filter operator
must be a real coefficient array (LRM 9.19). The coefficient type check accepted
anything its array-literal / array-variable special cases did not catch and
returned its type *without requiring a real value* — so a bare **net** reference
(`laplace_nd(1.0, 1.0, p)`), a branch, or a string slipped through to `hir_lower`,
where resolving a net reference as a value panicked (`invalid HIR: path .. was not
resolved`), exit 101.

A second, adjacent crash is fixed too: an **empty direct denominator**
(`laplace_nd(V, 1.0, '{})`) made the state-space realization read `den[len-1]` on a
zero-length array and crash. `infere_laplace` now rejects it, while an empty
*numerator* (`H(s)=0`) and an empty *pole* list in the `*_np`/`*_zp` forms
(denominator polynomial `1`) stay legal.

| File | What | Result |
|---|---|---|
| `bad_coeff_net.va` | `laplace_nd(1.0, 1.0, p)` — 3rd arg is a net | was a **panic**; now `error: type mismatch: expected real value but found net reference` |
| `good_filter.va` | single-pole `laplace_nd(V, '{1.0}, '{1.0, tau})` | compiles unchanged |

## Fix

`openvaf/hir_ty/src/inference.rs` — the coefficient-argument fallback now requires
a real value (the same requirement the `laplace_*` *input* argument and every
ordinary value context already enforce), so an invalid coefficient raises the
normal type-mismatch diagnostic before lowering. Valid shapes (real/int array
literals, scalar coefficients, bare array-variable references, the `zi_*` forms)
are untouched.

## Verify

```
python3 verify_vaflaplace.py
```

Passes iff each malformed coefficient argument ERRORs cleanly (no crash/panic) and
each well-formed filter compiles (12 checks).
