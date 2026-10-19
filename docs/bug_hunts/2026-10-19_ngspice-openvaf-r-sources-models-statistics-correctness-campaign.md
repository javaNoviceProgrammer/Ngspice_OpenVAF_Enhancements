# Bug hunt — sources, code models, Verilog-A operators, statistics and periodic analyses against independent references

**When:** 2026-10-19, after the analyses correctness campaign's F9 was folded and released (E-904
to E-908).
**Binary:** the repo's `ngspice-46/build/src/ngspice` at E-908 and `openvaf-r` at its last compiler
change (E-863), KLU and XSPICE compiled in, the local build's code models.

**Method:** the [previous two campaigns](2026-10-16_ngspice-openvaf-r-analyses-correctness-campaign.md)
checked the device-level analyses. This one takes the parts of the stack they did not reach: what
drives a circuit, the behavioural blocks, the Verilog-A operators that are not devices, the
statistical commands and the periodic small-signal analyses. Each is checked against a reference
computed outside ngspice: the manual's formula, an exact transfer function, an exact probability or
numpy's solve. The harnesses are throwaway scripts in the session scratchpad (`rc8/fam*.py`).

- **A. The independent sources against their definitions.** 3,400 random V and I sources:
  PULSE (with NP), SIN, EXP, PWL (with `r=` and `td=`), SFFM, AM, PRBS and PAM4, with trailing
  arguments randomly left out so the defaults are exercised. `op`, then every accepted point of a
  transient is compared with the waveform evaluated in Python from the manual's formulas (4.1) and
  the enhancements that changed them (E-318, E-446, E-475, E-752). Each PULSE, PWL and PRBS corner
  must be a time point.
- **B. The XSPICE analog code models (manual 8.2).** 900 cases. `gain`, `summer`, `mult`, `divide`,
  `limit`, `climit` and `pwl` swept in `dc` against the ideal function away from the smoothing
  corners; `gain`, `summer`, `s_xfer`, `int` and `d_dt` in `ac` against H(jω); in transient `int`
  against the trapezoid sum of its own input samples, `d_dt` against their backward difference,
  `s_xfer` against the exact step response, `slew` against exact ramps, and the `sine`, `triangle`
  and `square` oscillators against their phase.
- **C. openvaf-r's filters and time operators.** `laplace_nd`/`zp`/`zd`/`np` of orders 1 to 4 with
  random stable poles: `ac` against H(jω), a step against partial fractions. `zi_nd` and `zi_zp`.
  `absdelay`, `idt`, `idtmod`, `transition`, `slew`, and the event times of `cross` and `timer`
  against the analytic crossings of a sine and `tstart + k·tper`. 120 + 40 decks, the coefficients
  set from the model card so one object serves every seed.
- **D. The statistics against exact probabilities.** `.option osdimc` with one parameter of every
  declared shape (gauss, uniform, `std_rel`, lognormal, `trunc`, `tgauss`, and an instance
  mismatch pair): KS tests against the declared distribution. `montecarlo -lhs`: one sample per
  probability stratum. `highsigma` and `wcd` on a linear limit state against Φ(−β). `montecarlo`
  yield of a correlated sum (`mccorr`/`mvnorm`) against the exact normal probability, and the
  recorded draws' correlation against ρ. 500 runs.
- **E. Controlled sources against an independent MNA.** 150 random linear networks of R, C, L with
  `K` couplings, V, E, F, G and H, in `ac` at three frequencies under Sparse and KLU, against
  numpy's solve of the same modified nodal equations. Then POLY(1..3) E, G, F and H sources up to
  cubic terms, and E TABLE, in `op` against the manual's polynomial and the table's clamped
  interpolation: 150 cases.
- **F. `.pac` and `.pnoise` on a linear periodically time-varying circuit.** A B-source mixer
  `v(m) = v(rf)·(1 + m·v(lo))` into an RC: every sideband's conversion gain is c_k·H(f + k·f_lo),
  and the output noise of a resistor ahead of the mixer folds from three sidebands. 160 cases,
  Sparse and KLU, input frequencies on both sides of f_lo.

