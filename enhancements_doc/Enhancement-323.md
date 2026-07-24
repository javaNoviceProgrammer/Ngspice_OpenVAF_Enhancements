# Enhancement-323 — `.param` fast-sweep, OSDI-aware optimizer guard

Enhancement-322 gave the `optimize` command the `.param` fast path, gated by a
device-count guard: engage it only at `>= 80` device instances, because on a
small circuit a reset re-parses faster than the fast path's fixed per-eval
overhead. That threshold was calibrated on **resistor** ladders.

It is wrong for **OSDI** (compiled Verilog-A) devices.

## Why the crossover moves

A resistor reset just re-parses an element line. An OSDI reset re-initializes
each compiled model instance — it re-runs the model's `setup` / `temperature`
callbacks — which is far costlier per device. Measured with the fast path on and
off (same binary), on OSDI-resistor ladders:

| # OSDI instances | fast | reset | speedup |
|---|---:|---:|---:|
| 3 | 0.036 s | 0.077 s | **2.1×** |
| 41 | 0.040 s | 0.100 s | 2.5× |
| 161 | 0.053 s | 0.170 s | 3.2× |

The fast path wins at **3** OSDI instances, where resistors needed ~80. So the
E-322 count guard would keep a small OSDI optimization — common in device
model extraction / fitting — on the *slower* reset path, forgoing a 1.5–3×
speedup (a 300-instance OSDI `-dparam` fit measured 3.0× fast vs reset, same
optimum).

## The fix: weight the count by reset cost

The crossover is about reset **cost**, not device **count** — count was only a
proxy that happens to fail for OSDI. `opt_fp_arm` now walks the built circuit's
instances and weights each by its device kind:

- primitive (resistor, capacitor, built-in) → **1**
- OSDI → **30** (measured: ~3 OSDI ≈ the reset cost of ~80 primitives)

and compares the weighted total to the same `80` primitive-equivalent threshold.
So a handful of OSDI devices arms the fast path, while a small all-resistor
circuit still (correctly) keeps the cheap reset.

OSDI device types are identified by a stable marker: every OSDI `SPICEdev` is
built by `osdi_create_spicedev` and so shares the `OSDIparam` instance-parameter
setter, which no built-in device uses. A one-line helper,
`osdi_devtype_is_osdi(type)` (`osdi/osdiinit.c`), exposes this; the call in the
optimizer is `#ifdef OSDI`-guarded so a build without OSDI is unaffected (every
instance simply weighs 1).

## Correctness

Unchanged from E-322 — the guard only decides *whether* to arm, not *what* the
fast path computes. A small OSDI `-dparam` optimization now arms and converges to
the **same** optimum as the reset path (verified), and all 43 `optimize` checks
pass (2 new: a small OSDI optimization arms and converges).

## Files

- `ngspice-46/src/osdi/osdiinit.c` — `osdi_devtype_is_osdi(type)`.
- `ngspice-46/src/include/ngspice/osdiitf.h` — its declaration.
- `ngspice-46/src/frontend/com_optimize.c` — `opt_fp_arm` weights instances by
  device kind (OSDI = 30×) instead of counting cards.
- `examples/optimize_examples/verify_optimize.py` — a small OSDI `-dparam`
  optimization that arms the fast path and converges (2 new checks).
