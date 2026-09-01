# Enhancement-527: the kernel and random system functions, audited against the LRM

**Scope:** Accellera VAMS-2023 clause 9 (the kernel system functions), from
the full LRM conformance audit — four bugs (`$bound_step`, two `$table_model`
defaults, silent distribution domains), the missing 9.21 surface, the
`$simprobe`/alias/`type_string` rules, two new `$simparam$str` names, and the
`$vt` constants.

**Suite:** [`examples/lrmkernel_examples/`](../examples/lrmkernel_examples/)
— 43 checks, both solvers. The updated `table_model`, `alias`, `deckdomain`,
`dropguard`, `lrmfuncs` and `rangeguard` suites pin the same contracts from
their own angles; the full 440-suite sweep is ALL OK.

## $bound_step took the LAST bound, not the smallest (compiler)

LRM 9.17.2: "the simulator shall ensure that the next time step taken is no
larger than the SMALLEST $bound_step() argument currently active." The
lowering overwrote the bound place per call, so with several calls in one
evaluation the last executed call set the cap — `(1e-6, 1e-4)` capped at
1e-4 in one order and 1e-6 in the other. The place now takes the minimum
(E-24's negative discontinuity sentinel stays smaller than any usable bound,
so an announced discontinuity keeps winning). Both orders measure a 1e-6
max accepted step; single bounds are bit-identical.

## $table_model, brought to clause 9.21 (compiler)

Five independent fixes, one operator:

* **Default extrapolation is LINEAR** on both ends (Tables 9-31/9-32: "when
  no extrapolation method character is given, the linear extrapolation
  method will be used") — it clamped to the endpoints unless an `L`
  appeared. The audit's y = 2x table now reads 8.0 above and 0.0 below
  (was 6.0/2.0); `"1C"` is the spelling that clamps.
* **Per-dimension control sub-strings**: "comma separated sub-strings ...
  the first applying to the outermost dimension" — the lowering scanned
  the whole string, so any `L` made ALL axes extrapolate linearly and any
  `3` made all axes cubic. `"1C,1L"` on the 2-D grid now clamps y and
  extends x (2.0, was 3.0), and up to two extrapolation characters set
  each END separately.
* **`D` closest-point lookup** (Table 9-30) with 9.21.4's tie rule — "if
  two sample points are equally close, the one farther from zero shall be
  used" — decided at compile time per midpoint. **`E`** errors on
  extrapolation at run time via the E-509 fatal route. `2` (quadratic)
  and `I` (ignore-column) stay located refusals, now documented.
* **The normative 9.21.1 N+M-column isoline data format** — including
  RAGGED isolines ("the number and spacing of samples may be different on
  each isoline"; the LRM's own sample file) — read into a recursive
  isoline tree that each level interpolates with the shared 1-D kernels;
  the project's self-describing grid format stays as an extension, now
  gated on exact token count so the two cannot mis-parse each other. The
  **`;N` dependent-column selector** is honoured (it was parsed by
  validation and ignored by lowering), multi-dependent-column 1-D files
  read, and the 1-D `'{xs}, '{ys}` array pair joins the interleaved
  layout.
* The runtime array-variable form keeps `1`/`3` with same-both-ends
  `C`/`L` (its kernels carry a single switch); `D`/`E`/per-end there are
  honest refusals.

## Distribution domains: the mandated error, on the deck route too (compiler)

LRM 9.13.2: "the arguments mean, degree_of_freedom, and k_stage shall be
greater than zero (0). Otherwise an error shall be reported." Literal
violations were refused at compile time, but the ordinary deck-overridden
route was silent: exponential/poisson clamped to a point mass, and
chi-square/t/erlang passed the value straight to the RNG — `$rdist_erlang`
with negative arguments returned a *negative* deviate from a distribution
supported on [0, ∞). A deck-derived violation now aborts with the mandated
runtime error naming the function, argument and clause, for all five and
both families; the E-505/506 clamps stay as the net for values the guard
cannot attribute to a parameter.

## $simprobe, aliases, type_string (compiler)

The no-default `$simprobe` returned 0.0 and ran on — 9.16 says "an error
shall be generated" exactly there. It now warns at compile time and is
fatal at run time; the default form is untouched (returning the default IS
the LRM fallback). `$analog_node_alias`/`$analog_port_alias` outside an
`analog initial` block are the 9.20 error (keyed off the body owner, so
conditionals inside the initial block stay legal), and a `type_string`
argument outside a paramset draws a warning (9.13.1/9.13.2 scope it there,
where it is the Monte-Carlo idiom).

## $simparam$str and $vt (ngspice + compiler)

Table 9-28's `analysis_type` and `cwd` join the served set (`analysis_name`
already mirrored the `analysis()` naming; `cwd` refreshes per query);
`module`/`instance`/`path` stay honestly unserved — the channel carries no
instance identity. And `$vt` moved to the **2019 exact SI k and q**, the
same source E-519's `constants.vams` NIST2018 set uses, so `$vt(T)` equals
`` `P_K*T/`P_Q `` exactly under that set (measured dvt = 0.0; the shipped
header still *defaults* to NIST1998 for LRM backward compatibility, a ~1 ppm
difference now documented). The stale `lower_rng` comment claiming an
in-model seed advance that does not exist was rewritten to the documented
pure-(seed, salt) contract.
