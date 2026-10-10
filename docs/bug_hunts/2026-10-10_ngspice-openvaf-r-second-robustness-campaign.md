# Bug hunt — ngspice and openvaf-r: a second robustness and correctness campaign

**When:** 2026-10-10, after the [first campaign](2026-10-10_ngspice-openvaf-r-robustness-and-correctness-campaign.md)
was folded (E-836 to E-844).
**Binaries:** the repo's `ngspice-46/build/src/ngspice` and
`OpenVAF-master-20260610/target/opt/openvaf-r`, both at E-844. Tree at `b56b5ea9`.

**Method:** six new families of generated checks, none repeating the first campaign's. They
ran one compile or simulation at a time under a 12 GB RSS cap, through throwaway harnesses in
the session scratchpad (`rc2/*.py`). Each checks against a reference that shares no code with
the thing under test:

- **A. Verilog-A semantics against a Python reference.** 400 modules of 8 random expressions
  each, over real and integer operands, compiled three ways:
  - operands as literals, which the compiler may fold;
  - as model-card parameters, which go through setup code;
  - with the real operands as node voltages, which go through the eval function.

  Every expression drives `V(o) <+ expr` on its own port, and the op solution is printed to 17
  digits. The reference follows the LRM:
  - integer `/` truncates and `%` takes the dividend's sign;
  - integers are 32-bit, with `>>` logical and `>>>` arithmetic;
  - `~^` is bitwise;
  - real-to-integer assignment rounds half away from zero.

  A node route holds its input at 0 V and adds the value, so Newton's zero start is the
  solution and no domain is crossed on the way. That makes 9 528 comparisons.
- **B. Random-expression derivatives against the reference.** 400 modules with two terminals,
  `I(a,c) <+ f1 + ddt(q1)` and `I(b,c) <+ f2 + ddt(q2)` of random expressions of both branch
  voltages, at a random bias. The ac admittance at ω = 1 rad/s gives G + jC directly. It is
  compared with Richardson-extrapolated central differences of the same expressions, and the
  op currents with their values: 4 000 checks.
- **C. `.measure` against a recomputation.** 300 decks of PWL, SIN and RC-filtered nodes with
  12 random measurements each: AVG, RMS, INTEG, MIN, MAX, PP, FIND AT, WHEN with RISE, FALL,
  CROSS and TD, FIND..WHEN, and TRIG/TARG. Each is recomputed from the samples `wrdata`
  exports: 3 600 measurements.
- **D. Transient of random linear networks against the exact solution.** 300 RC and RCL
  networks with a capacitor from every node to ground, driven by PWL and SIN current sources.
  The exact solution is the matrix exponential of the network augmented with the sources' own
  dynamics, evaluated at ngspice's time points. Each runs at default and at tight tolerances,
  under trap, gear 2 or gear 6, from the op or from `.ic` with `uic`: 584 runs.
- **E. Noise against Johnson–Nyquist.** 300 random R, C, L networks; 8 400 frequency points.
  Resistors run at the circuit temperature, `temp=` or `dtemp=`, some with `noisy=0`, and some
  are OSDI resistors with `white_noise(4kT/R)`. The reference is my own MNA:
  S = Σ 4kT/R·|Z_out,R|², and the input-referred noise is S/|H|².
- **F. Memory growth of repeated commands.** 17 scenarios repeated 400 to 4 000 times in a
  control loop, read by `rusage space`: op, tran, ac, noise, dc, sens, tf, pz, alter, reset,
  meas, let, and OSDI op, tran, noise, altermod and reset.

Nothing was fixed; this is the list.