| | Finding | Severity |
|---|---|---|
| [F1](#f1) | **Verilog-A event:** `@(cross(...))` with the default time tolerance runs its body twice for one crossing — on the step that overshoots it and again on the retry that lands on it — and keeps both side effects: a crossing counter on a 1 MHz sine reads 30 after 20 crossings | high |
| [F2](#f2) | **source:** a voltage source's PULSE with `PER` left out repeats back to back (period TR+TF+PW), and with `PW` left out too it is a triangle; the manual gives both a default of TSTOP, and a current source with the same line gives the single pulse | high |
| [F3](#f3) | **source:** a current source's SFFM never applies its delay — `TD` is read as the modulation phase and `PHASEM` as the carrier phase — and a current source's AM is 0 before its delay and at the operating point; E-318 fixed both only on the voltage source | medium |
| [F4](#f4) | **source:** SFFM's default frequencies are the manual's swapped (carrier 5/TSTOP, modulation 500/TSTOP), so `SFFM(0 1)` is a 5 kHz carrier with its modulation index clamped to 0.01; the manual's general-form line orders the arguments FM MDI FC, against its own table and the code | low |
| [F5](#f5) | **source:** EXP with `TD1` left out starts one TSTEP late (the manual: at 0), so its waveform moves with the step — the case E-446 fixed only for an explicit 0 | low |
| [F6](#f6) | **controlled source:** a POLY(1) source with a single coefficient is refused as "Too few values for parameter 'coef'", where the manual's general form allows `P0` alone; the hint about missing node pairs does not apply | low |
| [D1](#d1) | an E or G `TABLE` source run without the code models loaded fails as "the controlling node 'e1_int1' does not exist … This is a typo": the internal node of its translation is named, the missing `pwl` code model is not | low |
| [N1](#n1)–N6 | notes: `zi_*` small-signal is the bilinear map (documented); a `dc` point just past a kink is within `reltol`; `d_dt` is first order; two PWL corners closer than the minimum break keep one; PRBS's default edge is clamped to the bit; `.pnoise` uses the pre-2019 Boltzmann constant | — |

<a id="f1"></a>
## F1 — `cross` with the default tolerance runs its body twice

```verilog
module cnt(in, out);
  inout in, out; electrical in, out;
  parameter real thr = 0.3;
  parameter integer dir = 0;
  integer n;
  analog begin
    @(initial_step) n = 0;
    @(cross(V(in) - thr, dir)) n = n + 1;
    V(out) <+ n;
  end
endmodule
```

Driven by `sin(0 1 1meg)` for 10 µs, the counter should read 20 (both directions) or 10:

| `dir` | max step | `cross(V(in) - thr, dir)` | `cross(V(in) - thr, dir, 1e-12)` | exact |
|---|---|---|---|---|
| 0 | 1 ns | 20 | 20 | 20 |
| 0 | 5 ns | **30** | 20 | 20 |
| 0 | 20 ns | **27** | 20 | 20 |
| +1 | 5 ns | **17** | 10 | 10 |
| +1 | 20 ns | **11** | 10 | 10 |
| −1 | 1, 5, 20 ns | 10 | 10 | 10 |

A `$strobe("XC %d %.17e", n, $abstime)` in the body shows the mechanism: after some crossings it
prints twice, the second time with an earlier `$abstime` — once at the step that overshot the
crossing (a full step past it, the expression already 0.13 V beyond the threshold) and once at the
retry that E-759 lands on the crossing. The overshooting step is rejected, but what its body did is
not undone. Over 40 random decks (10 periods each), 8 counted extra crossings. In the others the
worst crossing of a deck fired a median 1.0e-3 (`dir` = +1) and 1.7e-3 (`dir` = −1) of the maximum
step from the analytic crossing — E-759 states a thousandth of the step — but 0.997 of it for
`dir` = 0. With an explicit `time_tol` every crossing fired once, at the crossing.

Anything with state in a `cross` body is affected: a counter, a latch, a toggling divider, a
recorded `$abstime`.

<a id="f2"></a>
## F2 — a voltage source's PULSE without `PER` repeats

```
V1 a 0 PULSE(0 1 1u 1u 1u 5u)      * PER left out
I1 0 b PULSE(0 1 1u 1u 1u 5u)
```

At 20 µs `v(a)` is 1 and `v(b)` 0: the voltage source repeats every TR + TF + PW = 7 µs (its third
rising edge is at 15.5 µs), the current source gives one pulse. With `PW` left out as well,
`PULSE(0 1 1u 1u 1u)`, the voltage source is a 2 µs triangle (0 at 5 µs, 0.5 at 12.5 µs) and the
current source rises to 1 and stays.

The manual (4.1.1) gives PW and PER a default of TSTOP, and its table of a single pulse is what the
current source does. `vsrcload.c` takes an omitted PW as 0 and an omitted PER as TR + TF + PW;
`isrcload.c` takes both as `CKTfinalTime`. E-446 kept the voltage source's omitted-PER rule on
purpose ("so no existing deck changes") while making an explicit `PER=0` a single pulse. In a run
of 1,500 random sources, 74 voltage-source PULSE cases differed from the manual this way, all with
PW or PER left out. SPICE3's and LTspice's PULSE without a period is one pulse.

<a id="f3"></a>
## F3 — a current source's SFFM ignores its delay, and its AM drops its offset

```
V1 a 0 SFFM(0 1 1meg 2 100k 5u 30 60)
I1 0 b SFFM(0 1 1meg 2 100k 5u 30 60)
V2 c 0 AM(0.5 1 0.5 100k 1meg 5u)
I2 0 d AM(0.5 1 0.5 100k 1meg 5u)
```

| | `op` | at 2 µs | at 7.3 µs | manual |
|---|---|---|---|---|
| V1 SFFM | 0.888651 | 0.888651 | −0.997647 | 0.888651 held to 5 µs; −0.997985 |
| I1 SFFM | 0.500000 | 0.655990 | 0.411560 | |
| V2 AM | 0.5 | 0.5 | | 0.5 held to 5 µs (E-318) |
| I2 AM | 0 | 0 | | |

`isrcload.c`'s SFFM reads `TD = coeffs[5]` and then `PHASEM = coeffs[5]` and `PHASEC = coeffs[6]`,
and never subtracts `TD` from the time: the 5 µs delay is used as a modulation phase of 5e-6
degrees, the 30° modulation phase as the carrier phase, and the 60° is dropped. Its AM returns 0
for `time <= TD`, where E-318 made the voltage source hold the t = 0 value. In a run of 1,500
random sources, 45 current-source SFFM and 66 current-source AM cases differed this way.

<a id="f4"></a>
## F4 — SFFM's default frequencies are swapped

`V1 a 0 SFFM(0 1)` with `tran 1u 1m` crosses zero rising at 0.2 ms and 0.4 ms — a 5 kHz carrier —
and prints `Warning: MDI in v1 limited to FC/FM`. The manual's table gives FC 500/TSTOP and FM
5/TSTOP, which with the default MDI of 90 is a valid FM signal; the code gives FC 5/TSTOP and FM
500/TSTOP, a modulation faster than its carrier, and clamps MDI to FC/FM = 0.01. The argument order
the code reads (VO VA FC MDI FM TD PHASEM PHASEC) is the table's, but the manual's general-form
line reads `SFFM(VO VA FM MDI FC TD PHASEM PHASEC)` and its example `SFFM(0 2 20 45 1k 1m 0 0)` is
written in that order, so it means a 20 Hz carrier, and its MDI of 45 is clamped to 0.02.

<a id="f5"></a>
## F5 — EXP with `TD1` left out starts one step late

`V1 a 0 EXP(0 1)`: `v(3u)` is 4.9e-13 with `tran 0.1u 20u` and 0.236 with `tran 1u 20u`. TD1 left
out is TSTEP in both source files; the manual's default is 0. The time constants default to TSTEP
on purpose, but the delay then shifts the whole waveform by one more step, which E-446 removed only
for a written `TD1=0`. Two runs of 1,500 random sources had 15 and 22 such EXP cases.

The SIN entry has the opposite gap: before TD the manual says V0, the code (both sources) holds
VO + VA·sin(PHASE), the value the waveform starts from. The code's choice is the continuous one;
the manual's formula is the one to change.

<a id="f6"></a>
## F6 — POLY(1) with a single coefficient is refused

```
E1 o 0 POLY(1) c0 0 2.5
```

```
Too few values for parameter 'coef' of model 'a$poly$e1': fatal.
        This is a poly() source: check the number of INPUT NODE PAIRS as well -- poly(n) needs exactly n of them, and any that are missing are consumed from the coefficients.
```

The manual's general form is `POLY(ND) NC1+ NC1- P0 (P1...)`; SPICE2 read a lone coefficient of a
one-dimensional POLY as the gain P1. ngspice accepts neither, and the hint points at the node
pairs, which are right. Every other POLY case — 94 E, G, F and H sources in one to three
dimensions up to cubic terms — matched the manual's ordering to 4.3e-15.

<a id="d1"></a>
## D1 — TABLE without the code models names an internal node as a typo

`E1 o 0 TABLE {V(c0)} = (...)` is translated into `E1 o 0 e1_int1 0 1`, a B source and an `a`
instance of the `pwl` code model that drives `e1_int1`. Without the code models loaded, the
instance cannot be made, and E-492's check reports `the controlling node 'e1_int1' does not exist --
no device connects to it … This is a typo, not a circuit`. The node is the translation's, and the
cause is the missing `pwl` model, which is not mentioned. With the code models loaded, all 32
TABLE cases matched the clamped interpolation to 4.2e-15.

## Notes

<a id="n1"></a>
- **N1 — `zi_*` in small-signal is the bilinear map.** `ac` of `zi_nd` and `zi_zp` equals H(z) at
  z = (1 + sT/2)/(1 − sT/2) to 1.6e-15, not at z = e^{sT}, and the transient is the continuous
  image of that map. This is the deviation the [compliance
  report](../compliance/OpenVAF_Verilog-A_LRM_Compliance.md) states (4.5.12, ⚠️); both forms match
  it to 1.3e-14 in `ac` and 1.8e-4 in a step.
- **N2 — a `dc` point just past a kink** of `climit`, `pwl` or `divide` is off by up to `reltol`
  (9.97e-4 at the default): the iterate linearised on the previous segment is accepted within the
  tolerance. With `reltol=1e-10` every static block is exact to 1.1e-14.
- **N3 — `d_dt` is first order**, as the manual says (the slope since the previous point): 3 % from
  the exact derivative at 100 points per period, and equal to its backward difference to 1e-11.
- **N4 — two PWL corners closer than the minimum break** (2e-13 s apart) keep one time point: on a
  rising edge the first corner, on a falling edge the second, so a block that reads its input's
  change since the last point (`slew`) starts a falling ramp one step early.
- **N5 — PRBS's default edge** (TSTEP) is clamped to the bit when the step is longer than the bit,
  without a word; an explicit `tr` longer than the bit is refused.
- **N6 — `.pnoise` is 1.738e-7 below** the exact folding in V/√Hz: ngspice's Boltzmann constant is
  1.38064852e-23, not the 2019 SI 1.380649e-23.

## What was clean

- **The sources**, outside F2 to F5: every accepted point of 3,400 random waveforms equals the
  formula at that time to 1e-9 (PULSE with NP, SIN with damping and phase, EXP, PWL with repeat
  and delay including the jump at each repeat, SFFM, AM, PRBS and PAM4 against an independent
  Fibonacci LFSR with the O.150 and 802.3 taps); every corner is a time point; `op` is the dc value
  when given and the t = 0 value otherwise.
- **The XSPICE analog models:** `gain`, `summer`, `mult`, `divide`, `limit`, `climit` and `pwl`
  exact to 1.1e-14 in `dc` (N2 at the default tolerance); `ac` of `gain`, `summer`, `s_xfer` (with
  `denormalized_freq`), `int` and `d_dt` exact to 1e-14; `int` within 8.6e-7 of the trapezoid sum
  of its input samples, `s_xfer`'s step within 7e-5 of exact, `slew`'s ramps within 2.3e-12, and
  `sine`, `triangle` and `square` within 4.1e-12 of their phase.
- **`laplace_*`:** all four forms, orders 1 to 4, `ac` within 1.1e-14 of H(jω) and a step within
  5e-5 of partial fractions. **`absdelay`:** `ac` e^{−jωτ} to 7e-13; the transient interpolates its
  history linearly (2e-3 at 50 points per period, 8e-6 at 800). **`idt`, `idtmod`** to the
  integrator's accuracy; **`slew`** exact; **`transition`** within its input's edge;
  **`timer`** at `tstart + k·tper` to 2.3e-13 of the period (one deck 2e-7 of it, 5e-13 s, the
  breakpoint resolution).
- **The statistics:** every `osdimc` shape matches its declared distribution. Over 100 runs the KS
  p-values are uniform but for `std_rel` (0.009, one of eight shapes), and 20,000 draws of each
  pass (lowest p 0.055; means and spreads within their errors, bounds exact). Two instances'
  mismatch draws independent (z sd 0.95). `-lhs` has exactly one sample per stratum in all 100
  runs. `highsigma`'s estimate against Φ(−k) has z mean −0.09, sd 1.00 over 100 runs: its error bar
  is right. `wcd`'s β is exact and its mean-shift estimate has z sd 1.05. `montecarlo`'s correlated
  yield is unbiased (z sd 0.77, half the runs `-lhs`) and the draws' correlation is ρ.
- **Controlled sources:** 150 networks with E, F, G, H, V and K couplings within 5.1e-13 (Sparse)
  and 1.8e-13 (KLU) of the independent MNA.
- **`.pac`:** every sideband of the mixer within 8.8e-14 of c_k·H(f + k·f_lo), on both sides of f_lo
  (a lower sideband at a negative frequency is that frequency's amplitude), Sparse and KLU, 128 to
  1,024 points. **`.pnoise`:** the three-sideband folding of white noise exact but for N6.
