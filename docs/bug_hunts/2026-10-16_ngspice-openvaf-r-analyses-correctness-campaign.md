# Bug hunt — ngspice's analyses against independent references

**When:** 2026-10-16, after the nonlinear correctness campaign's findings were folded and released
(E-889 to E-894).
**Binary:** the repo's `ngspice-46/build/src/ngspice` and `openvaf-r` at E-894, tree at `3f873f0f`,
KLU and XSPICE compiled in. An E-888 build (worktree at `03c5b297`) served as the reference where a
result had to be told apart from E-889's change.

**Method:** the [previous campaign](2026-10-15_ngspice-openvaf-r-nonlinear-correctness-campaign.md)
checked operating points, noise, charge, temperature, `ac` at 1 Hz, `fourier`, the random
distributions and transients. This one takes the analyses it did not reach. It checks each against
a reference computed outside the analysis: the transient, numpy, or the closed-form answer. Devices
were the built-in diode, Gummel–Poon BJT, VBIC, HICUM, MOS1, BSIM3 and BSIM4. The compiled
Verilog-A models were the CMC diode, VBIC 1.3, HICUM L2, BSIM4 and PSP 103, from the corpus, built
with today's openvaf-r. The harnesses are throwaway scripts in the session scratchpad
(`rc7/fam*.py`).

- **A. `ac` and `.disto` against the transient's harmonics.** One stage around one device: a diode
  with its charges, a common-emitter stage, a common-source stage. 96 seeds over the 12 models.
  - The input carries `dc V0 ac 1 distof1 A sin(V0 A f)`, at 10 kHz to 300 MHz.
  - Python fits the harmonics of tight transients (`reltol=1e-9`) on whole settled periods, at
    three amplitude levels A, A/4 and A/16. Each level is a pair (A, A/2) extrapolated past the
    next Volterra order.
  - The fundamental per volt is compared with `ac`; the 2nd and 3rd harmonics, cosine-referenced,
    with `disto`'s `disto1` and `disto2`. The best level is taken.
  - 576 transients.
- **B. `hb` and `pss` against a long transient's steady state.** A half-wave rectifier (built-in
  and CMC diode), an antiparallel-diode clipper, an overdriven common-emitter stage, and a
  common-source stage (built-in and compiled BSIM4): 120 seeds.
  - The transient is fitted with 60 harmonics.
  - `hb` runs at K = 16 and 48; harmonics 0 to 6 are compared.
  - `pss`'s period is compared point by point with the transient at the same phase.
- **C. `.sp` against the network's own S-parameters.** Random R, L, C and VCCS networks with one to
  four ports at unequal reference impedances: 300 networks × 2 solvers. Python folds the internal
  nodes out of the nodal admittance and forms the power-wave S matrix. It also checks Y and Z; and,
  for the passive networks, `Cy` against Twiss's theorem 2kT(Y + Yᴴ) and NF against the IEEE
  definition.
- **D. Transient noise against its spectrum.** `trnoise` sources: their samples, waveform variance
  and Welch PSD, then through an RC. A Verilog-A resistor with `white_noise(4kT/R)` (E-364's
  injection), paired with a `trnoise` current source of the same amplitude. 40 + 30 seeds.
- **E. `dc` sweep points against fresh operating points.** The previous campaign's random networks,
  built-in and twin: 200 runs. Sweeps were forward, reversed, nested in a second source, `dc temp`,
  and after a `tran`. Every point was re-solved from scratch with `alter` and `op`.
- **F. The vector functions against numpy.** Random real and complex vectors built with `compose`,
  through 33 functions: `mag`, `ph`, `cph`, `unwrap`, `db`, `log10`, `ln`, `exp`, `sqrt`, the trig
  and hyperbolic functions, `norm`, `mean`, `stddev`, `avg`, `vecmin`, `vecmax`, `floor`, `ceil`,
  `nint`, `pos` and `sortorder`. Then `fft` with all nine windows, and `integ`, on a transient that
  reproduces random samples exactly. 200 + 200 runs.
