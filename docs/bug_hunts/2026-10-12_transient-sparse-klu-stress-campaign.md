# Bug hunt — stress-testing transient analysis under Sparse and KLU, with every error-control setting

**When:** 2026-10-12, after the [Sparse and KLU correctness campaign](2026-10-11_sparse-klu-correctness-campaign.md)
was folded and released (E-867 to E-872).
**Binary:** the repo's `ngspice-46/build/src/ngspice` at E-872, tree at `be6d2e14`, KLU and XSPICE
compiled in.

**Method:** the earlier campaigns checked the transient with trap and Gear on linear networks
([second campaign, Family D](2026-10-10_ngspice-openvaf-r-second-robustness-campaign.md)). This one
covers every setting the repo added for controlling transient error, under both solvers:
- the integration methods `trbdf2` (with `trgamma`), `sdirk` and `adams` ([E-419](../../enhancements_doc/Enhancement-419.md));
- `dynorder` ([E-128](../../enhancements_doc/Enhancement-128.md)) and `ordfix` ([E-181](../../enhancements_doc/Enhancement-181.md));
- `errpreset` ([E-110](../../enhancements_doc/Enhancement-110.md));
- `maxord` under every method ([E-853](../../enhancements_doc/Enhancement-853.md));
- the checkpoint commands `savestate` and `loadstate` ([E-131](../../enhancements_doc/Enhancement-131.md));
- `klu_scale`, `klu_ordering` and `klu_btf` ([E-152](../../enhancements_doc/Enhancement-152.md));
- the stock knobs beside them: `trtol`, `reltol`, `chgtol`, `xmu`, `tmax`, `minbreak`, `itl4` and `newtrunc`.

Families A, C and E ran every deck under `.option sparse` and under `.option klu`; Family D chose
one per trial. Runs went six at a time, each with a timeout and a 2 GB RSS cap. The harnesses are throwaway scripts in the session scratchpad (`rc5/*.py`):

- **A. Linear transients against the exact solution.** 527 random networks with R, C, L and VCCSs,
  driven by PWL, SIN and PULSE sources. Unlike the second campaign's Family D, a network here has
  - nodes with no capacitance at all (eliminated by a Schur complement);
  - ideal voltage sources, so a capacitor to a source node puts u′ into the dynamics;
  - PULSE edges down to 1e-9 of the period.

  The exact solution is the matrix exponential of the reduced ODE, augmented by the sources' own
  dynamics, at ngspice's time points. It agrees with scipy's DOP853 to 8e-12. Each network ran
  with one of 45 settings and again as plain trap at the same tolerance, under both solvers:
  2 108 runs, plus a pilot of 344.
- **B. Tolerance sweeps.** The methods at reltol 1e-3 to 1e-6 on an RC and an RL, and on the
  Family A networks that stood out.
- **C. Nonlinear transients.** 440 decks from 11 templates:
  - a diode rectifier, a CMOS inverter chain and a BJT amplifier;
  - a boost converter, a charge pump and a Schmitt trigger;
  - a coupled-inductor tank, a Van der Pol oscillator from a B-source, a T-line with diode clamps;
  - a PRBS-driven RC and a B-source step into a tanh stage.

  Each ran with a random setting under both solvers and once as a tight trap reference (reltol
  1e-6): 1 320 runs.
- **D. Sessions.** 383 trials, each compared with an uninterrupted fresh run of the same options:
  - `stop when` … `delete all` … `resume`;
  - `savestate` in one process and `loadstate` in another;
  - two `tran` runs with `option` changes between them;
  - a solver switch between runs.

  A further 22 decks changed options while a run was paused.
- **E. Stress decks.** 29 decks under 10 settings and both solvers: 580 runs. They cover
  - large meshes (up to 200 × 150) and a 2 000-section RLC line;
  - a 100 000-point PWL, a near-tie PWL, vertical PWL steps and 60 overlapping pulse trains;
  - femtosecond and megasecond time scales, 1e-15 s steps and a 1e-13 s maximum step;
  - extreme element values, floating capacitor islands and inductor loops with `uic`;
  - switches between 1 µΩ and 1 PΩ.
- **F. Memory.** Guard Malloc (`/usr/lib/libgmalloc.dylib`) over 124 runs:
  - 8 decks of every method at its largest order;
  - 25 session decks (switch, sequence, resume, savestate and loadstate);
  - 69 nonlinear decks covering all 45 settings;
  - the 22 pause-and-change decks.

Nothing was fixed; this is the list.

