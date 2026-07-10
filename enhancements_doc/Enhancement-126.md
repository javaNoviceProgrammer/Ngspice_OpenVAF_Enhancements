# Enhancement-126 — cyclostationary noise

The first refinement of the RF periodic small-signal suite. [`.pnoise`](Enhancement-124.md)
folds every device's noise through the conversion matrix, but its first cut made a
**stationary** approximation: it evaluated each device's noise PSD at a single
operating point. For a device pumped by a large signal that is exactly the
approximation that loses the physics — a diode's shot noise `2qI(t)`, a transistor's
`gm(t)` noise, or a resistor's flicker noise `∝|I(t)|` all vary along the PSS period.
E-126 adds a **cyclostationary** mode that captures that variation.

## The idea

A cyclostationary noise source has a periodic PSD `S(t)`. Its harmonics couple the
noise between sidebands, so the output noise is the double sum

```
onoise(f) = Σ_k Σ_l  ΔΨ_k* ΔΨ_l  S_{k−l},
```

where `ΔΨ_k` is the sideband-`k` adjoint transfer (E-124) and `S_m` is the `m`-th
harmonic of `S(t)`. Substituting `S_m = (1/P)Σ_s S(t_s)e^{−jmω₀t_s}` and collapsing
the sums gives a form that needs no explicit harmonics of the noise:

```
onoise(f) = (1/P) Σ_s  S(t_s) · |ΔA_s(f)|²,
A_s(j)    = Σ_k Ψ_k(j) · e^{+j2πks/P}   (inverse-DFT of the sideband transfers).
```

So the cyclostationary output noise is the **period average** of the instantaneous
noise power `S(t_s)` weighted by the **time-domain** adjoint transfer `A_s`. This is
computed by looping over the `P` retained PSS samples: at each sample its bias is
restored (`CKTload`, so every device's noise PSD is evaluated at that instant), the
time-domain transfer `A_s` is loaded into `CKTrhs`/`CKTirhs`, and the existing device
noise routines are called and accumulated — then divided by `P`. It reuses the
device noise models exactly as E-124 does; only the transfer and the averaging
change. Enabled by a trailing `cyclo` keyword on `.pnoise`.

## Two things it must satisfy

**1. Reduction (rigorous).** When the noise source is bias-independent — a
resistor's thermal noise `4kTG` — `S(t)` is constant, and by Parseval the period
average equals the sideband sum, so cyclostationary reduces **exactly** to the
stationary result, i.e. to ordinary `.noise`. On the linear RC low-pass the
cyclostationary output noise equals `4kTR1/(1+(2πfR1C1)²)` to every printed digit,
identical to E-124 and to a plain `.noise` run — validating the whole per-sample /
time-domain-transfer / averaging machinery.

**2. Cyclostationary effect (quantitative).** A resistor `R1` carries a *known*
periodic current `I(t) = Idc + Iac·sin(ω₀t)` (driven by a current source) and has a
flicker model (`KF`, `AF = 2`). Its flicker noise `∝ KF·|I(t)|²` is genuinely
cyclostationary, the circuit is linear (fast PSS), and the transfer to the output is
flat (`= R1`), so

```
onoise_flicker(f) · f  =  R1² · KF · ⟨|I(t)|²⟩  =  R1² · KF · (Idc² + Iac²/2),
```

a constant independent of frequency. With `Idc = 1 mA`, `Iac = 0.8 mA`,
`⟨I²⟩ = 1.32e−6 A²` — **32 % above** the DC-current value `Idc² = 1e−6` a
stationary analysis at the operating point would use. The cyclostationary result
matches `R1²·KF·⟨I²⟩` across the sweep, confirming it uses the period average, not a
single sample.

## The command

```
.pnoise Fguess StabTime OscNode Points Harmonics SC_iter Steady_coeff \
        OutNode InSrc <DEC|OCT|LIN> Npts Fstart Fstop [cyclo]
```

The trailing `cyclo` selects the cyclostationary mode; without it, `.pnoise` keeps
the E-124 stationary behaviour.

## Files changed

| File | Change |
|---|---|
| `ngspice-46/src/include/ngspice/pssdefs.h` | `PSSan.PSSpnCyclo`; `PNOISE_CYCLO` param id |
| `ngspice-46/src/spicelib/analysis/psssetp.c` | `pnoise_cyclo` setter + IFparm entry |
| `ngspice-46/src/spicelib/parser/inp2dot.c` | `dot_pnoise` parses the optional trailing `cyclo` |
| `ngspice-46/src/spicelib/analysis/dcpss.c` | `pnoise_sweep` cyclostationary branch — precompute the adjoint per frequency, loop PSS samples restoring each bias, fold the time-domain transfer through the device noise routines, average over the period |
| `examples/rfpss_examples/rc_pnoise.cir`, `verify_rccyclo.py` | reduction check (RC → `.noise`) + quantitative flicker check |

## Scope

Cyclostationary noise makes `.pnoise` correct for pumped devices whose noise depends
on the operating point (mixers, oscillators, switched circuits). The remaining
refinement is a dedicated **phase-noise** (jitter) spectrum, which reuses the same
cyclostationary fold specialised to the oscillator's phase mode.
