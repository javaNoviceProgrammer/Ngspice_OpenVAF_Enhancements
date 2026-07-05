# paramrange_examples — CMC default-range idiom + sweep fixes (Enhancement-56)

Demonstrates **Enhancement-56**: the fixes found by running the whole VA_TEST
corpus (92 standalone industry models) **end-to-end through ngspice**
(op/AC/tran/noise) instead of compile-only, using the committed
`openvaf-r` and `ngspice-46`.

## What was broken

- **Parameter DEFAULTS were range-checked at setup.** CMC-standard models
  declare a default *outside* the parameter's own range as the "feature
  disabled" state — `diode_cmc`'s `CORECOVERY = 0.0 from (0.0:1.0]`,
  FBH-HBT's `Fb = 0.0 from (0.0:inf)`, and friends — and expect range
  constraints to bind only user-**given** values. OpenVAF validated the
  default too, so the stock CMC models (diode_cmc, bsimcmg-110, fbh_hbt,
  psphv fragments, …) were rejected at setup with
  "Parameter … is out of bounds". Defaults are now exempt; given values are
  still validated (both `from` ranges and `exclude` constraints).
- **A `$fatal`/`$finish` raised during setup surfaced as ngspice's baffling
  "impossible error - can't occur".** Models validate their configuration at
  setup (HiSIM's `$port_connected`/`COSUBNODE` guards) and reject it by
  design; ngspice now says "a Verilog-A device rejected its configuration
  during setup ($finish raised)" — right next to the model's own message.
- **A singular AC matrix during noise analysis crashed ngspice with a
  SIGABRT** — `noisean.c` ignored `NIacIter`'s return, and the noise adjoint
  solve then asserted on the unfactored matrix. It now aborts the noise
  analysis cleanly ("AC solution failed at … Hz"); the noise analysis also
  honors E-55's deferred `$finish`/`$stop` raised at its operating point.

## The sweep verdicts (all 92 corpus models)

Everything not fixed above was triaged to model/bench characteristics:
HiSIM-HV/SOI reject an all-terminals bench without `COSUBNODE`/`COBCNODE=1`
(by design, now with clean diagnostics); `vbic_4T_et_cf` floats internal
nodes at `RCX=0`/`RS=0` by design (use `.option rshunt`); EPFL-HEMT wants a
realistic bias; FBH-HBT divides by its own out-of-range default `Fb=0` in a
`ddt()` (give `fb>0` for transients) — reachable at all only thanks to the
default fix.

## Run

```
python3 verify_paramrange.py
```

Checks (13, ALL PASS): out-of-range defaults accepted with exact solutions
(feature-off and feature-on conductances); given out-of-range values still
rejected (exclusive range bound, exclude list, beyond-range); the hisimsoi
noise crash reproducer now aborts cleanly (was SIGABRT); and the stock CMC
`diode_cmc` from VA_TEST runs op/AC/noise at default parameters with a
positive noise spectrum. Checks 4–5 use the VA_TEST corpus and are skipped
if it is absent.