| | Finding | Severity |
|---|---|---|
| [F1](#f1) | **compiler, wrong value:** a ternary or `==`/`!=` with a logical operand and an integer operand turns the integer into 0 or 1. For `n` = 5, `(n > 0) ? n : (n < 0)` is 1 and `n == (n > 0)` is 1 | high |
| [F2](#f2) | **transient accuracy:** the first time step is accepted without a truncation check. At `reltol=1e-7` the first samples are off by 21 % to 32 % when the input moves at t = 0 or a `uic` start is far from equilibrium | medium |
| [F3](#f3) | **transient failure:** a 7-element linear L–C network fails with "Timestep too small" right after the first step at `reltol` ≤ 1e-6; it runs at the defaults and at 1e-5 | medium |
| [F4](#f4) | **measure:** AVG, INTEG and RMS with `from=` drop the first sample inside the window. E-302's start interpolation overwrites it; the error is 3e-4 on a triangle and up to 5 % on a sampled waveform | medium |
| [F5](#f5) | **measure:** WHEN and FIND..WHEN with `td=` skip the first sample interval after TD. A single crossing there makes the measurement fail | medium |
| [F6](#f6) | **noise:** `inoise_spectrum` is wrong wherever the gain is below 1e-10. The gain squared is floored at 1e-20 with no note: 16 times low at 1 Hz through 1 fF | low |
| [F7](#f7) | **measure:** the `meas` command's result keeps 7 significant digits, a `%e` round trip through `let`; a `.meas` card's keeps 16 (E-802). `val=<vector>` is substituted the same way | low |
| [F8](#f8) | **uic:** a `uic` transient has no t = 0 sample, so the `.ic` state is never output | low |
| [F9](#f9) | **diagnostic:** `.option method=gear maxord=6` without `dynorder` is identical to `maxord=2`, and nothing says so | low |
| [F10](#f10) | **diagnostic:** an OSDI device that loads a non-finite value at Newton's start (`ln(V(x))` at 0 V) ends the op with "cause unrecorded" and names nothing; a B-source `ln()` converges | low |
| [F11](#f11) | **measure, consistency:** AVG integrates by trapezoids and INTEG by Simpson's rules, so INTEG/(to−from) and AVG disagree on the same window, by 2e-3 on a sampled sine. E-302 calls them the same quantity | low |

<a id="f1"></a>
## F1 — a ternary or an equality with a logical operand collapses the integer

```verilog
`include "disciplines.vams"
module g1(o1, o2, o3, o4, o5);
inout o1, o2, o3, o4, o5; electrical o1, o2, o3, o4, o5;
parameter integer n = 5;
analog begin
  V(o1) <+ ((n > 0) ? n : (n < 0));    // 5     -- openvaf-r: 1
  V(o2) <+ (n == (n > 0));             // 0     -- openvaf-r: 1
  V(o3) <+ (n != (n > 0));             // 1     -- openvaf-r: 0
  V(o4) <+ ((n > 0) ? n : 0);          // 5 (control)
  V(o5) <+ ((n > 0) + n);              // 6 (control)
end
endmodule
```

The value is silently wrong, with exit 0. It is the same whether the operands are literals,
parameters or node voltages.

The compiler types a relational or logical result as `Bool`. An operator's overloads are tried
in table order, and the first whose arguments all convert wins. `Integer` converts implicitly
to `Bool`, and two tables list the `Bool` signature first:
- `SELECT`, for `?:`, is `[BOOL_BIN_OP, REAL_BIN_OP, INT_BIN_OP, STR_BIN_OP]`;
- `ANY_COMPARISON`, for `==` and `!=`, starts with `BOOL_COMPARISON`.

So `int ? : bool` and `int == bool` resolve to `Bool`, and the integer is cast to 0 or 1. The
LRM's logical and relational operators yield the integer 1 or 0, so the integer must win:
`Type::union` already says `Bool ∪ Integer = Integer`. Arithmetic, bitwise and relational
operators list `INT` first and are unaffected. Of the campaign's 16 Family A mismatches, all 16
were this. The 5 of Family B were too, through `(4 << 2) == (100 && 13)` and the like in a
charge's ternary.

Noticed in passing: `Type::union`'s array branch reads `self.base_type()` twice and never
`other`'s. That is latent, since no signature table unions arrays of different base types.

<a id="f2"></a>
## F2 — the first time step is never checked

```spice
* from the op: a sine into a 1 ns RC
i1 0 1 sin(0 1m 100meg)
r1 1 0 1k
c1 1 0 1p
.option reltol=1e-7
.tran 1u 10u
```

The first step is min(tstop/100, tstep)/100 = 1 ns here, a whole time constant. It is taken by
backward Euler and accepted unchecked; `dctran.c` says "no check on first time
point". `v(1)` at 1 ns is 0.2939, while the exact value is 0.2227: 32 % high at `reltol=1e-7`.
The error then decays with the circuit.

With `uic` it is worse, because the start is far from equilibrium. The same RC charged by 1 mA
from `.ic v(1)=0` gives 0.500 at 1 ns against the exact 0.632, 21 % low.

In Family D, 42 runs had a first-step error above the limit, all of them `uic` starts. Tight
tolerances do not help, since the first step does not depend on them: seed 6 is 2.8 % off at
`reltol=1e-7` with 16 458 points.
A PWL source with a breakpoint close to t = 0 hides it, because the breakpoint limits the step.
The behaviour is SPICE3's and upstream ngspice-46's.

<a id="f3"></a>
## F3 — a linear L–C network fails "Timestep too small" at reltol 1e-6

```spice
r9 5 0 2285.405580218766
r10 1 8 757.4759645133245
l17 3 1 5.58612830132151e-07
c18 5 1 2.914119347771001e-12
c19 6 3 2.4794844806727606e-12
l20 0 6 2.3225052696110058e-05
l23 8 6 1.7832400428838883e-06
i0 0 1 sin(0.0002786245656298781 -0.00037963181379056766 929399.7948612613)
.option reltol=1e-6
.tran 5.3798161218083645e-08 1.0759632243616729e-05
```

The first step is 538 ps, and the second drops to 47 fs. From there the steps shrink
geometrically, and the run ends at `time = 5.38121e-10, timestep = ...: cause unrecorded`. It
fails at `reltol` 1e-6 and 1e-7, with or without `chgtol`, under trap or gear, and with
`abstol=1e-9`. It runs at `reltol=1e-5` (613 points) and at the defaults (217 points).

The deck was reduced from Family D seed 322: elements were removed one at a time for as long
as the collapse stayed and every node kept a dc path. 7 of the 300 Family D trials failed this
way at tight tolerances, and every one had inductors. A first look suspected `CKTterr`'s
`abstol`, a current, used as the floor of an inductor's flux tolerance, where it acts as a
voltage. Raising `abstol` cured the unreduced deck but not this one, so the cause is not
isolated. Upstream ngspice-46 was not checked.

<a id="f4"></a>
## F4 — AVG, INTEG and RMS with `from=` drop the first sample in the window

```spice
v1 1 0 pwl(0 0 1u 1 2u 0)
r1 1 0 1k
.meas tran a1 avg v(1) from=0.97u to=1.5u
.meas tran i1 integ v(1) from=0.97u to=1.5u
.tran 0.1u 2u
```

The first sample inside the window is the corner at 1 µs. `a1` = 0.7630755 and
`i1` = 4.04430e-7, where the waveform's own values are 0.7633019 and 4.04550e-7. Without
`from=`, both are exact.

E-302 made AVG start at exactly `from` by interpolating there. It does so by overwriting the
first in-window sample's value and time, so that sample never enters the sum. The trapezoid
runs from `from` straight to the second sample. `measure_rms_integral` does the same for INTEG
and RMS. In Family C a model of that arithmetic, with F11's quadrature, reproduces every
flagged AVG, INTEG and RMS to 1e-9; the AVG above it matches to 6e-17. The 96 windowed AVGs
that flagged were off by up to 4.8 %.

<a id="f5"></a>
## F5 — WHEN with `td=` skips the first interval after TD

```spice
v1 1 0 pwl(0 0 1u 1)
r1 1 0 1k
.meas tran w0 when v(1)=0.55 rise=1
.meas tran w1 when v(1)=0.55 rise=1 td=0.45u
.meas tran w2 when v(1)=0.55 rise=1 td=0.35u
.tran 0.1u 1u 0 0.1u
```

`w0` and `w2` are 0.55 µs, but `w1` fails "out of interval". The only crossing lies between
the first two samples after TD, at 0.5024 µs and 0.6024 µs. `com_measure_when` uses the first
sample only to remember a value, and the second to classify the section, without counting a
crossing. E-418 did that because, without TD, the first interval runs from the operating point.
After TD it lies between two real samples, and a crossing there is lost: with several
crossings, the next one is reported instead. Family C found two, among them `when v(c)=0.341
fall=1 td=0.465`, which reported 0.614 where the samples cross at 0.477.

<a id="f6"></a>
## F6 — inoise is floored where the gain is below 1e-10

```spice
v1 in 0 dc 0 ac 1
c1 in out 1f
r1 out 0 1k
.control
noise v(out) v1 lin 3 1 100
```

At 1 Hz the gain is 2π·1·1e-15·1e3 = 6.3e-12. `inoise_spectrum` = 40.7 V/√Hz, where
`onoise`/|gain| = 648. `noisean.c` computes `1/MAX(gain², N_MINGAIN)` with `N_MINGAIN` = 1e-20,
and says nothing. 3 of Family E's 300 networks hit it: an output coupled to the input only
through a small capacitor, at low frequency. `dcpss.c` uses the same floor.

<a id="f7"></a>
## F7 — the `meas` command keeps 7 digits

```spice
v1 1 0 sin(0 1 1meg)
r1 1 0 1k
.meas tran card find v(1) at=0.123456789u
.tran 1n 1u
.control
set numdgt=17
run
meas tran cmd find v(1) at=0.123456789u
print card cmd
```

`card` = 0.700215328413115, and `cmd` = 0.7002153. `com_meas` stores its result with
`let name = %e`, and E-802 gave `.meas` cards `%.15e`. A vector named in `val=`, `at=` and the
like is substituted into the line with `%e` too. Seven digits do not hold the difference of
two nearby measured times.

<a id="f8"></a>
## F8 — a `uic` transient has no t = 0 sample

The deck in F2 with `uic` starts at `time[0]` = 1 ns. Without `uic`, `time[0]` = 0 and
`v(1)[0]` is the op. `dctran.c` dumps a point under `uic` only for `CKTtime > 0`, so the `.ic`
state, the waveform's initial value, is never output. `meas` and `fourier` over such a run
start at the first step. This is upstream's condition.

<a id="f9"></a>
## F9 — `maxord` above 2 does nothing without `dynorder`

| options | points | final value |
|---|---|---|
| `method=gear maxord=2` | 3 390 | 5.711600823213e-3 |
| `method=gear maxord=6` | 3 390 | 5.711600823213e-3 |
| `method=gear maxord=6 dynorder` | 2 027 | 5.711291075241e-3, highest order used 6 |

The stock order control only toggles between 1 and 2; Enhancement-128's `dynorder` and
Enhancement-181's `ordfix` are the ways above 2. `maxord` is still accepted up to 6 and range
checked, with no note that it has no effect. In Family D, gear 2 to gear 6 gave identical
results to the last digit on every network.

<a id="f10"></a>
## F10 — an OSDI device's non-finite load is not named

```verilog
`include "disciplines.vams"
module q(x, o); inout x, o; electrical x, o;
analog V(o) <+ ln(V(x));
endmodule
```

With `vx x 0 1.056`, Newton's zero start evaluates ln(0) = −∞ and an infinite derivative.
Every homotopy restarts from the same point, and the op ends `Timestep too small; cause
unrecorded`, naming neither the device nor the non-finite value. A B-source `v=ln(v(x))`
converges, since ngspice's own `ln()` is guarded. The model is at fault, but the user is not
told which one.

<a id="f11"></a>
## F11 — AVG and INTEG integrate differently

AVG integrates by trapezoids. INTEG and RMS use Simpson's 3/8 or 1/3 rule on runs of equal
steps, and trapezoids elsewhere. So INTEG/(to−from) and AVG over the same window differ: by
2.1e-3 on Family C seed 1005's sampled sine, where INTEG is closer to the analytic integral,
and the other way round across a PWL corner. E-302 calls them "the same quantity". One rule for
both would make them agree; for smooth data Simpson's is the better of the two.

## Verified clean

- **A, semantics:** 9 528 comparisons. Every mismatch, 16 expressions, was F1.
  - Correct: `+ - * /`, integer `/` and `%` with negative operands, `& | ^ ~^ ~`, the four
    shifts, `! && ||`, and the six comparisons;
  - `min`, `max` and `abs` on both types, integer `**` with negative bases, real `pow` and
    `**`;
  - `sqrt`, `exp`, `ln`, `log`, the trig, hyperbolic and inverse functions, `atan2`,
    `hypot`, `floor` and `ceil`;
  - real-to-integer rounding;
  - mixed promotion;
  - literal parsing to the last bit.

  The three routes always agreed with each other.
- **B, derivatives:** 4 000 checks. Every mismatch, 5 in 3 modules, was F1. Conductances,
  capacitances (`ddt`) and dc currents agree with the extrapolated differences to 1e-6.
- **C, measure:** after F4 and F11 are modelled, every one of the 3 600 measurements but F5's
  two agrees to 1e-9, and the 447 with no crossing in the samples were refused by ngspice
  too. That covers FIND AT, WHEN, FIND..WHEN without TD, TRIG/TARG, and MIN, MAX and PP.
  MIN, MAX and PP use only the samples inside the window, by design (E-302's "whole-sample
  semantics"); they do not include the interpolated window edges.
- **D, transient:** away from F2, F3 and F8, tight runs are within 3e-4 at the 90th
  percentile, with a median of 4e-5. Default-tolerance errors of 1 % to 14 % on picofarad
  networks come from `chgtol` = 1e-14 C, which is about 14 % of their charges with `trtol` =
  7. That is SPICE's default, not a defect.
- **E, noise:** 8 400 points, all within 1e-6 or ε·κ of the reference, except F6. That holds
  for `temp=`, `dtemp=` and `noisy=0` resistors, and for OSDI `white_noise` with the same
  Boltzmann constant. In the pilot, one network with condition 1.7e12 differed by 3e-6. numpy agrees with an
  exact rational solve to 1e-7, so that is the double-precision solve, not the noise.
- **F, memory:** nothing above 125 B per iteration over 4 000 iterations (`sens`; `tf` 57,
  `reset; op` 16, OSDI `op` 0).
