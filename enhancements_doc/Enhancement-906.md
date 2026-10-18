# Enhancement-906: TXL's convolution steps are exact — a lossy line driven in its RC regime grew from 0.19 V to −2.6 V on a 0.25 V signal

**Scope:** found while digging into F9 of the
[analyses correctness campaign of 2026-10-16](../docs/bug_hunts/2026-10-16_ngspice-openvaf-r-analyses-correctness-campaign.md)
([E-904](Enhancement-904.md)).

ngspice:
- `spicelib/devices/txl/txlload.c`: the load forms each step of its three convolutions (the
  characteristic admittance, the propagated voltage and current) with the exact weights of a linear
  segment, as the history update does.

**ngspice only.**

**Suites:**
- [`txlcpl_examples`](../examples/txlcpl_examples/): check [4].
- The full sweep: 596 of 596.

## What was wrong

A TXL line's response is three sums of terms c·e^(x·t). Each time step, the load forms the step's
part of every convolution: the characteristic admittance on the line's own port voltage, and the
propagation terms on the other port's voltage and current one delay earlier. Once the point is
accepted, the characteristic admittance's history advances by the step's exact integral.

The load formed the same step by the trapezoid rule, (h/2)·c·(v_old·e^(xh) + v_new). That differs
from the exact integral by (x·h)²/12 of it each step, and the history then replaced the load's
value with the exact one. On a lossy line driven well below its RC corner R/L the disagreement fed
back, and the transient grew without bound. A 200 m line of R·length = 100 Ω (1.18 Z_c) between
50 Ω, driven at 10 kHz (R/(2πL) = 221 kHz), at the same phase each period:

| | 1.025 ms | 1.925 ms | 2.225 ms | 2.925 ms |
|---|---|---|---|---|
| E-903 | 0.184 | −0.135 | −0.572 | −0.572 (frozen, [E-907](Enhancement-907.md)) |
| E-904, E-905, E-907, trapezoid steps | 0.189 | −0.112 | −0.420 | −2.58 |
| now | 0.2480 | 0.2480 | 0.2480 | 0.2480 |

The exact line gives 0.2500.

## The change

The step of each term is t·(v_new·w_n + v_old·w_o), t = c/x, with w_n = (e^z − 1 − z)/z and
w_o = (e^z − 1) − w_n, z = x·h, by a series where z is small, and in complex arithmetic for a pole
pair. The constant part is stamped with w_n, the old point goes to the right-hand side with w_o. The
history update uses the same weights for the step the load took ([E-905](Enhancement-905.md)), so
the two agree to rounding. For a constant input the step adds t·v·(e^z − 1), and the history
settles at exactly −c·v/x, the term's dc gain.

## The checks

`txlcpl_examples`:
- **[4]** The 200 m line above: the four peaks equal to 1e-3 of the amplitude and within 2 % of
  the exact line (0.8 %). E-903: 0.184 to −0.572.

Over the campaign's Family G lines, which run for tens of periods, the exact steps leave the error
where it was: median 8.8e-5 with either, 90th percentile 3.2e-3 against 3.1e-3 with the trapezoid.
