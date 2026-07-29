# Enhancement-359 — `.disto` for Verilog-A, rebuilt without the compiler

[Enhancement-352](Enhancement-352.md) gave Verilog-A devices distortion analysis
by having the compiler emit a **symbolic closed form** for the 2nd/3rd-order
Taylor tensors. It worked, but the cost was out of all proportion to what the
feature does:

| | E-352 / E-353 | **E-359** |
|---|---|---|
| compile, `asmhemt` | 126 s (**35×**) | **3.5 s** — baseline is 3.6 s |
| compile, `hisimhv` | 130 s (**20×**) | **6.2 s** — baseline is 6.5 s |
| `.osdi`, `asmhemt` | 30.2 MB | **0.65 MB** |
| runtime, DC/AC/tran | **3.3–3.9×** | **1.0×** |
| OSDI ABI | 0.9, models must be rebuilt | **0.7** — existing objects work |
| ground-referenced probe | warned, returned zero | **works** |
| compiler code | ~600 lines | **none** |

---

## The mistake in the original design

`.disto` needs the Taylor coefficients **at one point, once per instance, once
per analysis**. E-352 computed a closed form valid at *every* point — 707k
intermediate derivatives and 1.4M MIR instructions on ASMHEMT — and shipped it,
so that it could be evaluated once.

Everything that went wrong descends from that: the compile-time blowup, the 30 MB
objects, and a 3.9× runtime penalty on every Newton iteration of every analysis
because the tensors were computed inside `eval`.

## What replaces it

The model already publishes its **first** derivatives analytically — that is the
Jacobian every analysis loads. The higher derivatives follow by differencing
*that* at the operating point:

```
d2 R_r/dv_p dv_q       = d/dv_q  [ J_rp ]
d3 R_r/dv_p dv_q dv_s  = d2/dv_q dv_s [ J_rp ]
```

Differencing an already-analytic first derivative — rather than the residual — is
what keeps this accurate. It runs in `osdidistonum.c`, ~300 lines, entirely
inside ngspice.

Two properties make it cheap. The tensors are evaluated at the **DC operating
point**, so they are frequency-independent: built once at `D_SETUP`, reused by
every mode and every frequency. And they are built in **node coordinates**, where
instances have 5–20 nodes rather than the 52 "model inputs" ASMHEMT reports.

The entries keep the exact `(row, col…)` shape the analytic path produced, so the
whole verified Volterra contraction in `osdidisto.c` is reused unchanged.

## Node coordinates remove a real limitation

E-352 indexed the tensors by *model input* — a branch voltage with a hi/lo pair.
A nonlinearity in a **ground-referenced probe** `V(a)` has no pair, so it was
never recorded, and the device reported *"contributes no distortion"* and
returned zero. Node coordinates have no pair to miss:

```
device: I(a) <+ g*V(a) + k*V(a)*V(b)
E-352:  0.0                      (with a warning)
E-359: -4.16666665e-02
exact: -4.16666667e-02           (k*H_d*H_e/2)/Ytot_d
```

[Enhancement-353](Enhancement-353.md)'s `$limit` chain-fold disappears for the
same reason: differencing the real Jacobian sees whatever the simulator sees, so
there is no chain to fold. Its seven-shape test suite — written specifically to
break that logic — passes unchanged against an implementation that contains none
of it.

## Accuracy

Measured against **exact closed forms**, not against the old implementation:

| model | 2nd order | 3rd order |
|---|---|---|
| cubic polynomial (exact) | `4.0e-09` | `5.4e-09` |
| exponential diode | `2e-10` | `~1e-10` |
| internal node (exact) | `3.6e-12` | `1.2e-08` |
| ground-referenced (exact) | — | `4e-09` |
| MEXTRAM vs the analytic implementation | `5e-09` | `1e-07` |

For scale, the built-in-diode oracle already sits at `1.9e-06` because OpenVAF's
`$vt` and ngspice's differ by 0.24 ppm. The numerical error is well below the
agreement floor that already existed.

**The step size is the whole game.** Truncation is O(h²) and roundoff O(eps/h)
for 2nd order but O(eps/h²) for the 3rd, so one step cannot serve both: a single
`1e-3·V` step put the result 8.5e-5 out. And the right yardstick is not the
operating voltage but the **curvature scale** — `v_t` = 26 mV for a diode,
volts for a polynomial — so a voltage-relative step left a cubic biased at 0 V
11% wrong. The second-order pass measures `|dJ/dv|/|J|` = 1/V₀ directly, and the
third-order step is derived from it as `h = 1.2e-4 · V₀ ≈ V₀ · eps^(1/4)`.

## Only `.disto` is approximate

The Jacobian is still OpenVAF's exact symbolic autodiff. After this change the
compiler emits nothing distortion-related at all, so a model's `.osdi` is what a
pre-E-352 compiler would have produced. Verified to 15 digits against a build
with the tensor pass disabled:

| | E-359 | no-tensor reference |
|---|---|---|
| op | `1.95325885410138e+00` | identical |
| dc | `1.99165270337578e+00` | identical |
| ac | `3.26521551462750e+00` | identical |
| tran | `1.98683915067080e+00` | identical |
| noise | `1.55443859052605e-04` | identical |

`.disto` perturbs the solution vector during setup, so it re-evaluates at the
unperturbed point as its last act; an `op` before and after a `.disto` agree
exactly.

## What was deleted

`build_taylor_tensors`, `taylor_unknown_chain`, `taylor_input_values`, the
`Taylor2/3Entry` types and their sparsification, six descriptor fields plus
`eval_taylor`, `store_taylor`, `load_taylor2/3`, `CALC_TAYLOR`, `has_taylor`, and
the OSDI 0.8→0.9 bump. **Zero lines of compiler code remain.**

## Three ways this produced plausible wrong numbers

None of these failed loudly; each returned a believable value.

1. **One step for both orders** — 8.5e-5 error. Fixed with per-order steps.
2. **A voltage-relative step** — 11% error on a cubic biased at 0 V. Fixed by
   deriving the step from the measured curvature scale.
3. **Indexing `write_jacobian_array_resist` as if parallel to
   `jacobian_entries[]`** — it is a *dense array of resistive entries only*, so
   the two coincide only for a model with no charge storage. This is why simple
   models agreed and MEXTRAM was out by 3–10×.

A fourth belongs to the prototype rather than the implementation, and mattered
most: **collapsed nodes**. `V(a,b) <+ 0` shorts nodes together — MEXTRAM merges
three onto one — and treating them as independent perturbs the shared node once
per alias. That was a silent ~0.2% error, and it briefly looked like a defect in
the *shipped* analytic implementation. It was not; E-352/E-353 are correct on
every model tested.

## Verification

Regression 285/285. `examples/osdidisto_examples` 6/6 and
`examples/limitdisto_examples` 7/7, both against closed-form oracles rather than
against the previous implementation.
