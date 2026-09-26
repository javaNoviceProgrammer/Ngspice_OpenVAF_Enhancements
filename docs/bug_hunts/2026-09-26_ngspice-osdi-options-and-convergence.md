# Bug hunt — simulator options that do not reach compiled models, and long-chain convergence

**Date:** 2026-09-26 · **Commit under test:** `ebc808a3` · **Binaries:**
`ngspice-46/build/src/ngspice` at the E-738 state (KLU, `--disable-openmp`,
Apple clang) and `OpenVAF-master-20260610/target/opt/openvaf-r`. **Status:
open** — a one-hour hunt, nothing in the repository was changed, no finding
was fixed. Probe decks and logs are under the session scratchpad `bh/`.

The hunt worked in two directions that earlier passes had not taken: the
simulator-wide `.option`s and instance keywords that ngspice's built-in
devices honour, checked one by one against a compiled twin; and the Newton
and timestep behaviour of a compiled BSIM4 on long chains, where the E-543
limiter and the OSDI truncation-error path meet ngspice's own control. Every
probe below pairs the compiled model with ngspice's hand-written device on
the same physics — the VA-Models BSIM4 4.8 against `nmos level=14
version=4.8`, `vadiode.va` against the built-in diode, `nres.va` against the
resistor — so a difference is the integration's, not the model's.