- **G. Transmission lines against the telegrapher's equations.** A source, a series resistance, one
  line and a load. The lines were `T`, `O` (LTRA: RLC, RC and LC), `U` (URC), `P` (CPL, one
  conductor) and `Y` (TXL): 70 seeds. `ac` at five frequencies, and a sine transient's steady-state
  fundamental, were compared with the exact two-port Y₁₁ = coth(γl)/Z_c, Y₁₂ = −csch(γl)/Z_c.

| | Finding | Severity |
|---|---|---|
| [F1](#f1) | **regression (E-889):** the device convergence tests demanded more than the solve can resolve. At `reltol=1e-9` a Gummel–Poon stage's transient ended "Timestep too small", and a compiled VBIC's operating point needed 1,359 iterations of gmin stepping under KLU; E-888 ran both, the VBIC in 71 plain iterations. *(fixed in [E-895](../../enhancements_doc/Enhancement-895.md))* | high |
| [F2](#f2) | **small-signal:** the built-in HICUM's Jacobian disagrees with its own currents: `ac` at 1 Hz is 2.1 % off the dc finite difference when `t0` is 0 (its default), 0.1 % with `rbi0` > 0; `noise`, `pz` and `.sp` stamp the same matrix | high |
| [F3](#f3) | **distortion:** `.disto` returns exact zeros for every device without a distortion routine (BSIM2 to 4, the SOI models, HiSIM, VBIC, HICUM, …), without a word: a BSIM4 stage reports no distortion at all | high |
| [F4](#f4) | **distortion:** the built-in BJT's `.disto` is wrong with base resistance `rb` (2nd harmonic 45 % off, at 1 kHz too) and with reverse transit time `tr` (74 % at 10 MHz) | high |
| [F5](#f5) | **transmission line:** TXL has no AC model and acts as one without saying so: its input sees the characteristic impedance to ground, and nothing reaches the output | high |
| [F6](#f6) | **command:** `compose v values 1 -2 3` makes [−1, 3]: a negative value is subtracted from the one before it, without a word | medium |
| [F7](#f7) | **RF:** `.sp` normalises NF, NFmin and Rn by the circuit's temperature instead of the standard 290 K: at 27 °C a passive two-port's NF reads 0.149 dB low | medium |
| [F8](#f8) | **steady state:** `hb` gives up on 5 of 20 overdriven BJT stages, its source stepping stalled with the residual already at 1e-10; under Sparse it takes 450 s to give up, under KLU 3 s | medium |
| [F9](#f9) | **transmission line:** TXL's and CPL's transients are up to 6 % off the exact lossy line, and a smaller step does not reduce it; LTRA is within 5e-4 on the same lines | medium |
| [D1](#d1) | `ac` with a CPL line aborts with "ac simulation(s) aborted" and no reason | low |
| [D2](#d2) | `.sp` prints NF = nan for a two-port with no transmission, where it is infinite | low |
| [D3](#d3) | `fft` prints the frequency resolution of the unpadded data, twice the spacing of the bins it returns | low |
| [N1](#n1)–N3 | notes: URC is a lumped approximation (2.4 % off above its RC corner); `hb` of a hard clipper needs few harmonics to converge; `ln` refuses a negative argument that `sqrt` takes to the complex plane | — |

<a id="f1"></a>
## F1 — E-889's device tests demanded more than the solve can resolve

*(fixed in [E-895](../../enhancements_doc/Enhancement-895.md): the device tests count a step no
larger than the node test's absolute tolerance, or than the rounding at the circuit's scale, as no
step; a Verilog-A row is granted the rounding of the terms it sums; convtest [10] to [12])*

E-889 made the device convergence tests decide. They see the new solution with every unknown
that moved by no more than its rounding held at the load point. That rounding was measured on the
unknown's own value. At tight tolerance, this asked a device for a current change smaller than the
solve can resolve:

- **A Gummel–Poon common-emitter stage** at `reltol=1e-9` (Family A seed 2).
  - The emitter, at 20 mV in a 5.8 V circuit, moved 1.55e-15 V each iteration: 350 of its own ulps,
    but rounding at the circuit's volts.
  - The base current's conductance at that step holds the capacitive companion C/h: 38 S at
    t = 50 fs. It turned the move into 16 times the base current's tolerance.
  - Newton never converged, the step shrank to 6e-24 s, and the run ended "Timestep too small" at
    t = 0.78 ps (KLU; 0.057 ps under Sparse).
  - E-888 ran it to the end (53 008 points).
- **A compiled VBIC's operating point** at `reltol=1e-9` (seed 4). On macOS under KLU, E-894 reached
  it only through dynamic gmin stepping, in 1,359 iterations; E-888 converged in 71 without an aid.
  Under Sparse every build takes the aid: E-888 1,913 iterations, E-894 2,758. Plain Newton on this
  deck is path-dependent, so the route varies with rounding: E-888 itself takes the aid in 3 of 80
  runs with the element values perturbed by 1e-15 to 1e-9. Three rows failed:
  - an internal base node bouncing 6e-14 V through `rbx`'s 0.1 S;
  - the thermal row (watts), judged against the user's `abstol` of 1e-15, which is a current;
  - the internal collector, tied by 1000 S to two nodes. A common step of 1e-10 V left 1e-12 A of
    rounding in the differences, against a tolerance of 4.5e-13 A.

**The fix:**
- **`NIconvTest`:** an unknown has not moved when it moved by no more than the node test's absolute
  tolerance for it (`vntol`, `abstol` or its nature's), or 64 ε of the largest unknown of its kind.
- **`OSDIconvTest`:** a residual of a nature other than the terminals' keeps its nature's `abstol`.
  A row is also granted the rounding of the terms it sums, 64 ε of Σ|J|·s.

**Results with the fix:**
- Seed 2 runs to the end, with E-888's 53 008 points.
- The VBIC converges in 71 iterations under KLU, to E-888's value; under Sparse in E-888's 1,913.
- On the previous campaign's 500 networks against E-894: all solve; 27 runs take fewer iterations,
  none more.
- `convtest` (E-889's F1 cases, and [10] to [12] for these two and a control) and the
  Newton-sensitive suites pass; the full sweep is 591 of 591.

<a id="f2"></a>
## F2 — the built-in HICUM's Jacobian disagrees with its currents

At 1 Hz, `ac` should give the derivative of the dc solution. In Family A seed 5 (a common-emitter
stage, built-in HICUM, `level=8`), the collector's `ac` gain is −41.2271. The finite difference of
two operating points ±1 µV apart is −41.2649: 9.2e-4 apart. The compiled HICUM L2, with the same
parameters, agrees with its own finite difference to 1e-8, and its dc gain matches the built-in's.

| model card | `ac` against the dc finite difference |
|---|---|
| `c10 qp0` only | 2.1 % |
| `+ t0=1e-12` | 1.6e-10 |
| `+ cjei0 cjci0 t0` | 3.9e-11 |
| `+ … t0 rbi0=10` | 1.0e-3 |
| `+ … t0 re rcx rbx` | < 1e-9 |

So `t0` = 0 (the default) and `rbi0` > 0 each leave a term out of the conductances the model
stamps. The transient is unaffected: Newton converges on the currents. `ac` was measured; `noise`,
`pz` and `.sp` stamp the same matrix and inherit it by construction. Family A: 5 of 8 built-in HICUM
seeds were off by 2.3e-5 to 1.7e-3, where every other model was within 3.4e-6.

<a id="f3"></a>
## F3 — `.disto` treats a device without a distortion routine as linear

```
v(d) = 0.000000000000000e+00,0.000000000000000e+00      (BSIM3 stage, disto1 and disto2)
```

Only some built-in devices have a distortion routine: the diode, BJT, JFET, MESFET, MOS levels
1 to 3 and 9, VDMOS and BSIM1. Compiled Verilog-A devices have one since E-352. Every other
nonlinear device contributes nothing to `.disto`: BSIM2 to BSIM4, the SOI models, HiSIM, VBIC,
HICUM and the rest. Nothing is printed. A stage whose only nonlinearity is a BSIM4 transistor
reports a distortion of exactly 0. In a mixed circuit, the result silently omits those devices.

<a id="f4"></a>
## F4 — the built-in BJT's `.disto` with base resistance or reverse transit time

Family A seeds 110, 134 and 170 (Gummel–Poon common-emitter stages). Their transient harmonics agree
to five digits at all three amplitude levels; `disto` does not:

| seed 134 at 1 kHz | 2nd harmonic of v(c) per V² |
|---|---|
| `disto` | 1.1941 |
| transient | 0.8228 |
| `disto`, `rb=0` | 0.8047 = transient |

| seed 110 (`rb=0`, `tr=7.8 ns`) | `disto` error, 2nd harmonic |
|---|---|
| 1 kHz | 1.2e-4 |
| 1 MHz | 12 % |
| 10 MHz | 74 % |
| any, `tr=0` | 3e-7 |

So the base resistance's internal node is mishandled at every frequency, and the reverse transit
time's charge as frequency rises. The 3rd harmonic is off by 100 % to 160 % in the same seeds. The
diode, MOS1 and the compiled models were right: 2nd harmonic within 1e-4, and 3rd within the
transient's own precision.

<a id="f5"></a>
## F5 — TXL has no AC model and behaves as one

```
y1 a 0 b 0 ym
.model ym txl r=5.75 l=1.088e-7 g=0 c=1.398e-11 length=0.0953
```

`ac` gives v(a) = 0.22476 and v(b) = 1.9e-12. v(a) is what a 304 Ω source sees into 88.2 Ω, and
88.2 Ω is the line's √(L/C). The input is terminated in Z_c, and nothing is transmitted. The exact
line passes most of the signal: all 10 seeds were off by 100 % to 820 %. The transient works (see
F9). Nothing says the AC model is a stub.

<a id="f6"></a>
## F6 — `compose … values` subtracts a negative value from the one before it

```
compose a1 values 1 -2 3        -> [-1, 3]
compose a3 values 1, -2, 3      -> [-1, 3]
compose a2 values 1 (-2) 3      -> [1, -2, 3]
```

The values are parsed as one expression list, and `1 -2` is the expression 1 − 2. A vector of
random values in [−5, 5] came out with 8 elements instead of 11, its values sums of neighbours.
Nothing is printed.

<a id="f7"></a>
## F7 — `.sp`'s noise figure uses the circuit's temperature as the reference

`span.c` normalises the noise correlation matrix by 4k·`CKTtemp`. The IEEE noise figure is defined
with the source at T₀ = 290 K. A passive two-port at physical temperature T has
F = 1 + (T/T₀)(1/G_a − 1). ngspice computes 1/G_a, which holds only at T = T₀.

- A 100 Ω/100 Ω attenuator between 50 Ω ports: NF 8.7506 dB, against 8.8805 dB.
- 110 passive two-ports: 0.149 dB low where their own noise dominates, the asymptote being
  10·log₁₀(300.15/290), and 0.009 dB at the smallest.
- Rn reads 3.5 % low.

`Cy` itself is right: within 2.5e-12 of 2kT(Y + Yᴴ) in 420 passive runs.

<a id="f8"></a>
## F8 — `hb` gives up on overdriven BJT stages, slowly under Sparse

Five of Family B's 20 overdriven common-emitter stages failed at K = 48, and some at K = 16:

```
HB: source stepping stalled at lambda=0.8726 (|F|=1.084e-10); the circuit may be singular or have no periodic steady state at this drive.
hb: harmonic balance did not complete (error 103).
```

The transient settles to a periodic steady state, and `pss` finds it within 1.3e-4. The residual at
the stall is already 1e-10. Under Sparse the same failure took 450 s; under KLU, 3 s. When `hb`
converges, both take 0.2 s.

<a id="f9"></a>
## F9 — TXL's and CPL's transients on a lossy line

The fundamental of a sine transient against the exact line at that frequency:

| line | R·len/Z_c | T/400 | T/2000 | T/8000 |
|---|---|---|---|---|
| TXL, seed 167 | 0.22 | 6.01e-2 | 5.96e-2 | 5.96e-2 |
| TXL, seed 132 | 0.10 | 2.9e-3 | 2.3e-3 | 2.1e-3 |
| CPL, seed 117 | 0.017 | 6.0e-2 | | |

The error does not fall with the step. It is the approximation of the line. LTRA on the same kind
of lines is within 5e-4; T and the LC LTRA within 1e-6. TXL's error grows with the line's loss;
CPL's appeared on an electrically short line (ωt_d = 0.015). Neither model states the limit.

<a id="d1"></a>
## D1 — `ac` with a CPL line aborts without a reason

`ac` prints "ac simulation(s) aborted", and every vector is missing. CPL has no AC model; nothing
says so.

<a id="d2"></a>
## D2 — NF = nan for a two-port with no transmission

With y₂₁ = 0, `Rn = Cy₂₂/|y₂₁|²` divides by zero, and NF, NFmin and SOpt print nan in 16 runs. The
noise figure of a two-port with no transmission is infinite.

<a id="d3"></a>
## D3 — `fft`'s printed resolution

`fft` zero-pads to the next power of two (1025 samples to 2048) and returns bins `length/(N·span)`
apart: 62.5 Hz for an 8 ms record. It prints "Frequency resolution: 124.878 Hz", the unpadded
1/span. The returned values are right (see below).

## Notes

<a id="n1"></a>
- **N1 — URC is a lumped approximation.** `ac` with a URC line is within 2e-5 of the exact
  distributed RC line well below its corner 1/(2πRC), and 3.6 % off at 14 times above it. That is
  its `k`-segment approximation.
- **N2 — `hb` of a hard clipper.** A 2.9 V sine through 130 Ω into antiparallel diodes converges at
  K = 16 and not at K = 48 (error 103, said).
- **N3 — `ln` of a negative real** is refused ("argument out of range for log"), while `sqrt` of
  one returns a complex result.

## What was clean

- **`ac`**, for 11 of 12 models (all but F2's HICUM), is within 3.4e-6 of the transient's
  extrapolated fundamental (best level). Models: diode, CMC diode, Gummel–Poon, VBIC built-in and
  compiled, HICUM compiled, MOS1, BSIM3, BSIM4 built-in and compiled, and PSP 103, from 10 kHz to
  300 MHz.
- **`.disto`** of the diode, the CMC diode, MOS1, and the compiled BSIM4, PSP 103 and HICUM: 2nd
  harmonic within 1e-4 of the transient, 3rd within the transient's own precision.
- **`hb`** at K = 48 within 1e-4 of the transient's harmonics where it converges. **`pss`**: one
  period within 6e-5 of the transient at the same phase, one compiled-diode rectifier at 1.1e-3.
- **`.sp`:** S within 2e-11 of the power-wave reference over 600 runs, one to four ports, unequal
  z₀; Y and Z within 3e-11; `Cy` = 2kT(Y + Yᴴ) for passive networks.
- **Transient noise:** a `trnoise` source's samples have variance NA², its waveform interpolates
  them linearly (variance 2/3·NA²), and its PSD is 2·NA²·NT·sinc⁴(f·NT) to 1 %. A Verilog-A
  `white_noise(4kT/R)` in a transient gives 4kTR across a capacitor: 0.996 ± 0.005. Its node
  variance is 0.995 ± 0.003 of the sinc⁴-shaped kT/C, the same as the `trnoise` reference.
- **`dc` sweeps:** in 200 runs every point matched a fresh operating point within 2.3e-4 of a
  1e-6 tolerance. Sweeps were forward, reversed, nested, `temp`, and after a `tran`.
- **The vector functions:** 33 functions within 1e-12 of numpy. `fft` with every window matched
  numpy's FFT with the same window, padding and scaling; `integ` the trapezoid sum.
- **Transmission lines:** T and LTRA `ac` within 4e-12 of the exact line; transients within 5e-4.