| | Finding | Severity |
|---|---|---|
| [F1](#f1) | *(fixed in [E-873](../../enhancements_doc/Enhancement-873.md): the truncation estimate at order k ≥ 3 was (k+1)!/3! too small; scaled, the network gives 0.919 V at every `maxord`)* **transient accuracy, both solvers:** `dynorder` raises the Gear or Adams order on a stiff network until the integration is unstable, and the answer explodes with status 0 and no message. A nine-element RLC network whose node peaks at 0.919 V reaches 2.5e7 at `gear maxord=4 dynorder`, 9.2e22 at `maxord=6`, and 1.2e8 at `adams maxord=3 dynorder`. Over Family A the worst cases are 2e21×, 6e28× and 7e192× the trap error | high |
| [F2](#f2) | *(fixed in [E-874](../../enhancements_doc/Enhancement-874.md): the stages sit above the history and `maxord` is pinned to the method's order; the RC takes 388 and 165 points at 1e-6)* **transient cost, both solvers:** `trbdf2` and `sdirk` at the default `maxord=2` take ten times the points for every decade of `reltol`, the scaling of a first-order method. At `reltol=1e-6` an RC needs 580 045 and 265 117 points against trap's 512. Their truncation estimate reads an interior stage parked in the history slot of q(tₙ₋₂); at `maxord=3` (`trbdf2`) or `6` (`sdirk`) they need 388 and 121 | high |
| [F3](#f3) | *(fixed in [E-876](../../enhancements_doc/Enhancement-876.md): dynorder runs for Gear, Adams and trap only, and says it has no effect with the staged methods; the RC takes 38 points, the capacitor 16)* **transient hang, both solvers:** `dynorder` with `trbdf2` or `sdirk` freezes the step at the first step's size. The staged method resets the order every step, so `dynorder` "changes" it every step and holds the step. An RC under `trbdf2 dynorder` takes 1 391 814 points against 130. 61 runs of Families A and C never ended | high |
| [F4](#f4) | *(fixed in [E-877](../../enhancements_doc/Enhancement-877.md): the current source schedules its corners as the voltage source does; the pulse is 2.8e-4 off, as from a voltage source)* **transient accuracy, stock code:** a PULSE current source stops scheduling breakpoints once an edge is shorter than `minbreak`; every later edge is stepped over. The same pulse into the same RC is 3.0e-2 off as a current source and 2.8e-4 as a voltage source. Over the 68 Family A networks with such a source, trap's median error is 3× that of the rest | medium |
| [F5](#f5) | *(fixed in [E-878](../../enhancements_doc/Enhancement-878.md): a step that does not converge is retried from where it started; the oscillator peaks at 2.0199 V)* **transient robustness, stock code:** after one Newton iteration runs far, every retry starts from that iteration (`PREDICTOR` is off). A Van der Pol oscillator from a B-source ends in "timestep too small" under every method, solver and tolerance; clamped at ±1 kV, which changes nothing on the true path, it runs | medium |
| [F6](#f6) | *(fixed in [E-879](../../enhancements_doc/Enhancement-879.md): `loadstate` copies the method and `maxord` before the setup, and a mismatch names the order)* **checkpoint:** `loadstate` refuses every checkpoint taken with `maxord` above 2, including `trbdf2 maxord=3`, F2's workaround. It says "does not match this circuit (equations 4 vs 4, states 2 vs 2)": the check compares `maxord` against the default before the options are copied in, and the message prints the two counts that match | medium |
| [F8](#f8) | *(found while folding F2; fixed in [E-875](../../enhancements_doc/Enhancement-875.md): a time within `minbreak` of the period's end is the next period's start)* **transient accuracy, stock code:** a voltage source landed on a pulse's rise reads it, through floor((t − TD)/PER) = 3.999999999999843, as the end of the period before, and schedules the rise's end one point late. A step that goes past it skips it: `trbdf2` 21× less accurate than trap on a Family A network. A repeating PWL does the same. Under trap, corners are missed in 28 of 60 random pulses and knots in 32 of 60 repeating PWLs | medium |
| [F7](#f7) | *(fixed in [E-880](../../enhancements_doc/Enhancement-880.md): a resume, in memory or from a checkpoint, re-derived `minbreak` by the rule of a build without XSPICE, 5e6 times larger; it now takes the run's)* **checkpoint:** a `loadstate` continuation drops the end of a voltage-source edge shorter than `minbreak`, which the uninterrupted run lands on. Two Family D continuations were 17× and 55× less accurate; two more were F4's current-source chain | low |
| [D1](#d1) | *(fixed in [E-881](../../enhancements_doc/Enhancement-881.md): refused with a warning)* **options:** `xmu` outside [0, 0.5] is accepted silently: `xmu=2` turns 3.757e-7 into −2.53e-7 | low |
| [D2](#d2) | *(fixed in [E-882](../../enhancements_doc/Enhancement-882.md): refused, capped with a warning, or noted)* **options:** `ordfix=-1`, `ordfix=100` and `reltol=10` pass without a word | low |
| [D3](#d3) | *(fixed in [E-883](../../enhancements_doc/Enhancement-883.md): the warning names the value and the kept method)* **diagnostic:** an unknown `method` prints "unsupported integration method" without naming it or saying that trap runs instead | low |
| [N1](#n1)–N6 | *(N1, N2, N4, N5 and N6 fixed in [E-884](../../enhancements_doc/Enhancement-884.md) to [E-888](../../enhancements_doc/Enhancement-888.md); N3's switch edges by [E-884](../../enhancements_doc/Enhancement-884.md), its tanks documented)* notes: a switch without hysteresis at `reltol` ≤ 1e-6; `xmu` and the step control; trap on high-Q tanks; `newtrunc` compiled out; `option` during a pause; `ordfix` at orders that are not A-stable | — |

<a id="f1"></a>
## F1 — `dynorder` raises the order into instability, and the answer explodes without a word

*Fixed in [E-873](../../enhancements_doc/Enhancement-873.md). The constants in `CKTterr` are error
constants for q⁽ᵏ⁺¹⁾, and the code multiplied them by the divided difference, q⁽ᵏ⁺¹⁾/(k+1)!. trtol's 7
makes up the 3! of order 2, so at order k ≥ 3 the estimate was (k+1)!/3! too small, and `dynorder`
took the high orders for 20 to 840 times cheaper than they were. Scaled at orders 3 to 6, the
network gives a peak of 0.919 V and −0.6996 V at the end under every setting below. No Family A run
blows up.*

`dynorder` ([E-128](../../enhancements_doc/Enhancement-128.md)) picks the Gear or Adams order by
which allows the biggest step. It never asks whether that order is stable for the circuit's poles.
BDF 3 to 6 are not A-stable: an underdamped pole pair far from the negative real axis is outside
their stability wedge once the step is large. Adams-Moulton above order 2 has a bounded stability
region. E-128 states that its guards keep the higher orders "from ever wrecking the answer".

Reduced from Family A seed 1313:

```
* nine elements; every node has a dc path
v1 in 0 pwl(0 -0.6 0.697u 0.19 0.70u 0.92 1.08u -0.7)
r1 in a 13.8k
r2 a b 21.2k
l1 b c 2.32u
l2 d b 6.7u
l3 e c 0.125u
r3 f d 44.9
c1 f e 1.23p
i1 e f sin(-0.42m 0.56m 164k)
.option method=gear maxord=6 dynorder
.control
tran 9n 1.82u
let m = maximum(abs(v(c)))
print m v(c)[length(v(c))-1]
.endc
.end
```

| options | max \|v(c)\| | v(c) at the end |
|---|---|---|
| `reltol=1e-7` (trap) | 0.919 | −0.6996 |
| default (trap); `method=gear maxord=2` or `6`; `gear maxord=3 dynorder` | 0.919 | −0.6995 to −0.6996 |
| `method=gear maxord=4 dynorder` | 2.5e7 | 6.8e6 |
| `method=gear maxord=5 dynorder` | 4.3e17 (KLU), 4.6e17 (Sparse) | −3.0e17, −4.6e17 |
| `method=gear maxord=6 dynorder` | 9.2e22 (KLU), 1.3e21 (Sparse) | −9.2e22, 6.7e20 |
| `method=adams maxord=3 dynorder` | 1.2e8 (KLU), 5.9e7 (Sparse) | 4.0e7, 2.0e7 |
| `errpreset=conservative method=gear maxord=4 dynorder` | 1.6e4 | 2.3e3 |

Every run ends with status 0 and prints nothing. Tightening the tolerance makes it worse. On
seed 1338, `gear maxord=4 dynorder reltol=1e-4` ends at 1e273, and `adams maxord=3 dynorder` at
7e281. Over Family A (20 to 24 runs per setting), the error relative to the same network's trap
run reaches:

| setting | median | max |
|---|---|---|
| `method=gear maxord=3 dynorder` | 3.2× | 156× |
| `method=gear maxord=6 dynorder` | 10× | 2.0e21× |
| `method=adams maxord=4 dynorder` | 14× | 5.8e28× |
| `errpreset=conservative method=gear maxord=4 dynorder` | 62× | 6.9e192× |

On Family C's nonlinear decks, the rms deviation from the reference reaches 7e15 times the
signal's range under `gear maxord=6 dynorder` and 8e81 times under `adams maxord=4 dynorder`.
Without `dynorder`, `maxord` above 2 has no effect ([E-853](../../enhancements_doc/Enhancement-853.md)),
so plain Gear never gets there.

<a id="f2"></a>
## F2 — `trbdf2` and `sdirk` at the default `maxord` take ten times the points per decade of `reltol`

*Fixed in [E-874](../../enhancements_doc/Enhancement-874.md). A staged step rotates through slots
above the accepted history, and `maxord` is pinned to the method's order. The RC takes 38, 80, 183
and 388 points under `trbdf2` and 34, 60, 98 and 165 under `sdirk`, within 1.42 times trap's error.
`sdirk` takes more than at `maxord=6` before, because E-873 made its order-3 estimate four times
larger. With larger steps a skipped pulse corner showed: [F8](#f8).*

```
* a sine into an RC
v1 in 0 sin(0 1 100k)
r1 in out 1k
c1 out 0 1n
.option method=trbdf2
.control
tran 1u 50u 0 50u
let n = length(time)
print n
.endc
.end
```

Points to the end, by `reltol` (both solvers alike):

| method | 1e-3 | 1e-4 | 1e-5 | 1e-6 |
|---|---|---|---|---|
| trap | 53 | 117 | 246 | 512 |
| gear | 68 | 162 | 340 | 708 |
| adams, maxord=3 | 70 | 160 | 335 | 687 |
| **trbdf2** | 130 | 5 626 | 57 898 | **580 045** |
| **sdirk** | 69 | 1 308 | 26 268 | **265 117** |
| trbdf2, maxord=3 | 38 | 80 | 183 | 388 |
| sdirk, maxord=6 | 20 | 43 | 74 | 121 |

A second-order method should need √10 ≈ 3.2× more points per decade of `reltol`; trap does
(2.1 to 2.2×). `trbdf2` and `sdirk` need ten times more, the scaling of a first-order method. On an
RL the same happens. With a larger `maxord` both scale as they should, and then beat trap:
388 and 121 points against 512 at 1e-6.

The likely cause is the slot each step parks its interior stage in. Both methods rotate the state
history once per stage and splice the interior stages back out to `CKTstates[maxord+1]`, then
`CKTstates[maxord]`. The truncation estimate (`CKTterr`) reads `CKTstates[0..order+1]`. At
`maxord=2` that is `CKTstates[3]` for `trbdf2`, which holds the interior stage, not q(tₙ₋₂). `sdirk`
at order 3 needs `maxord` ≥ 5 before its two interior stages are out of reach; `maxord=4` still
fails. The estimate then compares a stage value with the old points' spacing.

The answers are over-resolved rather than wrong: on Family A, `sdirk`'s median error is 0.03× the
trap error. Most of those runs are capped by the output step at default tolerance; at
`reltol=1e-5` one network took 36 848 points under `sdirk` against trap's 241. The cost can stop a
run. A Family A network under `trbdf2 trgamma=0.8` at
`reltol=1e-7` took 5 562 161 points (51 s) where trap took 412. In Family A two such runs hit
the 60 s timeout.

<a id="f3"></a>
## F3 — `dynorder` with `trbdf2` or `sdirk` freezes the step at its first size

*Fixed in [E-876](../../enhancements_doc/Enhancement-876.md). The order selection and its
rejection-rate order drop run for Gear, Adams and trap only; with `trbdf2` or `sdirk` a note says
`dynorder` has no effect. The RC takes 38 points and the capacitor 16, as without `dynorder`; all 48
Family A runs of the two settings end, at trap's point count.*

`trbdf2` sets the order to 2 at the start of every step, and `sdirk` to 3. `dynorder` then
re-decides the order after each accepted step. When a neighbouring order allows a bigger step, it
"changes" the order, and its rule is not to grow the step in the same step that changes the order:
`newdelta = MIN(delta, bestLte)`. The staged method resets the order next step, so the change
happens every step and the step never grows.

```
* a sine into an RC
v1 in 0 sin(0 1 100k)
r1 in out 1k
c1 out 0 1n
.option method=trbdf2 dynorder
.control
tran 1u 50u 0 50u
let n = length(time)
print n
.endc
.end
```

This takes 1 391 814 points (`trbdf2` without `dynorder`: 130). A capacitor that never moves
(`r2 x 0 1k`, `c1 x 0 1n`, driven by nothing) under `method=sdirk dynorder` takes 10 002 points
where `sdirk` takes 16, every step the first step's 5 ns.

With a small first step, the run does not end:
- Family A: 36 `trbdf2`/`sdirk` + `dynorder` runs hit the 60 s timeout, under both solvers, and
  one the 2 GB cap.
- Family C: 24 hit the 90 s timeout.
- Seed 14, a 48 ns run, took 10 004 points to reach 0.2 ns, at a step of 2e-14.

<a id="f4"></a>
## F4 — a PULSE current source stops scheduling its edges once an edge is shorter than `minbreak`

*Fixed in [E-877](../../enhancements_doc/Enhancement-877.md). The PULSE case of `ISRCaccept` is
`VSRCaccept`'s, with a per-run `ISRCbreak_time`, E-875's rule and the defaults of the current
source's own load. The two sources put their points at the same times on 15 random pulses; the
pulse below is 2.8e-4 off in 381 points. On the 68 Family A networks with such a source, trap's
median error went from 5.3e-4 to 1.8e-4.*

The voltage source schedules its next corner from its own `VSRCbreak_time`, skipping a corner
closer than `minbreak` ([vsrcacct.c](../../ngspice-46/src/spicelib/devices/vsrc/vsrcacct.c)). The current source still has the
older chain ([isrcacct.c](../../ngspice-46/src/spicelib/devices/isrc/isrcacct.c), unchanged from
stock ngspice-46): a corner schedules the next one only when an accepted point lands on it
(`SAMETIME`). A rise shorter than `minbreak` cannot be landed on, so the chain stops. Every later
edge is stepped over.

```
* the same pulse as a current and as a voltage source
i1 0 b pulse(0 1m 0.7u 0.1p 0.1p 1.4u 3u)
r1 b 0 1k
c1 b 0 1n
.control
tran 0.1u 13u
.endc
.end
```

| source | points | max error vs. exact | at reltol=1e-5 |
|---|---|---|---|
| `i1 0 b pulse(0 1m …)` into 1 kΩ ∥ 1 nF | 219 | 3.0e-2 | 4.9e-3 |
| `v1 a 0 pulse(0 1 …)` through 1 kΩ into 1 nF | 381 | 2.8e-4 | 2.8e-4 |

The two decks have the same ODE. With 1 ns edges both land on every corner. With the 0.1 ps rise,
the current source lands on its corners up to the second rise. From the second fall on, the
nearest point to every edge is 17.4 ns after it. Across Family A, plain trap has a median error of
5.3e-4 on the 68 networks with such a current source and 1.6e-4 on networks with no edge under
`minbreak`. On seed 1205 (`trtol=0.1`, `reltol=1e-5`) the run is 8.8e-4 off under Sparse and
3.4e-5 under KLU, at the third edge of a 0.1 ps current pulse.

(The first version of this page put seed 1338's 31 % error at default tolerance down to this
chain. That network rings for the whole run at 408 MHz with a Q of 42, and its error falls with
`reltol`, to 1.7e-2 at 1e-5: it is N3's.)

The same chain is behind three of the five resumed runs of Family D that were more than 10× less
accurate (seeds 8, 124, 304; the other two run under `ordfix` and `trbdf2`), and two of the four
checkpoint continuations (F7): pausing the run moves its points off a corner.

<a id="f5"></a>
## F5 — one diverging Newton iteration ends the transient, under every method and solver

*Fixed in [E-878](../../enhancements_doc/Enhancement-878.md). The solution a step starts from is
kept, and a step whose iteration does not converge is retried from it. The oscillator runs under
every method and both solvers, and peaks at 2.019945 V at `reltol=1e-6`. Family C's tight
references fail in 40 cases instead of 59, none of them Van der Pol.*

```
* Van der Pol from a B-source: a bounded limit cycle, peak 2.02 V (scipy Radau, rtol 1e-9)
l1 x 0 78.66u
c1 x 0 1.113p
b1 x 0 i=0.000595*(v(x)^3/3 - v(x))
r1 x 0 1e6
.ic v(x)=0.0458
.control
tran 1.41n 0.706u uic
.endc
.end
```

At about 38 ns, at the first fast swing, it prints `b1: expression evaluated to infinity` and
then `Timestep too small; time = 3.80136e-08, timestep = 1.7625e-21: trouble with node "x"`. The
same happens under trap and Gear, Sparse and KLU, and `reltol` from 1e-3 to 1e-6. Clamping the
cubic's argument to ±1 kV (`min(max(v(x),-1e3),1e3)^3`), which changes nothing on the true path,
gives 4 059 points and a peak of 2.04 V. Clamped at ±1e10 or ±1e100 it fails as before. So it
is not the overflow: once one iteration has gone far, no smaller step recovers.

`PREDICTOR` is not compiled in. After a failed step, `DCtran` cuts the step by 8 and calls
`NIiter` again, and the B-source evaluates at `CKTrhsOld`. That still holds the failed iteration's
far-off voltage, not the last accepted solution. From 1e10 V a cubic needs about 60 Newton steps
to come back, against `itl4`'s 10, at any step size. In Family C, 17 of 40 Van der Pol references
failed this way.

<a id="f6"></a>
## F6 — `loadstate` refuses every checkpoint taken with `maxord` above 2, and says the counts match

*Fixed in [E-879](../../enhancements_doc/Enhancement-879.md). `loadstate` copies the integration
method and `maxord` from the task before it sets the circuit up, with the staged methods' pin.
Every setting below restores; a real mismatch reads "maximum order 3 vs 2".*

```
* run part of a transient and save it; then, in a fresh process, load it
v1 a 0 pulse(0 1 0 1n 1n 1u 2u)
r1 a b 1k
c1 b 0 1n
.option sparse method=gear maxord=3
.tran 10n 4u
.control
stop when time > 1.5u
run
savestate ck.bin              ; the second deck has `loadstate ck.bin` here
.endc
.end
```

```
Error: loadstate: checkpoint does not match this circuit (equations 4 vs 4, states 2 vs 2).
```

The same happens with `maxord=3` alone, `method=adams maxord=4`, and `method=trbdf2 maxord=3`,
the setting that avoids F2. `maxord=2` restores. The signature check in `com_checkpoint.c`
compares the saved `maxOrder` with `ckt->CKTmaxOrder`. At `loadstate` time that is still the
default 2: `CKTsetup` runs before `CKTdoJob` copies the task's options in.
[E-180](../../enhancements_doc/Enhancement-180.md) copied only the KLU flags across that gap. The
message names the equation and state counts, which match, and not the order, which does not. In
Family D, 34 of 96 checkpoint trials stopped here.

<a id="f7"></a>
## F7 — a checkpoint continuation drops the end of an edge shorter than `minbreak`

*Fixed in [E-880](../../enhancements_doc/Enhancement-880.md). The cause was not the checkpoint:
the continuation is the in-memory resume, point for point. `CKTdoJob` puts `minbreak`'s 0 back for
every job, and both resume branches re-derived it as tmax/20 000 where the run, under XSPICE, had
started with ten times `delmin`: 1e-12 s against 2e-18 s on these decks. All three now use the
run's rule. Every Family D resume and continuation that was more than 10× worse now matches the
uninterrupted run, except one under `ordfix=6`.*

None of the 62 `loadstate` continuations that ran was on the uninterrupted run's time grid. E-131
reports bit-identical continuations on its decks. In four of them the continuation was more than
10× less accurate than the uninterrupted run:
- seeds 69 and 321 have a PULSE current source (F4);
- seeds 45 and 213 have only voltage sources.

On those two, the continuation lands on the start of each sub-`minbreak` rise but not on its end,
which the uninterrupted run lands on:
- seed 45 (rise 82 fs, `minbreak` 0.34 ps): 0.19 against 0.011;
- seed 213 (rise 11 fs): 2.3e-2 against 4.1e-4.

The voltage source's next corner time (`VSRCbreak_time`) is not in the checkpoint. On a lone RC
the difference costs no accuracy: 374 points against 597, at 8.3e-6 both. The in-memory
`resume` is no exception. None of the 97 resumed runs was on the uninterrupted grid, because the
step lands on the `stop when` time. Five were 12 to 163× less accurate, all with a PULSE current
source whose edges are at or under `minbreak`; three of them are F4's chain.

<a id="f8"></a>
## F8 — a voltage source landed on a pulse's rise schedules the rise's end one point late

*Found while folding F2; fixed in [E-875](../../enhancements_doc/Enhancement-875.md). A time within
`minbreak` of the period's end is taken as the next period's start, for PULSE and for a repeating
PWL. No corner or knot of the 120 random decks is missed, under trap, `trbdf2` and `sdirk`.*

With F2 fixed, `trbdf2` on Family A seed 1134 was 21× less accurate than trap at `reltol=1e-7`
(7.2e-4 against 3.5e-5). It had stepped over the end of a 26 ps rise. `VSRCaccept` finds a pulse's
next corner from the time within the period, floor((t − TD)/PER). Landed on the fifth rise, that
quotient is 3.999999999999843. The point reads as the end of the fourth period, and the "next
pulse" it waits for is 3.6e-21 s away. That breakpoint is under `minbreak` and dropped, and the
rise's end is scheduled only at the next accepted point. Trap's truncation estimate usually
rejects a step across the rise; `trbdf2`'s and `sdirk`'s do not.

Trap misses corners too. On E-872 it missed them in 28 of 60 random pulses into an RC, and knots in
32 of 60 repeating PWLs with an edge at each repeat's start. The repeating PWL wraps its time the
same way, and wrapped only past its last knot, so a point landed a hair under it found no knot
ahead.

<a id="d1"></a>
## D1 — `xmu` outside [0, 0.5] is accepted, and the answer is wrong

*Fixed in [E-881](../../enhancements_doc/Enhancement-881.md): `Warning -- Option xmu = 2 must lie
in [0, 0.5]; ignored, keeping 0.5`.*

`xmu` blends trapezoidal (0.5) toward backward Euler (0). On an RC with an inductor whose answer
is 3.757e-7 at 4 µs:
- `.option xmu=-1` gives 2.58e-6;
- `.option xmu=2` gives −2.53e-7.

Neither prints anything. Every sibling tolerance is range-checked
([E-426](../../enhancements_doc/Enhancement-426.md), [E-447](../../enhancements_doc/Enhancement-447.md)).

<a id="d2"></a>
## D2 — `ordfix` and `reltol` take values that have no meaning

*Fixed in [E-882](../../enhancements_doc/Enhancement-882.md). A negative `ordfix` is refused, one
above 6 is set to 6 with a warning, and one above the method's and `maxord`'s ceiling draws a note.
`reltol` of 1 or more is refused.*

- **`ordfix`:** `ordfix=-1` is taken as off; `ordfix=7`, `100` and `1e9` are clipped to the order
  ceiling. No warning in any case.
- **`reltol`:** `reltol=1` and `reltol=10` are accepted. E-426 refuses only `reltol <= 0`.

<a id="d3"></a>
## D3 — an unknown `method` is named in neither the message nor what runs instead

*Fixed in [E-883](../../enhancements_doc/Enhancement-883.md): `Warning -- Option method = trbdf is
unknown (use trap, gear, trbdf2, sdirk or adams); ignored, keeping trap`.*

`.option method=trbdf` (a typo), `method=bdf` or `method=gear2` prints
`setAnalysisParm(options) ci_curOpt: unsupported integration method`, and the run goes on with
trap. The message names neither the value nor trap.

## Notes

<a id="n1"></a>
- **N1 — a switch without hysteresis at tight tolerance.** *(fixed in [E-884](../../enhancements_doc/Enhancement-884.md): a built-in switch lands
  on its crossing, keeping its state there, and the step after it starts at order 1; all 80 charge-pump
  and boost references end, and a switch at a 100 ns step turns over within 0.1 ns)* With `vh=0`, a switch whose control ramps
  through `vt` ends the run ("timestep too small") at `reltol` ≤ 1e-6. This happened in 35 of 40
  charge-pump references and 5 of 15 boost references. Any hysteresis cures it: `vh=0.01` passes
  at 1e-7 on every deck tried. Stock `sw` behaviour.
- **N2 — `xmu` below 0.5 and the step control.** *(fixed in [E-885](../../enhancements_doc/Enhancement-885.md): the first-order term is
  estimated too; `xmu=0` takes backward Euler's steps)* On Family A, `xmu=0` is 106× the trap error at
  the same points (median), and `xmu=0.2` up to 764×. The truncation estimate keeps trap's
  constant. Stock.
- **N3 — trap on high-Q tanks.** *(the switch edges fixed by [E-884](../../enhancements_doc/Enhancement-884.md)'s order-1 step after a
  landing: the charge pump's switch node peaks at 2.50 V; the tanks are trap's phase error at the
  default tolerance, now in the handbook)* On 51 of 402 Family A networks, plain trap at default tolerance
  is more than 1 % off. One is a 274 MHz tank with Q ≈ 130 that rings for the whole run, at 11
  points a period, ending 71 % off; `reltol=1e-7` gives 0.57 %. This is the spread the second
  campaign's Family D measured. Trap also rings at switch edges (a charge pump's switch node
  reaches 2.66 V on a 2.49 V supply), which is what `trbdf2` is for.
- **N4 — `newtrunc` is compiled out:** `Warning: Option 'newtrunc' ignored`. *([E-886](../../enhancements_doc/Enhancement-886.md): `newtrunc`
  says what is used instead, and `ltereltol`, `lteabstol` and `ltetrtol`, which said nothing, say
  they have no effect)*
- **N5 — `option` during a pause.** *(fixed in [E-887](../../enhancements_doc/Enhancement-887.md): the options read at every step are taken by
  the resumed run, the ones it was built on are kept until the next analysis, and a note names
  each. Found while fixing it: on a run started by `run`, `option maxord=3` or `option klu` before
  `resume` was a segmentation fault)* An `option` given between `stop` and `resume` has no effect on
  the resumed run, and nothing says so. Method, `maxord`, `dynorder`, solver and `reltol` all
  gave the same 1 346 iterations.
- **N6 — `ordfix` with an order that is not A-stable.** *(fixed in [E-888](../../enhancements_doc/Enhancement-888.md): an `ordfix` run says it
  has no truncation control and, at Gear or Adams 3 and above, that the order is not A-stable; a
  node past 1e15 V stops it)* `ordfix` pins the order with no truncation
  control; [E-181](../../enhancements_doc/Enhancement-181.md) calls it a verification instrument.
  On stiff networks `ordfix=3` under Adams and `ordfix=6` under Gear blow up: Family A to
  5e206×, Family C to inf. Status 0, no message.

## What was clean

- **No crash anywhere.** 5 214 harness runs and about 250 hand runs ended without a signal, an
  assertion or a memory error. The only runs that did not end were F3's, two of F2's, one `ordfix=3` Adams
  run (N6), and four switching references at `reltol=1e-6` that ran past 90 s. The 124 Guard
  Malloc runs were clean.
- **Sparse and KLU agree.** Over Family A's 1 054 deck pairs, the two solvers differ by more than
  10× in error, or 1.5× in points, only where F4 put their points on different sides of a missed
  edge, or on a run of F3. On Family C their waveforms agree within 5 % rms except on the runs
  F1 and N6 blow up. Of the 440 Family C pairs, 4 failed under one solver only, all at an order
  that is not stable.
- **Sessions:** 95 `option` sequences and 95 solver switches between runs gave exactly the fresh
  run's waveform, to the bit.
- **Error control as intended:**
  - **Presets and knobs:** `errpreset=conservative` gives 0.57× the trap error at 1.16× the
    points, and `liberal` 1.0× at 1.0× (median, Family A). `trtol=0.1` gives 0.24×, and `tmax`
    0.06× at 3.9× the points.
  - **KLU options:** `klu_scale`, `klu_ordering` and `klu_btf` change nothing.
  - **Adams 2 to 6 and Gear 2 to 6 without `dynorder`:** within 1.5× (Adams) and 4× (Gear) of
    trap.
- **Family E stress decks:** all 580 runs ended.
  - **Large networks:** the 200 × 150 mesh (30 000 nodes) ran in at most 168 s and 281 MB under
    every setting and both solvers; the 2 000-section RLC line in 5 s.
  - **Long or crowded sources:** the 100 000-point PWL and 60 overlapping pulse trains agree
    across settings to within 1.8e-3 V and 5.6e-5 V.
  - **Extreme scales:** femtosecond and megasecond time scales, teraohm and petaohm switches,
    1e-20 F, 1e3 F and 1e-15 H, 1e6 V and 1e-12 V signals.
  - **Degenerate topology:** floating islands (reported as such), inductor loops under `uic`.
  - **Clean refusals:** a 1e-15 s step ("memory required 64000003200 Bytes") and
    `tstart = tstop` ("TSTART is invalid").
  - **Expected spread:** the lossless LC over 1 500 periods ends far apart across methods, which
    is numerical damping and phase drift.
- **Option values:** 52 malformed values (`trgamma` 0, 1, nan; `maxord` 0, 7; `klu_*` unknown;
  `reltol`, `trtol`, `chgtol`, `vntol` and `itl4` at zero or below; nan) ran with a warning or a
  refusal, except D1 to D3.
