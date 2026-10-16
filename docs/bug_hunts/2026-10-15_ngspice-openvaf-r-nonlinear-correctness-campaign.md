# Bug hunt — nonlinear correctness of ngspice and openvaf-r against independent references

**When:** 2026-10-15, after the transient stress campaign's N1 to N6 were folded and released
(E-884 to E-888).
**Binary:** the repo's `ngspice-46/build/src/ngspice` and `openvaf-r` at E-888, tree at `03c5b297`,
KLU and XSPICE compiled in.

**Method:** the earlier campaigns checked linear networks against exact solves, the compiler
against itself and against Python, and ngspice against its own tight runs
([first](2026-10-10_ngspice-openvaf-r-robustness-and-correctness-campaign.md),
[second](2026-10-10_ngspice-openvaf-r-second-robustness-campaign.md),
[third](2026-10-10_ngspice-openvaf-r-third-robustness-campaign.md) campaigns). This one takes
NONLINEAR circuits and checks each analysis against a reference computed outside ngspice. Every
family ran under `.option sparse` and `.option klu`. Devices were the built-in diode, npn BJT and
level-1 nmos, and Verilog-A twins of the same equations compiled with openvaf-r: kT/q from
ngspice's own constants, `$limit(…, "pnjlim", …)`, `limexp`, and the bulk-drain junction a bulk
tied to the source leaves. The harnesses are throwaway scripts in the session scratchpad
(`rc6/fam*.py`).

- **A. Operating points against the circuit equations.** 500 random networks of R, V and I
  sources, diodes, BJTs and MOSFETs, built-in and twin, both solvers: 2 000 runs. Python
  recomputes every node's KCL from the reported voltages and the device equations, with gmin
  where ngspice adds it, and judges the residual against the node's conductance times
  ngspice's voltage tolerance.
- **B. Noise against a small-signal reference.** The same networks with capacitors and flicker
  coefficients: `noise` against Python, which linearises every device at ngspice's own
  operating point and sums each source's PSD through the complex MNA system:
  - resistors: 4kT/R;
  - diode and BJT: 2qI and KF·I^AF/f;
  - MOS1: 4kT(2/3)|gm| and the `nlev` 2 flicker term.

  400 networks × 2 solvers × {built-in, twin with `white_noise`/`flicker_noise`}: 1 600 runs, 1 218 compared (370 skipped as N2, 12 with no noise at the output).
- **C. Charge conservation.** Two- and three-terminal Verilog-A `ddt(Q(V))`, the diode, the npn,
  level-1 MOS with `tox` (Meyer) and BSIM3/BSIM4, driven around closed periodic paths (two
  harmonics). The net charge per period is integrated on the accepted points and compared with the
  charge moved. Conduction was removed (IS 1e-30, junctions under 0.8 V, gmin 1e-20, drain on
  source): 700 runs, trap and gear.
- **D. Temperature on every route.** `.temp`, `.option temp`, `option temp`, `dc temp`; instance
  `temp=`/`dtemp=`; `tnom` on the model or from `.option tnom`. Checked on the resistor
  (`tc1`/`tc2`, `tce`), the diode (IS(T) with EG, XTI, N) and a Verilog-A resistor reading
  `$temperature`, against the SPICE formulas: 600 runs.
- **E. Small-signal analyses at a nonlinear point.** `ac` at 1 Hz and `.tf` (gain, input and output
  resistance) against central differences of three operating points in the same session
  (`alter`), reltol 1e-10: 1 144 runs, built-in and twin.
- **F. `fourier` and `.four` against exact harmonics.** Stacked sin sources up to the 6th harmonic,
  random `nfreqs`, `nperiods`, `polydegree`, `fourgridsize`, at ≥ 200 points a period: 800 runs.
- **G. Random distributions.**
  - Control language: `sgauss`, `sunif`, `poisson`, `exponential`, 20 000 draws each.
  - `.param` functions: `agauss`, `gauss`, `aunif`, `unif`, `limit`, 3 000 draws over ten seeds.
  - Verilog-A: the seven `$rdist_*` functions, 3 000 instances each.
  - Checks: Kolmogorov–Smirnov and moment tests, and seed reproducibility.
- **H. Nonlinear transients against scipy's Radau.** Pure-ODE networks (a capacitor at every
  node, current-source drive) integrated from ngspice's own operating point: 480 runs, trap and
  gear, built-in and twin.