| # | finding | severity |
|---|---|---|
| [F1](#f1--option-tnom-does-not-reach-compiled-models) | `.option tnom=50` changes nothing in a compiled BSIM4 while the built-in twin moves as it does with `tnom=50` on its card; the banner still prints *TNOM = 50* | **medium** — silent |
| [F2](#f2--option-scale-is-not-applied-to-compiled-instances) | `.option scale=1e-6` with `w=1 l=0.1` gives the built-in the same point as `w=1u l=100n`; the compiled instance is simulated as a 1 m × 0.1 m device with no message | **medium** — silent |
| [F3](#f3--the-operating-point-of-a-long-compiled-bsim4-chain-takes-24-the-built-ins-iterations-and-not-monotonically) | a common-source chain of N compiled BSIM4 stages converges its `op` in 9 iterations up to N = 500, then 100 at 700, 184 at 1 000, 135 at 2 000, 146 at 10 000 (built-in: 10, 46, 65); at 600 stages 73 under KLU and 363 under Sparse, COLAMD or `klu_btf=off` | medium — performance |
| [F4](#f4--the-long-chain-transient-rejects-two-to-three-times-the-built-ins-timepoints) | on the 1 000-stage chain 21 of 177 timepoints are rejected against the built-in's 8 of 206; 53 against 16 at 10 000 stages; 1 207 against 1 123 at reltol 1e-6; the limiter is not the cause | low–medium — performance |
| [F5](#f5--m0-deletes-a-compiled-instance-silently) | `m=0` or `_mfactor=0` on a compiled instance removes the device from the circuit with no message; a negative value is caught | low |
| [F6](#f6--the-negative-multiplier-check-prints-two-warnings-that-contradict-each-other) | the two warnings for `m=-1` say "the device's contribution is sign-inverted" and "the value is ignored"; measured, it is ignored | low — diagnostics |
| [F7](#f7--a-compiled-model-that-owns-a-parameter-m-cannot-be-used-inside-a-subcircuit-called-with-m) | a compiled diode (`vadiode`, whose grading coefficient is `m`) inside a `.subckt` instantiated with `m=2` is refused — *unknown parameter (m): it is a model parameter of this device* — because the expansion appends `m=2` to the inner line; `_mfactor=3` on the inner line is refused too, as a double setting; the built-in diode multiplies | **medium** |
| [F8](#f8--a-compiled-module-with-its-own-instance-parameter-m-is-not-multiplied-inside-a-subcircuit-called-with-m-its-parameter-is-overwritten) | a module declaring an instance parameter `m` of its own (`I <+ V/1k + m*1u`) inside a `.subckt` called with `m=2` reports 0.502 mA where a multiplied device gives 1.002 mA: the expansion's `m=2` sets the module's parameter and no multiplier is applied, with no message from ngspice (the compiler warns once at compile time) | **medium–high** — silent wrong result |
| [F9](#f9--disto-of-a-compiled-diode-with-diffusion-charge-is-wrong-by-a-sixth-in-the-second-harmonic-and-two-fifths-in-the-third-and-the-built-in-is-right) | `.disto` on the twin diodes agrees to six digits without charge storage and within 1 % with junction capacitance only, but with diffusion charge (`tt=5n`) the second harmonic at 10 MHz is −7.6e-5 + j6.3e-5 against the built-in's −1.15e-4 + j1.6e-5, and at 100 MHz 6.7e-6 − j1.9e-6 against 1.9e-5 + j4.0e-5; a tight transient's `fourier` gives 1.164e-4 at 82° for the second and 2.17e-6 for the third harmonic, the built-in's numbers, so the compiled path is the wrong one; a module whose only nonlinearity is a cubic charge gives exactly zero distortion where the transient shows 5.9 % THD — the compiled path contributes nothing from reactive nonlinearity, because its perturbed evaluations never ask for the reactive Jacobian (`osdidisto.c:237`) | **medium–high** — wrong numbers from an analysis, silently |
| [N1](#n1--notes-not-osdi-specific-or-by-design) | `level=` on a compiled model card is accepted silently; `off`, `ic=` and a wrong instance prefix give a bare *Error on line N*; `meas` on a device vector needs a `save` first; `stop when` re-fires at once on `resume`; `maxord` above 2 needs `dynorder` | notes |

---

## F1 — `.option tnom` does not reach compiled models

ngspice's built-in models take the circuit's nominal temperature as the
default of their `tnom` when the model card does not give one
(`CKTnomTemp`, set by `.option tnom`). The OSDI layer passes `tnom` only as
`$simparam("tnom")` ([`osdiload.c:579`](../../ngspice-46/src/osdi/osdiload.c)),
which the industry models do not read — their `tnom` is an ordinary
parameter with a literal default of 27 — and never sets that parameter on
the model. So the option is ignored while the run's banner reports it.

```
vdd vdd 0 dc 1.2
vin in 0 dc 0.6
nm1 out in 0 0 mos_va w=1u l=100n
R1 vdd out 20k
.model mos_va bsim4va()
.option tnom=50
```

| deck | compiled BSIM4 `v(out)` | built-in `nmos level=14 version=4.8` |
|---|---:|---:|
| no tnom anywhere | 0.084861 | 0.083282 |
| `.option tnom=50` | **0.084861** (unchanged) | 0.067959 |
| `tnom=50` on the model card | 0.067957 | 0.067959 |
| `altermod @mos_va[tnom] = 50` | 0.067957 | — |

The banner of the `.option` run reads *Doing analysis at TEMP = 27.000000
and TNOM = 50.000000*. The fix is the built-in rule: when a compiled model
declares a parameter named `tnom` (case-insensitively) and the card does not
give it, set it to `CKTnomTemp` before `setup_model`.

**The same gap makes the default wrong, not only the option.** With no
`tnom` anywhere, `bsim4va()` gives 0.034163 for a `w=2u` stage and
`bsim4va(tnom=27)` gives 0.033652, 1.5 % apart, while `showmod` prints
*tnom 27* for both. The VA-Models BSIM4 overrides an ungiven `tnom` in its
own code (`bsim4.va:3085`, `DEFAULT_TNOM` is 25 in that file), so the
compiled model runs at a 25 °C nominal by default where the built-in runs at
27 °C, and nothing in ngspice's output says so. Setting the circuit's
nominal temperature on the model, as above, makes the parameter given and
puts the compiled model at the simulator's nominal temperature like every
built-in.

| model, no nominal temperature on the card | default against the same value given | parameter |
|---|---|---|
| VA-Models BSIM4 4.8 | 0.034163 against 0.033652 with `tnom=27` — runs at 25 °C | `tnom` |
| HiCUM/L2 | −2.70477 mA against −2.70477 mA with `tnom=27` — consistent | `tnom` |
| PSP103 | 0.065578 against 0.062784 with `tr=27` — runs at its own 21 °C | `tr`, and `tnom=27` on its card is *Model issue* |

So the parameter is not always called `tnom`: PSP's reference temperature
is `tr`, MEXTRAM's is `tref`. A by-name rule needs the short list, or the
compiler's OSDI descriptor could flag the nominal-temperature parameter.

## F2 — `.option scale` is not applied to compiled instances

`.option scale` multiplies the geometric instance parameters of the built-in
MOSFETs (`w`, `l`, `as`, `ad`, `ps`, `pd`). A compiled model has no such
list, and the OSDI layer applies nothing, so a deck written for
`scale=1e-6` — common in foundry flows — simulates a compiled transistor
with `w=1 l=0.1` as one metre by ten centimetres, silently.

| instance line | option | compiled BSIM4 `v(out)` | built-in |
|---|---|---:|---:|
| `w=1u l=100n` | — | 0.084861 | 0.083282 |
| `w=1 l=0.1` | `.option scale=1e-6` | **0.025341** | 0.083282 |

Whether the layer should scale parameters by name (the built-ins' list), by
a unit attribute, or refuse the option with a warning when compiled devices
are present is a design question; today it does none of the three. A
warning at setup when `scale` is not 1 and a compiled instance exists would
already remove the silence.

## F3 — the operating point of a long compiled-BSIM4 chain takes 2–4× the built-in's iterations, and not monotonically

A chain of N common-source stages (`nm{k} in{k+1} in{k} 0 0 mos_va w=1u
l=100n`, `r{k} vdd in{k+1} 20k`, `vin` at 0.6 V, `vdd` 1.2 V), `op`, KLU, no
gmin or source stepping in any run (`itl1=1000` gives the same counts):

| stages N | compiled BSIM4 | compiled, `.option noosdilim` | built-in BSIM4 |
|---:|---:|---:|---:|
| 10 | 9 | 33 | 10 |
| 100 | 9 | 54 | 10 |
| 300 | 9 | 152 | 10 |
| 500 | 9 | — | — |
| 550 | 9 | — | — |
| 600 | 73 (77 at reltol 1e-4) | 281 | — |
| 650 | 92 | — | — |
| 700 | 100 | — | — |
| 1 000 | 184 (184 under Sparse) | 282 | 46 |
| 1 500 | 184 | — | — |
| 2 000 | 135 | — | — |
| 3 000 | 93 | 303 | 65 |
| 10 000 | 146 | 308 | 65 |

Up to 550 stages the E-543 limiter makes the compiled chain converge as the
built-in does; at 600 the count jumps and then wanders with N. The load
matters as much as the length: the 1 000-stage chain takes 43 iterations
with 5 k loads, 184 with 20 k and 103 with 100 k. At 600 stages the count
is 73 under KLU's defaults and 363 under Sparse, under COLAMD or with
`klu_btf=off`, while `klu_scale=none` keeps 73: the Newton path is
sensitive to the factorisation's rounding, the mark of a search that
passes close to a point where two paths part, as E-737's was.
The limiter is not simply the cause — without it every length is worse —
but it is involved: the bypass prototype measured earlier today, which skips
both the evaluation and the limiter for an instance whose voltages and
currents are within tolerance, brought the 10 000-stage `op` to 26
iterations with the same solution to 1.8e-9 V. So in the long chains the
limiter, or the non-convergence it flags, keeps devices that are already
within tolerance in play for a hundred more iterations. The converged point
is the same in every run. The mechanism is open; the place to look is
`osdi_lim_apply` and its `CKTnoncon++` in
[`osdiload.c`](../../ngspice-46/src/osdi/osdiload.c), iteration by iteration
on the 700- and 1 000-stage decks.

Smaller signs of the same family, for the record: the compiled diode's DC
sweep of 101 points takes 258 iterations against the built-in's 209, and its
`op` 14 against 9; a 100-stage chain's DC sweep is even, 177 against 171.

## F4 — the long-chain transient rejects two to three times the built-in's timepoints

The same chains with a pulse on `vin`, `tran`:

| deck | compiled: iterations / accepted / rejected | built-in |
|---|---:|---:|
| 1 000 stages, `tran 0.5n 20n` | 1 190 / 156 / **21** | 1 030 / 198 / 8 |
| 1 000 stages, `.option noosdilim` | 1 446 / 160 / 22 | — |
| 1 000 stages under Sparse | 1 369 / 156 / 21 | — |
| 10 000 stages, `tran 0.5n 60n` | 3 396 / 502 / **53** | 3 048 / 592 / 16 |
| 100 stages, reltol 1e-6 abstol 1e-15 vntol 1e-9 | 13 447 / 2 851 / 1 207 | 11 300 / 2 756 / 1 123 |
| diode + capacitor at 50 MHz | 618 / 308 / 0 | 625 / 308 / 0 |

The compiled chain takes fewer, larger steps and has 2.6× the rejections,
so its iterations per accepted point are 7.6 against 5.2. Without the
limiter the rejections stay (22), and under Sparse they are the same (21),
so it is neither the limiter nor the solver. The candidates
are the truncation-error path (`OSDItrunc` over the reactive residual states
against `CKTterr` over the built-in's charge states) and `$bound_step`. Open.

## F5 — `m=0` deletes a compiled instance silently

```
V1 in 0 dc 1
R1 in a 1k
nr1 a 0 nmod m=0
.model nmod nres(r=1k)
```

`v(a)` is 1.0 V and `@nr1[i]` is 0: the resistor is gone, and nothing says
so. `_mfactor=0` does the same, so does `m=0` on the `X` line of a
subcircuit that holds the instance, and so does `alter @nr1[m] = 0` at run
time. The negative check sits at
[`osdiparam.c:187`](../../ngspice-46/src/osdi/osdiparam.c); zero belongs
beside it. A negative value is caught by the check
that E-686's family added, so zero is the one value that check lets through.
The built-ins are inconsistent about it — BSIM4 stops with *Fatal:
multiplier = 0 is not positive*, the resistor and the diode accept it
silently (the diode's node then floats into gmin stepping) — which is an
argument for the compiled layer to take the strict side.

## F6 — the negative-multiplier check prints two warnings that contradict each other

`nr1 a 0 nmod m=-1` prints, in this order:

```
Warning: nr1: multiplier m=-1 is negative; the device's contribution is sign-inverted (a passive device becomes active) and any noise contribution becomes NaN.
Warning: multiplier m=-1 is negative; the value is ignored (a negative multiplicity sign-inverts the device and makes its noise NaN).
```

Measured: `v(a)` = 0.5 V and `@nr1[i]` = 0.5 mA, so the value was ignored
and the device ran with m = 1. The first warning describes what does not
happen. They come from two layers — the parser's
[`inpdpar.c:94`](../../ngspice-46/src/spicelib/parser/inpdpar.c) and the
OSDI layer's [`osdiparam.c:187`](../../ngspice-46/src/osdi/osdiparam.c) —
and the parser's text is the wrong one. One warning, saying what is done,
is enough.

## F7 — a compiled model that owns a parameter `m` cannot be used inside a subcircuit called with `m=`

```
.subckt dsub p n
nd1 p n dva
.model dva vadiode(is_=1e-14 n=1.2)
.ends
X1 a 0 dsub m=2
```

stops with *unknown parameter (m): it is a model parameter of this device --
set it on the .model card, not on the instance line*, on a line the user
never wrote a parameter on. The built-in diode in the same subcircuit gives
`v(a)` = 0.7246 V under `m=2` against 0.7439 V under `m=1`. A diode's
grading coefficient is called `m` in every SPICE-derived Verilog-A diode,
so this is the ordinary case, not a corner: a PDK subcircuit with a
multiplier cannot hold a compiled diode.

The inner line cannot help itself either. With `nd1 p n dva _mfactor=3` the
run stops with *Error on line 3*; with a resistor module the message is
*'_mfactor' and 'm' are the same parameter (aliasparam) and both are set on
this line; LRM 3.4.7 makes that an error -- remove one*. The user set one.
The subcircuit expansion appends the X-line's `m=2` to every inner instance
line and, for the built-ins and for a compiled instance that says `m=3`,
multiplies the two (a `6k m=3` resistor under `m=2` reads 1 k, compiled or
built-in). It does not recognise `_mfactor` as the same knob, so the
expanded line carries both spellings and the alias check refuses it. And
`_mfactor` is the only spelling available to a model whose own parameter is
named `m`, such as this diode's grading coefficient: `nd1 p n dva m=3` is
refused as a model parameter. A compiled diode, or any model that owns `m`,
therefore cannot have an instance multiplier inside a subcircuit that is
itself multiplied.

There is no spelling that works: `X1 a 0 dsub _mfactor=2` is a numparam
error (the X line takes only `m`). A compiled BSIM4, whose module has no
`m` of its own, multiplies inside the same subcircuit as expected.

The fix is in the expansion: append the multiplier under the alias the
inner device accepts (`_mfactor` for a compiled instance), and multiply an
existing `_mfactor` as an existing `m` is multiplied today.

## F8 — a compiled module with its own instance parameter `m` is not multiplied inside a subcircuit called with `m=`; its parameter is overwritten

```
module mmode(p, n);
    (* type="instance" *) parameter integer m = 1 from [1:8];
    analog I(p, n) <+ V(p, n) / 1k + m * 1u;
endmodule
```

```
.subckt msub p n
nx1 p n mm
.model mm mmode
.ends
V1 a 0 dc 0.5
X1 a 0 msub m=2
```

`i(V1)` is 0.502 mA. A multiplied device would draw 1.002 mA (two of
0.5 mA + 1 µA); 0.502 mA is one device with its own `m` set to 2. The
subcircuit expansion appends `m=2` to the inner line, the OSDI layer hands
it to the module's parameter because the module declares one by that name,
and no multiplier is applied. ngspice prints nothing. The compiler does say,
once, at compile time — *warning[L029]: parameter name 'm' is ngspice's
reserved instance parameter for the multiplier* — which is the right
warning in the right place for the module's author, but the deck's author
sees a number that is silently wrong.

For contrast, `temp=` and `dtemp=` on an instance whose module declares a
parameter of that name reach both sides: a module with its own `dtemp`
sees 5 and `show` reports `dt 5`, one with its own `temp` sees 50 and the
device runs at 50 °C. Only `m` is lost, because it is the one the
subcircuit expansion writes on the user's behalf.

This is the same expansion as F7, and the same fix: append the multiplier
under the simulator's own alias (`_mfactor`), which no module can declare,
rather than under `m`. Until then a module that owns `m` as an instance
parameter should not be placed in a multiplied subcircuit, and the compiler
warning is the only guard.

## F9 — `.disto` of a compiled diode with diffusion charge is wrong by a sixth in the second harmonic and two fifths in the third, and the built-in is right

`V1 in 0 dc 0.7 ac 1 distof1 0.01`, `R1 in a 1k`, the diode from `a` to
ground, `C1 a 0 1p`, `disto dec 1 1meg 100meg`, second harmonic of `v(a)`
from the `disto1` plot, compiled `vadiode` against the built-in diode with
the same card:

| diode card | 1 MHz | 10 MHz | 100 MHz |
|---|---|---|---|
| no charge storage, compiled | −1.07903e-4 + j1.46244e-6 | −1.06562e-4 + j1.45169e-5 | −2.53524e-5 + j7.60218e-5 |
| no charge storage, built-in | −1.07902e-4 + j1.46243e-6 | −1.06561e-4 + j1.45169e-5 | −2.53526e-5 + j7.60217e-5 |
| `cjo=2p vj=0.8 m=0.4`, compiled | −1.0766e-4 + j6.37e-6 | −8.47e-5 + j5.56e-5 | 1.085e-5 − j5.9e-7 |
| same, built-in | −1.0767e-4 + j6.24e-6 | −8.53e-5 + j5.45e-5 | 1.092e-5 + j7.2e-7 |
| `tt=5n`, compiled | −1.0754e-4 + j7.70e-6 | **−7.55e-5 + j6.32e-5** | **6.68e-6 − j1.90e-6** |
| same, built-in | −1.0802e-4 + j9.4e-7 | **−1.152e-4 + j1.57e-5** | **1.86e-5 + j4.00e-5** |

The third harmonic behaves the same way (1 MHz: 1.16e-6 − j2.8e-7 against
1.20e-6 + j1.0e-7; 10 MHz: −6.7e-7 − j1.1e-6 against 2.06e-6 + j6.8e-7), while
the `.ac` response of the very same pair is identical to six digits at every
frequency, so the linear model including the diffusion capacitance agrees
and the disagreement is confined to the second- and third-order terms. The
resistive core agrees to six digits, so the analysis itself and E-352/E-353/E-359's derivative machinery
are sound; the junction capacitance agrees within a per cent; only the
diffusion charge `tt·id(V)`, a reactive residual that is a function of the
resistive current, parts the two. Either the compiled path's reactive
Taylor terms for such a charge, or `diodisto.c`'s handling of `cdif`, is
off. It is not the two models: a 10 MHz transient of the `tt`-only pair
agrees to 4e-6 V in steady state at reltol 1e-5 (2.6e-4 V at the default
tolerance, inside its band), so their diffusion charges are the same
function and one of the two distortion paths is wrong. Which side is right was settled from the time domain: the same `tt`-only
diode driven by `sin(0.7 0.01 10meg)` — the `distof1 0.01` drive as a real
signal — at reltol 1e-6 for 2 µs, then ngspice's `fourier 10meg v(a)`:

| harmonic, 10 MHz | transient `fourier`, compiled | transient `fourier`, built-in | `.disto` built-in | `.disto` compiled |
|---|---|---|---|---|
| 2nd, magnitude / phase | 1.1636e-4 / 82.2° | 1.1620e-4 / 82.3° | 1.163e-4 / 172.2° − 90° = 82.2° | **9.85e-5 / 140.1° − 90° = 50.1°** |
| 3rd, magnitude | 2.168e-6 | 2.159e-6 | 2.17e-6 | **1.29e-6** |

(`.disto` reports the response to `cos`, the transient drive is `sin`, hence
the 90° shift.) The built-in `.disto` reproduces the time domain to three
digits; the compiled `.disto` is 15 % low and 32° off in the second
harmonic and 40 % low in the third. The defect is therefore in the compiled
distortion path's reactive terms for a charge that is a function of the
resistive current — `Q = tt·id(V)` — not in the model and not in
`diodisto.c`. The two-tone products carry the same defect: with `distof2 0.01` at
0.9·f1, the f1+f2 product at 10 MHz is −1.93e-4 + j7.8e-5 compiled against
−2.20e-4 + j1.2e-5 built-in, and at 100 MHz 2.8e-5 + j4.3e-5 against
−1.09e-4 + j1.3e-4.

The mechanism, established: the compiled path contributes nothing from a
nonlinear charge. A module with `I(p,n) <+ ddt(c1*V + c3*V^3)`
(`c1=1p`, `c3=20p`), alone or beside a linear `V/1k`, driven with
`distof1 0.1` at 10 MHz, reports `v(a)` = 0 + j0 in both the second- and
third-harmonic plots, while the transient at the same drive shows a second
harmonic of 4.17 mV (5.9 % THD) alone and 1.10 mV (2.2 %) with the
resistor. Every distortion product of a charge is missing, and the
diode's diffusion charge is only the case where that missing part is large
enough to see beside the resistive exponential: the junction capacitance's
share is about 1 %, which is the 1 % the `cjo`-only pair disagreed by.
`osdidisto.c` has a reactive pass rotated by j·ω "exactly as diodisto.c
does" ([`osdidisto.c:286`](../../ngspice-46/src/osdi/osdidisto.c)); the
reactive tensor it rotates is zero. That tensor is filled in
[`osdidistonum.c`](../../ngspice-46/src/osdi/osdidistonum.c) by finite
differences of `write_jacobian_array_react` (lines 120, 262, 337) around
perturbed evaluations whose flags are the caller's base flags minus
limiting (line 210). The compiled objects do export the reactive writer.
The cause is the flag set those evaluations run under: the driver builds
its `OsdiSimInfo` with `CALC_RESIST_JACOBIAN | CALC_RESIST_RESIDUAL |
CALC_OP | CALC_RESIST_LIM_RHS | ENABLE_LIM | ANALYSIS_DC | ANALYSIS_STATIC`
([`osdidisto.c:237`](../../ngspice-46/src/osdi/osdidisto.c)) — "the flags
mirror a DC operating-point eval", its comment says — and a DC evaluation
never computes the reactive Jacobian. So every perturbed evaluation leaves
the reactive Jacobian at whatever the last transient or AC evaluation left
there, every finite difference of it is zero, and the reactive tensor the
j·ω pass rotates is empty. The fix is two flags, `CALC_REACT_JACOBIAN |
CALC_REACT_RESIDUAL`, on that line, followed by the `tt`-only diode and
the cubic charge against the transient `fourier` as the checks the
distortion suites lack. The diode's numbers fit: its `.disto` still moves
with `tt` because the linear diffusion capacitance enters the small-signal
network from the AC-phase Jacobian, while the nonlinear part of the charge
is missing. The
distortion suites compare against the built-in on resistive cores and on
the junction capacitance, where the agreement is exact; a `tt`-only diode
against the transient `fourier` is the check they lack.

## N1 — notes, not OSDI-specific or by design

* `.model dva vadiode(level=1 is_=1e-14)` is accepted without a word;
  `bogus=3` on the same card gets a *Model issue* warning. `level` is
  special-cased by the model parser before the OSDI check sees it. A deck
  ported from a built-in card keeps its `level=54` and no one is told.
* `nm1 ... off`, `nm1 ... ic=0.5,0.6,0`, an unknown instance parameter
  (`nd1 a 0 dva foo=1`) and an instance with a prefix that is not `n`
  (`y1 a 0 dva`) each stop with *Error on line 4 or its substitute* and the
  line echoed, nothing more. E-687 gave `m` and the
  model-parameter-on-an-instance case a sentence; these three have none.
* `meas tran imax MAX @nd1[i]` after a `tran` without a prior `save` fails
  with *holds 1 point(s) but the analysis produced 211*; the built-in
  `@d1[id]` fails identically, and with `save` or `.option savecurrents`
  both work. ngspice-wide.
* `stop when time > 30n` followed by `resume` stops again at once, since the
  condition still holds; the built-in twin behaves the same. ngspice-wide.
* `.option bypass=1` is silently without effect for compiled devices; the
  built-in twin's transient load halves under it (measured earlier on
  2026-09-26 with a prototype that is not in the tree, and parked).
* `nd1 a 0 dva m=2` on a model that owns a parameter `m` is refused with
  *it is a model parameter of this device -- set it on the .model card*,
  which is right, but the message does not say that the multiplier the
  user wanted is reachable as `_mfactor=2`.
* A `$warning` or `$strobe` whose text does not change is printed once per
  analysis and its later arrivals are neither printed nor counted: 23
  arrivals over an 11-point sweep print one line, and two instances with the
  same text print one line each. The header of `osdicallbacks.c` promises
  five showings and a count for a repeated text, which is what a setup-time
  flood gets (*was repeated 9995 more times by other instances*); the
  analysis-time path has no count at all. A message whose text carries
  `$abstime` prints once per accepted point (68 lines for 68 points).
* `dc nr1 1k 3k 1k` over a compiled resistor stops with *Voltage source,
  current source, or resistor named "nr1" is not in the circuit*: accurate,
  since ngspice's `dc` sweeps only its own resistor, but a compiled resistor
  is not sweepable at all.
* `method=gear maxord=6` gives bit-identical results to `maxord=2` on every
  deck tried, built-in or compiled; the order is raised only with
  `.option dynorder` (E-128, E-259), under which the compiled charge
  integrates without incident.

## What was checked and holds

Each of these paired a compiled device with its built-in twin, or a run
with an independent reference, and found no difference beyond tolerance:

* DC sweeps: iterations per point on a linear divider (2 with either
  resistor), a nested two-source sweep, a backward sweep (`dc V1 1 0 -0.01`
  equals the forward sweep reversed to 1.7e-5 V), a sweep of `temp` against
  five separate `.temp` runs (2.7e-5 V, and bit-identical between KLU and
  Sparse), the same with `dtemp=50` on the instance.
* Temperature routes: `.temp`, `.option temp`, `alter @nd1[temp]`,
  `alter @nd1[dtemp]` and the instance's `temp=` all give the same point;
  `dtemp` is ignored when `temp` is given, as for the built-ins.
* Run control: `op` / `ac` / `tran` twice in one control block are
  bit-identical; `tran 0.1n 40n 20n` matches the full run from 20 ns to the
  bit for a `$abstime`-driven source; `stop`/`resume` matches the built-in;
  `noise` after a `dc` sweep equals a fresh `noise`; an `alterparam`+`reset`
  loop of 200 operating points runs at 7 MB and linear time (no leak), and a
  compiled BSIM4's setup message is printed once per `reset`.
* Netlist and front end: the same library given twice or the same module
  from two files is refused with a note; a model name reused for a second
  module warns and keeps the first; duplicate instance, too many terminals,
  a model parameter on an instance line and a missing model each stop with
  an error, too few terminals warns and names the absent terminal; unknown
  and duplicated parameters warn; `W=2U L=100N` and `BSIM4VA(TNOM=27)` work;
  `r=1kohm`, `1M` (milli), `1meg`, `1mil` follow SPICE; a `.save` card of
  `@nd1[i]` and `@nd1[i_a]`, `.option savecurrents` and `save all` list the
  currents and the internal nodes (`nm1#di`, `nm1#gi`, `nm1#si`); `show`, `showmod`,
  `listing e` print the compiled devices; `showmod` reflects an `altermod`.
* `alter`/`altermod`: `m` and `_mfactor` on an instance, model parameters,
  an out-of-range value (refused with the parameter, value and range named;
  the next in-range `altermod` recovers), two cards of one module altered
  separately; `m=2` halves the AC impedance and the noise of three
  multiplied resistors equals that of the explicit parallel set.
* Small-signal: `tf` (transfer function, input and output impedance within
  2e-6 relative), `sens` (`nr1:r` = −2.5e-4 against `r1` = −2.5e-4), `.ic`
  on a node with a compiled charge (first points 0.9000 on both).

## Coverage, honestly

* Only three compiled models were used — the VA-Models BSIM4, a one-diode
  and a one-resistor module — so a family-wide claim (every simulator
  option) rests on the options tried: `tnom`, `scale`, `temp`, `defw`/`defl`
  (ignored by the built-in BSIM4 too), `savecurrents`, `dynorder`,
  `maxord`, `method`, `bypass` (prototype only, not in the tree).
* F3 and F4 are measured, not explained; the iteration-by-iteration trace
  of the 700-stage chain is the next step and was not started within the
  hour.
* The `$abstime` probe used a module compiled during the hunt (`tsrc.va`
  in the scratchpad), the only compile of the session.
* One hour, one machine, one run per number; the chain counts are
  deterministic run to run, the wall times were not used.
