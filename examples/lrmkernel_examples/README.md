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

Run `python3 verify_lrmkernel.py` — 53 checks, both solvers (52 of 53 on the E-759
toolchain). Section [6] is Enhancement-758: `$simparam$str("cwd")` is read once and
re-read after `cd`, not with a `getcwd()` on every Newton iteration (`cwdprobe.va`
strobes it; one instance must load in under 6 µs per iteration, where the E-757 binary
took 12–14 µs). Section [7] is Enhancement-760: the rest of the load path's fixed
per-iteration bookkeeping is hoisted — the repeated-message summary's 64-slot walk, the
three option lookups by name (`noosdilim`, `osdilim_verbose`, `scale`), the version
string parse and the compiled runtime's file-slot walk. `optprobe.va` strobes
`$simparam("scale")` at its initial step: `set scale=2.5` and `unset scale` between runs
reach the next run (1, 2.5, 1), a deck's `.option scale=4` is what the first run reads,
`set osdilim_verbose` between two runs reports the limiter decision only after the set,
and one compiled instance's load per iteration is under 4× a built-in resistor's over
20 000 iterations (0.16 against 0.12 µs; the E-759 binary took 0.57–0.66 µs, 5×).
