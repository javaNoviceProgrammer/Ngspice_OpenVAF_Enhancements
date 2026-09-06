# lrmkernel — kernel & random system functions vs. the LRM (Enhancement-527)

An LRM-2023 conformance audit of clause **9** found four bugs and a set of
undisclosed gaps across `$bound_step`, `$table_model`, the distributions,
`$simprobe` and `$simparam$str`. This suite pins the fixes:

- **`$bound_step` smallest-wins** (9.17.2): several calls in one
  evaluation used to leave the *last* one as the cap; both orders of a
  (1e-6, 1e-4) pair now cap the transient at 1e-6.
- **`$table_model` brought to clause 9.21**: default **linear**
  extrapolation (Tables 9-31/9-32 — it clamped), **per-dimension**
  control sub-strings (`"1C,1L"` used to apply any code to every axis),
  per-end extrapolation characters, closest-point **`D`** with the
  9.21.4 farther-from-zero tie rule, **`E`** = runtime error on
  extrapolation, the **`;N` dependent-column selector**, the normative
  **N+M-column isoline files** — *ragged* isolines included (the LRM's
  own sample file interpolates to exact f = 0.5x+y) — and the
  `'{xs}, '{ys}` array pair. `2` (quadratic spline) and `I` (ignore a
  column) followed in E-562; the suite pins `2` exact on linear data.
- **9.13.2 domain errors on the deck route**: a deck-supplied
  non-positive mean/dof/k now aborts with the mandated runtime error for
  all five listed distributions (chi-square/t/erlang previously returned
  deviates outside their own support, silently).
- **`$simprobe` with no default** is the 9.16 error (compile warning +
  runtime fatal; was a silent 0.0); aliases are analog-initial-only per
  9.20; `type_string` warns outside a paramset.
- **`$simparam$str`** serves `analysis_type` and `cwd` (Table 9-28), and
  **`$vt`** uses the 2019 exact SI k/q — equal to `` `P_K*T/`P_Q ``
  exactly under `` `define PHYSICAL_CONSTANTS_NIST2018 ``.

Run `python3 verify_lrmkernel.py` — 43 checks, both solvers.