- **I. Memory.** Guard Malloc (`/usr/lib/libgmalloc.dylib`) over 89 decks sampled from every
  family, twins included.

Nothing was fixed; this is the list.

| | Finding | Severity |
|---|---|---|
| [F1](#f1) | *(fixed in [E-889](../../enhancements_doc/Enhancement-889.md): the device tests read the new solution and their count decides, and a Verilog-A device has one; the diode converges off at 100 V, the sweep's current is within reltol; the second face is within `vntol`)* **operating point:** the device convergence tests compare the point the device was loaded at with itself, so convergence rests on node-voltage changes alone. A diode across a resistor between two 100 V nodes converges 0.68 V forward with 2.47 mA of KCL error (the only solution is 0 V); at ordinary voltages a junction's current is reported up to 2 % off (20 × reltol); a nA current into a low-impedance node is missing from the solution. Built-in and Verilog-A devices alike. Stock | high |
| [F2](#f2) | **analysis:** `ft_polyfit` fits each local polynomial in absolute time. `fourier` at `polydegree=3` adds a 1e-4 floor and shifts a harmonic's phase by 1°; `deriv()` at `dpolydegree=3` returns 3e20 times the derivative over a 500 ms run | medium |
| [F3](#f3) | **statistics:** `setseed N` is not reproducible within a session: the first `setseed 11` and every later one give different `sgauss` sequences | medium |
| [D1](#d1) | **analysis:** `fourier` refuses a window exactly `nperiods` long by one ulp; on the `.four` route it then says "No transient data available" | low |
| [D2](#d2) | **output:** `wrdata` writes a vector longer than its plot's scale truncated to the scale's length, without a word: 1 000 values become one row | low |
| [N1](#n1)–N4 | notes: the Meyer model loses charge on a closed path; a junction forward-biased by a source with no resistance carries 1e155 A without a word; MOS1's default flicker term uses AF as the frequency exponent; the truncation tolerance's charge term | — |

<a id="f1"></a>
## F1 — the device convergence tests compare the linearisation point with itself

*Fixed in [E-889](../../enhancements_doc/Enhancement-889.md). It was worse than the deck showed:
`NIiter` assigns `NIconvTest`'s return value to `CKTnoncon`, and `CKTconvTest` returns `OK` after a
device has counted itself unconverged. So the count of all 30 tests was overwritten with 0,
including the MOSFETs of levels 1 to 9, whose tests read the new solution. The tests now see the new
solution, their count decides, and `OSDIconvTest` gives a Verilog-A device the same test. The diode,
the npn and the MOSFET junction converge off at 100 V, built-in and Verilog-A alike. The `dc temp`
sweep reports 0.5210601 V, its current within reltol. Family A's networks 1436 and 1031 converge to
their solution, and 1031's built-in and Verilog-A runs now agree to 4 µV, where they differed by
1.9 V. The second face below is within the tolerance's definition: 82 nV is under `vntol`, and a
current into a 65 Ω node is resolved only to `vntol` over 65 Ω.*

**The deck.** A diode across a 794 kΩ resistor, both between node 3 (driven to a voltage V3) and
node 4, which nothing else touches. The only solution is 0 V across the pair.

```
i1 0 3 dc 1e-4
r1 3 0 1e6
r2 4 3 793581
d1 4 3 dbi
.model dbi d is=1e-14
```

| V3 | vd | `@d1[id]` | resistor | iterations |
|---|---|---|---|---|
| 10 V, 20 V | 1.7e-11 V | 2.4e-23 A | 2.2e-17 A | 15 |
| 30 V … 10 kV | **0.6786 V** | **2.47 mA** | 0.86 µA | 3 |
| any, `reltol=1e-6` | 0 V | 0 | 0 | 16 |

From 26 V up (vt/reltol), node 4's KCL is off by the whole diode current. A Verilog-A diode, or the
body diode of the Verilog-A MOSFET twin, does the same. Family A found it as seed 1436, a twin at
183 V, and seed 1031, at 65 V.

**Why.** `NIiter` calls `NIconvTest` after the solve and before it swaps `CKTrhs` and
`CKTrhsOld`. `NIconvTest` runs `CKTconvTest` (NEWCONV is defined), and every device test —
`DIOconvTest`, `BJTconvTest`, `MOS1convTest` — reads its terminal voltages from `CKTrhsOld`. That
is the point the device was just loaded at, so `delvd` is 0 and the predicted current equals the
stored one. Instrumented, `delvd = 0` at every iteration. The new solution had moved 26 mV, which
predicts the current falling from 2.47 mA to near zero.

So the tests only ever see limiting, and what decides convergence is the node test,
reltol·|V| + vntol: 0.1 V per step at 100 V. E-256's residual guard measures 38, under its
threshold of 100, because its scale reltol·|G·x| holds the junction's Norton terms gd·vd, about
26 times its current. OSDI devices have no convergence test at all. The originally imported
ngspice-46 (`4f29ffad6`) has the same order.

**Second face, at low voltage** (Family A seed 1168). A reversed level-1 nmos (vds = −0.30 V)
whose bulk-drain junction carries 1.25 nA into a node with 65 Ω to ground. `@m14[id]` reports
−1.2536 nA, but `v(3)` is −1.9e-11 V; one more iteration, which `vntol=1e-12` brings, puts it at
−8.19e-8 V. The 81 nV correction is under vntol, and the drain source's branch current misses the
1.25 nA.

**Third face, the common one** (Family D). `NIiter` returns before the swap, and the analysis
reports `CKTrhsOld`: the point the devices were loaded at, not the solve just made. That is
SPICE's design, since the device states belong to that point. But the last update may be
reltol·|V|, and on a junction that is a large share of the current.

A `dc temp` sweep of one diode on 2.69 µA, 40-degree steps:

| | reported | the solve dropped | exact |
|---|---|---|---|
| −31.68 °C | 0.5215276 V | 0.5210601 V | 0.5210549 V |
| 8.32 °C | 0.4882827 V | 0.4882469 V | 0.4882468 V |

The reported diode current is 2 % off, twenty times reltol. At 4-degree steps it is exact to 4e-9.
A working device test would have asked for one more iteration: the update moves the current 2 %.

<a id="f2"></a>
## F2 — `ft_polyfit` fits in absolute time

`ft_interpolate` and the derivative code fit each local polynomial with `ft_polyfit`, whose
Vandermonde matrix is built on the abscissa itself: 1, t, t², t³ with t around 1e-6 s and the
points 2e-10 s apart. Its condition number grows as (t/h)^degree. The callers are `fourier`
(`polydegree`), `deriv()` (`dpolydegree`), `interpolate()`, `linearize` and plot interpolation.

- **`fourier`.** A 5.07 MHz waveform with four harmonics, at 1 000 points a period. At
  `polydegree=3` the 4th harmonic is 0.24 % high and 1.07° off, and harmonics that are zero read
  about 1e-4. At degrees 1 and 2 the result is exact to 1e-9 and 1e-11.
  A pure 1 kHz sine over 20 periods at 1 µs reads a THD of 0.0024 % (−92 dB) at degree 3, against
  2.8e-11 % at degree 1.
- **`deriv()`.** A 1 kHz sine at 1 µs steps, against 2πf·cos, for the default degree 2 and for
  degree 3:

  | run | `dpolydegree=2` | `dpolydegree=3` |
  |---|---|---|
  | 2 ms | 6.6e-6 | 4e-8 |
  | 50 ms | 6.6e-6 | 1.2e-2 |
  | 500 ms | 6.6e-6 | **3.2e20** |

  Degree 1 is 3.1e-3 throughout.

<a id="f3"></a>
## F3 — `setseed` is not reproducible within a session

```
setseed 11
let g = sgauss(vector(3))     -> -0.8159, 0.6548, -0.4705
setseed 11
let g2 = sgauss(vector(3))    -> -1.0678, -1.3123, 1.5295
```

Every later `setseed 11` gives `g2`'s values. Draws made before the first `setseed` change
nothing. The two states come from two places:
- `com_sseed` calls `ng_srand` and `TausSeed`, then, since
  [E-374](../../enhancements_doc/Enhancement-374.md), refills the Wallace pools, which draws from
  the generator.
- `checkseed()` keeps its own static `oldseed`, which `com_sseed` does not update. So the first
  random call after the FIRST `setseed` reseeds again, without the pool refill, and that run starts
  from the fresh state. Every later `setseed` leaves the state after the refill.

A script that runs `setseed 1`, a Monte Carlo, then `setseed 1` and the same Monte Carlo gets two
different results. `sunif` reproduces.

<a id="d1"></a>
## D1 — `fourier` refuses an exact-fit window by one ulp

`fourier.c` refuses when `dp[1] - dp[0] < nperiods/fundfreq`, with no tolerance. Twelve of 800
runs, all with `tstart` one period and `tstop` three periods at `nperiods=2`, were refused with
"(2 * wavelength) longer than time span". On the `.four` route the run then prints "No transient
data available for fourier analysis", which is not what happened.

<a id="d2"></a>
## D2 — `wrdata` truncates a vector to its plot's scale, without a word

`let g = vector(1000)` followed by `wrdata wg.txt g` writes one row, in the constants plot and after
an `op` alike, and says nothing. With `set wr_singlescale` it refuses instead: "Vectors g and g have
different lengths!"

## Notes

<a id="n1"></a>
- **N1 — the Meyer model loses charge on a closed path.** Level-1 MOS with `tox`, drain on source,
  gate and bulk driven around a closed path: 1 % to 98 % of the moved charge per period is lost. The
  loss is the same at every step size (0.675 at T/200, T/1000 and T/5000). This is the known
  behaviour of the capacitance-based Meyer model of MOS levels 1 to 3. BSIM3 and BSIM4 conserve,
  `capmod=0` to first order in the step.
- **N2 — a junction forward-biased by a source with no resistance.** In 93 of Family B's 400
  networks a random source forward-biased a junction directly. ngspice computed and reported
  currents from 2e3 to 4e155 A, without a word. The circuit is the user's; a warning would
  help.
- **N3 — MOS1's default flicker term.** At `nlev=2`, the default, the term is
  KF·gm²/(f^AF·W·Leff·Cox): AF is the FREQUENCY exponent there, not the current's. Giving `tox` adds
  the Meyer gate capacitances, which change ac and noise. Both are ngspice's documented behaviour;
  the reference first had them wrong.
- **N4 — the truncation tolerance's charge term.** At reltol 1e-7 and trtol 1, nonlinear transients
  came within 5.7e-4 of their range. The charge term reltol·|q|/h is loose at small steps. At 1e-9
  they are within 3.3e-4 and converge with reltol. This is SPICE's definition.

## What was clean

- **No crash anywhere.** 7 445 harness runs and about 120 hand runs ended without a signal or a
  memory error. The 89 Guard Malloc runs were clean.
- **Sparse and KLU agree** in every family, to the printed digit.
- **Built-in devices and their Verilog-A twins agree.** Operating points agree to 1.3 mV, except
  where a junction is past `limexp`'s knee and the twin is then a different device. Transients
  agree to the digit, noise to 1e-7, and small-signal to 1e-9.
- **Noise:** 1 218 spectra within 1e-7 of the small-signal reference: shot, flicker and thermal
  noise of the diode, BJT and MOS1, and openvaf-r's `white_noise` and `flicker_noise` through OSDI.
- **Charge:** Verilog-A `ddt(Q)` in two and three terminals (non-reciprocal too), the diode, the
  npn and BSIM3/4 `capmod` 1 to 3 conserve to 5e-8…3e-7 per period under trap.
- **Temperature:** every route within 5.7e-7 of the SPICE formulas at tight tolerance: `.temp`,
  `.option temp`, `option temp`, the `dc temp` sweep, instance `temp`/`dtemp` (OSDI included),
  `tnom` from the model or the option, and the resistor's `tce`.
- **Small-signal:** `ac`, `.tf` gain and input resistance within 1.7e-5 of finite differences, and
  every resolvable output resistance within 8.6e-5.
- **`fourier`** outside F2 and D1: harmonics and THD within interpolation accuracy; the dc term is
  reported signed.
- **Distributions:**
  - control language: `sgauss`, `sunif`, `poisson` and `exponential` pass KS and moment tests at
    20 000 draws;
  - `.param` functions: `agauss`, `gauss`, `aunif`, `unif` and `limit` pass over ten seeds;
  - Verilog-A: all seven `$rdist_*` functions pass at 3 000 instances.
- **Nonlinear transients** converge to Radau with reltol, under trap and gear.
